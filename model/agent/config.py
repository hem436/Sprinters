"""Agent settings. Every threshold the rules use lives here (contracts 04 and 11), never in the rule code."""
import os
from dataclasses import dataclass, field, fields

RERANK_DEFAULT_MODEL = "ms-marco-MiniLM-L-12-v2"
# The relevance gate per reranker, measured on the demo corpus (27 Oct, 284 chunks): lowest top score of an answerable
# question / highest of an unanswerable one. MiniLM-L-12: 0.144 / 0.001. TinyBERT-L-2: 0.003 / 0.000.
RERANK_GATES = {"ms-marco-MiniLM-L-12-v2": 0.1, "ms-marco-TinyBERT-L-2-v2": 0.002}
DESIGN_GATE = 0.3       # contract 11 section 6, for a reranker we have not measured


def rerank_model() -> str:
    return os.getenv("AGENT_RERANK_MODEL") or RERANK_DEFAULT_MODEL


def default_relevance_min() -> float:
    """AGENT_RELEVANCE_MIN when set; else the measured gate of the reranker in use, so switching the reranker never
    leaves the other model's gate behind (review #25)."""
    if os.getenv("AGENT_RELEVANCE_MIN"):
        return float(os.environ["AGENT_RELEVANCE_MIN"])
    return RERANK_GATES.get(rerank_model(), DESIGN_GATE)


@dataclass(frozen=True)
class AgentConfig:
    config_id: str = "B"                 # 11 section 8: "A" = vector only, "B" = hybrid + RRF + rerank

    # 04 M1: conversation window
    ctx_max_turns: int = 3
    ctx_max_chars_per_turn: int = 600

    # 04 H1 to H4: retrieval
    ret_vector_k: int = 20
    ret_bm25_k: int = 20
    ret_rrf_k: int = 60
    ret_fused_k: int = 20
    ret_rerank_top_n: int = 5

    # 04 G1 and 11 section 6: relevance and grounding thresholds
    # top rerank score below this means "no relevant evidence"; measured per reranker (RERANK_GATES above).
    # Remeasure whenever the reranker or the corpus changes.
    obs_relevance_min: float = field(default_factory=default_relevance_min)
    obs_relevance_min_vector: float = 0.6   # the same for config A, which has only cosine scores
    obs_relevance_high: float = 0.7         # confidence HIGH (rerank score)
    obs_relevance_high_vector: float = 0.8  # confidence HIGH (cosine score, config A)
    obs_grounding_min: float = 0.8

    # 04 A4: evidence budget
    llm_max_context_tokens: int = 6000

    @classmethod
    def from_dict(cls, values: dict) -> "AgentConfig":
        """Build from the `agent` section of config/app.yaml; unknown keys are refused so a typo cannot pass silently."""
        known = {f.name for f in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"unknown agent config keys: {sorted(unknown)}")
        return cls(**values)
