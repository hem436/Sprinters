"""WP-AG2: rules R1 and R1b (contract 04, contract 14 section 7)."""
from agent.router import parse_planner, route_question
from agent.stubs import FakeLLM, StubTools
from agent.types import Turn


def _route(question: str, planner_reply, context=None):
    llm = FakeLLM({"route": [planner_reply]})
    decision, _ = route_question(question, context or [], llm, StubTools())
    return decision, llm


def test_route_sql_with_args():
    args = {"project_id": "P-104", "fiscal_year": "FY2026-27", "category": "TRAVEL"}
    decision, _ = _route("Is P-104 over its travel budget in FY2026-27?",
                         {"route": "SQL", "standalone_query": "Is P-104 over its travel budget in FY2026-27?",
                          "tool": "budget_status", "tool_args": args})
    assert (decision.route, decision.tool, decision.tool_args, decision.reason) == ("SQL", "budget_status", args, "PLANNER")


def test_route_both():
    decision, _ = _route("Is P-104 over its travel budget, and who must approve the overrun under the policy?",
                         {"route": "BOTH", "standalone_query": "q", "tool": "budget_status", "tool_args": {}})
    assert decision.route == "BOTH" and decision.reason == "PLANNER"


def test_doc_question_with_project_id():
    """Gap G2: a policy question that names a project needs both routes, even if the planner says SQL."""
    decision, _ = _route("What does the policy say about P-104's overspend?",
                         {"route": "SQL", "standalone_query": "q", "tool": "budget_status", "tool_args": {}})
    assert decision.route == "BOTH" and decision.reason == "RULE_OVERRIDE"


def test_rule_forces_data_when_planner_says_docs():
    decision, _ = _route("Compare Company A revenue FY2024 and FY2025",
                         {"route": "DOCS", "standalone_query": "q", "tool": None, "tool_args": {}})
    assert decision.route == "SQL" and decision.reason == "RULE_OVERRIDE"


def test_route_fallback_on_bad_json():
    decision, _ = _route("What is the per diem in Mumbai?", "Sure! The route is DOCS.")
    assert (decision.route, decision.reason, decision.standalone_query) == ("DOCS", "ROUTE_FALLBACK", "What is the per diem in Mumbai?")


def test_greeting_needs_no_model_call():
    decision, llm = _route("Hello!", {"route": "DOCS"})
    assert decision.route == "CONVERSATIONAL" and llm.calls == []


def test_followup_rewrite():
    """M1 + R1: the planner sees the earlier turns and returns a standalone question."""
    context = [Turn("user", "What is the per diem in Mumbai?"), Turn("assistant", "₹2,000 under policy v2.0 [E1].")]
    decision, llm = _route("and for Delhi?",
                           {"route": "DOCS", "standalone_query": "What is the per diem for Delhi?", "tool": None},
                           context)
    assert decision.standalone_query == "What is the per diem for Delhi?"
    assert "per diem in Mumbai" in llm.calls[0][2]


def test_planner_json_in_fences_is_read():
    decision = parse_planner('```json\n{"route": "DOCS", "standalone_query": "x"}\n```', "x")
    assert decision.route == "DOCS" and decision.reason == "PLANNER"
