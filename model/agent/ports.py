"""What the agent needs from the other parts. Each is a Protocol, so tests and early work use stubs (agent/stubs.py).

Owners (contract 01 section 3): search is Myank's, tools and the recorder are Sinngam's, the LLM client is ours.
"""
from contextlib import AbstractContextManager
from typing import Any, Protocol

from agent.types import Chunk, Hit, LLMReply, ToolResult


class SearchPort(Protocol):
    """Myank: 10 section 9."""

    def vector_search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]: ...

    def bm25_search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]: ...

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]: ...

    def get_section_versions(self, doc_key: str, section: str) -> list[Chunk]:
        """Chunks of the same section in every version of a document; used by rule C1."""
        ...


class ToolPort(Protocol):
    """Sinngam: 13 sections 4 and 5."""

    def list_tools(self) -> list[dict]:
        """Each tool's name, description and argument schema; the planner sees only this."""
        ...

    def run_tool(self, name: str, args: dict) -> ToolResult: ...


class RerankerPort(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class LLMPort(Protocol):
    def complete(self, system: str, user: str, *, purpose: str, json_mode: bool = True) -> LLMReply: ...


class RecorderPort(Protocol):
    """Sinngam's QueryRecorder (backend/app/observability/recorder.py), call shapes of contract 11 section 3.

    It never raises into the answer path, except from stage(), which re-raises the agent's own exception.
    agent/recording.py turns agent objects into these calls.
    """

    query_id: str

    def stage(self, name: str) -> AbstractContextManager: ...

    def hits(self, list_name: str, hits: list[dict]) -> None: ...

    def llm_call(self, purpose: str, model: str, usage: Any = None, latency_ms: int | None = None,
                 prompt_version: str | None = None, *, cache_hit: bool = False, estimate: Any = None,
                 raw_output: str | None = None) -> None: ...

    def tool_call(self, tool: str, args: dict | None, status: str, row_count: int = 0, latency_ms: int | None = None,
                  *, result_summary: str | None = None, error_category: str | None = None,
                  version: Any = None, sql: list[dict] | None = None) -> str: ...

    def citations(self, validated: list[dict]) -> None: ...

    def context_turns(self, turns: list) -> None: ...

    def finish(self, answer: str | None, route: str | None, grounding_score: float | None = None, *,
               facts: Any = None, normalized_query: str | None = None, retrieval_relevant: bool | None = None,
               grounding_detail: Any = None, safety_flags: list[str] = (), error_category: str | None = None,
               http_status: int = 200, outcome: str | None = None, reason_code: str | None = None,
               confidence: str | None = None) -> Any:
        """Returns a result with cost_usd and cost_estimated (backend FinishResult). The agent passes its own
        outcome, reason_code and confidence, so the store holds what the user saw (one copy of the rules)."""
        ...
