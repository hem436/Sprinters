"""`Agent.answer` (contract 01 section 3): what Sinngam's POST /query calls. Runs the graph, then the outcome rules."""
import threading
import time
from dataclasses import asdict, replace

from agent.config import AgentConfig
from agent.graph import AgentState, build_graph
from agent.outcome import QueryFacts, classify, confidence, has_relevant_evidence
from agent.ports import LLMPort, RecorderPort, RerankerPort, SearchPort, ToolPort
from agent.recording import OutcomeFactsOut, citation_rows
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
        _record(recorder, state, response, cfg)
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
        # "id" is the evidence id the answer cites (T1, T2...), so the chat can link a claim to its tool result
        tool_results=[{"id": f"T{i}", "tool": t.tool, "status": t.status, "summary": t.summary, "args": t.args}
                      for i, t in enumerate(state.get("tools", []), start=1)],
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
                       section=c.section, method=c.method, url=url, snippet=_snippet(c.text))


SNIPPET_CHARS = 300      # enough for one or two sentences in the chat's source viewer


def _snippet(text: str) -> str:
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + " ..."


def _record(recorder: RecorderPort, state: AgentState, response: QueryResponse, cfg: AgentConfig) -> None:
    """11 section 3: citations, context turns, then finish() once. The recorder prices the calls; the cost comes
    back into the response (05 usage.cost_usd)."""
    evidence = {e.id: e for e in state.get("evidence", [])}
    recorder.citations(citation_rows(state.get("citation_checks", []), evidence))
    recorder.context_turns([{"role": t.role, "text": t.text} for t in state.get("context", [])])
    facts = _facts(state)
    retrieval = state.get("retrieval")
    result = recorder.finish(
        response.answer_markdown, response.route, state.get("grounding"),
        facts=OutcomeFactsOut(
            llm_error=facts.llm_failed, output_invalid=facts.output_invalid, blocked=facts.blocked,
            fallback=facts.fallback, tool_failed=facts.tool_needed and facts.tool_failed, conflict=facts.conflict,
            grounding_score=state.get("grounding"), top_score=retrieval.top_score if retrieval else None),
        normalized_query=state["route"].standalone_query if state.get("route") else None,
        retrieval_relevant=has_relevant_evidence(retrieval.top_score, retrieval.score_kind, cfg) if retrieval else None,
        grounding_detail=[asdict(c) for c in state.get("claim_checks", [])],
        safety_flags=state.get("safety_flags", []),
    )
    if result is not None:
        response.usage.cost_usd = result.cost_usd
        response.usage.estimated = response.usage.estimated or result.cost_estimated
