"""Dashboard data, feedback and evaluation runs (contract 05; contract 11 sections 7 and 9).

GET /metrics/summary, GET /queries, GET /queries/{id}, POST /feedback, POST /queries/{id}/review,
GET and POST /eval/runs. Shapes follow web/src/api/types.ts.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.auth import require_admin
from app.api.errors import ApiError
from app.api.query import get_agent
from app.config import Config, get_config
from app.observability import metrics, store

router = APIRouter(tags=["dashboard"])


class Filters(BaseModel):
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    config_id: Literal["A", "B", ""] | None = None
    route: Literal["DOCS", "SQL", "BOTH", "CONVERSATIONAL", "BLOCKED", ""] | None = None
    outcome: Literal["SUCCESS", "PARTIAL", "FAILED", ""] | None = None

    def as_dict(self) -> dict:
        return {"from": self.from_, "to": self.to, "config_id": self.config_id, "route": self.route,
                "outcome": self.outcome}


class FeedbackRequest(BaseModel):
    query_id: str
    helpful: bool
    comment: str | None = Field(default=None, max_length=2000)


class ReviewRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


def _db(config: Config) -> Path:
    return config.paths.resolve(config.paths.observability_db)


def _document_titles(config: Config) -> dict[str, str]:
    """Titles for the ingestion-cost list, from knowledge.db when it exists."""
    path = config.paths.resolve(config.paths.knowledge_db)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            return dict(conn.execute("SELECT document_id, title FROM document").fetchall())
        finally:
            conn.close()
    except sqlite3.Error:
        return {}


def _require_query(conn: sqlite3.Connection, query_id: str) -> None:
    if conn.execute("SELECT 1 FROM query_event WHERE query_id = ?", (query_id,)).fetchone() is None:
        raise ApiError(404, "NOT_FOUND", f"Query {query_id} not found.")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@router.get("/metrics/summary", dependencies=[Depends(require_admin)])
def metrics_summary(filters: Filters = Depends(), config: Config = Depends(get_config)) -> dict:
    return metrics.summary(_db(config), filters.as_dict(), config.get("obs.grounding_min", 0.8),
                           _document_titles(config))


@router.get("/queries", dependencies=[Depends(require_admin)])
def list_queries(filters: Filters = Depends(), page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100), config: Config = Depends(get_config)) -> dict:
    return metrics.list_queries(_db(config), filters.as_dict(), page, page_size)


@router.get("/queries/{query_id}", dependencies=[Depends(require_admin)])
def get_query(query_id: str, config: Config = Depends(get_config)) -> dict:
    found = metrics.drill_down(_db(config), query_id)
    if found is None:
        raise ApiError(404, "NOT_FOUND", f"Query {query_id} not found.")
    return found


@router.post("/feedback", status_code=201)
def feedback(body: FeedbackRequest, config: Config = Depends(get_config)) -> dict:
    conn = store.connect(_db(config))
    try:
        _require_query(conn, body.query_id)
        try:
            with conn:
                conn.execute("INSERT INTO feedback (query_id, helpful, comment, ts) VALUES (?, ?, ?, ?)",
                             (body.query_id, int(body.helpful), body.comment, _now()))
        except sqlite3.IntegrityError as exc:
            raise ApiError(409, "FEEDBACK_EXISTS", "Feedback for this answer was already given.") from exc
    finally:
        conn.close()
    return {"query_id": body.query_id, "helpful": body.helpful, "comment": body.comment}


@router.post("/queries/{query_id}/review", status_code=201, dependencies=[Depends(require_admin)])
def review_query(query_id: str, body: ReviewRequest, config: Config = Depends(get_config)) -> dict:
    conn = store.connect(_db(config))
    try:
        _require_query(conn, query_id)
        with conn:
            conn.execute("INSERT INTO query_review (query_id, comment, ts) VALUES (?, ?, ?)",
                         (query_id, body.comment, _now()))
    finally:
        conn.close()
    return {"query_id": query_id, "comment": body.comment}


# Evaluation runs: the runner is Arka's (WP-AG6); these read what it stores. ------------------------------------

def _run_row(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    done = conn.execute("SELECT COUNT(*) FROM eval_result WHERE run_id = ?", (r["run_id"],)).fetchone()[0]
    summary = json.loads(r["summary"]) if r["summary"] else None
    return {"run_id": r["run_id"], "config_id": r["config_id"], "status": r["status"], "started_at": r["started_at"],
            "finished_at": r["finished_at"], "cases_done": done,
            "cases_total": (summary or {}).get("cases_total", done), "summary": summary}


@router.get("/eval/runs", dependencies=[Depends(require_admin)])
def list_eval_runs(config: Config = Depends(get_config)) -> list[dict]:
    conn = store.connect(_db(config))
    try:
        return [_run_row(conn, r) for r in conn.execute("SELECT * FROM eval_run ORDER BY started_at DESC")]
    finally:
        conn.close()


@router.get("/eval/runs/{run_id}", dependencies=[Depends(require_admin)])
def get_eval_run(run_id: str, config: Config = Depends(get_config)) -> dict:
    conn = store.connect(_db(config))
    try:
        r = conn.execute("SELECT * FROM eval_run WHERE run_id = ?", (run_id,)).fetchone()
        if r is None:
            raise ApiError(404, "NOT_FOUND", f"Evaluation run {run_id} not found.")
        out = _run_row(conn, r)
        out["results"] = [{"case_id": x["case_id"], "scenario": x["scenario"], "query_id": x["query_id"],
                           **json.loads(x["measures"] or "{}")}
                          for x in conn.execute("SELECT * FROM eval_result WHERE run_id = ? ORDER BY case_id",
                                                (run_id,))]
        return out
    finally:
        conn.close()


class EvalRunRequest(BaseModel):
    config_id: Literal["A", "B"] = "B"
    case_ids: list[str] | None = None


@router.post("/eval/runs", status_code=202, dependencies=[Depends(require_admin)])
def start_eval_run(req: EvalRunRequest, config: Config = Depends(get_config), agent=Depends(get_agent)) -> dict:
    """Arka's runner (model/agent/eval_store.py) on the agent that serves /query, in a background thread."""
    from agent.eval_store import EvalSetError, RunInProgress, UnknownCases, start_run

    from app.observability.recorder import QueryRecorder

    # EVAL_SET and EVAL_OUTPUT_DIR override the config paths (the Docker image sets both, see backend/Dockerfile)
    cases = Path(os.getenv("EVAL_SET") or config.paths.resolve(config.paths.eval_set))
    out_dir = Path(os.getenv("EVAL_OUTPUT_DIR") or config.paths.resolve(config.paths.output_dir))
    try:
        run_id = start_run(agent, cases, req.config_id, _db(config), lambda q, s, c: QueryRecorder.start(q, s, c),
                           out_dir=out_dir, case_ids=req.case_ids)
    except RunInProgress as exc:
        raise ApiError(409, "RUN_IN_PROGRESS", str(exc)) from exc
    except UnknownCases as exc:           # the request named a case the set does not have
        raise ApiError(422, "INVALID_CASES", str(exc)) from exc
    except EvalSetError as exc:           # the server's eval set file is missing or broken (review #25)
        raise ApiError(500, "EVAL_SET_INVALID", str(exc)) from exc
    return {"run_id": run_id}
