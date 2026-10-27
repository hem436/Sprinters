"""budget_status: budget, spent, remaining and % used. "Is P-104 over its travel budget?\""""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, inr, query, require_exists

Category = Literal["TRAVEL", "MEALS", "LODGING", "SOFTWARE", "HARDWARE", "TRAINING"]

# Tested SQL of contract 13 section 4; "spent" comes from v_budget_status, defined once.
SQL = """
SELECT project_id, category, budget_paise, spent_paise,
       budget_paise - spent_paise AS remaining_paise,
       ROUND(100.0 * spent_paise / NULLIF(budget_paise, 0), 1) AS pct_used
FROM v_budget_status
WHERE project_id = :project_id AND fiscal_year = :fiscal_year
  AND (:category IS NULL OR category = :category)
ORDER BY category
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern=r"^P-\d{3}$", examples=["P-104"])
    fiscal_year: str = Field(pattern=r"^FY\d{4}-\d{2}$", examples=["FY2026-27"])
    category: Category | None = None


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "project", "project_id", args.project_id, "project_id")
    return query(conn, SQL, args.model_dump(), TOOL.max_rows, TOOL.timeout_ms)


def summary(args: Args, rows: list[dict]) -> str:
    parts = []
    for r in rows:
        left = r["remaining_paise"]
        state = f"over by {inr(-left)}" if left < 0 else f"remaining {inr(left)}"
        parts.append(f"{r['project_id']} {r['category']} {args.fiscal_year}: budget {inr(r['budget_paise'])}, "
                     f"spent {inr(r['spent_paise'])}, {state} ({r['pct_used']} % used)")
    return "; ".join(parts) + "."


TOOL = Tool(
    name="budget_status", version=1,
    description="Budget, spent, remaining and percent used for one project and fiscal year, per category.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_budget_status_p104",
)
