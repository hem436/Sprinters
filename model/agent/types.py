"""Data shapes shared by the agent, copied from the contracts so the names match the other parts exactly."""
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

Route = Literal["DOCS", "SQL", "BOTH", "CONVERSATIONAL", "BLOCKED"]
ToolStatus = Literal["OK", "EMPTY", "ARGS_INVALID", "TIMEOUT", "DB_ERROR", "NO_TOOL"]
Outcome = Literal["SUCCESS", "PARTIAL", "FAILED"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class Hit:
    """10 section 9: what vector_search and bm25_search return (Myank's interface)."""
    chunk_id: str
    score: float
    rank: int


@dataclass(frozen=True)
class Chunk:
    """10 section 9: the chunk record. Only the fields the agent reads."""
    chunk_id: str
    document_id: str
    doc_key: str
    title: str
    version: str
    effective_date: str
    page: int | None
    section: str
    method: str
    text: str
    injection_suspect: bool = False
    current: bool | None = None       # true when this is the current version of its doc_key (Myank fills it)


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float          # rerank score (config B) or cosine score (config A)


@dataclass(frozen=True)
class ToolResult:
    """13 section 5: what Sinngam's run_tool returns."""
    tool: str
    status: ToolStatus
    summary: str = ""
    rows: list[dict] = field(default_factory=list)
    args: dict = field(default_factory=dict)
    version: int = 1
    latency_ms: int = 0
    message: str = ""


@dataclass(frozen=True)
class Turn:
    """One message of the conversation, as the session keeps it (04 M1)."""
    role: Literal["user", "assistant"]
    text: str
    blocked: bool = False


@dataclass(frozen=True)
class RouteDecision:
    """04 R1: the router's result. reason says who decided: the planner, a rule, or the fallback."""
    route: Route
    standalone_query: str
    tool: str | None = None
    tool_args: dict = field(default_factory=dict)
    reason: Literal["PLANNER", "RULE_OVERRIDE", "ROUTE_FALLBACK", "RULE_GREETING", "ROUTE_NO_TOOL"] = "PLANNER"
    note: str = ""        # what the drill-down should know, for example a failed tool re-ask (review #25)


@dataclass(frozen=True)
class Evidence:
    """One numbered item given to the answer model (04 A1): E1, E2 for chunks, T1 for a tool result."""
    id: str
    kind: Literal["document", "tool"]
    text: str
    chunk: Chunk | None = None
    tool: ToolResult | None = None


@dataclass(frozen=True)
class LLMReply:
    """One model call and its usage, for the recorder (11 section 4)."""
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    latency_ms: int = 0
    cache_hit: bool = False
    usage_source: Literal["PROVIDER", "ESTIMATED"] = "PROVIDER"


class Claim(BaseModel):
    text: str
    citations: list[str] = Field(default_factory=list)


class AnswerJSON(BaseModel):
    """04 A2: the only shape the answer model may return."""
    answer_markdown: str
    claims: list[Claim] = Field(default_factory=list)
    insufficient_evidence: bool = False
    conflict: bool = False


class CitationOut(BaseModel):
    """05 QueryResponse citation."""
    id: str
    kind: Literal["document", "tool"]
    title: str | None = None
    version: str | None = None
    page: int | None = None
    section: str | None = None
    method: str | None = None
    url: str | None = None
    snippet: str | None = None       # CHANGES DC-4 (Hemant): the cited passage, so the chat can show it
    current: bool | None = None       # CHANGES DC-4: is this the current version; None when extraction does not say
    tool: str | None = None
    args: dict | None = None
    row_count: int | None = None


class UsageOut(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: str | None = None      # Sinngam's recorder fills the price (11 section 4)
    estimated: bool = False


class QueryResponse(BaseModel):
    """05: the body of POST /query."""
    query_id: str
    answer_markdown: str
    outcome: Outcome
    reason_code: str
    confidence: Confidence
    route: Route
    citations: list[CitationOut] = Field(default_factory=list)
    tool_results: list[dict] = Field(default_factory=list)
    conflict: bool = False
    usage: UsageOut = Field(default_factory=UsageOut)
    latency_ms: int = 0
