"""Shared by the four facts tools (contract 14 section 6): they read v_fact_current in knowledge.db, read-only.

Rules for all four: compare only facts with the same basis and value kind; a missing metric or period is
EMPTY ("not found in the reports"), never an estimate; growth and shares are computed in SQL; each number
is cited as report, page, table, row.
"""

from __future__ import annotations

from typing import Literal

from app.tools.base import fact_value

# Standard metrics of contract 14 section 4.
Metric = Literal[
    "revenue", "other_income", "total_income", "employee_cost", "ebitda", "depreciation", "finance_cost", "pbt",
    "tax", "pat", "eps_basic", "total_assets", "total_equity", "borrowings", "cash", "operating_cash_flow",
    "operating_margin", "headcount", "segment_revenue",
]
Basis = Literal["CONSOLIDATED", "STANDALONE"]
PERIOD = r"^FY\d{4}-\d{2}( Q[1-4])?$"
ANNUAL_PERIOD = r"^FY\d{4}-\d{2}$"
NOT_FOUND = "Not found in the reports."

# Columns every facts tool returns, with what the citation and the restated note need.
FACT_SELECT = """
SELECT v.company, v.metric, v.period, v.basis, v.segment, v.value_kind, v.value_num, v.value_printed,
       t.unit_printed, t.statement, v.report_id, r.fiscal_year AS report_year, r.report_type, v.page, v.row_no,
       v.restated, v.prev_value_num, pr.fiscal_year AS prev_report_year, v.prev_page
FROM v_fact_current v
JOIN report r ON r.report_id = v.report_id
JOIN fin_table t ON t.table_id = v.table_id
LEFT JOIN report pr ON pr.report_id = v.prev_report_id
"""


def source(row: dict) -> str:
    """Company A FY2024-25 annual report, p.52, PL row 3."""
    return (f"{row['company']} {row['report_year']} {row['report_type'].lower()} report, p.{row['page']}, "
            f"{row['statement']} row {row['row_no']}")


def restated_note(row: dict) -> str:
    if not row["restated"]:
        return ""
    was = fact_value(row["value_kind"], row["prev_value_num"])
    return (f" (restated in the {row['report_year']} report; was {was} in the {row['prev_report_year']} report, "
            f"p.{row['prev_page']})")


def with_value(rows: list[dict]) -> list[dict]:
    """Adds the value in words next to the base-unit number, for the agent and the screens."""
    return [{**r, "value": fact_value(r["value_kind"], r["value_num"])} for r in rows]
