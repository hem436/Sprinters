"""`Agent.answer` (contract 01 section 3): what Sinngam's POST /query calls. Runs the graph, then the outcome rules."""
import threading
import time
from dataclasses import asdict, replace

from agent.config import AgentConfig
from agent.graph import AgentState, build_graph
from agent.outcome import QueryFacts, classify, confidence
from agent.ports import LLMPort, RecorderPort, RerankerPort, SearchPort, ToolPort
from agent.safety import mask_pii
from agent.types import CitationOut, Evidence, QueryResponse, Turn, UsageOut


class SessionStore:
    """Conversation turns per session, in memory. Enough for one API process (contract 08); M1 picks from it."""

    def __init__(self):
        self._turns: dict[str, list[Turn]] = {}
        self._lock = threading.Lock()

    def history(self, session_id: str) -> list[Turn]:
        with self._lock:
            return list(self._turns.get(session_id, []))

    def add(self, session_id: str, *turns: Turn) -> None:
        with self._lock:
            self._turns.setdefault(session_id, []).extend(turns)


class Agent:
    def __init__(self, search: SearchPort, tools: ToolPort, llm: LLMPort, reranker: RerankerPort,
                 cfg: AgentConfig | None = None, sessions: SessionStore | None = None):
        self.cfg = cfg or AgentConfig()
        self.sessions = sessions or SessionStore()
        self._graph = build_graph(search, tools, llm, reranker)

    def answer(self, question: str, session_id: str, recorder: RecorderPort, filters: dict | None = None,
               config_id: str | None = None) -> QueryResponse:
        """05 POST /query. config_id "A" or "B" is for the evaluation runs (11 section 8)."""
        started = time.perf_counter()
        cfg = replace(self.cfg, config_id=config_id) if config_id else self.cfg
        state: AgentState = self._graph.invoke({
            "question": question, "filters": filters, "cfg": cfg, "recorder": recorder,
            "history": self.sessions.history(session_id), "replies": [], "safety_flags": [],
        })
        response = _response(state, recorder.query_id, cfg, int((time.perf_counter() - started) * 1000))
        self.sessions.add(session_id, Turn("user", question, blocked=state.get("blocked", False)),
                          Turn("assistant", response.answer_markdown))
        recorder.citations(state.get("citation_checks", []))
        recorder.finish(response, _details(state))
        return response


def _response(state: AgentState, query_id: str, cfg: AgentConfig, latency_ms: int) -> QueryResponse:
    facts = _facts(state)
    outcome, reason = classify(facts, cfg)
    retrieval = state.get("retrieval")
    top, kind = (retrieval.top_score, retrieval.score_kind) if retrieval else (0.0, "rerank")
    replies = [r for r in state.get("replies", []) if r]
    return QueryResponse(
        query_id=query_id,
        answer_markdown=state.get("text", ""),
        outcome=outcome,
        reason_code=reason,
        confidence=confidence(outcome, top, kind, cfg),
        route="BLOCKED" if state.get("blocked") else state["route"].route,
        citations=_citations(state),
        tool_results=[{"tool": t.tool, "status": t.status, "summary": t.summary, "args": t.args}
                      for t in state.get("tools", [])],
        conflict=facts.conflict,
        usage=UsageOut(tokens_in=sum(r.tokens_in for r in replies), tokens_out=sum(r.tokens_out for r in replies),
                       estimated=any(r.usage_source == "ESTIMATED" for r in replies)),
        latency_ms=latency_ms,
    )


def _facts(state: AgentState) -> QueryFacts:
    checks = state.get("citation_checks", [])
    answer = state.get("answer")
    route = state.get("route")
    tools = state.get("tools", [])
    return QueryFacts(
        llm_failed=state.get("llm_failed", False),
        output_invalid=state.get("output_invalid", False),
        blocked=state.get("blocked", False),
        conversational=state.get("conversational", False),
        fallback=state.get("fallback", False),
        tool_needed=bool(route and route.route in ("SQL", "BOTH")),
        tool_failed=any(t.status not in ("OK", "EMPTY") for t in tools),
        citations_valid=sum(c.valid for c in checks),
        citations_total=len(checks),
        grounding_score=state.get("grounding", 0.0),
        conflict=bool(answer and answer.conflict),
    )


def _citations(state: AgentState) -> list[CitationOut]:
    """05: one entry per evidence id the answer actually cites, in the order first cited."""
    answer = state.get("answer")
    if answer is None:
        return []
    evidence = {e.id: e for e in state.get("evidence", [])}
    cited = list(dict.fromkeys(cid for claim in answer.claims for cid in claim.citations))
    return [_citation(evidence[cid]) for cid in cited if cid in evidence]


def _citation(e: Evidence) -> CitationOut:
    if e.kind == "tool":
        return CitationOut(id=e.id, kind="tool", tool=e.tool.tool, args=e.tool.args, row_count=len(e.tool.rows))
    c = e.chunk
    url = f"/documents/{c.document_id}/pages/{c.page}" if c.page is not None else f"/documents/{c.document_id}"
    return CitationOut(id=e.id, kind="document", title=c.title, version=c.version, page=c.page,
                       section=c.section, method=c.method, url=url)


def _details(state: AgentState) -> dict:
    """What the drill-down needs beyond the response (11 sections 2 and 9)."""
    route = state.get("route")
    return {
        "question_masked": mask_pii(state["question"])[0],
        "normalized_query": route.standalone_query if route else None,
        "route_reason": route.reason if route else "BLOCKED",
        "context_turns": [{"role": t.role, "text_masked": t.text, "chars": len(t.text)} for t in state.get("context", [])],
        "grounding_detail": [asdict(c) for c in state.get("claim_checks", [])],
        "safety_flags": state.get("safety_flags", []),
        "conflicts": [{"doc_key": c.doc_key, "section": c.section, "versions": [v.version for v in c.versions]}
                      for c in state.get("conflicts", [])],
        # C1: code found differing versions but the answer did not show them; the reviewer must see that
        "conflict_not_shown": bool(state.get("conflicts")) and not bool(state.get("answer") and state["answer"].conflict),
        "facts": asdict(_facts(state)),
    }
