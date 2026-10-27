"""WP-BE4 and WP-BE5: event store, QueryRecorder, PII masking, tokens and cost (contract 11 sections 2 to 5)."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.observability import store
from app.observability.cost import Price, compute_cost, format_usd
from app.observability.outcome import OutcomeFacts, classify, confidence
from app.observability.pii import mask_pii
from app.observability.recorder import QueryRecorder, dropped_events, record_ingest_llm_call
from app.observability.usage import Usage, estimated_usage, normalize_usage


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


def _full_query(db: Path, **finish_kwargs):
    rec = QueryRecorder.start("Is P-104 over its travel budget? Call me on 9876543210", "s-91", "B", db_path=db)
    with rec.stage("guard"):
        pass
    with rec.stage("retrieve_vector"):
        pass
    rec.hits("vector", [{"chunk_id": "c_1", "document_id": "doc_7f3a", "page": 7, "score": 0.62}])
    rec.hits("reranked", [SimpleNamespace(chunk_id="c_1", document_id="doc_7f3a", page=7, score=0.81)])
    rec.llm_call("route", "openai/gpt-oss-20b", {"prompt_tokens": 380, "completion_tokens": 40}, 300, "route-v1")
    rec.llm_call("answer", "openai/gpt-oss-120b", {"prompt_tokens": 2030, "completion_tokens": 56}, 2100, "answer-v1")
    t1 = rec.tool_call("budget_status", {"project_id": "P-104", "fiscal_year": "FY2026-27"}, "OK", 1, 40,
                       result_summary="P-104 TRAVEL FY2026-27: budget ₹4,00,000, spent ₹4,35,500", version=1)
    rec.citations([
        {"citation_id": "E1", "chunk_id": "c_1", "valid": True},
        {"citation_id": t1, "tool_call_id": t1, "valid": True},
    ])
    rec.context_turns([{"role": "user", "text": "Mail me at a.b@example.com"}])
    return rec, rec.finish("P-104 is over budget [E1][T1].", "BOTH", 1.0, **finish_kwargs)


# Cost (WP-BE5) --------------------------------------------------------------

def test_cost_decimal():
    cost = compute_cost(Usage(1200, 300), Price(Decimal("0.15"), Decimal("0.60")))
    assert cost == Decimal("0.00036")
    assert format_usd(cost) == "0.000360"


def test_missing_price_not_zero(db):
    rec = QueryRecorder.start("What is the per diem?", "s-1", "A", db_path=db)
    rec.llm_call("answer", "some/unpriced-model", {"prompt_tokens": 100, "completion_tokens": 10})
    rec.citations([{"citation_id": "E1", "chunk_id": "c", "valid": True}])
    result = rec.finish("answer [E1]", "DOCS", 1.0)
    assert result.cost_usd is None
    (row,) = rows(db, "SELECT cost_usd FROM query_event WHERE query_id = ?", result.query_id)
    assert row["cost_usd"] is None
    (call,) = rows(db, "SELECT cost_usd FROM llm_call WHERE query_id = ?", result.query_id)
    assert call["cost_usd"] is None


def test_cached_tokens_use_cached_price():
    price = Price(Decimal("0.15"), Decimal("0.60"), Decimal("0.075"))
    # 1000 uncached at 0.15 + 1000 cached at 0.075, per 1M.
    assert compute_cost(Usage(2000, 0, 1000), price) == Decimal("0.000225")


def test_cache_hit_costs_zero():
    assert compute_cost(Usage(5000, 500), None, cache_hit=True) == Decimal(0)


def test_prices_come_from_the_reviewed_file(db):
    (row,) = rows(db, "SELECT * FROM model_price WHERE model = 'openai/gpt-oss-120b'")
    assert row["usd_per_1m_in"] == "0.15" and row["source_url"] and row["checked_on"] == "2026-10-27"


def test_usage_from_openai_and_gemini_shapes():
    openai_like = {"prompt_tokens": 10, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 4}}
    assert normalize_usage(openai_like) == Usage(10, 5, 4, "PROVIDER")
    gemini_like = SimpleNamespace(prompt_token_count=7, candidates_token_count=3, cached_content_token_count=None)
    assert normalize_usage(gemini_like) == Usage(7, 3, 0, "PROVIDER")
    assert normalize_usage(None) is None


def test_estimated_usage_is_marked(db):
    rec = QueryRecorder.start("q", "s", "B", db_path=db)
    rec.llm_call("answer", "openai/gpt-oss-120b", None, estimate=estimated_usage("x" * 400, "y" * 40))
    rec.citations([{"citation_id": "E1", "chunk_id": "c", "valid": True}])
    result = rec.finish("a [E1]", "DOCS", 1.0)
    assert result.cost_estimated is True and result.tokens_in == 100
    (call,) = rows(db, "SELECT usage_source FROM llm_call WHERE query_id = ?", result.query_id)
    assert call["usage_source"] == "ESTIMATED"


def test_ingestion_cost_is_per_document(db):
    cost = record_ingest_llm_call("doc_19c0", "ocr", "gemini-2.5-flash", {"prompt_token_count": 1000,
                                  "candidates_token_count": 200}, 6000, "ocr-v1", db_path=db)
    assert cost == "0.000800"   # 1000 x 0.30 + 200 x 2.50, per 1M
    (row,) = rows(db, "SELECT query_id, document_id FROM llm_call WHERE document_id = 'doc_19c0'")
    assert row["query_id"] is None


# Recorder (WP-BE4) ----------------------------------------------------------

def test_recorder_writes_every_table(db):
    rec, result = _full_query(db)
    assert result.recorded and result.outcome == "SUCCESS" and result.reason_code == "OK"
    assert result.confidence == "HIGH"          # top rerank 0.81 >= 0.7
    assert result.tokens_in == 2410 and result.tokens_out == 96
    # route 380 x 0.075 + 40 x 0.30, answer 2030 x 0.15 + 56 x 0.60, per 1M
    assert result.cost_usd == "0.000379"   # 40.5 + 338.1 = 378.6 per 1M
    qid = result.query_id
    assert len(qid) == 26
    for table, expected in [("query_stage", 2), ("retrieval_hit", 2), ("llm_call", 2), ("tool_call", 1),
                            ("citation", 2), ("context_turn", 1)]:
        assert len(rows(db, f"SELECT 1 FROM {table} WHERE query_id = ?", qid)) == expected, table
    (event,) = rows(db, "SELECT * FROM query_event WHERE query_id = ?", qid)
    assert event["citations_valid"] == 2 and event["route"] == "BOTH" and event["config_id"] == "B"
    (tool,) = rows(db, "SELECT * FROM tool_call WHERE query_id = ?", qid)
    assert tool["result_summary"].startswith("P-104 TRAVEL") and tool["tool_version"] == "1"


def test_recorder_never_raises(tmp_path):
    broken = tmp_path / "not-a-dir"
    broken.write_text("a file where a folder should be")
    before = dropped_events(broken / "x.db")
    rec = QueryRecorder.start("question", "s", "A", db_path=broken / "x.db")
    with rec.stage("generate"):
        pass
    rec.hits("vector", None)                    # bad input is swallowed, not raised
    rec.llm_call("answer", "openai/gpt-oss-120b", {"prompt_tokens": 1, "completion_tokens": 1})
    result = rec.finish("the answer still comes back", "DOCS", 1.0)
    assert result.recorded is False
    assert dropped_events(broken / "x.db") == before + 1


def test_write_is_one_transaction(db):
    rec = QueryRecorder.start("q", "s", "A", db_path=db)
    # Two citations with the same id break the citation insert after query_event was written.
    rec.citations([{"citation_id": "E1", "chunk_id": "a", "valid": True},
                   {"citation_id": "E1", "chunk_id": "b", "valid": True}])
    result = rec.finish("a", "DOCS", 1.0)
    assert result.recorded is False
    assert rows(db, "SELECT 1 FROM query_event WHERE query_id = ?", result.query_id) == []
    assert dropped_events(db) >= 1


def test_stage_records_error_and_reraises(db):
    rec = QueryRecorder.start("q", "s", "A", db_path=db)
    with pytest.raises(ValueError):
        with rec.stage("retrieve_bm25"):
            raise ValueError("index missing")
    with pytest.raises(TimeoutError):
        with rec.stage("tool"):
            raise TimeoutError
    rec.stage_skipped("rerank", "config A")
    result = rec.finish(None, "DOCS")
    stages = rows(db, "SELECT stage, status FROM query_stage WHERE query_id = ? ORDER BY seq", result.query_id)
    assert [(s["stage"], s["status"]) for s in stages] == [
        ("retrieve_bm25", "ERROR"), ("tool", "TIMEOUT"), ("rerank", "SKIPPED")]


# PII ----------------------------------------------------------------------

def test_pii_masked(db):
    rec, result = _full_query(db)
    (event,) = rows(db, "SELECT question_masked, safety_flags FROM query_event WHERE query_id = ?", result.query_id)
    assert "9876543210" not in event["question_masked"] and "[PHONE]" in event["question_masked"]
    assert "PII" in event["safety_flags"]
    (turn,) = rows(db, "SELECT text_masked FROM context_turn WHERE query_id = ?", result.query_id)
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


# Outcome rules (Arka owns; contract 11 section 5) -------------------------

@pytest.mark.parametrize("facts, expected", [
    (OutcomeFacts(system_error=True, llm_error=True), ("FAILED", "SYSTEM_ERROR")),
    (OutcomeFacts(llm_error=True, blocked=True), ("FAILED", "LLM_ERROR")),
    (OutcomeFacts(output_invalid=True), ("FAILED", "OUTPUT_INVALID")),
    (OutcomeFacts(blocked=True, fallback=True), ("PARTIAL", "BLOCKED_SAFETY")),
    (OutcomeFacts(fallback=True, tool_failed=True), ("PARTIAL", "NO_EVIDENCE")),
    (OutcomeFacts(tool_failed=True, citations_valid=1, citations_total=1), ("PARTIAL", "TOOL_FAILED")),
    (OutcomeFacts(citations_valid=0, citations_total=2), ("FAILED", "UNGROUNDED_ANSWER")),
    (OutcomeFacts(citations_valid=1, citations_total=2, grounding_score=1.0), ("PARTIAL", "UNSUPPORTED_CLAIMS")),
    (OutcomeFacts(citations_valid=2, citations_total=2, grounding_score=0.5), ("PARTIAL", "UNSUPPORTED_CLAIMS")),
    (OutcomeFacts(citations_valid=2, citations_total=2, grounding_score=1.0, conflict=True),
     ("SUCCESS", "OK_CONFLICT")),
    (OutcomeFacts(citations_valid=2, citations_total=2, grounding_score=0.9), ("SUCCESS", "OK")),
])
def test_outcome_order(facts, expected):
    assert classify(facts) == expected


def test_confidence_levels():
    assert confidence("SUCCESS", 0.75) == "HIGH"
    assert confidence("SUCCESS", 0.5) == "MEDIUM"
    assert confidence("PARTIAL", 0.9) == "LOW"
    assert confidence("FAILED", 0.9) is None


def test_fallback_recorded_with_flag(db):
    rec = QueryRecorder.start("What is the CEO salary?", "s", "B", db_path=db)
    result = rec.finish("I could not find this in the approved documents or data.", "DOCS",
                        facts=OutcomeFacts(fallback=True))
    assert (result.outcome, result.reason_code, result.confidence) == ("PARTIAL", "NO_EVIDENCE", "LOW")
    (event,) = rows(db, "SELECT safety_flags FROM query_event WHERE query_id = ?", result.query_id)
    assert "FALLBACK" in event["safety_flags"]
