"""The dashboard's numbers, all read from observability.db (contract 11 section 9).

Shapes follow the web app (web/src/api/types.ts): MetricsSummary, Page<QueryListRow> and DrillDown.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.observability.cost import format_usd
from app.observability.recorder import dropped_events

RETRIEVAL_STAGES = ("retrieve_vector", "retrieve_bm25", "fuse", "rerank")


def _where(filters: dict[str, Any], alias: str = "q") -> tuple[str, dict[str, Any]]:
    clauses, params = [], {}
    for key, column, op in (("from", "ts", ">="), ("to", "ts", "<="), ("config_id", "config_id", "="),
                            ("route", "route", "="), ("outcome", "outcome", "=")):
        if filters.get(key):
            clauses.append(f"{alias}.{column} {op} :{key}")
            params[key] = filters[key]
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _pct(values: list[float], p: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    return round(values[min(len(values) - 1, int(p * len(values)))])


def _latency(values: list[float]) -> dict[str, int]:
    return {"p50": _pct(values, 0.5), "p95": _pct(values, 0.95)}


def _sum_cost(values: list[str | None]) -> Decimal | None:
    priced = [Decimal(v) for v in values if v is not None]
    return sum(priced, Decimal(0)) if priced else None


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def summary(db: Path, filters: dict[str, Any], grounding_min: float = 0.8,
            document_titles: dict[str, str] | None = None) -> dict[str, Any]:
    where, params = _where(filters)
    conn = _connect(db)
    try:
        q = [dict(r) for r in conn.execute(f"SELECT * FROM query_event q {where}", params)]
        ids = [r["query_id"] for r in q]
        scope = f"query_id IN (SELECT q.query_id FROM query_event q {where})"

        outcomes = {o: sum(1 for r in q if r["outcome"] == o) for o in ("SUCCESS", "PARTIAL", "FAILED")}
        buckets: dict[str, dict[str, int]] = {}
        for r in q:
            b = buckets.setdefault(r["ts"][:10], {"SUCCESS": 0, "PARTIAL": 0, "FAILED": 0})
            b[r["outcome"]] += 1

        relevant = [r["retrieval_relevant"] for r in q if r["retrieval_relevant"] is not None]
        grounded = [r["grounding_score"] for r in q if r["grounding_score"] is not None]
        tools = conn.execute(f"SELECT COUNT(*), SUM(status = 'OK') FROM tool_call WHERE {scope}", params).fetchone()
        flags: dict[str, int] = {}
        for r in q:
            for flag in json.loads(r["safety_flags"] or "[]"):
                flags[flag] = flags.get(flag, 0) + 1

        def per_query(sql: str) -> list[float]:
            got = dict(conn.execute(sql + f" AND {scope} GROUP BY query_id", params).fetchall())
            return [got.get(i, 0) for i in ids]

        stage_in = ", ".join(f"'{s}'" for s in RETRIEVAL_STAGES)
        latency = {
            "total": _latency([r["latency_ms_total"] or 0 for r in q]),
            "retrieval": _latency(per_query(
                f"SELECT query_id, SUM(latency_ms) FROM query_stage WHERE stage IN ({stage_in})")),
            "tool": _latency(per_query("SELECT query_id, SUM(latency_ms) FROM query_stage WHERE stage = 'tool'")),
            "llm": _latency(per_query("SELECT query_id, SUM(latency_ms) FROM llm_call WHERE query_id IS NOT NULL")),
        }

        total_cost = _sum_cost([r["cost_usd"] for r in q])
        priced = sum(1 for r in q if r["cost_usd"] is not None)
        routes: dict[str, list] = {}
        for r in q:
            routes.setdefault(r["route"], []).append(r["cost_usd"])
        ingest = conn.execute("SELECT document_id, cost_usd FROM llm_call WHERE document_id IS NOT NULL").fetchall()
        per_doc: dict[str, list] = {}
        for doc, cost in ingest:
            per_doc.setdefault(doc, []).append(cost)
        titles = document_titles or {}

        fb = conn.execute(f"SELECT SUM(helpful = 1), SUM(helpful = 0) FROM feedback WHERE {scope}", params).fetchone()
        hit = conn.execute("SELECT summary FROM eval_run WHERE status = 'DONE' ORDER BY finished_at DESC LIMIT 1"
                           ).fetchone()
    finally:
        conn.close()

    return {
        "total_queries": len(q),
        "outcomes": outcomes,
        "outcome_over_time": [{"bucket": k, **v} for k, v in sorted(buckets.items())],
        "retrieval_success_rate": round(sum(relevant) / len(relevant), 3) if relevant else 0,
        "hit_at_5": (json.loads(hit[0]) or {}).get("hit_at_5") if hit and hit[0] else None,
        "grounding_rate": round(sum(g >= grounding_min for g in grounded) / len(grounded), 3) if grounded else 0,
        "citation_support": {"valid": sum(r["citations_valid"] for r in q),
                             "total": sum(r["citations_total"] for r in q)},
        "tool_success": {"ok": tools[1] or 0, "total": tools[0] or 0},
        "safety_events": flags,
        "latency_ms": latency,
        "usage": {
            "tokens_in": sum(r["tokens_in"] for r in q),
            "tokens_out": sum(r["tokens_out"] for r in q),
            "total_cost_usd": format_usd(total_cost),
            "cost_per_query_usd": format_usd(total_cost / priced) if total_cost is not None and priced else None,
            "cost_per_route": [{"route": route, "cost_usd": format_usd(_sum_cost(costs)), "queries": len(costs)}
                               for route, costs in sorted(routes.items(), key=lambda kv: str(kv[0]))],
            "ingestion_cost_per_document": [
                {"document_id": doc, "title": titles.get(doc, doc), "cost_usd": format_usd(_sum_cost(costs))}
                for doc, costs in sorted(per_doc.items())],
        },
        "feedback": {"helpful": fb[0] or 0, "not_helpful": fb[1] or 0},
        "dropped_events": dropped_events(),
    }


def list_queries(db: Path, filters: dict[str, Any], page: int, page_size: int) -> dict[str, Any]:
    where, params = _where(filters)
    conn = _connect(db)
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM query_event q {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT q.query_id, q.ts, q.question_masked, q.route, q.outcome, q.reason_code,
                       q.latency_ms_total AS latency_ms, q.cost_usd, f.helpful
                FROM query_event q LEFT JOIN feedback f ON f.query_id = q.query_id {where}
                ORDER BY q.ts DESC LIMIT :limit OFFSET :offset""",
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        ).fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        item = dict(r)
        helpful = item.pop("helpful")
        item["cost_usd"] = format_usd(Decimal(item["cost_usd"])) if item["cost_usd"] is not None else None
        item["feedback"] = None if helpful is None else ("HELPFUL" if helpful else "NOT_HELPFUL")
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def drill_down(db: Path, query_id: str) -> dict[str, Any] | None:
    conn = _connect(db)
    try:
        q = conn.execute("SELECT * FROM query_event WHERE query_id = ?", (query_id,)).fetchone()
        if q is None:
            return None

        def rows(sql: str) -> list[dict]:
            return [dict(r) for r in conn.execute(sql, (query_id,))]

        stages = rows("SELECT stage, status, latency_ms, retries, detail FROM query_stage WHERE query_id = ? "
                      "ORDER BY rowid")
        hits = rows("SELECT list, rank, chunk_id, document_id, page, score FROM retrieval_hit WHERE query_id = ? "
                    "ORDER BY list, rank")
        calls = rows("SELECT * FROM llm_call WHERE query_id = ? ORDER BY call_id")
        tools = rows("SELECT * FROM tool_call WHERE query_id = ? ORDER BY rowid")
        cites = rows("SELECT citation_id, valid, reason FROM citation WHERE query_id = ?")
        turns = rows("SELECT turn_index, role, chars, text_masked FROM context_turn WHERE query_id = ? "
                     "ORDER BY turn_index")
        fb = conn.execute("SELECT helpful, comment FROM feedback WHERE query_id = ?", (query_id,)).fetchone()
        reviews = [r["comment"] for r in rows("SELECT comment FROM query_review WHERE query_id = ? ORDER BY ts")]
    finally:
        conn.close()

    details = {s["stage"]: json.loads(s["detail"]) if s["detail"] else {} for s in stages}
    flags = json.loads(q["safety_flags"] or "[]")
    answer_calls = [c for c in calls if c["purpose"] == "answer"]
    gen = answer_calls[-1] if answer_calls else (calls[-1] if calls else None)
    validate = next((s for s in stages if s["stage"] == "validate"), None)
    reranked = [h for h in hits if h["list"] == "reranked"] or [h for h in hits if h["list"] == "vector"]

    def ms(names: tuple[str, ...]) -> int:
        return sum(s["latency_ms"] or 0 for s in stages if s["stage"] in names)

    return {
        "identity": {"query_id": q["query_id"], "ts": q["ts"], "session_id": q["session_id"],
                     "app_version": q["app_version"], "config_id": q["config_id"]},
        "question": {"original_masked": q["question_masked"], "normalized": q["normalized_query"],
                     "route": q["route"], "route_reason": details.get("plan", {}).get("route_reason")},
        "execution": [{"stage": s["stage"], "status": s["status"], "latency_ms": s["latency_ms"],
                       "detail": s["detail"]} for s in stages],
        "outcome": {"outcome": q["outcome"], "reason_code": q["reason_code"]},
        "retrieval": {name: [{"rank": h["rank"], "chunk_id": h["chunk_id"], "doc": h["document_id"],
                              "page": h["page"], "score": h["score"]} for h in hits if h["list"] == name]
                      for name in ("vector", "bm25", "fused", "reranked")},
        "evidence_quality": {"relevant": bool(q["retrieval_relevant"]) if q["retrieval_relevant"] is not None
                             else None, "top_score": reranked[0]["score"] if reranked else None,
                             "expected_match": None},
        "context_turns": turns,
        "tool_calls": [{"tool": t["tool"], "args_sanitized": json.loads(t["args_sanitized"] or "{}"),
                        "status": t["status"], "row_count": t["row_count"], "summary": t["result_summary"],
                        "latency_ms": t["latency_ms"],
                        # the fixed SQL that ran, with its bound parameters: where each number came from
                        "sql": json.loads(t["sql_text"]) if t.get("sql_text") else []} for t in tools],
        "generation": {"model": gen["model"] if gen else None, "prompt_version": gen["prompt_version"] if gen else None,
                       "validation": validate["status"] if validate else None,
                       "raw_output": gen["raw_output"] if gen else None},
        "citations": [{"id": c["citation_id"], "valid": bool(c["valid"]), "reason": c["reason"]} for c in cites],
        "grounding": {"score": q["grounding_score"],
                      "claims": [{"text": c.get("text"), "supported": c.get("supported")}
                                 for c in json.loads(q["grounding_detail"] or "[]")]},
        "safety": {"flags": flags, "pii_masked": "PII" in flags, "fallback": "FALLBACK" in flags},
        "performance": {"retrieval_ms": ms(RETRIEVAL_STAGES), "tool_ms": ms(("tool",)),
                        "llm_ms": sum(c["latency_ms"] or 0 for c in calls), "total_ms": q["latency_ms_total"]},
        "usage": {"calls": [{"purpose": c["purpose"], "tokens_in": c["tokens_in"], "tokens_out": c["tokens_out"],
                             "cached_tokens": c["tokens_cached"]} for c in calls],
                  "cost_usd": format_usd(Decimal(q["cost_usd"])) if q["cost_usd"] is not None else None,
                  "usage_source": "ESTIMATED" if q["cost_estimated"] else "PROVIDER"},
        "feedback": None if fb is None or fb["helpful"] is None else {"helpful": bool(fb["helpful"]),
                                                                       "comment": fb["comment"]},
        "reviewer_comments": reviews,
        "errors": [{"category": q["error_category"] or s["status"], "stage": s["stage"], "retries": s["retries"],
                    "correlation_id": q["correlation_id"]} for s in stages if s["status"] in ("ERROR", "TIMEOUT")],
    }
