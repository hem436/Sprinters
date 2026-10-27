"""GET /health: {status, qdrant, llm, ocr_available, reranker, db} (contract 05).

Each check is cheap and time-limited, so /health never hangs. status is "ok" only when
Qdrant is up, the LLM key is set and the observability store opens; otherwise "degraded".
"""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends

from app.config import Config, get_config

router = APIRouter(tags=["health"])


async def check_qdrant(config: Config) -> str:
    try:
        async with httpx.AsyncClient(timeout=config.health.timeout_s) as client:
            resp = await client.get(f"{config.qdrant.url.rstrip('/')}/readyz")
        return "ok" if resp.status_code == 200 else "down"
    except httpx.HTTPError:
        return "down"


def check_llm(config: Config) -> str:
    # A live model check at start-up (contract 06, model_not_found) belongs to the agent's client.
    return "configured" if config.secrets.portkey_api_key else "not_configured"


def check_ocr(config: Config) -> bool:
    return bool(config.secrets.gemini_api_key)


def check_reranker() -> str:
    return "ok" if importlib.util.find_spec("flashrank") is not None else "not_installed"


def _check_sqlite(path: Path, create: bool) -> str:
    if not create and not path.exists():
        return "missing"
    try:
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=1)
        else:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return "ok"
    except sqlite3.Error:
        return "down"


def check_dbs(config: Config) -> dict[str, str]:
    paths = config.paths
    return {
        # The service owns this store, so it may create the file.
        "observability": _check_sqlite(paths.resolve(paths.observability_db), create=True),
        # These are built by the ingestion pipeline and make_business_data.py.
        "knowledge": _check_sqlite(paths.resolve(paths.knowledge_db), create=False),
        "business": _check_sqlite(paths.resolve(paths.business_db), create=False),
    }


@router.get("/health")
async def health(config: Config = Depends(get_config)) -> dict:
    qdrant, db = await asyncio.gather(check_qdrant(config), asyncio.to_thread(check_dbs, config))
    llm = check_llm(config)
    ready = qdrant == "ok" and llm == "configured" and db["observability"] == "ok"
    return {
        "status": "ok" if ready else "degraded",
        "qdrant": qdrant,
        "llm": llm,
        "ocr_available": check_ocr(config),
        "reranker": check_reranker(),
        "db": db,
    }
