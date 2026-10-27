"""Agent settings. Every threshold the rules use lives here (contracts 04 and 11), never in the rule code."""
from dataclasses import dataclass, fields


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
    obs_relevance_min: float = 0.3          # top rerank score below this means "no relevant evidence"
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
