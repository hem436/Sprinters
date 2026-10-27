"""Stand-ins for the other parts and the LLM, built from the contract examples.

Used by the tests and for early demos, until Myank's search, Sinngam's tools and recorder, and a real model are wired in.
"""
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from agent.types import Chunk, Hit, LLMReply, ToolResult


class FakeLLM:
    """Returns prepared replies in order, per purpose ("route", "answer", "repair"); records what it was asked."""

    def __init__(self, replies: dict[str, list[str | dict]]):
        self._replies = {k: list(v) for k, v in replies.items()}
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, system: str, user: str, *, purpose: str, json_mode: bool = True) -> LLMReply:
        self.calls.append((purpose, system, user))
        queue = self._replies.get(purpose) or []
        if not queue:
            raise RuntimeError(f"FakeLLM has no reply left for purpose {purpose!r}")
        reply = queue.pop(0)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return LLMReply(text=text, model="fake", tokens_in=len(system + user) // 4, tokens_out=len(text) // 4)


@dataclass
class StubSearch:
    """Myank's search interface over a fixed list of chunks, with fixed ranked lists per query."""
    chunks: dict[str, Chunk]
    vector: list[Hit] = field(default_factory=list)
    bm25: list[Hit] = field(default_factory=list)

    def vector_search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]:
        return self.vector[:k]

    def bm25_search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]:
        return self.bm25[:k]

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        return [self.chunks[c] for c in chunk_ids if c in self.chunks]

    def get_section_versions(self, doc_key: str, section: str) -> list[Chunk]:
        return [c for c in self.chunks.values() if c.doc_key == doc_key and c.section == section]


@dataclass
class StubTools:
    """Sinngam's tool registry with prepared results per tool name."""
    results: dict[str, ToolResult] = field(default_factory=dict)
    catalogue: list[dict] = field(default_factory=lambda: [
        {"name": "budget_status", "description": "Budget, spent, remaining and % used for one project, year and category",
         "args": {"project_id": "P-ddd", "fiscal_year": "FYyyyy-yy", "category": "TRAVEL|MEALS|...|null"}},
    ])
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def list_tools(self) -> list[dict]:
        return self.catalogue

    def run_tool(self, name: str, args: dict) -> ToolResult:
        self.calls.append((name, args))
        return self.results.get(name, ToolResult(tool=name, status="NO_TOOL", args=args, message="unknown tool"))


@dataclass
class StageHandle:
    detail: dict = field(default_factory=dict)
    retries: int = 0


@dataclass(frozen=True)
class FinishResultStub:
    query_id: str
    cost_usd: str | None = None
    cost_estimated: bool = False


class NullRecorder:
    """Same call shapes as Sinngam's QueryRecorder (contract 11 section 3); keeps every call in memory for tests."""

    def __init__(self, cost_usd: str | None = None):
        self.query_id = uuid.uuid4().hex[:12]
        self.cost_usd = cost_usd
        self.stages: list[str] = []
        self.stage_details: dict[str, dict] = {}
        self.hit_lists: dict[str, list[dict]] = {}
        self.llm_calls: list[dict] = []
        self.tool_calls: list[dict] = []
        self.citation_rows: list[dict] = []
        self.turns: list = []
        self.finished: dict | None = None

    @contextmanager
    def stage(self, name: str, *, retries: int = 0):
        self.stages.append(name)
        handle = StageHandle(retries=retries)
        yield handle
        self.stage_details[name] = handle.detail

    def hits(self, list_name: str, hits: list[dict]) -> None:
        self.hit_lists[list_name] = list(hits)

    def llm_call(self, purpose, model, usage=None, latency_ms=None, prompt_version=None, *, cache_hit=False,
                 estimate=None) -> None:
        self.llm_calls.append({"purpose": purpose, "model": model, "usage": usage, "estimate": estimate,
                               "prompt_version": prompt_version, "cache_hit": cache_hit})

    def tool_call(self, tool, args, status, row_count=0, latency_ms=None, *, result_summary=None,
                  error_category=None, version=None) -> str:
        self.tool_calls.append({"tool": tool, "args": args, "status": status, "row_count": row_count,
                                "result_summary": result_summary, "error_category": error_category})
        return f"T{len(self.tool_calls)}"

    def citations(self, validated) -> None:
        self.citation_rows = list(validated)

    def context_turns(self, turns) -> None:
        self.turns = list(turns)

    def finish(self, answer, route, grounding_score=None, **kwargs) -> FinishResultStub:
        self.finished = {"answer": answer, "route": route, "grounding_score": grounding_score, **kwargs}
        return FinishResultStub(self.query_id, self.cost_usd)
