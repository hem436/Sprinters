"""`Agent.answer` and `Agent.answer_stream` (contract 01 section 3): what Sinngam's POST /query and /query/stream call.

Both run the same graph and the same outcome rules; the stream also yields the stage events of contract 05.
"""
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import asdict, replace

from agent.config import AgentConfig
from agent.graph import AgentState, build_graph
from agent.outcome import QueryFacts, classify, confidence, has_relevant_evidence
from agent.ports import LLMPort, RecorderPort, RerankerPort, SearchPort, ToolPort
from agent.recording import OutcomeFactsOut, citation_rows
from agent.safety import mask_pii
from agent.types import CitationOut, Evidence, QueryResponse, Turn, UsageOut

log = logging.getLogger(__name__)

SYSTEM_ERROR_TEXT = "Something went wrong while answering. The error is recorded; please try again."
SNIPPET_CHARS = 300      # enough for one or two sentences in the chat's source viewer
CONFIG_IDS = ("A", "B")  # 11 section 8


class SessionStore:
    """Conversation turns per session, in memory, bounded (contract 08); rule M1 picks from it.

    Each session keeps its last `max_messages`; the store keeps the `max_sessions` used most recently.
    """

    def __init__(self, max_messages: int = 20, max_sessions: int = 1000):
        self._turns: OrderedDict[str, list[Turn]] = OrderedDict()
        self._lock = threading.Lock()
        self.max_messages = max_messages
        self.max_sessions = max_sessions

    def history(self, session_id: str) -> list[Turn]:
        with self._lock:
            return list(self._turns.get(session_id, []))

    def add(self, session_id: str, *turns: Turn) -> None:
        with self._lock:
            kept = (self._turns.pop(session_id, []) + list(turns))[-self.max_messages:]
            self._turns[session_id] = kept                       # most recently used goes last
            while len(self._turns) > self.max_sessions:
                self._turns.popitem(last=False)


class OneAtATime:
    """Calls the wrapped part one call at a time (review #25). The API answers users in a thread pool and the eval
    runs in its own thread, all on one agent. The local Qdrant client is not documented as thread safe, and FlashRank's
    tokenizer is not either (ONNX Runtime itself is), so both take turns (review #25, two rounds). Each has its own
    lock: one user's search never waits for another user's rerank (about 0.6 s with MiniLM-L-12), and the model
    calls (seconds) run in parallel. The locks are re-entrant, so a nested call cannot block itself."""

    def __init__(self, inner, lock):
        self._inner, self._lock = inner, lock

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            with self._lock:
                return value(*args, **kwargs)
        return call


class Agent:
    def __init__(self, search: SearchPort, tools: ToolPort, llm: LLMPort, reranker: RerankerPort,
                 cfg: AgentConfig | None = None, sessions: SessionStore | None = None,
                 parts_lock=None):           # (search lock, rerank lock), shared with with_tools() copies
        self.cfg = cfg or AgentConfig()
        self.sessions = sessions or SessionStore()
        self._parts = (search, llm, reranker)
        self._parts_lock = parts_lock or (threading.RLock(), threading.RLock())
        self.search = OneAtATime(search, self._parts_lock[0])   # the eval runner reads chunks from search too
        self.tools = tools
        self._graph = build_graph(self.search, tools, llm, OneAtATime(reranker, self._parts_lock[1]))

    def with_tools(self, tools: ToolPort) -> "Agent":
        """The same agent with other tools. The eval's tool-failure cases use this, so the registry that serves real
        users is never switched to failure (review #25). Both agents share one parts lock."""
        search, llm, reranker = self._parts
        return Agent(search, tools, llm, reranker, self.cfg, self.sessions, self._parts_lock)

    def answer(self, question: str, session_id: str, recorder: RecorderPort, filters: dict | None = None,
               config_id: str | None = None) -> QueryResponse:
        """05 POST /query: the same run as the stream, keeping only the final response."""
        _check_config(config_id)
        for event, data in self._run(question, session_id, recorder, filters, config_id):
            if event == "done":
                return data
        raise RuntimeError("the agent run ended without a response")     # _run always ends with "done"

    def answer_stream(self, question: str, session_id: str, recorder: RecorderPort, filters: dict | None = None,
                      config_id: str | None = None) -> Iterator[tuple[str, dict]]:
        """05 POST /query/stream: (event, data) pairs; the route writes each as `event: <event>` and `data: <json>`.

        Order: status (one per stage) ... citations, token (the checked answer, word by word), done. On a system
        error: status ..., error, done. The answer is sent only after the checks (V1, V2, V4), so the user never
        sees text that a check later removes.

        Not a generator itself: a bad config_id raises here, before the route starts the response, so it can give a
        422 and not a broken stream (review #25).
        """
        _check_config(config_id)
        run = self._run(question, session_id, recorder, filters, config_id)
        return ((event, data.model_dump() if event == "done" else data) for event, data in run)

    def _run(self, question: str, session_id: str, recorder: RecorderPort, filters: dict | None,
             config_id: str | None) -> Iterator[tuple[str, object]]:
        started = time.perf_counter()
        cfg = replace(self.cfg, config_id=config_id) if config_id else self.cfg
        # 04 S3, 06: masked once, here, so no stage, prompt or session ever holds the raw personal data (review #25)
        question, pii = mask_pii(question)
        inputs = {"question": question, "filters": filters, "cfg": cfg, "recorder": recorder,
                  "history": self.sessions.history(session_id), "replies": [],
                  "safety_flags": [f"PII_IN_QUESTION_{kind}" for kind in pii]}
        state: dict = dict(inputs)
        try:
            for mode, chunk in self._graph.stream(inputs, stream_mode=["custom", "values"]):
                if mode == "custom":
                    yield "status", chunk
                else:
                    state = chunk            # the state after each node, so a failure keeps what was done
        except Exception as error:
            # 11 section 5 rule 1: a failure in any part (search, tool, model client) is answered and recorded
            log.exception("agent run failed", extra={"query_id": recorder.query_id})
            state = {**state, "system_error": type(error).__name__, "text": SYSTEM_ERROR_TEXT, "answer": None}
        response = _response(state, recorder.query_id, cfg, int((time.perf_counter() - started) * 1000))
        self.sessions.add(session_id, Turn("user", question, blocked=state.get("blocked", False)),
                          Turn("assistant", response.answer_markdown))
        _record(recorder, state, response, cfg)
        if state.get("system_error"):
            yield "error", {"code": "SYSTEM_ERROR", "message": SYSTEM_ERROR_TEXT, "query_id": response.query_id}
        else:
            yield "citations", {"citations": [c.model_dump() for c in response.citations]}
            for piece in re.findall(r"\S+\s*", response.answer_markdown):
                yield "token", {"text": piece}
        yield "done", response


def _check_config(config_id: str | None) -> None:
    """11 section 8: an unknown config must not silently run B; the route turns this ValueError into a 422."""
    if config_id is not None and config_id not in CONFIG_IDS:
        raise ValueError(f"config_id must be one of {CONFIG_IDS}, not {config_id!r}")


def _response(state: dict, query_id: str, cfg: AgentConfig, latency_ms: int) -> QueryResponse:
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
        route=_route(state),
        citations=_citations(state),
        # "id" is the evidence id the answer cites (T1, T2...), so the chat can link a claim to its tool result
        tool_results=[{"id": f"T{i}", "tool": t.tool, "status": t.status, "summary": t.summary, "args": t.args,
                       "rows": t.rows}     # the SQL itself is shown only in the admin drill-down
                      for i, t in enumerate(state.get("tools", []), start=1)],
        conflict=facts.conflict,
        usage=UsageOut(tokens_in=sum(r.tokens_in for r in replies), tokens_out=sum(r.tokens_out for r in replies),
                       estimated=any(r.usage_source == "ESTIMATED" for r in replies)),
        latency_ms=latency_ms,
    )


def _route(state: dict) -> str:
    """The route of contract 05. A run that failed before planning has no route; it is reported as DOCS."""
    if state.get("blocked"):
        return "BLOCKED"
    route = state.get("route")
    return route.route if route else "DOCS"


def _facts(state: dict) -> QueryFacts:
    checks = state.get("citation_checks", [])
    answer = state.get("answer")
    route = state.get("route")
    tools = state.get("tools", [])
    return QueryFacts(
        system_error=bool(state.get("system_error")),
        llm_failed=state.get("llm_failed", False),
        output_invalid=state.get("output_invalid", False),
        blocked=state.get("blocked", False),
        conversational=state.get("conversational", False),
        fallback=state.get("fallback", False),
        tool_needed=bool(route and route.route in ("SQL", "BOTH")),
        tool_failed=any(t.status not in ("OK", "EMPTY", "NO_TOOL") for t in tools),     # NO_TOOL: nothing failed
        citations_valid=sum(c.valid for c in checks),
        citations_total=len(checks),
        grounding_score=state.get("grounding", 0.0),
        conflict=bool(answer and answer.conflict),
    )


def _citations(state: dict) -> list[CitationOut]:
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
    return CitationOut(id=e.id, kind="document", title=c.title, version=c.version, page=c.page, section=c.section,
                       method=c.method, url=url, snippet=_snippet(c.text), current=getattr(c, "current", None))


def _snippet(text: str) -> str:
    """At most SNIPPET_CHARS, cut at the last space or line break, so an amount such as ₹4,35,500 is never cut."""
    if len(text) <= SNIPPET_CHARS:
        return text
    cut = re.match(r"(?s)(.*)\s", text[:SNIPPET_CHARS + 1])
    return (cut.group(1).rstrip() if cut else text[:SNIPPET_CHARS]) + " ..."


def _record(recorder: RecorderPort, state: dict, response: QueryResponse, cfg: AgentConfig) -> None:
    """11 section 3: citations, context turns, then finish() once. The recorder prices the calls; the cost comes
    back into the response (05 usage.cost_usd)."""
    evidence = {e.id: e for e in state.get("evidence", [])}
    recorder.citations(citation_rows(state.get("citation_checks", []), evidence, state.get("tool_call_ids", [])))
    recorder.context_turns([{"role": t.role, "text": t.text} for t in state.get("context", [])])
    facts = _facts(state)
    retrieval = state.get("retrieval")
    result = recorder.finish(
        response.answer_markdown, response.route, state.get("grounding"),
        facts=OutcomeFactsOut(
            system_error=facts.system_error, llm_error=facts.llm_failed, output_invalid=facts.output_invalid,
            blocked=facts.blocked, fallback=facts.fallback, tool_failed=facts.tool_needed and facts.tool_failed,
            conflict=facts.conflict, grounding_score=state.get("grounding"),
            top_score=retrieval.top_score if retrieval else None),
        # review #25: no personal data reaches the store from the agent's side either
        normalized_query=mask_pii(state["route"].standalone_query)[0] if state.get("route") else None,
        retrieval_relevant=has_relevant_evidence(retrieval.top_score, retrieval.score_kind, cfg) if retrieval else None,
        grounding_detail=[{**asdict(c), "text": mask_pii(c.text)[0]} for c in state.get("claim_checks", [])],
        safety_flags=state.get("safety_flags", []),
        error_category=state.get("system_error") or ("LLM_ERROR" if facts.llm_failed else None),
        # one copy of the outcome rules (CHANGES DC-1): the store keeps exactly what the user saw
        outcome=response.outcome, reason_code=response.reason_code, confidence=response.confidence,
    )
    if result is not None:
        response.usage.cost_usd = result.cost_usd
        response.usage.estimated = response.usage.estimated or result.cost_estimated
