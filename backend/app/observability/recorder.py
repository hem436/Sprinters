"""QueryRecorder: the interface from the agent (P2) to the event store (contract 11 section 3).

    rec = QueryRecorder.start(question, session_id, config_id)    # assigns query_id, masks PII
    with rec.stage("retrieve_vector"):                             # times it; ERROR or TIMEOUT on exception
        hits = vector_search(...)
    rec.hits("vector", hits)
    rec.llm_call(purpose="answer", model=m, usage=resp.usage, latency_ms=t, prompt_version="answer-v1")
    rec.tool_call(tool="budget_status", args=args, status="OK", row_count=1, latency_ms=40)
    rec.citations(validated)        # [{citation_id, chunk_id | tool_call_id, valid, reason?}]
    result = rec.finish(answer, route, grounding_score, facts=OutcomeFacts(...))

No method raises into the answer path. Everything is written once, in finish(), in one
transaction. A failed write is logged, dropped and counted (dropped_events()).
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Iterable, Iterator
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
from app.observability.outcome import OutcomeFacts, classify
from app.observability.outcome import confidence as confidence_for
from app.observability.pii import mask_pii
from app.observability.usage import Usage, normalize_usage

log = logging.getLogger(__name__)

_dropped = 0


def dropped_events() -> int:
    """Writes lost since the process started; the dashboard shows this number."""
    return _dropped


def _count_dropped() -> None:
    global _dropped
    _dropped += 1


def _field(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _never_raise(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            log.exception("recorder.%s failed", method.__name__, extra={"query_id": self.query_id})
            return None

    return wrapper


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
    ) -> None:
        self.query_id = query_id or new_ulid()
        self.session_id = session_id
        self.config_id = config_id
        self.correlation_id = correlation_id
        self.question_masked, self.pii_found = mask_pii(question)
        self._db_path = db_path
        self._started = time.perf_counter()
        self._ts = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self._stages: list[dict[str, Any]] = []
        self._hits: dict[str, list[dict[str, Any]]] = {}
        self._llm_calls: list[dict[str, Any]] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._citations: list[dict[str, Any]] = []
        self._turns: list[dict[str, Any]] = []

    @classmethod
    def start(cls, question: str, session_id: str | None, config_id: str | None, **kwargs: Any) -> QueryRecorder:
        return cls(question, session_id, config_id, **kwargs)

    @contextmanager
    def stage(self, name: str, *, retries: int = 0) -> Iterator[StageHandle]:
        """Records the stage even when it fails; the agent's own exception still propagates."""
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
            self._stages.append({
                "stage": name, "status": status, "retries": handle.retries, "detail": handle.detail or None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            })

    @_never_raise
    def stage_skipped(self, name: str, reason: str | None = None) -> None:
        self._stages.append({
            "stage": name, "status": "SKIPPED", "latency_ms": 0, "retries": 0,
            "detail": {"reason": reason} if reason else None,
        })

    @_never_raise
    def hits(self, list_name: str, hits: Iterable[Any]) -> None:
        self._hits[list_name] = [
            {
                "rank": _field(hit, "rank") or i,
                "chunk_id": _field(hit, "chunk_id"),
                "document_id": _field(hit, "document_id"),
                "page": _field(hit, "page"),
                "score": _field(hit, "score"),
            }
            for i, hit in enumerate(hits, start=1)
        ]

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
        raw_output: str | None = None,
    ) -> None:
        """usage: the provider's usage object. If it is missing, pass estimate=estimated_usage(...).
        raw_output: the model's reply text, shown in the drill-down (masked before it is stored)."""
        self._llm_calls.append({
            "purpose": purpose, "model": model, "prompt_version": prompt_version, "cache_hit": cache_hit,
            "latency_ms": latency_ms, "usage": normalize_usage(usage) or estimate or Usage(source="ESTIMATED"),
            "raw_output": mask_pii(raw_output)[0] if raw_output else None,
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
    ) -> str:
        """Returns the tool call id (T1, T2, ...) that a citation points to."""
        call_id = f"T{len(self._tool_calls) + 1}"
        self._tool_calls.append({
            "tool_call_id": call_id, "tool": tool, "tool_version": None if version is None else str(version),
            "args_sanitized": json.dumps(_mask_values(args or {}), default=str, sort_keys=True),
            "status": status, "row_count": row_count, "latency_ms": latency_ms, "error_category": error_category,
            "result_summary": mask_pii(result_summary)[0] if result_summary else None,
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
        """The prior turns actually sent to the model (rule M1)."""
        self._turns = []
        for i, turn in enumerate(turns, start=1):
            text = _field(turn, "text") or _field(turn, "content") or ""
            self._turns.append({
                "turn_index": i, "role": _field(turn, "role", "user"),
                "text_masked": mask_pii(text)[0], "chars": len(text),
            })

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
        safety_flags: Iterable[str] = (),
        error_category: str | None = None,
        http_status: int = 200,
        outcome: str | None = None,
        reason_code: str | None = None,
        confidence: str | None = None,
    ) -> FinishResult:
        """Writes every row in one transaction. Never raises.

        The agent's outcome, reason_code and confidence are stored as given, so the dashboard
        shows what the user saw (one copy of the rules: model/README.md open item 1). The recorder's
        own rules run only when the agent gave none, for example a system error before the agent ran.
        """
        given = (outcome, reason_code) if outcome and reason_code else None
        latency_ms = round((time.perf_counter() - self._started) * 1000)
        facts = facts or OutcomeFacts()
        outcome, reason, conf, cost = "FAILED", "SYSTEM_ERROR", None, None
        usages = [c["usage"] for c in self._llm_calls]
        tokens_in = sum(u.tokens_in for u in usages)
        tokens_out = sum(u.tokens_out for u in usages)
        estimated = any(u.source == "ESTIMATED" for u in usages)
        recorded = False
        try:
            config = get_config()
            db_path = self._db_path or store.default_db_path()

            facts.citations_valid = sum(1 for c in self._citations if c["valid"])
            facts.citations_total = len(self._citations)
            if grounding_score is not None:
                facts.grounding_score = grounding_score
            if facts.top_score is None:
                facts.top_score = self._top_score()
            outcome, reason = given or classify(facts, config.get("obs.grounding_min", 0.8))
            conf = confidence if given and confidence else confidence_for(
                outcome, facts.top_score, config.get("obs.relevance_high", 0.7))

            flags = (["PII"] if self.pii_found else []) + list(safety_flags)
            flags += [f for f, on in (("GUARD_BLOCKED", facts.blocked), ("FALLBACK", facts.fallback)) if on]

            prices = load_prices(db_path)
            call_costs = [compute_cost(c["usage"], prices.get(c["model"]), c["cache_hit"]) for c in self._llm_calls]
            # One unpriced call makes the query "price not set" rather than a low number.
            cost = None if None in call_costs else sum(call_costs, Decimal(0))

            event = {
                "query_id": self.query_id, "ts": self._ts, "session_id": self.session_id,
                "app_version": config.app.version, "config_id": self.config_id,
                "question_masked": self.question_masked,
                "normalized_query": mask_pii(normalized_query)[0] if normalized_query else None,
                "route": route, "answer": answer, "outcome": outcome, "reason_code": reason, "confidence": conf,
                "retrieval_relevant": None if retrieval_relevant is None else int(retrieval_relevant),
                "grounding_score": facts.grounding_score, "citations_valid": facts.citations_valid,
                "citations_total": facts.citations_total, "safety_flags": json.dumps(list(dict.fromkeys(flags))),
                "latency_ms_total": latency_ms, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "tokens_cached": sum(u.tokens_cached for u in usages),
                "cost_usd": None if cost is None else str(cost), "cost_estimated": int(estimated),
                "http_status": http_status,
                "grounding_detail": None if grounding_detail is None else json.dumps(grounding_detail, default=str),
                "error_category": error_category, "correlation_id": self.correlation_id,
            }
            self._write(db_path, event, call_costs)
            recorded = True
        except Exception:
            log.exception("recorder could not write the query; counted as dropped", extra={"query_id": self.query_id})
            _count_dropped()

        return FinishResult(
            self.query_id, outcome, reason, conf, tokens_in, tokens_out, format_usd(cost), estimated, latency_ms,
            recorded,
        )

    def _top_score(self) -> float | None:
        for name in ("reranked", "vector"):
            rows = self._hits.get(name)
            if rows and rows[0]["score"] is not None:
                return float(rows[0]["score"])
        return None

    def _write(self, db_path: Path, event: dict[str, Any], call_costs: list[Decimal | None]) -> None:
        qid = self.query_id
        conn = store.connect(db_path)
        try:
            with conn:
                _insert(conn, "query_event", [event])
                _insert(conn, "query_stage", [{"query_id": qid, **s, "detail": _json(s["detail"])}
                                              for s in self._stages])
                _insert(conn, "retrieval_hit", [{"query_id": qid, "list": name, **h}
                                                for name, rows in self._hits.items() for h in rows])
                _insert(conn, "llm_call", [
                    {"query_id": qid, "purpose": c["purpose"], "model": c["model"],
                     "prompt_version": c["prompt_version"], "tokens_in": c["usage"].tokens_in,
                     "tokens_out": c["usage"].tokens_out, "tokens_cached": c["usage"].tokens_cached,
                     "cache_hit": int(c["cache_hit"]), "latency_ms": c["latency_ms"],
                     "cost_usd": None if cc is None else str(cc), "usage_source": c["usage"].source,
                     "raw_output": c.get("raw_output")}
                    for c, cc in zip(self._llm_calls, call_costs, strict=True)
                ])
                # Tool call ids are T1, T2 per query; stored with the query id so they are unique.
                _insert(conn, "tool_call", [{**t, "query_id": qid, "tool_call_id": f"{qid}:{t['tool_call_id']}"}
                                            for t in self._tool_calls])
                _insert(conn, "citation", [
                    {"query_id": qid, **c, "valid": int(c["valid"]),
                     "tool_call_id": f"{qid}:{c['tool_call_id']}" if c["tool_call_id"] else None}
                    for c in self._citations
                ])
                _insert(conn, "context_turn", [{"query_id": qid, **t} for t in self._turns])
        finally:
            conn.close()


def _insert(conn, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    conn.executemany(sql, rows)


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str)


def _mask_values(value: Any) -> Any:
    if isinstance(value, str):
        return mask_pii(value)[0]
    if isinstance(value, dict):
        return {k: _mask_values(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask_values(v) for v in value]
    return value


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
    try:
        path = db_path or store.default_db_path()
        u = normalize_usage(usage) or estimate or Usage(source="ESTIMATED")
        cost = compute_cost(u, load_prices(path).get(model))
        conn = store.connect(path)
        try:
            with conn:
                _insert(conn, "llm_call", [{
                    "document_id": document_id, "purpose": purpose, "model": model, "prompt_version": prompt_version,
                    "tokens_in": u.tokens_in, "tokens_out": u.tokens_out, "tokens_cached": u.tokens_cached,
                    "cache_hit": 0, "latency_ms": latency_ms, "cost_usd": None if cost is None else str(cost),
                    "usage_source": u.source,
                }])
        finally:
            conn.close()
        return format_usd(cost)
    except Exception:
        log.exception("could not record an ingestion model call; counted as dropped")
        _count_dropped()
        return None
