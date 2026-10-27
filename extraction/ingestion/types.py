"""Data shapes of the extraction part.

`Hit` and `Chunk` have exactly the fields of `model/agent/types.py` (Arka), so the agent can use our objects as they
are. Keep them in step: a change is a contract 10 change.
"""
from dataclasses import dataclass, field
from typing import Literal

PageClass = Literal["TEXT", "TABLE_HEAVY", "MIXED", "SCANNED", "GARBLED", "BLANK"]
PageStatus = Literal["INDEXED", "NEEDS_REVIEW", "APPROVED", "REJECTED", "SKIPPED"]
DocStatus = Literal["QUEUED", "EXTRACTING", "INDEXED", "PARTIAL_REVIEW", "FAILED", "SUPERSEDED", "DELETED"]
BlockType = Literal["heading", "paragraph", "list", "table"]

SEARCHABLE_PAGE_STATES = ("INDEXED", "APPROVED")


@dataclass(frozen=True)
class Hit:
    """Contract 10 section 9: one result of vector_search or bm25_search. Ranks start at 1."""
    chunk_id: str
    score: float
    rank: int


@dataclass(frozen=True)
class Chunk:
    """Contract 10 section 9: the chunk record, the fields the agent reads (same as Arka's agent.types.Chunk)."""
    chunk_id: str
    document_id: str
    doc_key: str
    title: str
    version: str
    effective_date: str
    page: int | None
    section: str
    method: str
    text: str
    injection_suspect: bool = False


@dataclass
class Block:
    """One piece of a page in reading order (X4, X5). Tables keep caption, unit and rows for the chunker."""
    type: BlockType
    text: str
    section: str = ""
    method: str = "text"                       # text, text_pypdf, ocr, ocr_tesseract
    level: int = 0                             # heading level (1 = top)
    caption: str = ""                          # tables only
    unit: str = ""                             # tables only, as printed, e.g. "₹ in crore"
    rows: list[list[str]] = field(default_factory=list)   # tables only; rows[0] is the header row


@dataclass
class OcrUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: str | None = None                # Decimal as text; None = price not set
    prompt_version: str = "ocr-v1"
    attempts: int = 1


@dataclass
class OcrResult:
    """X5: what the vision model returned for one page (the JSON schema), plus usage."""
    text_markdown: str
    has_handwriting: bool = False
    has_table: bool = False
    illegible_count: int = 0
    word_count: int = 0
    self_confidence: Literal["high", "medium", "low"] = "high"
    usage: OcrUsage | None = None


@dataclass
class PageResult:
    """One unit (PDF page, image, or DOCX/TXT section) after extraction, before chunking."""
    page: int
    page_class: PageClass
    method: str
    blocks: list[Block] = field(default_factory=list)
    chars: int = 0
    tables: int = 0
    quality: float = 1.0
    flags: list[str] = field(default_factory=list)
    status: PageStatus = "INDEXED"
    printed_page: str | None = None
    section_label: str | None = None           # DOCX/TXT locator: section path or "lines 120-158"
    ocr: OcrUsage | None = None
    ocr_result: OcrResult | None = None
    signals: dict = field(default_factory=dict)
    removed_lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text)
