"""The agent as a LangGraph graph (WP-AG5). Each node applies the rules of contract 04 in their documented order:

guard (S1) -> plan (M1, R1) -> retrieve (H1 to H4, C1) and/or tool (T1 to T4) -> generate (A1 to A4, G1) -> validate (V1, V2, V4)
"""
import operator
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.answer import (ANSWER_PROMPT_VERSION, BLOCKED_TEXT, NO_EVIDENCE_TEXT, NO_TOOL_TEXT, REPAIR_INSTRUCTION,
                          TOOL_UNAVAILABLE_TEXT, build_evidence, build_prompt, parse_answer)
from agent.config import AgentConfig
from agent.context import select_context
from agent.llm import LLMError
from agent.outcome import has_relevant_evidence
from agent.ports import LLMPort, RecorderPort, RerankerPort, SearchPort, ToolPort
from agent.recording import report_llm, report_tool, run_stage
from agent.retrieval import Conflict, RetrievalResult, find_conflicts, retrieve
from agent.router import ROUTE_PROMPT_VERSION, route_question
from agent.safety import check_output, guard_question
from agent.types import AnswerJSON, Evidence, LLMReply, RouteDecision, ToolResult, Turn
from agent.validate import check_citations, check_grounding

SMALLTALK_TEXT = "Hello. Ask me about the company's policies, reports or business data."


class AgentState(TypedDict, total=False):
    question: str
    filters: dict | None
    cfg: AgentConfig
    recorder: RecorderPort
    history: list[Turn]
    context: list[Turn]
    blocked: bool
    route: RouteDecision
    retrieval: RetrievalResult | None
    conflicts: list[Conflict]
    tools: list[ToolResult]
    evidence: list[Evidence]
    answer: AnswerJSON | None
    text: str
    fallback: bool
    conversational: bool
    llm_failed: bool
    output_invalid: bool
    llm_error_detail: str
    citation_checks: list
    grounding: float
    claim_checks: list
    no_tool: bool
    tool_call_ids: list[str]
    replies: Annotated[list[LLMReply], operator.add]
    safety_flags: Annotated[list[str], operator.add]


def build_graph(search: SearchPort, tools: ToolPort, llm: LLMPort, reranker: RerankerPort):
    """Compile the graph once; the other parts come in here, the per-query values come in the state."""

    def guard(state: AgentState) -> dict:
        with run_stage(state["recorder"], "guard") as stage:
            blocked, reason = guard_question(state["question"])
            if blocked:     # review #25: a blocked query keeps its route decision in the drill-down too
                _detail(stage, route="BLOCKED", route_reason=f"GUARD_{reason}")
        if blocked:
            return {"blocked": True, "text": BLOCKED_TEXT, "safety_flags": [f"GUARD_{reason}"]}
        return {"blocked": False}

    def plan(state: AgentState) -> dict:
        context = select_context(state.get("history", []), state["cfg"])
        with run_stage(state["recorder"], "plan", "context", "route") as stage:
            try:
                decision, replies = route_question(state["question"], context, llm, tools)
            except LLMError as error:
                # 06 AI-4: the planner failed, so answer from the documents with the user's own words
                decision, replies = RouteDecision("DOCS", state["question"], reason="ROUTE_FALLBACK"), []
                _detail(stage, llm_error=str(error)[:300])
            _detail(stage, route=decision.route, route_reason=decision.reason, tool=decision.tool)
        for reply in replies:
            report_llm(state["recorder"], "route", reply, ROUTE_PROMPT_VERSION)
        return {"context": context, "route": decision, "replies": replies}

    def retrieve_docs(state: AgentState) -> dict:
        query, cfg = state["route"].standalone_query, state["cfg"]
        result = retrieve(query, state.get("filters"), cfg, search, reranker, state["recorder"])
        usable = has_relevant_evidence(result.top_score, result.score_kind, cfg)
        conflicts = find_conflicts([s.chunk for s in result.reranked], search) if usable else []
        return {"retrieval": result, "conflicts": conflicts}

    def run_tool(state: AgentState) -> dict:
        decision = state["route"]
        if decision.tool is None:
            # no approved tool fits: nothing runs, so nothing is recorded as a tool call (13 section 5, NO_TOOL)
            return {"tools": [], "no_tool": True}
        with run_stage(state["recorder"], "tool"):
            result = tools.run_tool(decision.tool, decision.tool_args)
        # the recorder's own id for this call, so a citation of T1 points at the stored tool_call row
        call_id = report_tool(state["recorder"], result)
        return {"tools": [result], "tool_call_ids": [call_id]}

    def generate(state: AgentState) -> dict:
        with run_stage(state["recorder"], "generate", "answer") as stage:
            result = _generate(state, llm)
            if result.get("llm_error_detail"):          # the provider's reason, for the drill-down (never a key)
                _detail(stage, llm_error=result["llm_error_detail"])
            return result

    def validate(state: AgentState) -> dict:
        with run_stage(state["recorder"], "validate") as stage:
            result = _validate(state)
            conflicts = state.get("conflicts", [])
            answer = result.get("answer") or state.get("answer")
            _detail(stage, conflicts=[{"doc_key": c.doc_key, "section": c.section,
                                       "versions": [v.version for v in c.versions]} for c in conflicts],
                    # C1: the model answered, code found differing versions, and the answer did not show them
                    conflict_not_shown=bool(conflicts) and answer is not None and not answer.conflict)
            return result

    graph = StateGraph(AgentState)
    for name, node in (("guard", guard), ("plan", plan), ("retrieve", retrieve_docs), ("tool", run_tool),
                       ("generate", generate), ("validate", validate)):
        graph.add_node(name, node)
    graph.add_edge(START, "guard")
    graph.add_conditional_edges("guard", lambda s: END if s["blocked"] else "plan")
    graph.add_conditional_edges("plan", _after_plan)
    graph.add_conditional_edges("retrieve", lambda s: "tool" if s["route"].route == "BOTH" else "generate")
    graph.add_edge("tool", "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


def _detail(stage, **values) -> None:
    """Add facts to the recorder's stage row (its `detail` column), when the recorder offers one."""
    if stage is not None and hasattr(stage, "detail"):
        stage.detail.update(values)


def _after_plan(state: AgentState) -> str:
    route = state["route"].route
    if route in ("DOCS", "BOTH"):
        return "retrieve"
    if route == "SQL":
        return "tool"
    return "generate"           # CONVERSATIONAL


def _generate(state: AgentState, llm: LLMPort) -> dict:
    """A1 to A4 and G1. The fixed texts are chosen in code; the model is called only when there is evidence."""
    if state["route"].route == "CONVERSATIONAL":
        return {"text": SMALLTALK_TEXT, "conversational": True}
    cfg, retrieval = state["cfg"], state.get("retrieval")
    docs_ok = retrieval is not None and has_relevant_evidence(retrieval.top_score, retrieval.score_kind, cfg)
    tool_results = state.get("tools", [])
    if not docs_ok and not any(t.status in ("OK", "EMPTY") for t in tool_results):
        return _without_evidence(tool_results, state.get("no_tool", False))
    ranked = retrieval.reranked if docs_ok else []
    evidence = build_evidence(ranked, state.get("conflicts", []), tool_results, cfg.llm_max_context_tokens)
    system, user = build_prompt(state["route"].standalone_query, state.get("context", []), evidence)
    return {"evidence": evidence, **_ask_model(state, llm, system, user)}


def _without_evidence(tool_results: list[ToolResult], no_tool: bool) -> dict:
    """04 G1 and 13 section 5: which fixed text to show when nothing usable was found."""
    if no_tool or any(t.status == "NO_TOOL" for t in tool_results):
        return {"text": NO_TOOL_TEXT, "fallback": True}
    if tool_results:            # the tool was needed and failed (timeout, database error, bad arguments)
        return {"text": TOOL_UNAVAILABLE_TEXT, "fallback": False}
    return {"text": NO_EVIDENCE_TEXT, "fallback": True}


def _ask_model(state: AgentState, llm: LLMPort, system: str, user: str) -> dict:
    """A2 and V3: one answer call, one repair call if the JSON is invalid, then give up with OUTPUT_INVALID."""
    recorder, replies = state["recorder"], []
    try:
        reply = llm.complete(system, user, purpose="answer")
        replies.append(reply)
        report_llm(recorder, "answer", reply, ANSWER_PROMPT_VERSION)
        try:
            answer = parse_answer(reply.text)
        except ValueError:
            repair = llm.complete(system, user + "\n\n" + REPAIR_INSTRUCTION, purpose="repair")
            replies.append(repair)
            report_llm(recorder, "repair", repair, ANSWER_PROMPT_VERSION)
            answer = parse_answer(repair.text)
    except LLMError as error:
        return {"text": NO_EVIDENCE_TEXT, "llm_failed": True, "replies": replies, "llm_error_detail": str(error)[:300]}
    except ValueError:
        return {"text": NO_EVIDENCE_TEXT, "output_invalid": True, "replies": replies}
    if answer.insufficient_evidence:
        return {"text": NO_EVIDENCE_TEXT, "fallback": True, "replies": replies}
    return {"answer": answer, "replies": replies}


def _validate(state: AgentState) -> dict:
    """V1 citations, V2 grounding, V4 output safety. Nothing to check when a fixed text was chosen."""
    answer = state.get("answer")
    if answer is None:
        return {}
    evidence = {e.id: e for e in state.get("evidence", [])}
    answer, citation_checks = check_citations(answer, set(evidence))
    grounding, claim_checks = check_grounding(answer, evidence)
    suspects = [e.text for e in evidence.values() if e.chunk and e.chunk.injection_suspect]
    # the live model sometimes marks citations as 【T1】; the chat links the plain [T1] form
    text, flags = check_output(re.sub(r"【(\w+)】", r"[]", answer.answer_markdown), suspects)
    if suspects:
        flags = ["INJECTION_IN_EVIDENCE", *flags]
    return {"answer": answer, "text": text, "citation_checks": citation_checks, "grounding": grounding,
            "claim_checks": claim_checks, "safety_flags": flags}
