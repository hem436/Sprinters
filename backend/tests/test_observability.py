"""WP-BE4 and WP-BE5: event store, QueryRecorder (the agent's RecorderPort), PII masking, tokens and cost."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent.service import Agent
from agent.stubs import FakeLLM, StubSearch, StubTools
from agent.types import Chunk, Hit, LLMReply, QueryResponse, ToolResult, UsageOut
from agent.validate import CitationCheck

from app.observability import store
from app.observability.cost import Price, compute_cost, format_usd
from app.observability.pii import mask_pii
from app.observability.recorder import QueryRecorder, dropped_events, record_ingest_llm_call
from app.observability.usage import Usage, normalize_usage


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "observability.db"
    store.init_db(path)
    store.seed_prices(path, store.load_price_file())
    return path


def rows(db: Path, sql: str, *params) -> list[sqlite3.Row]:
    conn = store.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


P104 = ToolResult(tool="budget_status", status="OK",
                  summary="P-104 TRAVEL FY2026-27: budget ₹4,00,000, spent ₹4,35,500, over by ₹35,500 (108.9 % used)",
                  rows=[{"project_id": "P-104", "pct_used": 108.9}],
                  args={"project_id": "P-104", "fiscal_year": "FY2026-27", "category": "TRAVEL"}, latency_ms=40)


def _response(rec: QueryRecorder, **overrides) -> QueryResponse:
    fields = dict(query_id=rec.query_id, answer_markdown="P-104 is over budget [T1][E1].", outcome="SUCCESS",
                  reason_code="OK", confidence="HIGH", route="BOTH", usage=UsageOut(tokens_in=2410, tokens_out=96),
                  latency_ms=3120)
    return QueryResponse(**{**fields, **overrides})


def _details(**overrides) -> dict:
    details = {
        "question_masked": "Is P-104 over its travel budget? Call me on [PHONE]",
        "normalized_query": "Is P-104 over its travel budget?",
        "route_reason": "PLANNER",
        "context_turns": [{"role": "user", "text_masked": "Mail me at a.b@example.com", "chars": 26}],
        "grounding_detail": [{"text": "P-104 spent ₹4,35,500", "citations": ["T1"], "supported": True, "reason": ""}],
        "safety_flags": [],
        "conflicts": [],
        "conflict_not_shown": False,
        "facts": {"citations_valid": 2, "citations_total": 2, "grounding_score": 1.0, "fallback": False},
    }
    return {**details, **overrides}


def _full_query(db: Path):
    rec = QueryRecorder.start("Is P-104 over its travel budget? Call me on 9876543210", "s-91", "B", db_path=db)
    with rec.stage("guard"):
        pass
    with rec.stage("retrieve_vector"):
        pass
    rec.hits("vector", [Hit("c_1", 0.62, 1)])
    rec.hits("reranked", [Hit("c_1", 0.81, 1)])
    rec.llm_call("route", LLMReply("{}", "openai/gpt-oss-20b", 380, 40, latency_ms=300), "route-v1")
    rec.llm_call("answer", LLMReply("{}", "openai/gpt-oss-120b", 2030, 56, latency_ms=2100), "answer-v1")
    rec.tool_call(P104)
    rec.citations([CitationCheck("T1", True, ""), CitationCheck("E1", True, "")])
    response = _response(rec)
    rec.finish(response, _details())
    return rec, response


# Recorder (WP-BE4), with the agent's own types --------------------------------

def test_recorder_writes_every_table(db):
    rec, response = _full_query(db)
    # route 380 x 0.075 + 40 x 0.30, answer 2030 x 0.15 + 56 x 0.60 = 378.6 per 1M
    assert response.usage.cost_usd == "0.000379"
    qid = rec.query_id
    assert len(qid) == 26
    for table, expected in [("query_stage", 2), ("retrieval_hit", 2), ("llm_call", 2), ("tool_call", 1),
                            ("citation", 2), ("context_turn", 1)]:
        assert len(rows(db, f"SELECT 1 FROM {table} WHERE query_id = ?", qid)) == expected, table
    (event,) = rows(db, "SELECT * FROM query_event WHERE query_id = ?", qid)
    assert (event["outcome"], event["reason_code"], event["route"]) == ("SUCCESS", "OK", "BOTH")
    assert event["tokens_in"] == 2410 and event["citations_valid"] == 2 and event["grounding_score"] == 1.0
    assert '"route_reason": "PLANNER"' in event["agent_detail"]
    (tool,) = rows(db, "SELECT * FROM tool_call WHERE query_id = ?", qid)
    assert tool["row_count"] == 1 and tool["tool_version"] == "1" and tool["result_summary"].startswith("P-104")
    (cite,) = rows(db, "SELECT tool_call_id FROM citation WHERE query_id = ? AND citation_id = 'T1'", qid)
    assert cite["tool_call_id"] == f"{qid}:T1"


def test_repair_call_is_stored(db):
    rec = QueryRecorder.start("q", "s", "B", db_path=db)
    rec.llm_call("repair", LLMReply("{}", "openai/gpt-oss-120b", 100, 20), "answer-v1")
    rec.finish(_response(rec), _details())
    assert rows(db, "SELECT purpose FROM llm_call WHERE query_id = ?", rec.query_id)[0]["purpose"] == "repair"


def test_smalltalk_reason_code_is_stored(db):
    rec = QueryRecorder.start("hello", "s", "B", db_path=db)
    rec.finish(_response(rec, route="CONVERSATIONAL", reason_code="OK_SMALLTALK"), _details())
    (event,) = rows(db, "SELECT reason_code FROM query_event WHERE query_id = ?", rec.query_id)
    assert event["reason_code"] == "OK_SMALLTALK"


def test_recorder_never_raises(tmp_path):
    broken = tmp_path / "not-a-dir"
    broken.write_text("a file where a folder should be")
    before = dropped_events()
    rec = QueryRecorder.start("question", "s", "A", db_path=broken / "x.db")
    with rec.stage("generate"):
        pass
    rec.hits("vector", None)                    # bad input is swallowed, not raised
    rec.tool_call(None)
    rec.finish(_response(rec), _details())
    assert dropped_events() == before + 1


def test_write_is_one_transaction(db):
    before = dropped_events()
    rec = QueryRecorder.start("q", "s", "A", db_path=db)
    # Two citations with the same id break the citation insert after query_event was written.
    rec.citations([CitationCheck("E1", True, ""), CitationCheck("E1", True, "")])
    rec.finish(_response(rec), _details())
    assert rows(db, "SELECT 1 FROM query_event WHERE query_id = ?", rec.query_id) == []
    assert dropped_events() == before + 1


def test_stage_records_error_and_reraises(db):
    rec = QueryRecorder.start("q", "s", "A", db_path=db)
    with pytest.raises(ValueError):
        with rec.stage("retrieve_bm25"):
            raise ValueError("index missing")
    with pytest.raises(TimeoutError):
        with rec.stage("tool"):
            raise TimeoutError
    rec.finish(_response(rec), _details())
    stages = rows(db, "SELECT stage, status FROM query_stage WHERE query_id = ? ORDER BY rowid", rec.query_id)
    assert [(s["stage"], s["status"]) for s in stages] == [("retrieve_bm25", "ERROR"), ("tool", "TIMEOUT")]


def test_failed_tool_keeps_its_reason(db):
    rec = QueryRecorder.start("q", "s", "A", db_path=db)
    rec.tool_call(ToolResult(tool="budget_status", status="TIMEOUT", args={"project_id": "P-104"},
                             message="query took longer than 2000 ms"))
    rec.finish(_response(rec), _details())
    (tool,) = rows(db, "SELECT status, error_category FROM tool_call WHERE query_id = ?", rec.query_id)
    assert (tool["status"], tool["error_category"]) == ("TIMEOUT", "query took longer than 2000 ms")


def test_agent_end_to_end_with_this_recorder(db):
    """Arka's real Agent, with his stubs for search, tools and the model, writing through this recorder."""
    chunk = Chunk("c_v2_overrun", "doc_travel_2", "travel-policy", "Travel and Expense Policy", "2.0", "2026-04-01",
                  9, "4.5 Overruns", "text", "Spend above the approved project budget needs department head approval.")
    args = {"project_id": "P-104", "fiscal_year": "FY2026-27", "category": "TRAVEL"}
    llm = FakeLLM({
        "route": [{"route": "BOTH", "standalone_query": "Is P-104 over budget?", "tool": "budget_status",
                   "tool_args": args}],
        "answer": [{"answer_markdown": "Yes [T1]. The department head must approve [E1].",
                    "claims": [{"text": "P-104 spent ₹4,35,500 against a travel budget of ₹4,00,000.",
                                "citations": ["T1"]},
                               {"text": "Spend above the approved project budget needs department head approval.",
                                "citations": ["E1"]}]}],
    })
    reranker = SimpleNamespace(score=lambda query, texts: [0.85 for _ in texts])
    agent = Agent(StubSearch({chunk.chunk_id: chunk}, vector=[Hit("c_v2_overrun", 0.8, 1)]),
                  StubTools(results={"budget_status": P104}), llm, reranker)

    rec = QueryRecorder.start("Is P-104 over its travel budget, and who must approve?", "s1", "B", db_path=db)
    response = agent.answer("Is P-104 over its travel budget, and who must approve?", "s1", rec)

    assert response.query_id == rec.query_id
    assert (response.outcome, response.route) == ("SUCCESS", "BOTH")
    assert response.usage.cost_usd is None       # the fake model has no price: "price not set", never 0
    (event,) = rows(db, "SELECT * FROM query_event WHERE query_id = ?", rec.query_id)
    assert (event["outcome"], event["reason_code"]) == (response.outcome, response.reason_code)
    stages = [r["stage"] for r in rows(db, "SELECT stage FROM query_stage WHERE query_id = ? ORDER BY rowid",
                                       rec.query_id)]
    assert stages[:2] == ["guard", "plan"] and "tool" in stages and stages[-1] == "validate"
    assert len(rows(db, "SELECT 1 FROM tool_call WHERE query_id = ?", rec.query_id)) == 1
    assert len(rows(db, "SELECT 1 FROM citation WHERE query_id = ? AND valid = 1", rec.query_id)) == 2


# Cost (WP-BE5) --------------------------------------------------------------

def test_cost_decimal():
    cost = compute_cost(Usage(1200, 300), Price(Decimal("0.15"), Decimal("0.60")))
    assert cost == Decimal("0.00036")
    assert format_usd(cost) == "0.000360"


def test_missing_price_not_zero(db):
    rec = QueryRecorder.start("What is the per diem?", "s-1", "A", db_path=db)
    rec.llm_call("answer", LLMReply("{}", "some/unpriced-model", 100, 10), "answer-v1")
    response = _response(rec)
    rec.finish(response, _details())
    assert response.usage.cost_usd is None
    (row,) = rows(db, "SELECT cost_usd FROM query_event WHERE query_id = ?", rec.query_id)
    assert row["cost_usd"] is None


def test_cached_tokens_use_cached_price():
    price = Price(Decimal("0.15"), Decimal("0.60"), Decimal("0.075"))
    # 1000 uncached at 0.15 + 1000 cached at 0.075, per 1M.
    assert compute_cost(Usage(2000, 0, 1000), price) == Decimal("0.000225")


def test_cache_hit_costs_zero(db):
    rec = QueryRecorder.start("q", "s", "B", db_path=db)
    rec.llm_call("answer", LLMReply("{}", "openai/gpt-oss-120b", 5000, 500, cache_hit=True), "answer-v1")
    response = _response(rec)
    rec.finish(response, _details())
    assert response.usage.cost_usd == "0.000000"


def test_estimated_usage_is_marked(db):
    rec = QueryRecorder.start("q", "s", "B", db_path=db)
    rec.llm_call("answer", LLMReply("{}", "openai/gpt-oss-120b", 100, 10, usage_source="ESTIMATED"), "answer-v1")
    rec.finish(_response(rec), _details())
    (event,) = rows(db, "SELECT cost_estimated FROM query_event WHERE query_id = ?", rec.query_id)
    assert event["cost_estimated"] == 1


def test_prices_come_from_the_reviewed_file(db):
    (row,) = rows(db, "SELECT * FROM model_price WHERE model = 'openai/gpt-oss-120b'")
    assert row["usd_per_1m_in"] == "0.15" and row["source_url"] and row["checked_on"] == "2026-10-27"


def test_ingestion_usage_from_gemini_shape_is_per_document(db):
    gemini_like = SimpleNamespace(prompt_token_count=1000, candidates_token_count=200, cached_content_token_count=None)
    assert normalize_usage(gemini_like) == Usage(1000, 200, 0, "PROVIDER")
    cost = record_ingest_llm_call("doc_19c0", "ocr", "gemini-2.5-flash", gemini_like, 6000, "ocr-v1", db_path=db)
    assert cost == "0.000800"   # 1000 x 0.30 + 200 x 2.50, per 1M
    (row,) = rows(db, "SELECT query_id FROM llm_call WHERE document_id = 'doc_19c0'")
    assert row["query_id"] is None


# PII ----------------------------------------------------------------------

def test_pii_masked(db):
    rec, _ = _full_query(db)
    assert "9876543210" not in rec.question_masked
    (event,) = rows(db, "SELECT question_masked, safety_flags FROM query_event WHERE query_id = ?", rec.query_id)
    assert "9876543210" not in event["question_masked"] and "PII" in event["safety_flags"]
    (turn,) = rows(db, "SELECT text_masked FROM context_turn WHERE query_id = ?", rec.query_id)
    assert "a.b@example.com" not in turn["text_masked"]


@pytest.mark.parametrize("text, kind", [
    ("mail a.b@example.com", "EMAIL"),
    ("call +91 98765 43210", "PHONE"),
    ("PAN ABCDE1234F", "PAN"),
    ("aadhaar 2345 6789 0123", "AADHAAR"),
    ("card 4111 1111 1111 1111", "CARD"),
])
def test_pii_kinds(text, kind):
    masked, found = mask_pii(text)
    assert found == [kind] and f"[{kind}]" in masked


def test_business_ids_and_amounts_are_not_pii():
    text = "P-104 claim EXP-20871 by E1042 on LT-0457: ₹4,35,500 in FY2026-27, POL-HR-014"
    assert mask_pii(text) == (text, [])
