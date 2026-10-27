"""WP-EX6 table rules: contract 14 F2, F3, F6, F7(a), without PDFs."""
import copy

from ingestion.fin_parse import DICTIONARY
from ingestion.fin_tables import TableIn, analyse, join_continuations
from tests.files import PL_HEADER, PL_ROWS

CTX = "Consolidated Statement of Profit and Loss"


def _resolve(norm: str) -> str:
    return DICTIONARY.get(norm, "")


def _pl(rows=None, **kw) -> TableIn:
    return TableIn(page=52, rows=[PL_HEADER, *copy.deepcopy(rows or PL_ROWS)],
                   caption=kw.pop("caption", "for the year ended 31 March 2025"),
                   unit=kw.pop("unit", "(₹ in crore)"), context=kw.pop("context", CTX), **kw)


def _checks(ft, name):
    return [c for c in ft.checks if c["check"] == name]


def test_clean_pl_is_approved_with_facts():
    ft = analyse(_pl(), "t1", _resolve)
    assert ft.status == "APPROVED", ft.checks
    assert (ft.statement, ft.basis, ft.unit.scale) == ("PL", "CONSOLIDATED", 10_000_000)
    rev = {f.period: f for f in ft.facts if f.metric == "revenue"}
    assert rev["FY2024-25"].value_num == 11_256 * 10_000_000 and rev["FY2024-25"].value_printed == "11,256.00"
    assert rev["FY2023-24"].value_num == 10_050 * 10_000_000
    assert rev["FY2024-25"].row_no == 1 and rev["FY2024-25"].col_no == 2 and rev["FY2024-25"].page == 52
    eps = next(f for f in ft.facts if f.metric == "eps_basic" and f.period == "FY2024-25")
    assert (eps.value_kind, eps.value_num) == ("PER_SHARE", 4567)
    # F3: the Note column is dropped; "Expenses" (no values) gives no fact
    assert all(f.col_no != 1 for f in ft.facts) and not any(f.line_label == "Expenses" for f in ft.facts)
    totals = _checks(ft, "TOTAL")
    assert len(totals) == 4 and all(c["ok"] for c in totals)          # total income and total expenses, 2 years
    assert totals[0]["parts"] == ["Revenue from operations", "Other income"]


def test_totals_check_flags_review():
    """Contract 14: a misread component makes the total check fail; the table waits for review."""
    rows = copy.deepcopy(PL_ROWS)
    rows[0][2] = "11,265.00"                                          # 6 and 5 swapped by a bad read
    ft = analyse(_pl(rows), "t1", _resolve)
    failed = [c for c in _checks(ft, "TOTAL") if not c["ok"]]
    assert ft.status == "NEEDS_REVIEW"
    assert [(c["row"], c["period"]) for c in failed] == [("Total income", "FY2024-25")]


def test_total_within_printed_precision():
    rows = copy.deepcopy(PL_ROWS)
    rows[2][2] = "11,500.01"                                          # 1 unit of the printed precision: still ok
    assert analyse(_pl(rows), "t1", _resolve).status == "APPROVED"
    rows[2][2] = "11,500.02"
    assert analyse(_pl(rows), "t1", _resolve).status == "NEEDS_REVIEW"


def test_balance_sheet_subtotals():
    rows = [["Particulars", "As at 31 March 2025"],
            ["Property, plant and equipment", "1,000"], ["Investments", "500"],
            ["Total non-current assets", "1,500"],
            ["Trade receivables", "300"], ["Cash and cash equivalents", "200"],
            ["Total current assets", "500"],
            ["Total assets", "2,000"],
            ["Equity share capital", "100"], ["Other equity", "900"], ["Total equity", "1,000"],
            ["Borrowings", "600"], ["Total non-current liabilities", "600"],
            ["Trade payables", "400"], ["Total current liabilities", "400"],
            ["Total liabilities", "1,000"],
            ["Total equity and liabilities", "2,000"]]
    ft = analyse(TableIn(page=50, rows=rows, unit="(₹ in crore)", context="Consolidated Balance Sheet"), "t", _resolve)
    totals = _checks(ft, "TOTAL")
    assert all(c["ok"] for c in totals), totals
    assert next(c for c in totals if c["row"] == "Total assets")["parts"] == ["Total non-current assets",
                                                                                "Total current assets"]
    assert next(c for c in totals if c["row"] == "Total equity and liabilities")["parts"] == ["Total equity",
                                                                                               "Total liabilities"]
    assert ft.statement == "BS" and {f.metric for f in ft.facts} >= {"total_assets", "cash", "borrowings"}


def test_standalone_from_caption_and_unknown_basis():
    ft = analyse(_pl(context="Annual report", caption="Standalone Statement of Profit and Loss"), "t", _resolve)
    assert ft.basis == "STANDALONE" and all(f.basis == "STANDALONE" for f in ft.facts)
    ft = analyse(_pl(context="Annual report", caption="Profit and loss"), "t", _resolve)
    assert ft.status == "NEEDS_REVIEW" and _checks(ft, "BASIS_UNKNOWN")


def test_unknown_unit_waits_for_review():
    ft = analyse(_pl(unit="", caption="for the year"), "t", _resolve)
    assert _checks(ft, "UNIT_UNKNOWN") and ft.status == "NEEDS_REVIEW"


def test_unmapped_label_stored_but_not_mapped():
    rows = copy.deepcopy(PL_ROWS)
    rows[0][0] = "Total income from operations"
    ft = analyse(_pl(rows), "t", _resolve)
    fact = next(f for f in ft.facts if f.line_label == "Total income from operations")
    assert fact.metric == "" and ft.status == "NEEDS_REVIEW"
    assert _checks(ft, "UNMAPPED")[0]["labels"] == ["Total income from operations"]
    relaxed = analyse(_pl(rows), "t", _resolve, review_unmapped=False)
    assert _checks(relaxed, "UNMAPPED")[0]["ok"]


def test_suspect_number_waits_for_review():
    rows = copy.deepcopy(PL_ROWS)
    rows[1][2] = "2,4S.00"
    ft = analyse(_pl(rows), "t", _resolve)
    assert _checks(ft, "NUMBER_SUSPECT")[0]["cells"][0]["printed"] == "2,4S.00" and ft.status == "NEEDS_REVIEW"


def test_ocr_table_always_reviewed():
    ft = analyse(_pl(source="ocr"), "t", _resolve)
    assert ft.status == "NEEDS_REVIEW" and _checks(ft, "OCR_SOURCE")


def test_merged_header_filled_from_left():
    rows = [["Particulars", "Year ended 31 March", ""], ["", "2025", "2024"],
            ["Revenue from operations", "11,256", "10,050"]]
    ft = analyse(TableIn(page=1, rows=rows, unit="(₹ in crore)", context=CTX), "t", _resolve)
    assert {f.period for f in ft.facts} == {"FY2024-25", "FY2023-24"}


def test_segment_table():
    rows = [["Particulars", "FY2024-25", "FY2023-24"],
            ["Segment revenue", "", ""],
            ["Payments", "7,000", "6,200"], ["Lending", "4,256", "3,850"],
            ["Total segment revenue", "11,256", "10,050"],
            ["Segment results", "", ""],
            ["Payments", "1,900", "1,700"], ["Lending", "1,100", "900"]]
    ft = analyse(TableIn(page=60, rows=rows, unit="(₹ in crore)", context="Consolidated segment information"), "t",
                 _resolve, review_unmapped=False)
    seg = [(f.segment, f.period, f.value_printed) for f in ft.facts if f.metric == "segment_revenue"]
    assert ("Payments", "FY2024-25", "7,000") in seg and ("Lending", "FY2023-24", "3,850") in seg
    assert len(seg) == 4                                              # results rows are not revenue
    assert all(c["ok"] for c in _checks(ft, "TOTAL"))


def test_join_continuation_with_repeated_header():
    a = TableIn(page=52, rows=[PL_HEADER, *PL_ROWS[:6]])
    b = TableIn(page=53, rows=[PL_HEADER, *PL_ROWS[6:]])
    joined = join_continuations([a, b])
    assert len(joined) == 1 and joined[0].pages == [52, 53] and len(joined[0].rows) == 1 + len(PL_ROWS)
    ft = analyse(TableIn(**{**joined[0].__dict__, "unit": "(₹ in crore)", "context": CTX}), "t", _resolve)
    assert ft.status == "APPROVED"
    assert next(f for f in ft.facts if f.metric == "pat").page == 53


def test_join_continuation_without_header():
    a = TableIn(page=52, rows=[PL_HEADER, *PL_ROWS[:6]])
    b = TableIn(page=53, rows=[*PL_ROWS[6:]])
    assert len(join_continuations([a, b])) == 1


def test_no_join_when_columns_differ_or_pages_apart():
    a = TableIn(page=52, rows=[PL_HEADER, *PL_ROWS[:3]])
    assert len(join_continuations([a, TableIn(page=53, rows=[["x", "1"], ["y", "2"]])])) == 2
    assert len(join_continuations([a, TableIn(page=55, rows=[PL_HEADER, *PL_ROWS[3:]])])) == 2


def test_table_without_periods_is_not_financial():
    rows = [["Name", "Role"], ["A. Kumar", "Director"], ["B. Singh", "CFO"]]
    assert analyse(TableIn(page=3, rows=rows), "t", _resolve) is None
