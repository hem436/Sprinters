"""asset_compliance: per department, assets, not encrypted, patch overdue (POL-HR-014).
"How many Finance laptops are not encrypted?\""""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, query, require_exists

SQL = """
SELECT dept_id,
       COUNT(*) AS assets,
       SUM(CASE WHEN encrypted = 0 THEN 1 ELSE 0 END) AS not_encrypted,
       SUM(CASE WHEN julianday('now') - julianday(last_patch_date) > :max_patch_age_days THEN 1 ELSE 0 END)
           AS patch_overdue
FROM it_asset
WHERE (:dept_id IS NULL OR dept_id = :dept_id)
  AND (:asset_type IS NULL OR asset_type = :asset_type)
GROUP BY dept_id
ORDER BY dept_id
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dept_id: str | None = Field(default=None, pattern=r"^D-[A-Z]{2,4}$", examples=["D-FIN"])
    asset_type: Literal["LAPTOP", "DESKTOP", "PHONE"] | None = None
    max_patch_age_days: int = Field(default=30, ge=1, le=365)


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "department", "dept_id", args.dept_id, "dept_id")
    return query(conn, SQL, args.model_dump(), TOOL.max_rows, TOOL.timeout_ms)


def summary(args: Args, rows: list[dict]) -> str:
    kind = f"{args.asset_type.lower()}s" if args.asset_type else "assets"
    listed = "; ".join(f"{r['dept_id']}: {r['assets']} {kind}, {r['not_encrypted']} not encrypted, "
                       f"{r['patch_overdue']} not patched in {args.max_patch_age_days} days" for r in rows)
    return f"{listed}."


TOOL = Tool(
    name="asset_compliance", version=1,
    description="Per department: number of IT assets, how many are not encrypted and how many are overdue "
                "for patching.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_asset_compliance_finance_laptops",
)
