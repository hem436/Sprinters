"""Stand-ins for the other parts and the LLM, built from the contract examples.

Used by the tests and for early demos, until Myank's search, Sinngam's tools and recorder, and a real model are wired in.
"""
import json
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


class NullRecorder:
    """Accepts every report and stores it in memory, so tests can look at what the agent recorded."""

    def __init__(self):
        self.stages: list[str] = []
        self.hit_lists: dict[str, list[Hit]] = {}
        self.llm_calls: list[tuple[str, LLMReply, str]] = []
        self.tool_calls: list[ToolResult] = []

    @contextmanager
    def stage(self, name: str):
        self.stages.append(name)
        yield

    def hits(self, list_name: str, hits: list[Hit]) -> None:
        self.hit_lists[list_name] = hits

    def llm_call(self, purpose: str, reply: LLMReply, prompt_version: str) -> None:
        self.llm_calls.append((purpose, reply, prompt_version))

    def tool_call(self, result: ToolResult) -> None:
        self.tool_calls.append(result)
