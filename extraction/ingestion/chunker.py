"""X8 Chunking (contract 10 section 9): chunks pack whole blocks.

| Rule           | Value                                                                                     |
| Target size    | chunk.target_tokens = 400                                                                 |
| Hard maximum   | chunk.max_tokens = 700                                                                    |
| Overlap        | the last paragraph of the previous chunk, if under chunk.overlap_tokens = 80              |
| Page boundary  | a chunk never crosses a page (citations stay exact)                                       |
| Table          | one table is one chunk; a larger table splits by rows, every piece repeats caption, unit, header |
| Section        | a heading starts a new chunk, so a chunk belongs to one section (rule C1 compares sections) |
| Context header | `[{title} v{version} | {section} | p.{page}]` + text, in index_text only                   |

Tokens are estimated as characters / 4 (about right for English with the Gemini and Llama tokenizers). The estimate
only sizes chunks; no limit downstream depends on it being exact.
"""
import hashlib
import json
import math
import re
from dataclasses import dataclass

from ingestion.config import ExtractConfig
from ingestion.safety import injection_suspect, pii_found
from ingestion.tables import table_text, to_markdown
from ingestion.types import SEARCHABLE_PAGE_STATES, Block, PageResult

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def chunk_id(document_id: str, page: int, ordinal: int) -> str:
    return "c_" + hashlib.sha1(f"{document_id}:{page}:{ordinal}".encode()).hexdigest()[:12]


@dataclass
class _Item:
    block: Block
    overlap: bool = False


def chunk_document(doc: dict, pages: list[PageResult], cfg: ExtractConfig) -> list[dict]:
    """All chunk records of one document. `doc` has document_id, doc_key, title, version, effective_date,
    category, file_type."""
    out: list[dict] = []
    for page in pages:
        if page.status == "SKIPPED" or not page.blocks:
            continue
        for ordinal, blocks in enumerate(_page_groups(page.blocks, cfg)):
            out.append(_record(doc, page, ordinal, blocks))
    return out


def _page_groups(blocks: list[Block], cfg: ExtractConfig) -> list[list[Block]]:
    groups: list[list[Block]] = []
    buf: list[_Item] = []

    def content(items):
        return [i for i in items if not i.overlap]

    def size(items):
        return sum(tokens(i.block.text) for i in items)

    def flush(keep_overlap: bool) -> list[_Item]:
        """Emit the buffer; return the overlap that starts the next chunk."""
        nonlocal buf
        items = content(buf)
        if not items:
            buf = []
            return []
        if all(i.block.type == "heading" for i in items):
            return buf                               # headings wait for the content below them
        groups.append([i.block for i in buf])
        last = buf[-1].block
        carry = [_Item(last, overlap=True)] if (keep_overlap and last.type == "paragraph"
                                                 and tokens(last.text) < cfg.chunk_overlap_tokens) else []
        buf = []
        return carry

    for block in blocks:
        if block.type == "heading":
            if any(i.block.type != "heading" for i in content(buf)):
                flush(keep_overlap=False)            # a new section starts a new chunk, without overlap
            buf = [i for i in buf if not i.overlap]  # overlap never carries into another section
            buf.append(_Item(block))
        elif block.type == "table":
            heads = []
            if content(buf) and all(i.block.type == "heading" for i in content(buf)):
                heads = [i.block for i in content(buf)]
            else:
                flush(keep_overlap=False)
            buf = []
            for n, piece in enumerate(_table_pieces(block, cfg)):
                groups.append((heads if n == 0 else []) + [piece])
        else:
            for piece in _split_long(block, cfg):
                if content(buf) and size(buf) + tokens(piece.text) > cfg.chunk_target_tokens:
                    buf = flush(keep_overlap=True)
                buf.append(_Item(piece))
    if buf:
        if not content(buf):
            pass
        elif all(i.block.type == "heading" for i in content(buf)):
            if not groups:                           # a page with only a heading still gets one chunk
                groups.append([i.block for i in content(buf)])
        else:
            groups.append([i.block for i in buf])
    return groups


def _split_long(block: Block, cfg: ExtractConfig) -> list[Block]:
    """A paragraph or list over the hard maximum is cut at sentence ends (or words, as a last resort)."""
    if tokens(block.text) <= cfg.chunk_max_tokens:
        return [block]
    sep = "\n" if block.type == "list" else " "
    parts = block.text.split("\n") if block.type == "list" else _SENTENCE_END.split(block.text)
    pieces, cur = [], ""
    for part in parts:
        if tokens(part) > cfg.chunk_max_tokens:          # one huge sentence: cut by words
            if cur:                                      # what came before it goes first (review B2)
                pieces.append(cur)
                cur = ""
            words = part.split()
            step = max(1, cfg.chunk_target_tokens * 4 // 6)
            for i in range(0, len(words), step):
                pieces.append(" ".join(words[i:i + step]))
            continue
        if cur and tokens(cur + sep + part) > cfg.chunk_target_tokens:
            pieces.append(cur)
            cur = part
        else:
            cur = f"{cur}{sep}{part}" if cur else part
    if cur:
        pieces.append(cur)
    return [Block(block.type, p, block.section, block.method) for p in pieces]


def _table_pieces(block: Block, cfg: ExtractConfig) -> list[Block]:
    """One table, one chunk. A table over the hard maximum splits by rows; each piece repeats caption, unit, header."""
    if tokens(block.text) <= cfg.chunk_max_tokens or len(block.rows) < 3:
        return [block]
    header, body = block.rows[0], block.rows[1:]
    pieces, rows = [], []
    for row in body:
        trial = table_text(block.caption, block.unit, to_markdown([header, *rows, row]))
        if rows and tokens(trial) > cfg.chunk_max_tokens:
            pieces.append(rows)
            rows = []
        rows.append(row)
    if rows:
        pieces.append(rows)
    return [Block("table", table_text(block.caption, block.unit, to_markdown([header, *p])), block.section,
                  block.method, caption=block.caption, unit=block.unit, rows=[header, *p]) for p in pieces]


def _method(blocks: list[Block]) -> str:
    methods = {b.method for b in blocks}
    if "ocr" in methods or "ocr_tesseract" in methods:
        ocr = "ocr_tesseract" if "ocr_tesseract" in methods else "ocr"
        return f"text+{ocr}" if methods & {"text", "text_pypdf"} else ocr
    if "text_pypdf" in methods:
        return "text_pypdf"
    return "text+tables" if any(b.type == "table" for b in blocks) else "text"


def _record(doc: dict, page: PageResult, ordinal: int, blocks: list[Block]) -> dict:
    text = "\n\n".join(b.text for b in blocks if b.text)
    first = next((b for b in blocks if b.type != "heading"), blocks[0])
    section = first.section or page.section_label or ""
    header = f"[{doc['title']} v{doc['version']}"
    if section:
        header += f" | {section}"
    if doc["file_type"] not in ("docx", "txt"):
        header += f" | p.{page.page}"
    header += "]"
    return {
        "chunk_id": chunk_id(doc["document_id"], page.page, ordinal),
        "document_id": doc["document_id"], "doc_key": doc["doc_key"], "title": doc["title"],
        "version": doc["version"], "effective_date": doc["effective_date"], "category": doc["category"],
        "page": page.page, "ordinal": ordinal, "section": section,
        "block_types": json.dumps(list(dict.fromkeys(b.type for b in blocks))),
        "method": _method(blocks), "quality": page.quality,
        "searchable": int(page.status in SEARCHABLE_PAGE_STATES), "current": 1,
        "text": text, "index_text": f"{header} {text}",
        "injection_suspect": int(injection_suspect(text)), "pii_found": int(pii_found(text)),
    }
