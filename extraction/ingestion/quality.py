"""X6 quality score and X7 review gate (contract 10 section 8).

| Page source       | Score                                                                      | Flags                   |
| text layer        | 1.0 - cid_ratio                                                            | GARBLED if routed to OCR|
| OCR               | 1 - illegible / max(words, 1); -0.1 if confidence medium, -0.25 if low     | HANDWRITTEN, HAS_TABLE  |
| OCR with a table  | the OCR score, -0.2 if a table number does not parse (1,23,4S6)            | NUMBER_SUSPECT          |
| any               | 0                                                                          | OCR_FAILED, BLANK       |

X7: quality < review_threshold, OCR_FAILED, or an OCR page with a table -> NEEDS_REVIEW (gap G7: a confident but
wrong digit cannot be seen in the score). A score of exactly the threshold passes.
"""
import re

from ingestion.config import ExtractConfig
from ingestion.types import PageResult

# a token that is mostly digits but has a letter a scanner confuses with a digit: 1,23,4S6  2O25  1l0
_DIGIT_LIKE = set("OoSlIBZ")
_CELL_TOKEN = re.compile(r"[^\s|]+")


def suspect_number(token: str) -> bool:
    t = token.strip("()₹$%,.-–")
    if len(t) < 3 or not any(ch.isdigit() for ch in t):
        return False
    letters = [ch for ch in t if ch.isalpha()]
    if not letters or any(ch not in _DIGIT_LIKE for ch in letters):
        return False
    digits = sum(ch.isdigit() for ch in t)
    return digits >= 2 and digits / len(t.replace(",", "").replace(".", "")) >= 0.6


def table_numbers_suspect(page: PageResult) -> bool:
    for b in page.blocks:
        if b.type != "table":
            continue
        for row in b.rows[1:] if b.rows else []:
            for cell in row[1:]:                      # the first column holds labels
                if any(suspect_number(tok) for tok in _CELL_TOKEN.findall(cell)):
                    return True
    return False


def score_page(page: PageResult, cfg: ExtractConfig) -> None:
    """Sets page.quality, page.flags and page.status in place."""
    flags = list(dict.fromkeys(page.flags))           # keep order, no repeats

    if page.page_class == "BLANK":
        page.quality, page.status = 0.0, "SKIPPED"
        page.flags = _add(flags, "BLANK")
        return
    if "OCR_FAILED" in flags:
        page.quality, page.status = 0.0, "NEEDS_REVIEW"
        page.flags = flags
        return

    has_table = any(b.type == "table" for b in page.blocks)
    if has_table:
        flags = _add(flags, "HAS_TABLE")

    text_score = 1.0 - float(page.signals.get("cid_ratio", 0.0) or 0.0)
    if page.page_class == "GARBLED":
        flags = _add(flags, "GARBLED")

    ocr = page.ocr_result
    if ocr is not None:
        score = 1.0 - ocr.illegible_count / max(ocr.word_count, 1)
        score -= {"high": 0.0, "medium": 0.1, "low": 0.25}[ocr.self_confidence]
        if ocr.has_handwriting:
            flags = _add(flags, "HANDWRITTEN")
        if ocr.has_table:
            flags = _add(flags, "HAS_TABLE")
        if "HAS_TABLE" in flags and table_numbers_suspect(page):
            score -= 0.2
            flags = _add(flags, "NUMBER_SUSPECT")
        if page.page_class == "MIXED":
            score = min(score, text_score)            # the weaker part decides
        quality = score
    else:
        quality = text_score

    page.quality = round(max(0.0, min(1.0, quality)), 3)
    page.flags = flags
    ocr_with_table = ocr is not None and "HAS_TABLE" in flags
    if page.quality < cfg.review_threshold or ocr_with_table:
        page.status = "NEEDS_REVIEW"
    else:
        page.status = "INDEXED"


def _add(flags: list[str], flag: str) -> list[str]:
    return flags if flag in flags else [*flags, flag]
