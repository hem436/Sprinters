"""metric_trend: one value per year with year-on-year growth. "Profit over the last 5 years?\""""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, query, require_exists
from app.tools.facts_common import (
    ANNUAL_PERIOD,
    FACT_SELECT,
    NOT_FOUND,
    Basis,
    Metric,
    restated_note,
    source,
    with_value,
)

SQL = """
WITH facts AS (""" + FACT_SELECT + """
  WHERE v.company = :company AND v.metric = :metric AND v.basis = :basis AND v.segment = ''
    AND v.period BETWEEN :from_period AND :to_period AND v.period NOT LIKE '% Q%'
)
SELECT *,
       ROUND(100.0 * (value_num - LAG(value_num) OVER w) / NULLIF(LAG(value_num) OVER w, 0), 1) AS growth_pct
FROM facts
WINDOW w AS (ORDER BY period)
ORDER BY period
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(max_length=80, examples=["Company A"])
    metric: Metric = Field(examples=["pat"])
    from_period: str = Field(pattern=ANNUAL_PERIOD, examples=["FY2020-21"])
    to_period: str = Field(pattern=ANNUAL_PERIOD, examples=["FY2024-25"])
    basis: Basis = "CONSOLIDATED"


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "report", "company", args.company, "company")
    return with_value(query(conn, SQL, args.model_dump(), TOOL.max_rows, TOOL.timeout_ms))


def summary(args: Args, rows: list[dict]) -> str:
    parts = [f"{r['period']} {r['value']}" + ("" if r["growth_pct"] is None else f" ({r['growth_pct']:+} %)")
             + restated_note(r) + f" [{source(r)}]" for r in rows]
    return f"{args.company} {args.metric} ({args.basis.lower()}), year on year: " + "; ".join(parts) + "."


TOOL = Tool(
    name="metric_trend", version=1, source="knowledge", empty_summary=NOT_FOUND,
    description="One reported metric for a company per fiscal year over a range of years, with year-on-year "
                "growth percent.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_metric_trend_growth",
)
