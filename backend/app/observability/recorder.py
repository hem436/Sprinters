"""QueryRecorder: the interface from the agent (P2) to the event store (contract 11 section 3).

    rec = QueryRecorder.start(question, session_id, config_id)    # assigns query_id, masks PII
    with rec.stage("retrieve_vector"):                             # times it; ERROR or TIMEOUT on exception
        hits = vector_search(...)
    rec.hits("vector", hits)
    rec.llm_call(purpose="answer", model=m, usage=resp.usage, latency_ms=t, prompt_version="answer-v1")
    rec.tool_call(tool="budget_status", args=args, status="OK", row_count=1, latency_ms=40)
    rec.citations(validated)        # [{citation_id, chunk_id | tool_call_id, valid, reason?}]
    result = rec.finish(answer, route, grounding_score, facts=OutcomeFacts(...))

Rules: no method raises into the answer path. Everything is buffered and written once, in
finish(), in one transaction. A failed write is logged, dropped and counted (dropped_events).
"""

from __future__ import annotations

import functools
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import get_config
from app.ids import new_ulid
from app.observability import store
from app.observability.cost import compute_cost, format_usd, load_prices
from app.observability.outcome import OutcomeFacts, classify, confidence
from app.observability.pii import mask_pii
from app.observability.usage import Usage, normalize_usage

log = logging.getLogger(__name__)

Classifier = Callable[[OutcomeFacts, float], tuple[str, str]]

# Writes that failed and could not even be counted in the store yet.
_dropped_lock = threading.Lock()
_dropped_unpersisted = 0


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _field(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _never_raise(method):
    """The recorder must never break an answer: log and carry on."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            log.exception("recorder.%s failed; event detail lost", method.__name__, extra={"query_id": self.query_id})
            self._broken = True
            return None

    return wrapper


def _count_dropped(db_path: Path) -> None:
    global _dropped_unpersisted
    with _dropped_lock:
        _dropped_unpersisted += 1
        try:
            conn = sqlite3.connect(db_path, timeout=1)
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO counter (name, value) VALUES ('dropped_events', ?) "
                        "ON CONFLICT (name) DO UPDATE SET value = value + excluded.value",
                        (_dropped_unpersisted,),
                    )
            finally:
                conn.close()
            _dropped_unpersisted = 0
        except Exception:
            log.warning("could not persist the dropped_events counter; kept in memory")


def dropped_events(db_path: Path | None = None) -> int:
    """Stored count plus any drops not yet written; the dashboard shows this number."""
    stored = 0
    try:
        conn = sqlite3.connect(db_path or store.default_db_path(), timeout=1)
        try:
            row = conn.execute("SELECT value FROM counter WHERE name = 'dropped_events'").fetchone()
            stored = row[0] if row else 0
        finally:
            conn.close()
    except Exception:
        pass
    return stored + _dropped_unpersisted


@dataclass
class StageHandle:
    """Yielded by rec.stage(); the agent may add detail or count retries."""

    detail: dict[str, Any] = field(default_factory=dict)
    retries: int = 0


@dataclass(frozen=True)
class FinishResult:
    """What the agent needs for the QueryResponse (contract 05)."""

    query_id: str
    outcome: str
    reason_code: str
    confidence: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: str | None
    cost_estimated: bool
    latency_ms: int
    recorded: bool


class QueryRecorder:
    def __init__(
        self,
        question: str,
        session_id: str | None,
        config_id: str | None,
        *,
        query_id: str | None = None,
        correlation_id: str | None = None,
        db_path: Path | None = None,
        classifier: Classifier = classify,
    ) -> None:
        self.query_id = query_id or new_ulid()
        self.session_id = session_id
        self.config_id = config_id
        self.correlation_id = correlation_id
        self.question_masked, self.pii_found = mask_pii(question)
        self._db_path = db_path
        self._classifier = classifier
        self._started = time.perf_counter()
        self._ts = _now()
        self._stages: list[dict[str, Any]] = []
        self._hits: dict[str, list[dict[str, Any]]] = {}
        self._llm_calls: list[dict[str, Any]] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._citations: list[dict[str, Any]] = []
        self._turns: list[dict[str, Any]] = []
        self._safety_flags: list[str] = ["PII"] if self.pii_found else []
        self._error_category: str | None = None
        self._finished = False
        self._broken = False

    @classmethod
    def start(cls, question: str, session_id: str | None, config_id: str | None, **kwargs: Any) -> QueryRecorder:
        try:
            return cls(question, session_id, config_id, **kwargs)
        except Exception:
            # Even a broken start must hand back a recorder the agent can call.
            log.exception("recorder.start failed")
            safe = {k: v for k, v in kwargs.items() if k in ("query_id", "db_path")}
            return cls("", session_id, config_id, **safe)

    # Stages ---------------------------------------------------------------

    @contextmanager
    def stage(self, name: str, *, retries: int = 0) -> Iterator[StageHandle]:
        handle = StageHandle(retries=retries)
        started = time.perf_counter()
        status = "OK"
        try:
            yield handle
        except TimeoutError:
            status = "TIMEOUT"
            raise
        except BaseException as exc:
            status = "ERROR"
            handle.detail.setdefault("error", type(exc).__name__)
            raise
        finally:
            # Recording happens even when the stage fails; the agent's exception still propagates.
            try:
                self._stages.append({
                    "stage": name,
                    "status": status,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "retries": handle.retries,
                    "detail": handle.detail or None,
                })
            except Exception:
                log.exception("recorder.stage bookkeeping failed")

    @_never_raise
    def stage_skipped(self, name: str, reason: str | None = None) -> None:
        self._stages.append({
            "stage": name, "status": "SKIPPED", "latency_ms": 0, "retries": 0,
            "detail": {"reason": reason} if reason else None,
        })

    # Evidence ---------------------------------------------------------------

    @_never_raise
    def hits(self, list_name: str, hits: Iterable[Any]) -> None:
        rows = []
        for i, hit in enumerate(hits, start=1):
            rows.append({
                "rank": _field(hit, "rank") or i,
                "chunk_id": _field(hit, "chunk_id"),
                "document_id": _field(hit, "document_id"),
                "page": _field(hit, "page"),
                "score": _field(hit, "score"),
            })
        self._hits[list_name] = rows

    @_never_raise
    def llm_call(
        self,
        purpose: str,
        model: str,
        usage: Any = None,
        latency_ms: int | None = None,
        prompt_version: str | None = None,
        *,
        cache_hit: bool = False,
        estimate: Usage | None = None,
    ) -> None:
        """usage: the provider's usage object. If it is missing, pass estimate=estimated_usage(...)."""
        normalized = normalize_usage(usage) or estimate or Usage(source="ESTIMATED")
        self._llm_calls.append({
            "purpose": purpose, "model": model, "prompt_version": prompt_version, "usage": normalized,
            "cache_hit": cache_hit, "latency_ms": latency_ms, "ts": _now(),
        })

    @_never_raise
    def tool_call(
        self,
        tool: str,
        args: dict[str, Any] | None,
        status: str,
        row_count: int = 0,
        latency_ms: int | None = None,
        *,
        result_summary: str | None = None,
        error_category: str | None = None,
        version: str | int | None = None,
        tool_call_id: str | None = None,
    ) -> str:
        """Returns the tool call id (T1, T2, ...) that a citation can point to."""
        call_id = tool_call_id or f"T{len(self._tool_calls) + 1}"
        self._tool_calls.append({
            "tool_call_id": call_id, "tool": tool, "tool_version": None if version is None else str(version),
            "args_sanitized": _sanitize_args(args or {}), "status": status, "row_count": row_count,
            "result_summary": mask_pii(result_summary)[0] if result_summary else None,
            "latency_ms": latency_ms, "error_category": error_category,
        })
        return call_id

    @_never_raise
    def citations(self, validated: Iterable[Any]) -> None:
        self._citations = [
            {
                "citation_id": _field(c, "citation_id") or _field(c, "id"),
                "chunk_id": _field(c, "chunk_id"),
                "tool_call_id": _field(c, "tool_call_id"),
                "valid": bool(_field(c, "valid", False)),
                "reason": _field(c, "reason"),
            }
            for c in validated
        ]

    @_never_raise
    def context_turns(self, turns: Iterable[Any]) -> None:
        """The prior turns actually sent to the model (rule M1), masked here again to be safe."""
        self._turns = []
        for i, turn in enumerate(turns, start=1):
            text = _field(turn, "text") or _field(turn, "content") or ""
            self._turns.append({
                "turn_index": i, "role": _field(turn, "role", "user"),
                "text_masked": mask_pii(text)[0], "chars": len(text),
            })

    @_never_raise
    def safety_flag(self, flag: str) -> None:
        if flag not in self._safety_flags:
            self._safety_flags.append(flag)

    @_never_raise
    def error(self, category: str) -> None:
        self._error_category = category

    # Finish ---------------------------------------------------------------

    def finish(
        self,
        answer: str | None,
        route: str | None,
        grounding_score: float | None = None,
        *,
        facts: OutcomeFacts | None = None,
        normalized_query: str | None = None,
        retrieval_relevant: bool | None = None,
        grounding_detail: Any = None,
        http_status: int = 200,
    ) -> FinishResult:
        latency_ms = round((time.perf_counter() - self._started) * 1000)
        try:
            return self._finish(
                answer, route, grounding_score, facts or OutcomeFacts(), normalized_query,
                retrieval_relevant, grounding_detail, http_status, latency_ms,
            )
        except Exception:
            log.exception("recorder.finish failed", extra={"query_id": self.query_id})
            return FinishResult(self.query_id, "FAILED", "SYSTEM_ERROR", None, 0, 0, None, False, latency_ms, False)

    def _finish(
        self, answer, route, grounding_score, facts, normalized_query,
        retrieval_relevant, grounding_detail, http_status, latency_ms,
    ) -> FinishResult:
        config = get_config()
        db_path = self._db_path or store.default_db_path()

        facts.citations_valid = sum(1 for c in self._citations if c["valid"])
        facts.citations_total = len(self._citations)
        if grounding_score is not None:
            facts.grounding_score = grounding_score
        if facts.top_score is None:
            facts.top_score = self._top_score()
        if self._error_category and not facts.system_error and answer is None:
            facts.system_error = True

        outcome, reason = self._classifier(facts, config.get("obs.grounding_min", 0.8))
        conf = confidence(outcome, facts.top_score, config.get("obs.relevance_high", 0.7))
        for flag, on in (("GUARD_BLOCKED", facts.blocked), ("FALLBACK", facts.fallback)):
            if on:
                self.safety_flag(flag)
        for flag in facts.extra_flags:
            self.safety_flag(flag)

        recorded = False
        cost: Decimal | None = Decimal(0)
        estimated = any(c["usage"].source == "ESTIMATED" for c in self._llm_calls)
        tokens_in = sum(c["usage"].tokens_in for c in self._llm_calls)
        tokens_out = sum(c["usage"].tokens_out for c in self._llm_calls)
        tokens_cached = sum(c["usage"].tokens_cached for c in self._llm_calls)

        try:
            conn = store.connect(db_path)
            try:
                prices = load_prices(db_path)
                call_costs = [
                    compute_cost(c["usage"], prices.get(c["model"]), c["cache_hit"]) for c in self._llm_calls
                ]
                # One unpriced call makes the whole query "price not set" rather than a low number.
                cost = None if any(c is None for c in call_costs) else sum(call_costs, Decimal(0))
                with conn:
                    self._write(
                        conn, answer, route, outcome, reason, conf, facts, normalized_query,
                        retrieval_relevant, grounding_detail, http_status, latency_ms,
                        tokens_in, tokens_out, tokens_cached, cost, estimated, call_costs, config.app.version,
                    )
                recorded = not self._broken
            finally:
                conn.close()
        except Exception:
            log.exception("recorder could not write the query; counted as dropped", extra={"query_id": self.query_id})
            _count_dropped(db_path)
        self._finished = True

        return FinishResult(
            self.query_id, outcome, reason, conf, tokens_in, tokens_out,
            format_usd(cost), estimated, latency_ms, recorded,
        )

    def _top_score(self) -> float | None:
        for name in ("reranked", "vector"):
            rows = self._hits.get(name)
            if rows and rows[0]["score"] is not None:
                return float(rows[0]["score"])
        return None

    def _write(
        self, conn, answer, route, outcome, reason, conf, facts, normalized_query, retrieval_relevant,
        grounding_detail, http_status, latency_ms, tokens_in, tokens_out, tokens_cached, cost, estimated,
        call_costs, app_version,
    ) -> None:
        qid = self.query_id
        conn.execute(
            """
            INSERT INTO query_event (
                query_id, ts, session_id, app_version, config_id, question_masked, normalized_query, route,
                answer, outcome, reason_code, confidence, retrieval_relevant, grounding_score,
                citations_valid, citations_total, safety_flags, latency_ms_total, tokens_in, tokens_out,
                tokens_cached, cost_usd, cost_estimated, http_status, grounding_detail, error_category,
                correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                qid, self._ts, self.session_id, app_version, self.config_id, self.question_masked,
                mask_pii(normalized_query)[0] if normalized_query else None, route,
                answer, outcome, reason, conf,
                None if retrieval_relevant is None else int(retrieval_relevant), facts.grounding_score,
                facts.citations_valid, facts.citations_total, json.dumps(self._safety_flags), latency_ms,
                tokens_in, tokens_out, tokens_cached, None if cost is None else str(cost), int(estimated),
                http_status, None if grounding_detail is None else json.dumps(grounding_detail, default=str),
                self._error_category, self.correlation_id,
            ),
        )
        conn.executemany(
            "INSERT INTO query_stage (query_id, seq, stage, status, latency_ms, retries, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (qid, i, s["stage"], s["status"], s["latency_ms"], s["retries"],
                 None if s["detail"] is None else json.dumps(s["detail"], default=str))
                for i, s in enumerate(self._stages, start=1)
            ],
        )
        conn.executemany(
            "INSERT INTO retrieval_hit (query_id, list, rank, chunk_id, document_id, page, score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (qid, name, h["rank"], h["chunk_id"], h["document_id"], h["page"], h["score"])
                for name, rows in self._hits.items() for h in rows
            ],
        )
        conn.executemany(
            "INSERT INTO llm_call (query_id, ts, purpose, model, prompt_version, tokens_in, tokens_out, "
            "tokens_cached, cache_hit, latency_ms, cost_usd, usage_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (qid, c["ts"], c["purpose"], c["model"], c["prompt_version"], c["usage"].tokens_in,
                 c["usage"].tokens_out, c["usage"].tokens_cached, int(c["cache_hit"]), c["latency_ms"],
                 None if cc is None else str(cc), c["usage"].source)
                for c, cc in zip(self._llm_calls, call_costs, strict=True)
            ],
        )
        conn.executemany(
            "INSERT INTO tool_call (tool_call_id, query_id, tool, tool_version, args_sanitized, status, row_count, "
            "result_summary, latency_ms, error_category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f"{qid}:{t['tool_call_id']}", qid, t["tool"], t["tool_version"], t["args_sanitized"], t["status"],
                 t["row_count"], t["result_summary"], t["latency_ms"], t["error_category"])
                for t in self._tool_calls
            ],
        )
        conn.executemany(
            "INSERT INTO citation (query_id, citation_id, chunk_id, tool_call_id, valid, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (qid, c["citation_id"], c["chunk_id"],
                 f"{qid}:{c['tool_call_id']}" if c["tool_call_id"] else None, int(c["valid"]), c["reason"])
                for c in self._citations
            ],
        )
        conn.executemany(
            "INSERT INTO context_turn (query_id, turn_index, role, text_masked, chars) VALUES (?, ?, ?, ?, ?)",
            [(qid, t["turn_index"], t["role"], t["text_masked"], t["chars"]) for t in self._turns],
        )


def _sanitize_args(args: dict[str, Any]) -> str:
    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return mask_pii(value)[0]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [clean(v) for v in value]
        return value

    return json.dumps(clean(args), default=str, sort_keys=True)


def record_ingest_llm_call(
    document_id: str,
    purpose: str,
    model: str,
    usage: Any = None,
    latency_ms: int | None = None,
    prompt_version: str | None = None,
    *,
    estimate: Usage | None = None,
    db_path: Path | None = None,
) -> str | None:
    """OCR and embedding calls during ingestion (Myank), so cost per document is visible.

    Written at once, since ingestion has no finish(). Never raises; returns the cost or None.
    """
    path = db_path or store.default_db_path()
    try:
        normalized = normalize_usage(usage) or estimate or Usage(source="ESTIMATED")
        cost = compute_cost(normalized, load_prices(path).get(model))
        conn = store.connect(path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO llm_call (document_id, ts, purpose, model, prompt_version, tokens_in, tokens_out, "
                    "tokens_cached, cache_hit, latency_ms, cost_usd, usage_source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                    (document_id, _now(), purpose, model, prompt_version, normalized.tokens_in, normalized.tokens_out,
                     normalized.tokens_cached, latency_ms, None if cost is None else str(cost), normalized.source),
                )
        finally:
            conn.close()
        return format_usd(cost)
    except Exception:
        log.exception("could not record an ingestion model call; counted as dropped")
        _count_dropped(path)
        return None
