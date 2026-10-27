"""How the agent reports to Sinngam's QueryRecorder, in the call shapes of contract 11 section 3.

All translation from agent objects to recorder calls lives here, so graph.py and service.py stay about the rules.
"""
from contextlib import contextmanager
from dataclasses import dataclass

from langgraph.config import get_stream_writer

from agent.ports import RecorderPort
from agent.types import Chunk, Evidence, Hit, LLMReply, ToolResult


@dataclass(frozen=True)
class EstimatedUsage:
    """Same fields as the recorder's Usage, for calls where the provider sent no usage (11 section 4)."""
    tokens_in: int
    tokens_out: int
    tokens_cached: int = 0
    source: str = "ESTIMATED"


@dataclass
class OutcomeFactsOut:
    """The facts the recorder's finish() reads (field names of backend OutcomeFacts)."""
    system_error: bool = False
    llm_error: bool = False
    output_invalid: bool = False
    blocked: bool = False
    fallback: bool = False
    tool_failed: bool = False
    conflict: bool = False
    citations_valid: int = 0
    citations_total: int = 0
    grounding_score: float | None = None
    top_score: float | None = None


def report_llm(recorder: RecorderPort, purpose: str, reply: LLMReply, prompt_version: str) -> None:
    """11 sections 3 and 4. A repair call is an answer call (the purposes are route, answer, judge, ocr, embed);
    its prompt version says it was the repair."""
    usage, estimate = None, None
    if reply.usage_source == "PROVIDER":
        usage = {"prompt_tokens": reply.tokens_in, "completion_tokens": reply.tokens_out,
                 "prompt_tokens_details": {"cached_tokens": reply.tokens_cached}}
    else:
        estimate = EstimatedUsage(reply.tokens_in, reply.tokens_out)
    recorder.llm_call(purpose if purpose != "repair" else "answer", reply.model, usage, reply.latency_ms,
                      prompt_version if purpose != "repair" else f"{prompt_version}-repair",
                      cache_hit=reply.cache_hit, estimate=estimate, raw_output=reply.text)


def report_tool(recorder: RecorderPort, result: ToolResult) -> str | None:
    """Returns the recorder's id for this call; citations of the tool point at it (review #25)."""
    error = None if result.status in ("OK", "EMPTY") else result.status
    return recorder.tool_call(result.tool, result.args, result.status, len(result.rows), result.latency_ms,
                              result_summary=result.summary or result.message or None, error_category=error,
                              version=result.version)


def hit_rows(hits: list[Hit], chunks: dict[str, Chunk]) -> list[dict]:
    """retrieval_hit rows: chunk id, rank, score, and the document and page when the chunk is known."""
    rows = []
    for hit in hits:
        chunk = chunks.get(hit.chunk_id)
        rows.append({"chunk_id": hit.chunk_id, "rank": hit.rank, "score": hit.score,
                     "document_id": chunk.document_id if chunk else None, "page": chunk.page if chunk else None})
    return rows


def citation_rows(checks: list, evidence: dict[str, Evidence], tool_call_ids: list[str]) -> list[dict]:
    """citation rows: the cited id, the chunk or the recorded tool call it points to, valid or not, and why.

    Evidence T1, T2... are the tool results in run order, so T<n> maps to the n-th id the recorder returned.
    """
    rows = []
    for check in checks:
        e = evidence.get(check.id)
        call_id = None
        if e is not None and e.kind == "tool":
            n = int(check.id[1:]) - 1
            call_id = tool_call_ids[n] if 0 <= n < len(tool_call_ids) else None
        rows.append({"citation_id": check.id, "valid": check.valid, "reason": check.reason,
                     "chunk_id": e.chunk.chunk_id if e and e.chunk else None, "tool_call_id": call_id})
    return rows


# 05 /query/stream status events: the stage names the web app shows (issue #48), with a label for the user.
STAGE_LABELS = {
    "guard": "Checking the question",
    "context": "Reading the conversation",
    "route": "Choosing documents or data",
    "retrieve_vector": "Searching by meaning",
    "retrieve_bm25": "Searching for exact words",
    "fuse": "Merging the results",
    "rerank": "Ranking the passages",
    "tool": "Querying the business data",
    "answer": "Writing the answer",
    "validate": "Checking citations and numbers",
}


def emit_status(*stages: str) -> None:
    """Announce a stage to a streaming caller. Inside invoke() the writer does nothing; outside a graph there is none."""
    try:
        write = get_stream_writer()
    except RuntimeError:
        return
    for name in stages:
        write({"stage": name, "label": STAGE_LABELS[name]})


@contextmanager
def run_stage(recorder: RecorderPort, name: str, *stream_names: str):
    """One stage: announced on the stream (Hemant's names) and timed by the recorder (contract 11 names)."""
    emit_status(*(stream_names or (name,)))
    with recorder.stage(name) as handle:
        yield handle
