"""GET /tools and POST /tools/{name}/try (contract 05; admin; contract 13 section 6).

Shapes follow the web app's ToolInfo and ToolTryResult (web/src/api/types.ts).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import require_admin
from app.api.errors import ApiError
from app.config import Config, get_config
from app.tools.registry import ToolRegistry

router = APIRouter(tags=["tools"], dependencies=[Depends(require_admin)])


class TryRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


def get_registry(config: Config = Depends(get_config)) -> ToolRegistry:
    return ToolRegistry(config.paths.resolve(config.paths.business_db),
                        simulate_failure=bool(config.get("tools.simulate_failure", False)))


def _success_rates(config: Config) -> dict[str, float]:
    """Tool success (contract 11 section 9): OK calls / all calls, from the event store."""
    try:
        conn = sqlite3.connect(config.paths.resolve(config.paths.observability_db), timeout=1)
        try:
            rows = conn.execute("SELECT tool, AVG(status = 'OK') FROM tool_call GROUP BY tool").fetchall()
        finally:
            conn.close()
        return {tool: round(rate, 3) for tool, rate in rows}
    except sqlite3.Error:
        return {}


@router.get("/tools")
def list_tools(registry: ToolRegistry = Depends(get_registry), config: Config = Depends(get_config)) -> list[dict]:
    return registry.info(_success_rates(config))


@router.post("/tools/{name}/try")
def try_tool(name: str, body: TryRequest, registry: ToolRegistry = Depends(get_registry)) -> dict:
    result, fields = registry.run_checked(name, body.args)
    if result.status == "NO_TOOL":
        raise ApiError(404, "NOT_FOUND", f"{name} is not an approved tool.")
    if result.status == "ARGS_INVALID":
        raise ApiError(422, "ARGS_INVALID", "The arguments failed the check. The tool did not run.", fields)
    if result.status == "TIMEOUT":
        raise ApiError(504, "TIMEOUT", result.message)
    if result.status == "DB_ERROR":
        raise ApiError(503, "DB_ERROR", result.message)
    return {
        "rows": result.rows,
        "summary": result.summary,
        "provenance": {"tool": result.tool, "version": result.version, "source": "business",
                       "latency_ms": result.latency_ms, "row_count": len(result.rows)},
    }
