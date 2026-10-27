"""WP-EX6 parsing rules: contract 14 F3 to F6."""
from decimal import Decimal

import pytest

from ingestion.fin_parse import (
    DICTIONARY,
    normalise_label,
    parse_basis,
    parse_number,
    parse_period,
    parse_statement,
    parse_unit,
    to_base,
    value_kind,
)


def test_parse_brackets_negative():
    """Contract 14: (1,234.50) in crore = -12,345,000,000 rupees, exactly."""
    value = parse_number("(1,234.50)")
    assert value == Decimal("-1234.50")
    assert to_base(value, "AMOUNT", parse_unit("(₹ in crore)").scale) == (-12_345_000_000, False)


@pytest.mark.parametrize("printed,expected", [
    ("1,23,456", Decimal(123456)), ("123,456", Decimal(123456)), ("-", Decimal(0)), ("—", Decimal(0)),
    ("nil", Decimal(0)), ("Nil", Decimal(0)), ("₹ 2,000", Decimal(2000)), ("12.5%", Decimal("12.5")),
    ("-45.10", Decimal("-45.10")), ("(98,765)", Decimal(-98765)),
])
def test_numbers(printed, expected):
    assert parse_number(printed) == expected


@pytest.mark.parametrize("printed", ["1,2345", "1,23,4S6", "12,34,5", "Note 21", "", None])
def test_not_numbers(printed):
    assert parse_number(printed) is None


def test_crore_vs_million_not_mixed():
    """The same amount printed in a crore table and a million table gives the same base-unit value."""
    crore = to_base(parse_number("1,000"), "AMOUNT", parse_unit("(₹ in crore)").scale)
    million = to_base(parse_number("10,000"), "AMOUNT", parse_unit("Amount in INR million").scale)
    assert crore == million == (10_000_000_000, False)
    assert parse_unit("(₹ in lakh)").scale == 100_000
    assert parse_unit("USD thousand").currency == "USD"
    assert not parse_unit("Particulars").known


@pytest.mark.parametrize("header,period", [
    ("FY2024-25", "FY2024-25"), ("FY 2024-25", "FY2024-25"), ("2024-25", "FY2024-25"), ("FY25", "FY2024-25"),
    ("Year ended 31 March 2025", "FY2024-25"), ("As at 31st March, 2024", "FY2023-24"), ("31.03.2025", "FY2024-25"),
    ("March 31, 2025", "FY2024-25"), ("31-Mar-25", "FY2024-25"), ("Q2 FY25", "FY2024-25 Q2"),
    ("Quarter ended 30 September 2024", "FY2024-25 Q2"), ("Quarter ended 31 March 2025", "FY2024-25 Q4"),
    ("Year ended 31 December 2024", "CY2024"), ("Nine months ended 31 Dec 2024", None), ("Particulars", None),
    ("Note", None),
])
def test_periods(header, period):
    assert parse_period(header) == period


def test_basis_and_statement():
    assert parse_basis("Consolidated Statement of Profit and Loss") == "CONSOLIDATED"
    assert parse_basis("Financial statements > Standalone Balance Sheet") == "STANDALONE"
    assert parse_basis("Notes", "Revenue table") is None
    assert parse_statement("Consolidated Statement of Profit and Loss") == "PL"
    assert parse_statement("Standalone Balance Sheet") == "BS"
    assert parse_statement("Statement of Cash Flows") == "CF"
    assert parse_statement("Annual report > Segment information") == "SEGMENT"
    assert parse_statement("Key highlights") == "OTHER"


def test_labels_and_dictionary():
    assert DICTIONARY[normalise_label("I. Revenue from operations")] == "revenue"
    assert DICTIONARY[normalise_label("(a) Employee benefits expense")] == "employee_cost"
    assert DICTIONARY[normalise_label("Depreciation & amortisation expense")] == "depreciation"
    assert DICTIONARY[normalise_label("Basic EPS (₹)")] == "eps_basic"
    # contract 14 F6: these mean the same only when a person agrees
    assert normalise_label("Total income from operations") not in DICTIONARY


def test_value_kinds_and_base_units():
    crore = parse_unit("(₹ in crore)")
    assert value_kind("Basic EPS (₹)", "eps_basic", crore) == "PER_SHARE"
    assert to_base(Decimal("45.67"), "PER_SHARE", crore.scale) == (4567, False)          # paise, not crore
    assert value_kind("Operating margin (%)", "operating_margin", crore) == "PERCENT"
    assert to_base(Decimal("12.5"), "PERCENT", 1) == (1250, False)                         # basis points
    assert value_kind("Number of employees", "headcount", crore) == "COUNT"
    assert value_kind("Revenue from operations", "revenue", crore) == "AMOUNT"
    assert to_base(Decimal("0.123"), "AMOUNT", 1) == (0, True)                             # rounded, and said so
