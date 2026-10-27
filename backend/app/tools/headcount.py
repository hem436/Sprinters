"""headcount: counts of active employees, never a list of people. "How many G4 staff in Mumbai?\""""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, query, require_exists

SQL = """
SELECT COUNT(*) AS headcount
FROM employee
WHERE status = 'ACTIVE'
  AND (:dept_id IS NULL OR dept_id = :dept_id)
  AND (:location IS NULL OR location = :location)
  AND (:grade IS NULL OR grade = :grade)
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dept_id: str | None = Field(default=None, pattern=r"^D-[A-Z]{2,4}$", examples=["D-FIN"])
    location: str | None = Field(default=None, max_length=40, examples=["Mumbai"])
    grade: Literal["G1", "G2", "G3", "G4", "G5", "G6"] | None = None


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "department", "dept_id", args.dept_id, "dept_id")
    return query(conn, SQL, args.model_dump(), TOOL.max_rows, TOOL.timeout_ms)


def summary(args: Args, rows: list[dict]) -> str:
    filters = ", ".join(v for v in (args.dept_id, args.location, args.grade) if v) or "all"
    return f"{rows[0]['headcount']} active employees ({filters})."


TOOL = Tool(
    name="headcount", version=1,
    description="Number of active employees by department, location and grade; counts only, never names.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_headcount_never_lists_people",
)
