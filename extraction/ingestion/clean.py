"""X4 step 2: clean the text (FR-02).

- Remove lines that repeat in the same place (top or bottom of the page) on more than half of the pages: running
  headers, footers and page numbers. The removed lines go into the ExtractionReport.
- Join words split by a line-end hyphen; join lines broken inside a sentence (done in layout.py).
- NFKC and whitespace normalisation for prose. Table cells never pass through here, and no rule changes a number.
"""
import re
import unicodedata
from collections import Counter

EDGE_LINES = 3          # how many lines at the top and at the bottom of a page count as "header / footer zone"

_PAGE_NUMBER = re.compile(r"^(?:page\s+)?(\d{1,4}|[ivxlcdm]{1,7})(?:\s*(?:of|/)\s*\d{1,4})?$", re.IGNORECASE)
_SPACES = re.compile(r"[ \t  -​]+")


def normalise(text: str) -> str:
    """NFKC (ligatures such as "ﬁ" become "fi") and single spaces. Digits and their punctuation are unchanged."""
    text = unicodedata.normalize("NFKC", text)
    return _SPACES.sub(" ", text).strip()


def line_key(line: str) -> str:
    """Same key for "Page 3 of 10" and "Page 4 of 10": digits become #, case and spaces are ignored."""
    return re.sub(r"\d+", "#", normalise(line).lower())


def printed_page_number(line: str) -> str | None:
    m = _PAGE_NUMBER.match(normalise(line))
    return m.group(1) if m else None


FUZZY_MAX_WORDS = 6    # "Page 3 of 10", "Annual Report 2024-25 | 12": short lines whose numbers change per page


def exact_key(line: str) -> str:
    return normalise(line).lower()


def repeated_edge_lines(pages: list[list[str]], ratio: float) -> tuple[set[str], set[str]]:
    """Lines that sit in the top or bottom zone of more than `ratio` of the pages.

    Returns (exact keys, digit-free keys). A digit-free key ("page # of #") is only collected from short lines, so a
    content line such as "Section 3 Travel rules" at the top of each page is not taken for a running header.
    Needs at least 2 pages; with one page nothing can repeat.
    """
    if len(pages) < 2:
        return set(), set()
    exact: Counter[str] = Counter()
    fuzzy: Counter[str] = Counter()
    for lines in pages:
        zone = [x for x in lines[:EDGE_LINES] + lines[-EDGE_LINES:] if x.strip()]
        exact.update({exact_key(x) for x in zone})
        fuzzy.update({line_key(x) for x in zone if len(x.split()) <= FUZZY_MAX_WORDS})
    limit = ratio * len(pages)
    return {k for k, n in exact.items() if n > limit}, {k for k, n in fuzzy.items() if n > limit}


def is_edge_noise(line: str, index: int, total: int, repeated: tuple[set[str], set[str]],
                  is_heading: bool = False) -> bool:
    """True for a running header or footer, or a bare page number, in the edge zone of the page.
    A heading is removed only when the very same text repeats; a changing number never makes it noise."""
    in_zone = index < EDGE_LINES or index >= total - EDGE_LINES
    if not in_zone:
        return False
    exact, fuzzy = repeated
    if exact_key(line) in exact:
        return True
    if is_heading:
        return False
    if len(line.split()) <= FUZZY_MAX_WORDS and line_key(line) in fuzzy:
        return True
    return printed_page_number(line) is not None


def join_lines(prev: str, nxt: str) -> str:
    """Join two lines of one paragraph. "manage-" + "ment" gives "management"; "2025-" + "26" keeps the hyphen."""
    if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha() and nxt[:1].islower():
        return prev[:-1] + nxt
    return prev + " " + nxt
