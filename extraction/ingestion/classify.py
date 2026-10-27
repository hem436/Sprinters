"""X3 Classify each PDF page (contract 10 section 5). Signals are cheap and local; the first matching rule wins."""
import re
from dataclasses import asdict, dataclass

from ingestion.config import ExtractConfig
from ingestion.types import PageClass

_CID = re.compile(r"\(cid:\d+\)")
_TOKEN = re.compile(r"\S+")
_NUMERIC = re.compile(r"^[(\-–₹$]*\d[\d,.\-–/%]*\)?%?$")


@dataclass(frozen=True)
class PageSignals:
    chars: int            # text-layer characters (no whitespace)
    cid_ratio: float      # share of (cid:NN) or U+FFFD characters: a broken font map
    image_cover: float    # image area / page area, clipped to the page, at most 1
    tables: int           # pdfplumber tables with at least 3 rows and 2 columns
    num_ratio: float      # numeric tokens / all tokens

    def as_dict(self) -> dict:
        return {k: round(v, 3) if isinstance(v, float) else v for k, v in asdict(self).items()}


def classify(s: PageSignals, cfg: ExtractConfig) -> PageClass:
    """The routing rule. Order matters: it is the order of the table in contract 10 section 5."""
    if s.chars < cfg.blank_max_chars and s.image_cover < cfg.blank_max_image_cover:
        return "BLANK"
    if s.cid_ratio > cfg.max_garbage_ratio:
        return "GARBLED"
    if s.chars < cfg.min_text_chars and s.image_cover >= cfg.scanned_image_cover:
        return "SCANNED"
    if s.chars >= cfg.min_text_chars and s.image_cover >= cfg.mixed_image_cover:
        return "MIXED"
    if s.tables >= 1 or s.num_ratio >= cfg.table_num_ratio:
        return "TABLE_HEAVY"
    return "TEXT"


def page_signals(page, raw_text: str | None = None) -> PageSignals:
    """Signals for one pdfplumber page. `raw_text` may be passed when the caller already extracted it."""
    text = raw_text if raw_text is not None else (page.extract_text() or "")
    # (cid:NN), U+FFFD and NUL all mean a glyph without a Unicode mapping
    cid_count = len(_CID.findall(text)) + text.count("�") + text.count("\x00")
    plain = _CID.sub("", text).replace("�", "").replace("\x00", "")
    visible = sum(1 for ch in plain if not ch.isspace())
    total = visible + cid_count
    cid_ratio = cid_count / total if total else 0.0

    area = float(page.width * page.height) or 1.0
    covered = 0.0
    for im in page.images:
        x0, x1 = max(im["x0"], 0), min(im["x1"], page.width)
        top, bottom = max(im["top"], 0), min(im["bottom"], page.height)
        if x1 > x0 and bottom > top:
            covered += (x1 - x0) * (bottom - top)
    image_cover = min(covered / area, 1.0)

    tables = 0
    try:
        for t in page.find_tables():
            rows = t.extract()
            if len(rows) >= 3 and max((len(r) for r in rows), default=0) >= 2:
                tables += 1
    except Exception:  # a broken page must not stop classification
        tables = 0

    tokens = _TOKEN.findall(plain)
    num_ratio = sum(1 for t in tokens if _NUMERIC.match(t)) / len(tokens) if tokens else 0.0
    return PageSignals(chars=visible, cid_ratio=cid_ratio, image_cover=image_cover, tables=tables, num_ratio=num_ratio)
