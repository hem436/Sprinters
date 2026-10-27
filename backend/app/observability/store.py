"""observability.db: the one store every dashboard number comes from (contract 11 section 2)."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import BACKEND_DIR, get_config

PRICES_PATH = BACKEND_DIR / "config" / "model_prices.yaml"

SCHEMA = """
CREATE TABLE IF NOT EXISTS query_event (
    query_id           TEXT PRIMARY KEY,
    ts                 TEXT NOT NULL,
    session_id         TEXT,
    app_version        TEXT NOT NULL,
    config_id          TEXT,
    question_masked    TEXT NOT NULL,
    normalized_query   TEXT,
    route              TEXT CHECK (route IN ('DOCS','SQL','BOTH','CONVERSATIONAL','BLOCKED')),
    answer             TEXT,
    outcome            TEXT NOT NULL CHECK (outcome IN ('SUCCESS','PARTIAL','FAILED')),
    reason_code        TEXT NOT NULL,
    confidence         TEXT CHECK (confidence IN ('HIGH','MEDIUM','LOW')),
    retrieval_relevant INTEGER,
    grounding_score    REAL,
    citations_valid    INTEGER NOT NULL DEFAULT 0,
    citations_total    INTEGER NOT NULL DEFAULT 0,
    safety_flags       TEXT NOT NULL DEFAULT '[]',
    latency_ms_total   INTEGER,
    tokens_in          INTEGER NOT NULL DEFAULT 0,
    tokens_out         INTEGER NOT NULL DEFAULT 0,
    tokens_cached      INTEGER NOT NULL DEFAULT 0,
    cost_usd           TEXT,            -- Decimal as text; NULL means a price is not set
    cost_estimated     INTEGER NOT NULL DEFAULT 0,
    http_status        INTEGER,
    grounding_detail   TEXT,
    error_category     TEXT,
    correlation_id     TEXT
);
CREATE INDEX IF NOT EXISTS ix_query_event_ts ON query_event (ts);
CREATE INDEX IF NOT EXISTS ix_query_event_outcome ON query_event (outcome, ts);
CREATE INDEX IF NOT EXISTS ix_query_event_config ON query_event (config_id, ts);

CREATE TABLE IF NOT EXISTS query_stage (
    query_id   TEXT NOT NULL REFERENCES query_event (query_id),
    seq        INTEGER NOT NULL,
    stage      TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('OK','SKIPPED','ERROR','TIMEOUT')),
    latency_ms INTEGER,
    retries    INTEGER NOT NULL DEFAULT 0,
    detail     TEXT,
    PRIMARY KEY (query_id, seq)
);

CREATE TABLE IF NOT EXISTS retrieval_hit (
    query_id    TEXT NOT NULL REFERENCES query_event (query_id),
    list        TEXT NOT NULL CHECK (list IN ('vector','bm25','fused','reranked')),
    rank        INTEGER NOT NULL,
    chunk_id    TEXT NOT NULL,
    document_id TEXT,
    page        INTEGER,
    score       REAL,
    PRIMARY KEY (query_id, list, rank)
);

CREATE TABLE IF NOT EXISTS llm_call (
    call_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id       TEXT,
    document_id    TEXT,
    ts             TEXT NOT NULL,
    purpose        TEXT NOT NULL CHECK (purpose IN ('route','answer','judge','ocr','embed','repair')),
    model          TEXT NOT NULL,
    prompt_version TEXT,
    tokens_in      INTEGER NOT NULL DEFAULT 0,
    tokens_out     INTEGER NOT NULL DEFAULT 0,
    tokens_cached  INTEGER NOT NULL DEFAULT 0,
    cache_hit      INTEGER NOT NULL DEFAULT 0,
    latency_ms     INTEGER,
    cost_usd       TEXT,
    usage_source   TEXT NOT NULL CHECK (usage_source IN ('PROVIDER','ESTIMATED')),
    CHECK (query_id IS NOT NULL OR document_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_llm_call_query ON llm_call (query_id);
CREATE INDEX IF NOT EXISTS ix_llm_call_document ON llm_call (document_id);

CREATE TABLE IF NOT EXISTS tool_call (
    tool_call_id   TEXT PRIMARY KEY,
    query_id       TEXT NOT NULL REFERENCES query_event (query_id),
    tool           TEXT NOT NULL,
    tool_version   TEXT,
    args_sanitized TEXT NOT NULL DEFAULT '{}',
    status         TEXT NOT NULL CHECK (status IN ('OK','EMPTY','ARGS_INVALID','TIMEOUT','DB_ERROR','NO_TOOL')),
    row_count      INTEGER NOT NULL DEFAULT 0,
    result_summary TEXT,
    latency_ms     INTEGER,
    error_category TEXT
);
CREATE INDEX IF NOT EXISTS ix_tool_call_query ON tool_call (query_id);

CREATE TABLE IF NOT EXISTS citation (
    query_id     TEXT NOT NULL REFERENCES query_event (query_id),
    citation_id  TEXT NOT NULL,
    chunk_id     TEXT,
    tool_call_id TEXT,
    valid        INTEGER NOT NULL,
    reason       TEXT,
    PRIMARY KEY (query_id, citation_id)
);

CREATE TABLE IF NOT EXISTS context_turn (
    query_id   TEXT NOT NULL REFERENCES query_event (query_id),
    turn_index INTEGER NOT NULL,
    role       TEXT NOT NULL,
    text_masked TEXT NOT NULL,
    chars      INTEGER NOT NULL,
    PRIMARY KEY (query_id, turn_index)
);

CREATE TABLE IF NOT EXISTS feedback (
    query_id         TEXT PRIMARY KEY REFERENCES query_event (query_id),
    helpful          INTEGER,
    comment          TEXT,
    reviewer_comment TEXT,
    ts               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_price (
    model             TEXT PRIMARY KEY,
    usd_per_1m_in     TEXT,
    usd_per_1m_out    TEXT,
    usd_per_1m_cached TEXT,
    source_url        TEXT,
    checked_on        TEXT
);

CREATE TABLE IF NOT EXISTS eval_run (
    run_id       TEXT PRIMARY KEY,
    config_id    TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('RUNNING','DONE','FAILED')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    app_version  TEXT,
    versions     TEXT,   -- JSON: prompt and model versions used
    summary      TEXT    -- JSON: the measures of contract 11 section 7
);

CREATE TABLE IF NOT EXISTS eval_result (
    run_id    TEXT NOT NULL REFERENCES eval_run (run_id),
    case_id   TEXT NOT NULL,
    query_id  TEXT,
    scenario  TEXT,
    passed    INTEGER,
    measures  TEXT,      -- JSON: hit@5, recall@5, rr, route_ok, behaviour_ok, criteria_ok ...
    PRIMARY KEY (run_id, case_id)
);

-- Writes the recorder could not make (contract 11 section 3), so missing records are visible.
CREATE TABLE IF NOT EXISTS counter (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def load_price_file(path: Path = PRICES_PATH) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("prices", [])


def _price_text(value: Any) -> str | None:
    # Through str() so 0.15 stays "0.15" and never becomes a binary float in the Decimal maths.
    return None if value is None else str(value)


def seed_prices(path: Path, prices: list[dict[str, Any]]) -> None:
    """Upsert the price file into model_price; the file is the reviewed source."""
    conn = connect(path)
    try:
        with conn:
            conn.executemany(
                """
                INSERT INTO model_price
                    (model, usd_per_1m_in, usd_per_1m_out, usd_per_1m_cached, source_url, checked_on)
                VALUES (:model, :in_, :out, :cached, :source_url, :checked_on)
                ON CONFLICT (model) DO UPDATE SET
                    usd_per_1m_in = excluded.usd_per_1m_in, usd_per_1m_out = excluded.usd_per_1m_out,
                    usd_per_1m_cached = excluded.usd_per_1m_cached, source_url = excluded.source_url,
                    checked_on = excluded.checked_on
                """,
                [
                    {
                        "model": p["model"],
                        "in_": _price_text(p.get("usd_per_1m_in")),
                        "out": _price_text(p.get("usd_per_1m_out")),
                        "cached": _price_text(p.get("usd_per_1m_cached")),
                        "source_url": p.get("source_url"),
                        "checked_on": None if p.get("checked_on") is None else str(p["checked_on"]),
                    }
                    for p in prices
                ],
            )
    finally:
        conn.close()


@lru_cache(maxsize=1)
def default_db_path() -> Path:
    paths = get_config().paths
    return paths.resolve(paths.observability_db)
