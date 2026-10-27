"""metric_compare: values side by side with change and growth %. "Revenue FY2025 vs FY2024 and growth?"

Either one company over several periods, or several companies in one period. Growth is computed in SQL,
each item against the one before it in the order asked.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tools.base import Tool, fact_value, query, require_exists
from app.tools.facts_common import FACT_SELECT, NOT_FOUND, PERIOD, Basis, Metric, restated_note, source, with_value

SQL = """
WITH asked AS (SELECT key AS pos, value AS item FROM json_each(:items)),
facts AS (""" + FACT_SELECT + """
  WHERE v.metric = :metric AND v.basis = :basis AND v.segment = ''
    AND ((:mode = 'periods' AND v.company = :company) OR (:mode = 'companies' AND v.period = :period))
)
SELECT f.*, a.pos,
       f.value_num - LAG(f.value_num) OVER w AS change_num,
       ROUND(100.0 * (f.value_num - LAG(f.value_num) OVER w) / NULLIF(LAG(f.value_num) OVER w, 0), 1) AS growth_pct
FROM asked a
JOIN facts f ON (:mode = 'periods' AND f.period = a.item) OR (:mode = 'companies' AND f.company = a.item)
WINDOW w AS (ORDER BY a.pos)
ORDER BY a.pos
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Metric = Field(examples=["revenue"])
    basis: Basis = "CONSOLIDATED"
    company: str | None = Field(default=None, max_length=80, examples=["Company A"])
    periods: list[str] | None = Field(default=None, min_length=2, max_length=6, examples=[["FY2023-24", "FY2024-25"]])
    companies: list[str] | None = Field(default=None, min_length=2, max_length=6)
    period: str | None = Field(default=None, pattern=PERIOD)

    @model_validator(mode="after")
    def one_mode(self) -> Args:
        by_periods = self.company is not None and self.periods is not None
        by_companies = self.companies is not None and self.period is not None
        if by_periods == by_companies:
            raise ValueError("give either company and periods, or companies and period")
        return self


def run(conn, args: Args) -> list[dict]:
    mode = "periods" if args.periods else "companies"
    items = args.periods if mode == "periods" else args.companies
    for company in [args.company] if mode == "periods" else items:
        require_exists(conn, "report", "company", company, "company")
    params = {"metric": args.metric, "basis": args.basis, "company": args.company, "period": args.period,
              "mode": mode, "items": json.dumps(items)}
    rows = query(conn, SQL, params, TOOL.max_rows, TOOL.timeout_ms)
    if len(rows) < len(items):
        return []                               # one side missing: no comparison, never an estimate
    return [{**r, "change": fact_value(r["value_kind"], r["change_num"])} for r in with_value(rows)]


def summary(args: Args, rows: list[dict]) -> str:
    parts = []
    for r in rows:
        label = r["period"] if args.periods else r["company"]
        growth = "" if r["growth_pct"] is None else f", change {r['change']} ({r['growth_pct']:+} %)"
        parts.append(f"{label} {r['value']}{growth}{restated_note(r)} [{source(r)}]")
    return f"{args.metric} ({args.basis.lower()}): " + "; ".join(parts) + "."


TOOL = Tool(
    name="metric_compare", version=1, source="knowledge", empty_summary=NOT_FOUND,
    description="Compare one reported metric across periods for a company, or across companies for a period; "
                "gives each value, the change and the growth percent.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_growth_in_sql",
)
