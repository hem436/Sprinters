"""Gaps found when the live demo was checked against the case's functional requirements (27 Oct)."""
import pytest

from agent.answer import NO_EVIDENCE_TEXT
from agent.graph import plain_citations
from agent.router import route_question
from agent.service import Agent
from agent.stubs import FakeLLM, NullRecorder, StubSearch, StubTools
from agent.types import Hit

SMALLTALK = {"route": "CONVERSATIONAL", "standalone_query": "q", "tool": None, "tool_args": {}}


def _route(question, reply):
    decision, _ = route_question(question, [], FakeLLM({"route": [reply]}), StubTools())
    return decision


def test_fr07_a_company_question_is_never_small_talk():
    """Live: "Who is the CEO of Arka Fintech Services?" was answered with a greeting instead of "could not find"."""
    decision = _route("Who is the CEO of Arka Fintech Services?", {**SMALLTALK, "standalone_query": "CEO?"})
    assert (decision.route, decision.reason, decision.standalone_query) == ("DOCS", "RULE_OVERRIDE", "CEO?")


@pytest.mark.parametrize("question", ["What can you do?", "Who are you?", "Thanks, that helps!", "ok"])
def test_fr07_real_small_talk_stays_small_talk(question):
    assert _route(question, SMALLTALK).route == "CONVERSATIONAL"


def test_fr10_unanswerable_company_question_gets_the_honest_fallback(corpus, table_reranker):
    llm = FakeLLM({"route": [SMALLTALK]})
    r = Agent(StubSearch(corpus, vector=[Hit("c_v2_perdiem", 0.1, 1)]), StubTools(), llm, table_reranker({})).answer(
        "Who is the CEO of Arka Fintech Services?", "s1", NullRecorder())
    assert (r.route, r.reason_code, r.answer_markdown) == ("DOCS", "NO_EVIDENCE", NO_EVIDENCE_TEXT)


@pytest.mark.parametrize("written, shown", [
    ('Over budget ["T1"].', "Over budget [T1]."),
    ("Over budget ['T1'] and CFO [\"E2\"].", "Over budget [T1] and CFO [E2]."),
    ('Both versions ["E1", "E2"].', "Both versions [E1][E2]."),
    ("Within 30 days【E1】.", "Within 30 days[E1]."),
    ("Plain [E1] stays; [Note] and [T] are not ids.", "Plain [E1] stays; [Note] and [T] are not ids."),
])
def test_fr08_citation_markers_become_plain(written, shown):
    assert plain_citations(written) == shown


def test_tool_sql_goes_to_the_recorder_and_the_response(corpus, table_reranker):
    """The registry's SQL trail is passed on unchanged, so the store and the chat can show it."""
    from agent.types import ToolResult
    sql = [{"sql": "SELECT project_id FROM v_budget_status WHERE project_id = :project_id",
            "params": {"project_id": "P-104"}}]
    p104 = ToolResult("budget_status", "OK", summary="P-104 TRAVEL FY2026-27: spent 435500 of 400000",
                      rows=[{"project_id": "P-104"}], args={"project_id": "P-104"}, sql=sql)
    llm = FakeLLM({"route": [{"route": "SQL", "standalone_query": "q", "tool": "budget_status",
                              "tool_args": {"project_id": "P-104"}}]})
    recorder = NullRecorder()
    r = Agent(StubSearch(corpus), StubTools(results={"budget_status": p104}), llm, table_reranker({})).answer(
        "Is P-104 over its travel budget?", "s1", recorder)
    assert recorder.tool_calls[0]["sql"] == sql and r.tool_results[0]["sql"] == sql
