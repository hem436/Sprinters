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


class SegmentTools(StubTools):
    """segment_breakdown accepts only metric "segment_revenue", like Sinngam's tool (eval case F03, 27 Oct)."""

    def list_tools(self):
        return [{"name": "segment_breakdown", "description": "Segment figures for one company and period",
                 "args": {"company": "name", "period": "FYyyyy-yy", "metric": "segment_revenue|segment_result"}}]

    def run_tool(self, name, args):
        from agent.types import ToolResult
        self.calls.append((name, args))
        if args.get("metric") != "segment_revenue":
            return ToolResult(name, "ARGS_INVALID", args=args, message="metric: Input should be 'segment_revenue'")
        return ToolResult(name, "OK", summary="Payments ₹7,000 crore; Lending ₹4,256 crore", rows=[{"x": 1}], args=args)


def _segment_plan(metric):
    return {"route": "SQL", "standalone_query": "Company A revenue by segment FY2024-25", "tool": "segment_breakdown",
            "tool_args": {"company": "Company A", "period": "FY2024-25", "metric": metric}}


def test_fr07_refused_tool_arguments_are_fixed_once(corpus, table_reranker):
    answer = {"answer_markdown": "Payments ₹7,000 crore and Lending ₹4,256 crore [T1].",
              "claims": [{"text": "Payments ₹7,000 crore and Lending ₹4,256 crore.", "citations": ["T1"]}]}
    llm = FakeLLM({"route": [_segment_plan("revenue"), _segment_plan("segment_revenue")], "answer": [answer]})
    tools, recorder = SegmentTools(), NullRecorder()
    r = Agent(StubSearch(corpus), tools, llm, table_reranker({})).answer(
        "What is Company A's revenue by segment in FY2024-25?", "s1", recorder)
    assert [a["metric"] for _, a in tools.calls] == ["revenue", "segment_revenue"]
    assert [t["status"] for t in recorder.tool_calls] == ["ARGS_INVALID", "OK"]     # the refused call stays on record
    assert (r.outcome, r.reason_code) == ("SUCCESS", "OK") and recorder.stage_details["tool"]["args_fixed"] is True


def test_fr07_a_second_refusal_is_a_controlled_tool_error(corpus, table_reranker):
    llm = FakeLLM({"route": [_segment_plan("revenue"), _segment_plan("revenue")]})     # the planner repeats itself
    tools, recorder = SegmentTools(), NullRecorder()
    r = Agent(StubSearch(corpus), tools, llm, table_reranker({})).answer(
        "What is Company A's revenue by segment in FY2024-25?", "s1", recorder)
    assert len(tools.calls) == 1 and [t["status"] for t in recorder.tool_calls] == ["ARGS_INVALID"]
    assert (r.outcome, r.reason_code) == ("PARTIAL", "TOOL_FAILED")


def test_fr05_reranker_model_is_a_setting(monkeypatch):
    """MiniLM-L-12 by default (measured better on the demo corpus); AGENT_RERANK_MODEL changes it."""
    import sys
    import types

    from agent.retrieval import FlashRankReranker
    made = []
    fake = types.SimpleNamespace(Ranker=lambda **kw: made.append(kw), RerankRequest=None)
    monkeypatch.setitem(sys.modules, "flashrank", fake)
    monkeypatch.delenv("AGENT_RERANK_MODEL", raising=False)
    monkeypatch.delenv("AGENT_RERANK_CACHE", raising=False)
    FlashRankReranker()
    monkeypatch.setenv("AGENT_RERANK_MODEL", "ms-marco-TinyBERT-L-2-v2")
    FlashRankReranker(cache_dir="/tmp/fr")
    assert made == [{"model_name": "ms-marco-MiniLM-L-12-v2"},
                    {"model_name": "ms-marco-TinyBERT-L-2-v2", "cache_dir": "/tmp/fr"}]
