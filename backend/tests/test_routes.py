"""Issue 48 / WP-BE6 and BE7: every route the web app calls, in its shapes (web/src/api/types.ts).

/query runs Arka's real Agent (his stub search and model, our real tools and recorder). The document routes
run against a fake of Myank's service with the same function names, because extraction/ needs Python 3.11+.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent.service import Agent
from agent.stubs import FakeLLM, StubSearch
from agent.types import Chunk, Hit
from fastapi.testclient import TestClient

from app.api import documents as documents_api
from app.api import query as query_api
from app.main import create_app
from app.observability import store
from app.tools.registry import ToolRegistry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_business_data  # noqa: E402

P104 = {"project_id": "P-104", "fiscal_year": "FY2026-27", "category": "TRAVEL"}
OVERRUN = Chunk("c_v2_overrun", "doc_travel_2", "travel-policy", "Travel and Expense Policy", "2.0", "2026-04-01",
                9, "4.5 Overruns", "text", "Spend above the approved project budget needs department head approval.")


def _llm() -> FakeLLM:
    return FakeLLM({
        "route": [{"route": "BOTH", "standalone_query": "Is P-104 over budget?", "tool": "budget_status",
                   "tool_args": P104}],
        "answer": [{"answer_markdown": "Yes [T1]. The department head must approve [E1].",
                    "claims": [{"text": "P-104 spent ₹4,35,500 against a travel budget of ₹4,00,000.",
                                "citations": ["T1"]},
                               {"text": "Spend above the approved project budget needs department head approval.",
                                "citations": ["E1"]}]}],
    })


class IngestError(Exception):
    """Same attributes as Myank's ingestion.errors.IngestError."""

    def __init__(self, code, http_status, message, **detail):
        super().__init__(message)
        self.code, self.http_status, self.message, self.detail = code, http_status, message, detail


def _fake_service():
    docs = {
        "doc_a": {"document_id": "doc_a", "doc_key": "travel-policy", "title": "Travel and Expense Policy",
                  "category": "HR policy", "version": "2.0", "effective_date": "2026-04-01", "status": "INDEXED",
                  "page_count": 9},
        "doc_q": {"document_id": "doc_q", "doc_key": "notes", "title": "Meeting notes", "category": "Notes",
                  "version": "1.0", "effective_date": "2026-10-12", "status": "QUEUED", "page_count": 1},
    }
    pages = {("doc_a", 7): {"page": 7, "text": "Per diem for Mumbai is ₹2,000 a day.", "status": "INDEXED",
                            "image_url": "/documents/doc_a/pages/7/image"},
             ("doc_a", 8): {"page": 8, "text": "smudged", "status": "NEEDS_REVIEW", "image_url": None}}

    def get_document(i):
        if i not in docs:
            raise IngestError("NOT_FOUND", 404, f"{i} not found.")
        return docs[i]

    def get_page(i, n):
        get_document(i)
        if (i, n) not in pages:
            raise IngestError("NOT_FOUND", 404, f"Page {n} of {i} not found.")
        return pages[(i, n)]

    def submit_document(path, meta, file_name=None, uploaded_by="admin"):
        if not Path(path).read_bytes().startswith(b"%PDF"):
            raise IngestError("UNSUPPORTED_TYPE", 422, "Only PDF, DOCX, TXT and images.")
        if meta.get("version") == "":
            raise IngestError("INVALID_METADATA", 422, "Some metadata fields are missing or wrong.",
                              fields={"version": "required"})
        return {"document_id": "doc_new", "job_id": "job_1", "status": "QUEUED"}

    return SimpleNamespace(
        submit_document=submit_document,
        list_documents=lambda category=None, status=None: list(docs.values()),
        get_document=get_document, get_page=get_page,
        page_image=lambda i, n: b"\x89PNG fake",
        review_page=lambda i, n, d, admin, c=None: {**get_page(i, n), "status": "APPROVED" if d == "APPROVE"
                                                    else "REJECTED"},
        reindex=lambda i: {"document_id": i, "job_id": "job_2", "status": "QUEUED"},
        delete_document=lambda i: get_document(i) and None,
        list_jobs=lambda: [{"job_id": "job_1", "document_id": "doc_q", "title": "Meeting notes", "stage": "ocr",
                            "done": 0, "total": 1, "status": "RUNNING"}],
    )


@pytest.fixture
def api(config, monkeypatch) -> TestClient:
    business = config.paths.resolve(config.paths.business_db)
    make_business_data.build(business)
    obs = config.paths.resolve(config.paths.observability_db)
    store.init_db(obs)
    store.seed_prices(obs, store.load_price_file())
    # The recorder writes to the default store path; point it at this test's store.
    monkeypatch.setattr(store, "default_db_path", lambda: obs)

    agent = Agent(StubSearch({OVERRUN.chunk_id: OVERRUN}, vector=[Hit("c_v2_overrun", 0.8, 1)]),
                  ToolRegistry(business), _llm(), SimpleNamespace(score=lambda q, texts: [0.85] * len(texts)))
    app = create_app(config)
    app.dependency_overrides[query_api.get_agent] = lambda: agent
    app.dependency_overrides[documents_api.get_knowledge] = _fake_service
    return TestClient(app, raise_server_exceptions=False)


def _ask(api) -> dict:
    resp = api.post("/query", json={"question": "Is P-104 over its travel budget, and who approves?",
                                    "session_id": "s1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers["X-Request-Id"] == body["query_id"]
    return body


# Questions ------------------------------------------------------------------------------------------------------

def test_query_runs_the_agent_and_records_it(api):
    body = _ask(api)
    assert (body["route"], body["outcome"]) == ("BOTH", "SUCCESS")
    assert body["tool_results"][0]["status"] == "OK"
    assert api.get(f"/queries/{body['query_id']}").status_code == 200


def test_empty_question(api):
    resp = api.post("/query", json={"question": "  ", "session_id": "s1"})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "EMPTY_QUESTION"


def test_stream_sends_status_then_done(api):
    with api.stream("POST", "/query/stream", json={"question": "Is P-104 over budget?", "session_id": "s2"}) as resp:
        text = "".join(resp.iter_text())
        query_id = resp.headers["X-Request-Id"]
    events = [(b.split("\n")[0][len("event: "):], json.loads(b.split("\n")[1][len("data: "):]))
              for b in text.strip().split("\n\n")]
    names = [e for e, _ in events]
    stages = [d["stage"] for e, d in events if e == "status"]
    assert stages[:2] == ["guard", "route"] and "answer" in stages and "validate" in stages
    assert names[-3:] == ["citations", "token", "done"]
    assert events[-1][1]["query_id"] == query_id


# Feedback and reviewer comments ---------------------------------------------------------------------------------

def test_feedback_once_per_answer(api):
    qid = _ask(api)["query_id"]
    assert api.post("/feedback", json={"query_id": qid, "helpful": True, "comment": "clear"}).status_code == 201
    again = api.post("/feedback", json={"query_id": qid, "helpful": False})
    assert again.status_code == 409 and again.json()["error"]["code"] == "FEEDBACK_EXISTS"
    assert api.post("/feedback", json={"query_id": "nope", "helpful": True}).status_code == 404


def test_reviewer_comments_kept_apart_from_feedback(api):
    qid = _ask(api)["query_id"]
    assert api.post(f"/queries/{qid}/review", json={"comment": "check the overrun rule"}).status_code == 201
    drill = api.get(f"/queries/{qid}").json()
    assert drill["reviewer_comments"] == ["check the overrun rule"] and drill["feedback"] is None


# Dashboard ------------------------------------------------------------------------------------------------------

def test_metrics_summary_shape(api):
    _ask(api)
    s = api.get("/metrics/summary").json()
    assert set(s) == {"total_queries", "outcomes", "outcome_over_time", "retrieval_success_rate", "hit_at_5",
                      "grounding_rate", "citation_support", "tool_success", "safety_events", "latency_ms", "usage",
                      "feedback", "dropped_events"}
    assert s["total_queries"] == 1 and s["outcomes"]["SUCCESS"] == 1
    assert s["tool_success"] == {"ok": 1, "total": 1}
    assert set(s["latency_ms"]) == {"total", "retrieval", "tool", "llm"}
    assert api.get("/metrics/summary", params={"outcome": "FAILED"}).json()["total_queries"] == 0


def test_queries_are_paged(api):
    for _ in range(3):
        api.post("/query", json={"question": "hello", "session_id": "s3"})
    page = api.get("/queries", params={"page": 1, "page_size": 2}).json()
    assert (len(page["items"]), page["page"], page["page_size"], page["total"]) == (2, 1, 2, 3)
    assert set(page["items"][0]) == {"query_id", "ts", "question_masked", "route", "outcome", "reason_code",
                                     "latency_ms", "cost_usd", "feedback"}


def test_drill_down_shape(api):
    qid = _ask(api)["query_id"]
    d = api.get(f"/queries/{qid}").json()
    assert set(d) == {"identity", "question", "execution", "outcome", "retrieval", "evidence_quality",
                      "context_turns", "tool_calls", "generation", "citations", "grounding", "safety",
                      "performance", "usage", "feedback", "reviewer_comments", "errors"}
    assert d["question"]["route_reason"] == "PLANNER"
    assert d["tool_calls"][0]["summary"].startswith("P-104 TRAVEL")
    assert api.get("/queries/nope").status_code == 404


def test_eval_runs(api):
    assert api.get("/eval/runs").json() == []
    # connected to Arka's runner (model/agent/eval_store.py, tested there); an unknown config is refused here
    assert api.post("/eval/runs", json={"config_id": "C"}).status_code == 422


def test_eval_run_starts_and_finishes(api):
    """202 with a run_id; G01 ("Hello!") needs no model call. A subset run writes no output files."""
    import threading

    started = api.post("/eval/runs", json={"config_id": "B", "case_ids": ["G01"]})
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    for thread in threading.enumerate():
        if thread.name == run_id:
            thread.join(timeout=20)
    run = api.get(f"/eval/runs/{run_id}").json()
    assert run["status"] == "DONE" and [r["case_id"] for r in run["results"]] == ["G01"]
    assert api.post("/eval/runs", json={"config_id": "B", "case_ids": ["Z99"]}).status_code == 422


# Documents (Myank's service) ------------------------------------------------------------------------------------

def test_upload_and_its_errors(api):
    meta = {"title": "Policy", "category": "HR policy", "version": "2.0", "effective_date": "2026-04-01"}
    ok = api.post("/documents", files={"file": ("p.pdf", b"%PDF-1.7 ...", "application/pdf")}, data=meta)
    assert ok.status_code == 202 and ok.json()["status"] == "QUEUED"
    bad = api.post("/documents", files={"file": ("p.exe", b"MZ", "application/octet-stream")}, data=meta)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "UNSUPPORTED_TYPE"
    missing = api.post("/documents", files={"file": ("p.pdf", b"%PDF", "application/pdf")},
                       data={**meta, "version": ""})
    assert missing.json()["error"]["fields"] == [{"field": "version", "problem": "required"}]


def test_document_routes(api):
    assert len(api.get("/documents").json()) == 2
    assert api.get("/documents/missing").status_code == 404
    assert api.get("/documents/doc_a/pages/7").json()["status"] == "INDEXED"
    image = api.get("/documents/doc_a/pages/7/image")
    assert image.headers["content-type"] == "image/png"
    review = api.post("/documents/doc_a/pages/8/review", json={"decision": "APPROVE"})
    assert review.json()["status"] == "APPROVED"
    assert api.post("/documents/doc_a/reindex").status_code == 202
    assert api.delete("/documents/doc_a").status_code == 204
    assert api.get("/jobs").json()[0]["stage"] == "ocr"


def test_tables_and_metric_map_wait_for_extraction(api):
    resp = api.get("/documents/doc_a/tables")
    assert resp.status_code == 501 and resp.json()["error"]["code"] == "NOT_IMPLEMENTED"


def test_library_shows_only_searchable(api):
    assert [d["document_id"] for d in api.get("/library").json()] == ["doc_a"]
    assert api.get("/library/doc_a/pages/7").json()["text"].startswith("Per diem")
    assert api.get("/library/doc_a/pages/8").status_code == 404      # still waiting for review
    assert api.get("/library/doc_q/pages/1").status_code == 404


def test_tool_sql_reaches_the_answer_and_the_drill_down(api):
    """Interpretability: the reviewer sees the exact SQL and its bound values behind each number."""
    body = _ask(api)
    assert body["tool_results"][0]["sql"][0]["params"]["project_id"] == "P-104"
    detail = api.get(f"/queries/{body['query_id']}").json()
    ran = detail["tool_calls"][0]["sql"][0]
    assert "FROM v_budget_status" in ran["sql"] and ran["params"]["project_id"] == "P-104"
