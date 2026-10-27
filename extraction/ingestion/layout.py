"""Reading order and blocks (contract 10 X4 steps 2, 5 and 6).

Words -> lines (two-column pages are read left band, then right band) -> blocks: heading, paragraph, list, table.
The section path ("4 Travel > 4.2 Per diem") is kept in a SectionTracker that carries over to the next page.
"""
import re
import statistics
from dataclasses import dataclass, field

from ingestion.clean import join_lines, normalise
from ingestion.tables import parse_markdown_table, table_block
from ingestion.types import Block

NUMBERED_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Z][^.:;]{0,78})$")
LIST_ITEM = re.compile(r"^(?:[-•*▪●◦–]\s+|\(?[a-z0-9ivx]{1,3}[.)]\s+)", re.IGNORECASE)
ALL_CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9 &,/()'-]{2,78}$")


# ---- section path -------------------------------------------------------------------------------------------------

@dataclass
class SectionTracker:
    stack: list[tuple[int, str]] = field(default_factory=list)

    def enter(self, level: int, title: str) -> str:
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        self.stack.append((level, title))
        return self.path

    @property
    def path(self) -> str:
        return " > ".join(t for _, t in self.stack)


def numbered_level(text: str) -> int | None:
    m = NUMBERED_HEADING.match(text)
    if not m or len(text.split()) > 12:
        return None
    return m.group(1).count(".") + 1


# ---- lines from pdfplumber words ----------------------------------------------------------------------------------

@dataclass
class Line:
    text: str
    top: float
    bottom: float
    x0: float
    x1: float
    size: float
    bold: bool


def words_to_lines(words: list[dict], tolerance: float = 3.0) -> list[Line]:
    """Group words whose tops are within `tolerance` points; words in a line are read left to right."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    out = []
    for ws in lines:
        ws.sort(key=lambda w: w["x0"])
        sizes = [w.get("size", 0) or 0 for w in ws]
        out.append(Line(
            text=" ".join(w["text"] for w in ws),
            top=min(w["top"] for w in ws), bottom=max(w["bottom"] for w in ws),
            x0=min(w["x0"] for w in ws), x1=max(w["x1"] for w in ws),
            size=statistics.median(sizes) if sizes else 0,
            bold=all("bold" in str(w.get("fontname", "")).lower() for w in ws),
        ))
    return out


def column_split(words: list[dict], page_width: float, gap_pt: float) -> float | None:
    """X4 step 5: the x of an empty vertical band at least `gap_pt` wide, free through 80 % of the text height,
    with text on both sides. None for a one-column page."""
    if len(words) < 20:
        return None
    top = min(w["top"] for w in words)
    bottom = max(w["bottom"] for w in words)
    height = bottom - top
    if height <= 0:
        return None
    best = None
    centre = page_width / 2
    x = page_width * 0.3
    while x <= page_width * 0.7 - gap_pt:
        lo, hi = x, x + gap_pt
        blocking = [w for w in words if w["x0"] < hi and w["x1"] > lo]
        if _covered(blocking) <= 0.2 * height:
            left = [w for w in words if w["x1"] <= lo]
            right = [w for w in words if w["x0"] >= hi]
            if _covered(left) >= 0.3 * height and _covered(right) >= 0.3 * height:
                mid = (lo + hi) / 2
                if best is None or abs(mid - centre) < abs(best - centre):
                    best = mid
        x += 2
    return best


def _covered(words: list[dict]) -> float:
    """Total height covered by the vertical extents of the words (overlaps counted once)."""
    spans = sorted((w["top"], w["bottom"]) for w in words)
    total, cur_start, cur_end = 0.0, None, None
    for s, e in spans:
        if cur_end is None or s > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = s, e
        else:
            cur_end = max(cur_end, e)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def reading_order(words: list[dict], page_width: float, gap_pt: float) -> tuple[list[Line], bool]:
    """Lines in reading order, and whether the page was read as two columns."""
    split = column_split(words, page_width, gap_pt)
    if split is None:
        return words_to_lines(words), False
    half = gap_pt / 2
    left = [w for w in words if w["x1"] <= split + half]
    right = [w for w in words if w["x0"] >= split - half and w not in left]
    full = [w for w in words if w not in left and w not in right]
    col_top = min((w["top"] for w in left + right), default=0)
    above = [w for w in full if w["bottom"] <= col_top + 1]
    below = [w for w in full if w not in above]
    lines = words_to_lines(above) + words_to_lines(left) + words_to_lines(right) + words_to_lines(below)
    return lines, True


# ---- blocks from lines --------------------------------------------------------------------------------------------

def body_size(lines: list[Line]) -> float:
    """The most common font size, weighted by text length."""
    weights: dict[float, int] = {}
    for ln in lines:
        key = round(ln.size, 1)
        weights[key] = weights.get(key, 0) + len(ln.text)
    return max(weights, key=weights.get) if weights else 0.0


def heading_level(line: Line, body: float) -> int | None:
    """A line in a larger font than the body, a numbered short line ("4.2 Per diem"), or a short all-bold line."""
    text = line.text.strip()
    words = len(text.split())
    if not text or words > 15 or text.endswith((".", ",", ";", "-")):
        return None
    level = numbered_level(text)
    if level:
        return level
    if body and line.size >= body * 1.15:
        return 1 if line.size >= body * 1.5 else 2
    if line.bold and words <= 10 and not text[0].isdigit():
        return 2
    return None


def lines_to_blocks(lines: list[Line], tracker: SectionTracker, method: str = "text",
                    body: float | None = None) -> list[Block]:
    """Headings start sections; lines join into paragraphs; list items become one list block."""
    body = body if body is not None else body_size(lines)
    gaps = [b.top - a.top for a, b in zip(lines, lines[1:], strict=False) if b.top - a.top > 0]
    step = statistics.median(gaps) if gaps else 0
    blocks: list[Block] = []
    para: list[str] = []
    items: list[str] = []

    def flush():
        nonlocal para, items
        if para:
            text = para[0]
            for nxt in para[1:]:
                text = join_lines(text, nxt)
            blocks.append(Block("paragraph", normalise(text), tracker.path, method))
        if items:
            blocks.append(Block("list", "\n".join(normalise(i) for i in items), tracker.path, method))
        para, items = [], []

    prev: Line | None = None
    for ln in lines:
        text = ln.text.strip()
        if not text:
            continue
        new_para = prev is not None and step and (ln.top - prev.top) > 1.5 * step
        level = heading_level(ln, body)
        if level:
            flush()
            title = normalise(text)
            path = tracker.enter(level, title)
            blocks.append(Block("heading", title, path, method, level=level))
        elif LIST_ITEM.match(text):
            if para:
                flush()
            items.append(text)
        elif items and not new_para:
            items[-1] = join_lines(items[-1], text)          # continuation line of a list item
        else:
            if new_para or items:
                flush()
            para.append(text)
        prev = ln
    flush()
    return blocks


# ---- blocks from plain text (pypdf fallback, TXT, OCR Markdown) -----------------------------------------------------

def text_to_blocks(text: str, tracker: SectionTracker, method: str = "text", markdown: bool = False) -> list[Block]:
    """Paragraphs split on blank lines. With `markdown`, `#` lines are headings and `|` lines are tables."""
    blocks: list[Block] = []
    lines = text.splitlines()
    i = 0
    para: list[str] = []
    items: list[str] = []

    def flush():
        nonlocal para, items
        if para:
            joined = para[0]
            for nxt in para[1:]:
                joined = join_lines(joined, nxt)
            blocks.append(Block("paragraph", normalise(joined), tracker.path, method))
        if items:
            blocks.append(Block("list", "\n".join(normalise(x) for x in items), tracker.path, method))
        para, items = [], []

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s:
            flush()
            i += 1
            continue
        if markdown and s.startswith("|"):
            flush()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            caption = blocks[-1].text if blocks and blocks[-1].type == "paragraph" and len(blocks[-1].text) < 120 else ""
            if caption:
                blocks.pop()
            from ingestion.tables import find_unit
            rows = parse_markdown_table(table_lines)
            unit = find_unit(caption, " ".join(rows[0]) if rows else "")
            blocks.append(table_block(rows, caption, unit, tracker.path, method))
            continue
        md_heading = re.match(r"^(#{1,6})\s+(.+)$", s) if markdown else None
        level = len(md_heading.group(1)) if md_heading else numbered_level(s)
        if level is None and not markdown and ALL_CAPS_HEADING.match(s) and len(s.split()) <= 10:
            level = 1
        if level:
            flush()
            title = normalise(md_heading.group(2) if md_heading else s).strip("*_ ")
            blocks.append(Block("heading", title, tracker.enter(level, title), method, level=level))
        elif LIST_ITEM.match(s):
            if para:
                flush()
            items.append(s)
        elif items:
            items[-1] = join_lines(items[-1], s)
        else:
            para.append(s)
        i += 1
    flush()
    return blocks
