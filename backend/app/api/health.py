"""GET /health: {status, qdrant, llm, ocr_available, reranker, db} (contract 05), all true or false
as the web app's Health type reads them (web/src/api/types.ts).

Each check is cheap and time-limited, so /health never hangs. db is true when the event store and
business.db both open. status: "ok" when everything is true except optional OCR and reranker,
"down" when the stores do not open, otherwise "degraded".
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


async def check_qdrant(config: Config) -> bool:
    try:
        async with httpx.AsyncClient(timeout=config.health.timeout_s) as client:
            resp = await client.get(f"{config.qdrant.url.rstrip('/')}/readyz")
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def check_llm(config: Config) -> bool:
    # The agent reads LLM_API_KEY (Groq directly) or PORTKEY_API_KEY (model/README.md).
    return bool(config.secrets.llm_api_key or config.secrets.portkey_api_key)


def _opens(path: Path, *, create: bool) -> bool:
    if not create and not path.exists():
        return False
    try:
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        uri = f"file:{path}" + ("" if create else "?mode=ro")
        conn = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def check_db(config: Config) -> bool:
    paths = config.paths
    return (_opens(paths.resolve(paths.observability_db), create=True)
            and _opens(paths.resolve(paths.business_db), create=False))


@router.get("/health")
async def health(config: Config = Depends(get_config)) -> dict:
    qdrant, db = await asyncio.gather(check_qdrant(config), asyncio.to_thread(check_db, config))
    llm = check_llm(config)
    status = "down" if not db else "ok" if (qdrant and llm) else "degraded"
    return {
        "status": status,
        "qdrant": qdrant,
        "llm": llm,
        "ocr_available": bool(config.secrets.gemini_api_key),
        "reranker": importlib.util.find_spec("flashrank") is not None,
        "db": db,
    }
