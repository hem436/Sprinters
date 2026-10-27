"""metric_value: one figure from the reports. "Company A revenue in FY2024-25?\""""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, query, require_exists
from app.tools.facts_common import FACT_SELECT, NOT_FOUND, PERIOD, Basis, Metric, restated_note, source, with_value

SQL = FACT_SELECT + """
WHERE v.company = :company AND v.metric = :metric AND v.period = :period AND v.basis = :basis
  AND v.segment = COALESCE(:segment, '')
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(max_length=80, examples=["Company A"])
    metric: Metric = Field(examples=["revenue"])
    period: str = Field(pattern=PERIOD, examples=["FY2024-25"])
    basis: Basis = "CONSOLIDATED"
    segment: str | None = Field(default=None, max_length=80)


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "report", "company", args.company, "company")
    return with_value(query(conn, SQL, args.model_dump(), TOOL.max_rows, TOOL.timeout_ms))


def summary(args: Args, rows: list[dict]) -> str:
    r = rows[0]
    segment = f" {r['segment']}" if r["segment"] else ""
    return (f"{r['company']} {r['metric']}{segment} {r['period']} ({r['basis'].lower()}): {r['value']}"
            f"{restated_note(r)}. Source: {source(r)}.")


TOOL = Tool(
    name="metric_value", version=1, source="knowledge", empty_summary=NOT_FOUND,
    description="One reported figure (revenue, profit, EPS, ...) for a company and period from approved annual "
                "report tables, consolidated by default.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_metric_value_restated",
)
