"""PDF: one PageResult per page (contract 10 X2 to X5). The class of each page decides its method.

Two passes:
1. For every page: signals and class (X3), and the raw lines of text-layer pages.
2. Running headers and footers are found over all pages, then each page becomes blocks. OCR runs only on the
   pages whose class needs it, one page bitmap in memory at a time.

One bad page never spoils the others: a page that pdfplumber cannot read falls back to pypdf (`text_pypdf`); a page
the vision model cannot read is `OCR_FAILED` and goes to review (X7).
"""
import logging
from collections.abc import Callable
from pathlib import Path

import pdfplumber

from ingestion.classify import PageSignals, classify, page_signals
from ingestion.clean import EDGE_LINES, is_edge_noise, printed_page_number, repeated_edge_lines
from ingestion.config import ExtractConfig
from ingestion.layout import SectionTracker, body_size, heading_level, lines_to_blocks, reading_order, text_to_blocks
from ingestion.ocr import OcrEngine, OcrFailed, render_pdf_page
from ingestion.tables import find_unit, table_block
from ingestion.types import Block, PageResult

log = logging.getLogger(__name__)

OCR_CLASSES = {"SCANNED", "GARBLED", "MIXED"}

Progress = Callable[[str, int, int], None]


def extract_pdf(path: Path | str, cfg: ExtractConfig, ocr: OcrEngine | None,
                progress: Progress | None = None) -> list[PageResult]:
    path = str(path)
    pages: list[PageResult] = []
    raw: dict[int, dict] = {}       # page -> {"lines": [...], "tables": [...], "body": float}

    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for index, page in enumerate(pdf.pages, start=1):
            if progress:
                progress("classifying", index, total)
            try:
                signals = page_signals(page)
                page_class = classify(signals, cfg)
                result = PageResult(page=index, page_class=page_class, method="", chars=signals.chars,
                                    tables=signals.tables, signals=signals.as_dict())
                if page_class in ("TEXT", "TABLE_HEAVY", "MIXED"):
                    raw[index] = _text_layer(page, cfg)
            except Exception as e:  # pdfplumber failed on this page: pypdf text for this page only
                log.warning("pdfplumber failed on page %s: %s", index, e)
                result = PageResult(page=index, page_class="TEXT", method="text_pypdf",
                                    signals={"error": str(e)[:200]})
                raw[index] = {"pypdf": True}
            pages.append(result)

    # OCR first (one page bitmap at a time), so running headers can be found on OCR pages too
    ocr_pages = [p for p in pages if p.page_class in OCR_CLASSES]
    for n, result in enumerate(ocr_pages, start=1):
        if progress:
            progress("ocr", n, len(ocr_pages))
        _ocr_page(path, result, cfg, ocr)

    # running headers and footers: text-layer lines and OCR lines are compared separately, because a scan has the
    # header printed on it while the text layer of the same document may not
    repeated = repeated_edge_lines([[ln.text for ln in r["lines"]] for r in raw.values() if "lines" in r],
                                   cfg.repeat_line_ratio)
    ocr_lines = {p.page: _markdown_lines(p.ocr_result.text_markdown) for p in ocr_pages if p.ocr_result}
    ocr_repeated = repeated_edge_lines([[t for t, _ in lines] for lines in ocr_lines.values()], cfg.repeat_line_ratio)

    tracker = SectionTracker()
    for result in pages:
        if result.page_class == "BLANK":
            result.method = "none"
            continue
        blocks: list[Block] = []
        info = raw.get(result.page)
        if info and info.get("pypdf"):
            blocks = text_to_blocks(_pypdf_page_text(path, result.page), tracker, "text_pypdf")
        elif info:
            blocks = _text_blocks(result, info, repeated, tracker)
            result.method = "text+tables" if any(b.type == "table" for b in blocks) else "text"
        if result.page_class in OCR_CLASSES:
            ocr_blocks = []
            if result.ocr_result is not None:
                markdown = _strip_ocr_edges(result, ocr_lines[result.page], ocr_repeated)
                ocr_blocks = text_to_blocks(markdown, tracker, "ocr", markdown=True)
            if result.page_class == "MIXED":
                blocks = blocks + ocr_blocks
                result.method = "text+ocr"
            else:
                blocks = ocr_blocks             # SCANNED, GARBLED: the text layer is unusable
                result.method = "ocr"
        result.blocks = blocks
    return pages


def _markdown_lines(markdown: str) -> list[tuple[str, str]]:
    """(plain text, raw line) for each non-empty line; the plain text drops heading marks and bold marks."""
    out = []
    for raw in (markdown or "").splitlines():
        plain = raw.strip().lstrip("#").strip().strip("*_ ").strip()
        if plain:
            out.append((plain, raw))
    return out


def _strip_ocr_edges(result: PageResult, lines: list[tuple[str, str]], repeated) -> str:
    """X4 step 2 on an OCR page: drop the running header, footer and page number the scan shows.
    Blank lines stay, so paragraphs stay apart; table rows are never dropped."""
    drop = set()
    for i, (plain, raw) in enumerate(lines):
        if not raw.lstrip().startswith("|") and is_edge_noise(plain, i, len(lines), repeated):
            number = printed_page_number(plain)
            if number and not result.printed_page:
                result.printed_page = number
            result.removed_lines.append(plain)
            drop.add(raw)
    return "\n".join(r for r in result.ocr_result.text_markdown.splitlines() if r not in drop)


def _text_layer(page, cfg: ExtractConfig) -> dict:
    """Tables first (with caption and unit), then the words outside the tables in reading order."""
    tables = []
    try:
        found = page.find_tables()
    except Exception:
        found = []
    for t in found:
        rows = t.extract()
        if len(rows) >= 2 and max((len(r) for r in rows), default=0) >= 2:
            tables.append({"bbox": t.bbox, "rows": rows})

    def outside_tables(obj) -> bool:
        x = (obj.get("x0", 0) + obj.get("x1", 0)) / 2
        y = (obj.get("top", 0) + obj.get("bottom", 0)) / 2
        return not any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in (t["bbox"] for t in tables))

    words = page.filter(outside_tables).extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False,
                                                      use_text_flow=False)
    lines, two_columns = reading_order(words, float(page.width), cfg.column_gap_pt)
    return {"lines": lines, "tables": tables, "two_columns": two_columns, "body": body_size(lines)}


def _text_blocks(result: PageResult, info: dict, repeated: tuple[set[str], set[str]],
                 tracker: SectionTracker) -> list[Block]:
    lines = info["lines"]
    body = info["body"]
    kept = []
    for i, ln in enumerate(lines):
        # "(₹ in crore)" sits at the top of most statement pages: it repeats, but it is the table's unit, not noise
        is_unit_line = len(ln.text.strip()) <= 40 and bool(find_unit(ln.text))
        if not is_unit_line and is_edge_noise(ln.text, i, len(lines), repeated,
                                              is_heading=heading_level(ln, body) is not None):
            number = printed_page_number(ln.text) if (i < EDGE_LINES or i >= len(lines) - EDGE_LINES) else None
            if number and not result.printed_page:
                result.printed_page = number
            result.removed_lines.append(ln.text)
            continue
        kept.append(ln)
    if info.get("two_columns"):
        result.flags.append("TWO_COLUMN")
    # the body font, without the running header and footer; on a page with very few lines (a statement page with a
    # title, a caption and a table) the most common size can be the title's, so take the smallest size instead
    if len(kept) >= 4:
        body = body_size(kept) or body
    elif kept:
        body = min(ln.size for ln in kept)

    # place each table among the lines by its top; the line just above it is its caption
    tables = sorted(info["tables"], key=lambda t: t["bbox"][1])
    blocks: list[Block] = []
    pending: list = []
    for ln in kept:
        while tables and tables[0]["bbox"][1] < ln.top:
            blocks += _flush_lines(pending, tracker, body)
            pending = []
            blocks.append(_table(tables.pop(0), blocks, tracker))
        pending.append(ln)
    blocks += _flush_lines(pending, tracker, body)
    for t in tables:
        blocks.append(_table(t, blocks, tracker))
    return blocks


def _flush_lines(lines, tracker, body) -> list[Block]:
    return lines_to_blocks(lines, tracker, "text", body) if lines else []


def _table(t: dict, blocks: list[Block], tracker: SectionTracker) -> Block:
    """The paragraph just above the table is its caption when it is short; the unit is looked for there."""
    caption = ""
    if blocks and blocks[-1].type == "paragraph" and len(blocks[-1].text) <= 160:
        caption = blocks.pop().text
    header = " ".join(str(c or "") for c in t["rows"][0])
    unit = find_unit(caption, header)
    if not unit and blocks and blocks[-1].type == "heading":
        unit = find_unit(blocks[-1].text)
    return table_block(t["rows"], caption, unit, tracker.path, "text")


def _pypdf_page_text(path: str, page_no: int) -> str:
    from pypdf import PdfReader
    try:
        return PdfReader(path).pages[page_no - 1].extract_text() or ""
    except Exception as e:
        log.warning("pypdf also failed on page %s: %s", page_no, e)
        return ""


def _ocr_page(path: str, result: PageResult, cfg: ExtractConfig, ocr: OcrEngine | None) -> None:
    """X5 for one page: sets result.ocr_result and usage, or flags OCR_FAILED. Blocks are made later, in page order."""
    if ocr is None:
        result.flags.append("OCR_FAILED")
        result.signals["ocr_error"] = "no OCR engine configured"
        return
    try:
        image = render_pdf_page(path, result.page, cfg.ocr_max_edge_px)
        try:
            out = ocr.read(image)
        finally:
            image.close()
    except OcrFailed as e:
        result.flags.append("OCR_FAILED")
        result.signals["ocr_error"] = str(e)[:200]
        result.ocr = e.usage
        return
    result.ocr = out.usage
    result.ocr_result = out


def classify_only(path: Path | str, cfg: ExtractConfig) -> list[tuple[int, str, PageSignals]]:
    """X3 classes without extraction; used by the extraction quality check (route correct)."""
    out = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            s = page_signals(page)
            out.append((i, classify(s, cfg), s))
    return out
