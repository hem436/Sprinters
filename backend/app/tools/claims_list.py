"""claims_list: expense claim rows. "Largest pending claims on P-104?\""""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, inr, query, require_exists

Category = Literal["TRAVEL", "MEALS", "LODGING", "SOFTWARE", "HARDWARE", "TRAINING"]

_SELECT = """
SELECT claim_id, project_id, employee_code, category, city, claim_date, fiscal_year, amount_paise, status
FROM expense_claim
WHERE (:project_id IS NULL OR project_id = :project_id)
  AND (:employee_code IS NULL OR employee_code = :employee_code)
  AND (:status IS NULL OR status = :status)
  AND (:category IS NULL OR category = :category)
  AND (:min_amount_paise IS NULL OR amount_paise >= :min_amount_paise)
"""
SQL = {
    "newest": _SELECT + " ORDER BY claim_date DESC, claim_id DESC LIMIT :limit",
    "largest": _SELECT + " ORDER BY amount_paise DESC, claim_id LIMIT :limit",
}


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str | None = Field(default=None, pattern=r"^P-\d{3}$", examples=["P-104"])
    employee_code: str | None = Field(default=None, pattern=r"^E\d{4}$", examples=["E1042"])
    status: Literal["SUBMITTED", "APPROVED", "REJECTED", "PAID"] | None = None
    category: Category | None = None
    min_amount: int | None = Field(default=None, ge=0, description="rupees", examples=[10000])
    order: Literal["newest", "largest"] = "newest"
    limit: int = Field(default=10, ge=1, le=20)


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "project", "project_id", args.project_id, "project_id")
    require_exists(conn, "employee", "employee_code", args.employee_code, "employee_code")
    params = args.model_dump(exclude={"order", "min_amount"})
    params["min_amount_paise"] = None if args.min_amount is None else args.min_amount * 100
    return query(conn, SQL[args.order], params, TOOL.max_rows, TOOL.timeout_ms)


def summary(args: Args, rows: list[dict]) -> str:
    listed = "; ".join(f"{r['claim_id']} {r['project_id']} {r['category']} {inr(r['amount_paise'])} "
                       f"{r['status']} on {r['claim_date']}" for r in rows)
    return f"{len(rows)} claim(s), {args.order} first: {listed}."


TOOL = Tool(
    name="claims_list", version=1,
    description="Expense claim rows filtered by project, employee code, status, category or minimum amount; "
                "newest or largest first, at most 20.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_claims_list_pending_p104",
)
