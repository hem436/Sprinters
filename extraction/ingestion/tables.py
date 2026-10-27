"""X4 step 1: tables to Markdown, with the caption and the unit line kept beside them (contract 10 section 6).

Cell text is never changed: no rounding, no reformatting. Only line breaks inside a cell become spaces, and a pipe
is escaped, because both would break the Markdown table.
"""
import re

from ingestion.types import Block

# "₹ in crore", "(Rs. in lakhs)", "in millions", "Amount in INR million", "(%)", "USD thousand"
UNIT_RE = re.compile(
    r"(?:(?:₹|rs\.?|inr|usd|us\$|\$|amount)\s*)?(?:\(?\s*in\s+)?(?:₹|rs\.?|inr|usd|\$)?\s*"
    r"\b(crores?|lakhs?|lacs?|millions?|mn|billions?|bn|thousands?)\b|\(\s*%\s*\)|\bin\s+%|\bper\s*cent\b",
    re.IGNORECASE,
)


def find_unit(*lines: str) -> str:
    """The first unit phrase in the given lines, as printed (trimmed), or ""."""
    for line in lines:
        if not line:
            continue
        m = UNIT_RE.search(line)
        if m:
            return _unit_phrase(line, m)
    return ""


def _unit_phrase(line: str, m: re.Match) -> str:
    """Widen the match to its bracketed phrase ("(₹ in crore)"), else to the whole line when it is a short unit
    line ("₹ in crore"), else keep only the match."""
    start, end = m.span()
    open_at = line.rfind("(", 0, start + 1)
    close_at = line.find(")", end - 1)
    if open_at != -1 and close_at != -1 and close_at - open_at < 40 and ")" not in line[open_at:start]:
        return line[open_at:close_at + 1].strip()
    stripped = line.strip()
    if len(stripped) <= 25:
        return stripped
    return line[start:end].strip()


def clean_cell(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text.replace("|", "\\|")


def normalise_rows(rows: list[list]) -> list[list[str]]:
    """Square the rows (pad short ones), clean cells, drop rows and columns that are empty everywhere."""
    rows = [[clean_cell(c) for c in r] for r in rows if r is not None]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    return [[r[j] for j in keep] for r in rows]


def to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def table_block(rows: list[list[str]], caption: str, unit: str, section: str, method: str = "text") -> Block:
    """One table as one block. Its text is caption, unit and the Markdown table, the way the chunk shows it."""
    rows = normalise_rows(rows)
    return Block(type="table", text=table_text(caption, unit, to_markdown(rows)), section=section, method=method,
                 caption=caption, unit=unit, rows=rows)


def table_text(caption: str, unit: str, markdown: str) -> str:
    """Caption, then the unit line unless the caption already holds it, then the table."""
    caption, unit = caption.strip(), unit.strip()
    parts = [p for p in (caption, "" if unit and unit in caption else unit, markdown) if p]
    return "\n".join(parts)


# ---- Markdown tables in OCR output (X5 returns tables as Markdown) ---------------------------------------------------

_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def parse_markdown_table(lines: list[str]) -> list[list[str]]:
    """Rows of a Markdown table; the separator line is dropped. Escaped pipes stay inside their cell."""
    rows = []
    for line in lines:
        s = line.strip()
        if _SEPARATOR.match(s):
            continue
        s = s.strip("|")
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", s)]
        rows.append(cells)
    return rows
