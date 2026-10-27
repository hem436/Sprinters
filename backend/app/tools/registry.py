"""The approved tool registry: the agent's ToolPort (model/agent/ports.py) and the source of GET /tools.

run_tool never raises. Statuses (contract 13 section 5): OK, EMPTY, ARGS_INVALID, TIMEOUT, DB_ERROR, NO_TOOL.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from agent.types import ToolResult
from pydantic import ValidationError

from app.tools import asset_compliance, budget_status, claims_list, headcount, project_info, spend_summary
from app.tools.base import ArgsInvalid, Tool, ToolTimeout, argument_schema, connect_readonly, show_rows

log = logging.getLogger(__name__)

TOOLS: dict[str, Tool] = {
    t.TOOL.name: t.TOOL
    for t in (project_info, budget_status, spend_summary, claims_list, asset_compliance, headcount)
}


def _fields(exc: ValidationError) -> list[dict[str, str]]:
    return [{"field": ".".join(str(p) for p in e["loc"]) or "args", "problem": e["msg"]} for e in exc.errors()]


class ToolRegistry:
    def __init__(self, business_db: Path, *, simulate_failure: bool = False) -> None:
        self.business_db = business_db
        self.simulate_failure = simulate_failure      # tools.simulate_failure: the eval's tool-failure cases

    def list_tools(self) -> list[dict[str, Any]]:
        """What the planner sees: name, description and argument schema, nothing about the database."""
        return [{"name": t.name, "description": t.description, "args": argument_schema(t.args)}
                for t in TOOLS.values()]

    def run_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        return self.run_checked(name, args)[0]

    def run_checked(self, name: str, args: dict[str, Any]) -> tuple[ToolResult, list[dict[str, str]]]:
        """The ToolResult, plus the failed fields when the status is ARGS_INVALID (for POST /tools/{name}/try)."""
        started = time.perf_counter()

        def result(status: str, summary: str = "", rows: list | None = None, message: str = "") -> ToolResult:
            tool = TOOLS.get(name)
            return ToolResult(tool=name, status=status, summary=summary, rows=rows or [], args=args or {},
                              version=tool.version if tool else 1, message=message,
                              latency_ms=round((time.perf_counter() - started) * 1000))

        tool = TOOLS.get(name)
        if tool is None:
            return result("NO_TOOL", message=f"{name} is not an approved tool"), []
        if self.simulate_failure:
            return result("TIMEOUT", message="simulated tool failure (tools.simulate_failure)"), []
        try:
            checked = tool.args.model_validate(args or {})
            conn = connect_readonly(self.business_db)
            try:
                rows = tool.run(conn, checked)
            finally:
                conn.close()
        except ValidationError as exc:
            fields = _fields(exc)
            return result("ARGS_INVALID", message=ArgsInvalid(fields).args[0]), fields
        except ArgsInvalid as exc:
            return result("ARGS_INVALID", message=str(exc)), exc.fields
        except ToolTimeout as exc:
            return result("TIMEOUT", message=str(exc)), []
        except sqlite3.Error as exc:
            log.warning("tool %s failed: %s", name, exc)
            return result("DB_ERROR", message="the data is not available now"), []
        if not rows:
            return result("EMPTY", summary="There are no matching rows for these values."), []
        return result("OK", summary=tool.summary(checked, rows), rows=show_rows(rows)), []

    def info(self, success_rates: dict[str, float] | None = None) -> list[dict[str, Any]]:
        """GET /tools rows, in the shape of the web app's ToolInfo (web/src/api/types.ts)."""
        rates = success_rates or {}
        return [{"name": t.name, "version": t.version, "source": t.source, "description": t.description,
                 "argument_schema": argument_schema(t.args), "approved": bool(t.approved_by),
                 "approved_by": t.approved_by, "approved_on": t.approved_on, "success_rate": rates.get(t.name)}
                for t in TOOLS.values()]
