"""spend_summary: total spend per group, top 20. "Travel spend by city this year?"

group_by never goes into the SQL as text: it picks one of four fixed SQL strings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, inr, query, require_exists

Category = Literal["TRAVEL", "MEALS", "LODGING", "SOFTWARE", "HARDWARE", "TRAINING"]

_FILTERS = """
WHERE (:fiscal_year IS NULL OR s.fiscal_year = :fiscal_year)
  AND (:dept_id IS NULL OR p.dept_id = :dept_id)
  AND (:project_id IS NULL OR s.project_id = :project_id)
  AND (:category IS NULL OR s.category = :category)
"""
_FROM = "FROM v_spend s JOIN project p ON p.project_id = s.project_id"
SQL = {
    "project": f"SELECT s.project_id AS grp, SUM(s.amount_paise) AS spent_paise {_FROM} {_FILTERS} "
               "GROUP BY s.project_id ORDER BY spent_paise DESC",
    "department": f"SELECT p.dept_id AS grp, SUM(s.amount_paise) AS spent_paise {_FROM} {_FILTERS} "
                  "GROUP BY p.dept_id ORDER BY spent_paise DESC",
    "category": f"SELECT s.category AS grp, SUM(s.amount_paise) AS spent_paise {_FROM} {_FILTERS} "
                "GROUP BY s.category ORDER BY spent_paise DESC",
    "city": f"SELECT s.city AS grp, SUM(s.amount_paise) AS spent_paise {_FROM} {_FILTERS} "
            "GROUP BY s.city ORDER BY spent_paise DESC",
}


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_by: Literal["project", "department", "category", "city"] = Field(examples=["city"])
    fiscal_year: str | None = Field(default=None, pattern=r"^FY\d{4}-\d{2}$", examples=["FY2026-27"])
    dept_id: str | None = Field(default=None, pattern=r"^D-[A-Z]{2,4}$", examples=["D-FIN"])
    project_id: str | None = Field(default=None, pattern=r"^P-\d{3}$", examples=["P-104"])
    category: Category | None = None


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "department", "dept_id", args.dept_id, "dept_id")
    require_exists(conn, "project", "project_id", args.project_id, "project_id")
    params = args.model_dump(exclude={"group_by"})
    return query(conn, SQL[args.group_by], params, TOOL.max_rows, TOOL.timeout_ms)


def summary(args: Args, rows: list[dict]) -> str:
    year = f" in {args.fiscal_year}" if args.fiscal_year else ""
    listed = ", ".join(f"{r['grp']} {inr(r['spent_paise'])}" for r in rows)
    return f"Spend by {args.group_by}{year} (approved and paid claims): {listed}."


TOOL = Tool(
    name="spend_summary", version=1,
    description="Total approved and paid spend per project, department, category or city; top 20 groups.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_group_by_not_injectable",
)
