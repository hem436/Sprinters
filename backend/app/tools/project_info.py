"""project_info: who owns a project, its status and dates. "Who owns P-104 and is it active?\""""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import Tool, query, require_exists

SQL = """
SELECT p.project_id, p.name, p.dept_id, d.name AS department, p.status, p.start_date, p.end_date
FROM project p JOIN department d ON d.dept_id = p.dept_id
WHERE p.project_id = :project_id
"""


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern=r"^P-\d{3}$", examples=["P-104"])


def run(conn, args: Args) -> list[dict]:
    require_exists(conn, "project", "project_id", args.project_id, "project_id")
    return query(conn, SQL, args.model_dump(), TOOL.max_rows, TOOL.timeout_ms)


def summary(args: Args, rows: list[dict]) -> str:
    r = rows[0]
    until = f" to {r['end_date']}" if r["end_date"] else ""
    return (f"{r['project_id']} ({r['name']}) is owned by {r['department']} ({r['dept_id']}), "
            f"status {r['status']}, from {r['start_date']}{until}.")


TOOL = Tool(
    name="project_info", version=1,
    description="Project name, owning department, status and dates for one project id.",
    args=Args, run=run, summary=summary,
    approved_by="Sinngam", approved_on="2026-10-27", test="test_project_info_p104",
)
