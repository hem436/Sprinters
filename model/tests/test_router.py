"""WP-AG2: rules R1 and R1b (contract 04, contract 14 section 7)."""
from agent.router import parse_planner, route_question
from agent.stubs import FakeLLM, StubTools
from agent.types import Turn


def _route(question: str, planner_reply, context=None, second_reply=None):
    llm = FakeLLM({"route": [planner_reply] + ([second_reply] if second_reply is not None else [])})
    decision, _ = route_question(question, context or [], llm, StubTools())
    return decision, llm


DOCS_NO_TOOL = {"route": "DOCS", "standalone_query": "q", "tool": None, "tool_args": {}}


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


def test_override_asks_the_planner_again_for_the_tool():
    """Bug report: an override changed the route but kept the planner's tool, which is null for DOCS."""
    args = {"metric": "revenue", "company": "Company A", "periods": ["FY2023-24", "FY2024-25"]}
    decision, llm = _route("Compare Company A revenue FY2024 and FY2025", DOCS_NO_TOOL,
                           second_reply={"route": "SQL", "standalone_query": "q", "tool": "metric_compare", "tool_args": args})
    assert (decision.route, decision.tool, decision.tool_args, decision.reason) == ("SQL", "metric_compare", args, "RULE_OVERRIDE")
    assert len(llm.calls) == 2 and "needs business data" in llm.calls[1][2]


def test_reported_policy_question_stays_docs():
    """"budget" alone is no longer a data word, so a pure policy question is not forced to BOTH."""
    decision, llm = _route("What does the travel policy say about budget overruns?", DOCS_NO_TOOL)
    assert (decision.route, decision.reason, len(llm.calls)) == ("DOCS", "PLANNER", 1)


def test_reported_both_without_a_tool_drops_to_docs():
    """The rules force BOTH, but no tool fits approval time: answer from documents, not a failed tool."""
    decision, llm = _route("Why is the average Finance approval time long?", DOCS_NO_TOOL, second_reply=DOCS_NO_TOOL)
    assert (decision.route, decision.tool, decision.reason, len(llm.calls)) == ("DOCS", None, "ROUTE_NO_TOOL", 2)


def test_override_without_a_tool_keeps_the_planners_route():
    """Review #25 (fourth): no approved tool fits even after the re-ask, so the rule's "data" reading was wrong and the
    planner's own route stands. A planner that itself says SQL with no tool still gets NO_TOOL (test_r3_7)."""
    decision, _ = _route("Compare Company A revenue FY2024 and FY2025", DOCS_NO_TOOL, second_reply=DOCS_NO_TOOL)
    assert (decision.route, decision.tool, decision.reason) == ("DOCS", None, "ROUTE_NO_TOOL")


def test_planner_both_without_a_tool_drops_to_docs():
    decision, llm = _route("Is P-104 over its budget, and what does the policy require?",
                           {"route": "BOTH", "standalone_query": "q", "tool": None, "tool_args": {}})
    assert (decision.route, decision.reason, len(llm.calls)) == ("DOCS", "ROUTE_NO_TOOL", 1)


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
