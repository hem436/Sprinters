"""Contract 14 F1 to F7 as pure functions: page tables in, financial tables with facts and checks out.

F1 Find      tables from X4 (pdfplumber) and X5 (OCR Markdown); a numeric page with no ruled table goes to the vision
             model (fin_ai.GeminiTableReader), which returns the table as JSON
F2 Join      a table that continues on the next page (same header row, or no header and the same column count)
F3 Headers   each value column gets a period; the basis comes from the caption or the section; "Note" columns drop
F4 Unit      from the unit line, caption or header; one scale per table
F5 Numbers   fin_parse.parse_number; stored as integers in the base unit and as printed
F6 Labels    a dictionary of standard metrics; other labels wait for a person (a mapping proposal may be added later)
F7 Checks    (a) every "Total ..." row equals the rows above it, within 1 unit of its printed precision
             (b) restatements are found when the facts are written (fin_facts.py)
"""
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from ingestion.fin_parse import (
    Unit,
    decimals_printed,
    is_total_label,
    looks_numeric,
    normalise_label,
    parse_basis,
    parse_number,
    parse_period,
    parse_statement,
    parse_unit,
    to_base,
    value_kind,
)
from ingestion.types import PageResult

NOTE_HEADERS = {"note", "notes", "note no", "note nos", "notes no", "sch", "schedule"}


@dataclass
class TableIn:
    """One table as found on a page, before analysis."""
    page: int
    rows: list[list[str]]
    caption: str = ""
    unit: str = ""
    context: str = ""                 # section path and headings near the table: basis and statement come from here
    source: str = "text"              # text (pdfplumber), ocr (page OCR), vision (table vision call)
    row_pages: list[int] = field(default_factory=list)
    first_on_page: bool = True
    last_on_page: bool = True

    def __post_init__(self):
        if not self.row_pages:
            self.row_pages = [self.page] * len(self.rows)

    @property
    def pages(self) -> list[int]:
        return sorted(set(self.row_pages))


@dataclass
class Fact:
    period: str
    basis: str
    metric: str
    segment: str
    line_label: str
    label_norm: str
    value_kind: str
    value_num: int
    value_printed: str
    page: int
    row_no: int
    col_no: int


@dataclass
class FinTable:
    table_id: str
    pages: list[int]
    statement: str
    basis: str
    unit: Unit
    unit_printed: str
    caption: str
    source: str
    rows: list[list[str]]             # the table as read, for the review screen
    facts: list[Fact] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)

    @property
    def checks_passed(self) -> bool:
        return all(c.get("ok", True) for c in self.checks)

    @property
    def status(self) -> str:
        return "APPROVED" if self.checks_passed else "NEEDS_REVIEW"


# ---- F1 collect ----------------------------------------------------------------------------------------------------

def collect_tables(pages: list[PageResult]) -> list[TableIn]:
    """Every table block of every page, in reading order, with its context."""
    out: list[TableIn] = []
    for p in pages:
        blocks = [b for b in p.blocks if b.type == "table" and len(b.rows) >= 2]
        for i, b in enumerate(blocks):
            out.append(TableIn(page=p.page, rows=[list(r) for r in b.rows], caption=b.caption, unit=b.unit,
                               context=b.section, source="ocr" if b.method.startswith("ocr") else "text",
                               first_on_page=i == 0, last_on_page=i == len(blocks) - 1))
    return out


def needs_vision(page: PageResult) -> bool:
    """A page full of numbers on which pdfplumber found no ruled table: the table has no lines (F1)."""
    return (page.page_class == "TABLE_HEAVY" and not any(b.type == "table" for b in page.blocks)
            and float(page.signals.get("num_ratio", 0) or 0) >= 0.30)


# ---- F2 continuation -----------------------------------------------------------------------------------------------

def _row_key(row: list[str]) -> tuple:
    return tuple(" ".join(c.lower().split()) for c in row)


def _starts_with_data(rows: list[list[str]]) -> bool:
    return bool(rows) and any(parse_number(c) is not None and parse_period(c) is None for c in rows[0][1:])


def join_continuations(tables: list[TableIn]) -> list[TableIn]:
    out: list[TableIn] = []
    for t in tables:
        prev = out[-1] if out else None
        if (prev and t.page == max(prev.row_pages) + 1 and prev.last_on_page and t.first_on_page
                and len(t.rows[0]) == len(prev.rows[0])):
            if _row_key(t.rows[0]) == _row_key(prev.rows[0]):            # header repeated on the next page
                prev.rows += t.rows[1:]
                prev.row_pages += [t.page] * (len(t.rows) - 1)
                prev.last_on_page = t.last_on_page
                continue
            if _starts_with_data(t.rows):                                # no header, same column count
                prev.rows += t.rows
                prev.row_pages += [t.page] * len(t.rows)
                prev.last_on_page = t.last_on_page
                continue
        out.append(t)
    return out


# ---- F3 to F6 analyse ----------------------------------------------------------------------------------------------

def _header_count(rows: list[list[str]]) -> int:
    """Rows at the top whose value cells are text or periods, not amounts."""
    n = 0
    for row in rows:
        cells = [c for c in row[1:] if c.strip()]
        if cells and all(parse_number(c) is None or parse_period(c) is not None for c in cells):
            n += 1
            continue
        if not cells and n == 0 and not row[0].strip():
            n += 1                                                       # an empty top row
            continue
        break
    return n


def _column_headers(header_rows: list[list[str]], width: int) -> list[str]:
    """One header text per column. A merged cell is empty in the columns it spans: fill it from the left."""
    filled = []
    for row in header_rows:
        row = row + [""] * (width - len(row))
        new = list(row)
        for j in range(2, width):
            if not new[j].strip() and new[j - 1].strip() and parse_period(new[j - 1]) is None:
                new[j] = new[j - 1]
        filled.append(new)
    return [" ".join(r[j] for r in filled if r[j].strip()) for j in range(width)]


SEGMENT_STOP = re.compile(r"result|profit|loss|assets|liabilit|capital|expenditure", re.I)
SEGMENT_SKIP = re.compile(r"^(total|less|inter[- ]?segment|unallocable|unallocated|eliminat|net )", re.I)


def table_id_for(document_id: str, page: int, index: int) -> str:
    return "t_" + hashlib.sha1(f"{document_id}:{page}:{index}".encode()).hexdigest()[:10]


def analyse(t: TableIn, table_id: str, resolve: Callable[[str], str], review_unmapped: bool = True) -> FinTable | None:
    """F3 to F7(a) for one table. None when the table has no period columns (not a financial table)."""
    width = max(len(r) for r in t.rows)
    rows = [r + [""] * (width - len(r)) for r in t.rows]
    h = _header_count(rows)
    if h == 0 or h >= len(rows):
        return None
    headers = _column_headers(rows[:h], width)
    columns: list[tuple[int, str]] = []
    skipped = []
    for j in range(1, width):
        if normalise_label(headers[j]) in NOTE_HEADERS:
            continue                                                     # F3: the "Note" column is dropped
        period = parse_period(headers[j])
        if period:
            columns.append((j, period))
        elif headers[j].strip():
            skipped.append(headers[j])
    if not columns:
        return None

    statement = parse_statement(t.context, t.caption)
    basis_found = parse_basis(t.context, t.caption)
    basis = basis_found or "CONSOLIDATED"
    unit = parse_unit(t.unit, t.caption, " ".join(" ".join(r) for r in rows[:h]))
    ft = FinTable(table_id=table_id, pages=t.pages, statement=statement, basis=basis, unit=unit,
                  unit_printed=t.unit or "", caption=t.caption, source=t.source, rows=rows)
    if skipped:
        ft.checks.append({"check": "COLUMNS_SKIPPED", "ok": True, "headers": skipped})
    if basis_found is None:
        ft.checks.append({"check": "BASIS_UNKNOWN", "ok": False,
                          "detail": "neither 'consolidated' nor 'standalone' in the title or section; assumed CONSOLIDATED"})
    if t.source in ("ocr", "vision"):
        ft.checks.append({"check": "OCR_SOURCE", "ok": False,
                          "detail": "read by the vision model: a confident wrong digit cannot be seen (gap G7)"})

    suspect, unmapped, rounded = [], [], []
    in_segment_block = statement == "SEGMENT"
    amount_rows = False
    data_no = 0
    for i in range(h, len(rows)):
        row = rows[i]
        label = row[0].strip()
        values = {j: row[j].strip() for j, _ in columns if row[j].strip()}
        if not label:
            continue
        if not values:                                                   # a sub-heading row
            if statement == "SEGMENT":
                in_segment_block = not SEGMENT_STOP.search(label) and bool(re.search(r"revenue|income|sales", label, re.I))
            continue
        data_no += 1
        norm = normalise_label(label)
        segment = ""
        metric = resolve(norm)
        if statement == "SEGMENT" and not metric:
            if in_segment_block and not SEGMENT_SKIP.match(norm) and not is_total_label(label):
                metric, segment = "segment_revenue", label
        if not metric:
            unmapped.append(label)
        for j, period in columns:
            cell = values.get(j)
            if cell is None:
                continue
            value = parse_number(cell)
            if value is None:
                if looks_numeric(cell):
                    suspect.append({"row": label, "column": headers[j], "printed": cell})
                continue
            kind = value_kind(label, metric, unit)
            amount_rows = amount_rows or kind == "AMOUNT"
            num, was_rounded = to_base(value, kind, unit.scale)
            if was_rounded:
                rounded.append({"row": label, "printed": cell})
            ft.facts.append(Fact(period=period, basis=basis, metric=metric, segment=segment, line_label=label,
                                 label_norm=norm, value_kind=kind, value_num=num, value_printed=cell,
                                 page=t.row_pages[i], row_no=data_no, col_no=j))

    if amount_rows and not unit.known:
        ft.checks.append({"check": "UNIT_UNKNOWN", "ok": False,
                          "detail": "no unit line (crore, lakh, million...) near the table; values read as rupees"})
    if suspect:
        ft.checks.append({"check": "NUMBER_SUSPECT", "ok": False, "cells": suspect})
    totals = totals_check(rows, h, columns, headers)
    # a "Total ..." row that adds up is arithmetic, not a metric; any other unmapped label waits for a person (F6)
    sums = {c["row"] for c in totals if c["check"] == "TOTAL" and c["ok"]}
    unmapped = [lbl for lbl in dict.fromkeys(unmapped) if lbl not in sums]
    if unmapped:
        ft.checks.append({"check": "UNMAPPED", "ok": not review_unmapped, "labels": unmapped})
    if rounded:
        ft.checks.append({"check": "ROUNDED", "ok": True, "cells": rounded})
    ft.checks += totals
    return ft


# ---- F7(a) totals --------------------------------------------------------------------------------------------------

def totals_check(rows: list[list[str]], h: int, columns: list[tuple[int, str]], headers: list[str]) -> list[dict]:
    """Every "Total ..." row must equal a run of the rows (or subtotals) just above it, per column.

    Each column keeps a running list of values. At a total row the shortest run at the end of that list that adds up
    to the total (within 1 unit of the total's printed precision) is replaced by the total. So "Total assets" is
    checked against "Total non-current assets" + "Total current assets", and "Total tax expense" against the tax rows
    just above it, without knowing the layout in advance. A total with no matching run fails the check.
    """
    results = []
    for j, period in columns:
        seq: list[tuple[str, Decimal]] = []
        group = 0                     # rows added since the last sub-heading, total or result line
        for row in rows[h:]:
            label, cell = row[0].strip(), row[j].strip()
            value = parse_number(cell) if cell else None
            if not label:
                continue
            if value is None:         # a sub-heading such as "Expenses" or "Tax expense" starts a new group
                group = 0
                continue
            if not is_total_label(label) or not seq:
                seq.append((label, value))
                group = 0 if RESULT_LINE.match(normalise_label(label)) else group + 1
                continue
            tol = Decimal(1).scaleb(-decimals_printed(cell))
            match = None
            for k in range(1, len(seq) + 1):
                if abs(sum(v for _, v in seq[-k:]) - value) <= tol:
                    match = k
                    break
            if match:
                parts = [lbl for lbl, _ in seq[-match:]]
                del seq[-match:]
                results.append({"check": "TOTAL", "ok": True, "row": label, "period": period, "parts": parts})
            elif group:
                near = sum(v for _, v in seq[-group:])
                results.append({"check": "TOTAL", "ok": False, "row": label, "period": period, "column": headers[j],
                                "printed": cell, "detail": f"the {group} row(s) above add up to {near}, "
                                                           f"not to the printed total {cell}"})
            else:                     # a total line with no rows of its own above it: nothing to add up
                results.append({"check": "TOTAL_UNVERIFIED", "ok": True, "row": label, "period": period})
            seq.append((label, value))
            group = 0
    return results


# lines that close a part of a statement; rows after them start a new group
RESULT_LINE = re.compile(r"^(profit|loss|earnings|ebitda|ebit|net cash|net profit|net loss|net increase|"
                         r"net decrease|operating profit)\b")
