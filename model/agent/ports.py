"""What the agent needs from the other parts. Each is a Protocol, so tests and early work use stubs (agent/stubs.py).

Owners (contract 01 section 3): search is Myank's, tools and the recorder are Sinngam's, the LLM client is ours.
"""
from contextlib import AbstractContextManager
from typing import Protocol

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
    """Sinngam: 11 section 3. The agent reports; the recorder stores. It must never raise into the answer path."""

    def stage(self, name: str) -> AbstractContextManager: ...

    def hits(self, list_name: str, hits: list[Hit]) -> None: ...

    def llm_call(self, purpose: str, reply: LLMReply, prompt_version: str) -> None: ...

    def tool_call(self, result: ToolResult) -> None: ...
