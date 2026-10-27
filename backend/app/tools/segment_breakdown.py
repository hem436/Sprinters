"""segment_breakdown: value and share of total per segment. "Revenue by segment in FY2024-25?\""""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, query, require_exists
from app.tools.facts_common import FACT_SELECT, NOT_FOUND, PERIOD, Basis, restated_note, source, with_value

SQL = """
WITH facts AS (""" + FACT_SELECT + """
  WHERE v.company = :company AND v.period = :period AND v.metric = :metric AND v.basis = :basis
    AND v.segment != ''
)
SELECT *, ROUND(100.0 * value_num / NULLIF(SUM(value_num) OVER (), 0), 1) AS share_pct
FROM facts
ORDER BY value_num DESC
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(max_length=80, examples=["Company A"])
    period: str = Field(pattern=PERIOD, examples=["FY2024-25"])
    metric: Literal["segment_revenue"] = "segment_revenue"
    basis: Basis = "CONSOLIDATED"


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "report", "company", args.company, "company")
    return with_value(query(conn, SQL, args.model_dump(), TOOL.max_rows, TOOL.timeout_ms))


def summary(args: Args, rows: list[dict]) -> str:
    parts = [f"{r['segment']} {r['value']} ({r['share_pct']} %){restated_note(r)}" for r in rows]
    return f"{args.company} revenue by segment {args.period}: " + "; ".join(parts) + f". Source: {source(rows[0])}."


TOOL = Tool(
    name="segment_breakdown", version=1, source="knowledge", empty_summary=NOT_FOUND,
    description="Revenue per business segment for a company and period, with each segment's share of the total.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_segment_shares_in_sql",
)
