"""TXT (contract 10 X2): a unit is a section under a numbered or ALL-CAPS heading line; without headings, a run of
lines with the locator "lines 120-158". UTF-8 first, then cp1252.
"""
from pathlib import Path

from ingestion.layout import ALL_CAPS_HEADING, SectionTracker, numbered_level, text_to_blocks
from ingestion.types import PageResult

LINES_PER_UNIT = 40


def read_text(path: Path | str) -> str:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return numbered_level(s) is not None or (ALL_CAPS_HEADING.match(s) is not None and len(s.split()) <= 10)


def extract_text(path: Path | str, progress=None) -> list[PageResult]:
    lines = read_text(path).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tracker = SectionTracker()
    units: list[PageResult] = []

    has_headings = any(_is_heading(x) for x in lines)
    if has_headings:
        groups: list[list[str]] = [[]]
        for line in lines:
            # a heading starts a new unit only when the current one has text besides headings
            if _is_heading(line) and any(x.strip() and not _is_heading(x) for x in groups[-1]):
                groups.append([])
            groups[-1].append(line)
        for group in groups:
            blocks = text_to_blocks("\n".join(group), tracker)
            if blocks:
                units.append(PageResult(page=len(units) + 1, page_class="TEXT", method="text", blocks=blocks,
                                        section_label=tracker.path))
    else:
        # no headings: fixed runs of lines, cut at a blank line when there is one near the end of the run
        start = 0
        while start < len(lines):
            end = min(start + LINES_PER_UNIT, len(lines))
            if end < len(lines):
                for j in range(end, max(start + LINES_PER_UNIT // 2, start + 1), -1):
                    if not lines[j - 1].strip():
                        end = j
                        break
            label = f"lines {start + 1}-{end}"
            tracker.stack = [(1, label)]
            blocks = text_to_blocks("\n".join(lines[start:end]), tracker)
            if blocks:
                units.append(PageResult(page=len(units) + 1, page_class="TEXT", method="text", blocks=blocks,
                                        section_label=label))
            start = end
    for u in units:
        u.chars = sum(len(b.text) for b in u.blocks)
    if progress:
        progress("extracting", len(units), len(units))
    return units
