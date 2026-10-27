"""QueryRecorder: implements the agent's RecorderPort (model/agent/ports.py; contract 11 section 3).

    rec = QueryRecorder.start(question, session_id, config_id)    # assigns query_id
    with rec.stage("retrieve_vector"):                             # times it; ERROR or TIMEOUT on exception
        ...
    rec.hits("vector", hits)                                       # agent Hit: chunk_id, score, rank
    rec.llm_call("answer", reply, "answer-v1")                     # agent LLMReply
    rec.tool_call(result)                                          # agent ToolResult
    rec.citations(checks)                                          # agent CitationCheck: id, valid, reason
    rec.finish(response, details)                                  # agent QueryResponse and details dict

The agent decides the outcome; the recorder stores it and prices the model calls, writing
response.usage.cost_usd. No method raises into the answer path. Everything is written once,
in finish(), in one transaction. A failed write is logged, dropped and counted (dropped_events()).
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
        self._ts = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self._stages: list[dict[str, Any]] = []
        self._hits: dict[str, list[dict[str, Any]]] = {}
        self._llm_calls: list[dict[str, Any]] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._citations: list[dict[str, Any]] = []

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
    def llm_call(self, purpose: str, reply: Any, prompt_version: str | None = None) -> None:
        """reply: the agent's LLMReply (model, tokens in, out, cached, latency, cache_hit, usage_source)."""
        self._llm_calls.append({
            "purpose": purpose,
            "model": reply.model,
            "prompt_version": prompt_version,
            "cache_hit": bool(reply.cache_hit),
            "latency_ms": reply.latency_ms,
            "usage": Usage(reply.tokens_in, reply.tokens_out, reply.tokens_cached, reply.usage_source),
        })

    @_never_raise
    def tool_call(self, result: Any) -> None:
        """result: the agent's ToolResult. Ids T1, T2 follow call order, as the agent's evidence ids do."""
        failed = result.status not in ("OK", "EMPTY")
        self._tool_calls.append({
            "tool_call_id": f"T{len(self._tool_calls) + 1}",
            "tool": result.tool,
            "tool_version": str(result.version),
            "args_sanitized": json.dumps(_mask_values(result.args or {}), default=str, sort_keys=True),
            "status": result.status,
            "row_count": len(result.rows or []),
            "result_summary": mask_pii(result.summary)[0] if result.summary else None,
            "latency_ms": result.latency_ms,
            "error_category": (result.message or result.status) if failed else None,
        })

    @_never_raise
    def citations(self, checks: Iterable[Any]) -> None:
        """checks: the agent's CitationCheck list (rule V1): id, valid, reason."""
        self._citations = [
            {"citation_id": _field(c, "id"), "valid": bool(_field(c, "valid")), "reason": _field(c, "reason")}
            for c in checks
        ]

    def finish(self, response: Any, details: dict[str, Any]) -> None:
        """Stores the agent's QueryResponse and details in one transaction; fills response.usage.cost_usd.

        Never raises. details: question_masked, normalized_query, route_reason, context_turns,
        grounding_detail, safety_flags, conflicts, conflict_not_shown, facts.
        """
        try:
            config = get_config()
            db_path = self._db_path or store.default_db_path()
            facts = details.get("facts") or {}
            usages = [c["usage"] for c in self._llm_calls]

            prices = load_prices(db_path)
            call_costs = [compute_cost(c["usage"], prices.get(c["model"]), c["cache_hit"]) for c in self._llm_calls]
            # One unpriced call makes the query "price not set" rather than a low number.
            cost = None if None in call_costs else sum(call_costs, Decimal(0))
            response.usage.cost_usd = format_usd(cost)

            flags = list(details.get("safety_flags") or []) + (["PII"] if self.pii_found else [])
            if facts.get("fallback"):
                flags.append("FALLBACK")
            event = {
                "query_id": self.query_id, "ts": self._ts, "session_id": self.session_id,
                "app_version": config.app.version, "config_id": self.config_id,
                "question_masked": details.get("question_masked") or self.question_masked,
                "normalized_query": details.get("normalized_query"),
                "route": response.route, "answer": response.answer_markdown,
                "outcome": response.outcome, "reason_code": response.reason_code, "confidence": response.confidence,
                "retrieval_relevant": None,   # not reported by the agent yet
                "grounding_score": facts.get("grounding_score"),
                "citations_valid": facts.get("citations_valid", sum(c["valid"] for c in self._citations)),
                "citations_total": facts.get("citations_total", len(self._citations)),
                "safety_flags": json.dumps(list(dict.fromkeys(flags))),
                "latency_ms_total": response.latency_ms,
                "tokens_in": sum(u.tokens_in for u in usages), "tokens_out": sum(u.tokens_out for u in usages),
                "tokens_cached": sum(u.tokens_cached for u in usages),
                "cost_usd": None if cost is None else str(cost),
                "cost_estimated": int(any(u.source == "ESTIMATED" for u in usages)),
                "http_status": 200,
                "grounding_detail": _json(details.get("grounding_detail")),
                "error_category": "SYSTEM_ERROR" if facts.get("system_error") else None,
                "correlation_id": self.correlation_id,
                "agent_detail": _json({k: details.get(k) for k in
                                       ("route_reason", "conflicts", "conflict_not_shown", "facts")}),
            }
            self._write(db_path, event, call_costs, details.get("context_turns") or [])
        except Exception:
            log.exception("recorder could not write the query; counted as dropped", extra={"query_id": self.query_id})
            _count_dropped()

    def _write(self, db_path: Path, event: dict[str, Any], call_costs: list[Decimal | None],
               turns: list[dict[str, Any]]) -> None:
        qid = self.query_id
        tool_ids = {t["tool_call_id"] for t in self._tool_calls}
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
                     "cost_usd": None if cc is None else str(cc), "usage_source": c["usage"].source}
                    for c, cc in zip(self._llm_calls, call_costs, strict=True)
                ])
                # Tool call ids are T1, T2 per query; stored with the query id so they are unique.
                _insert(conn, "tool_call", [{**t, "query_id": qid, "tool_call_id": f"{qid}:{t['tool_call_id']}"}
                                            for t in self._tool_calls])
                _insert(conn, "citation", [
                    {"query_id": qid, **c, "valid": int(c["valid"]),
                     "tool_call_id": f"{qid}:{c['citation_id']}" if c["citation_id"] in tool_ids else None}
                    for c in self._citations
                ])
                _insert(conn, "context_turn", [
                    {"query_id": qid, "turn_index": i, "role": t.get("role", "user"),
                     "text_masked": mask_pii(t.get("text_masked", ""))[0], "chars": t.get("chars", 0)}
                    for i, t in enumerate(turns, start=1)
                ])
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
