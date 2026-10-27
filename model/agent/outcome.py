"""Outcome rules (contract 11 section 5) and the confidence category. Pure: the facts of one query in, a verdict out.

Sinngam's recorder stores the result; this module decides it (contract 01 section 3: `classify`).
"""
from dataclasses import dataclass

from agent.config import AgentConfig
from agent.types import Confidence, Outcome


@dataclass(frozen=True)
class QueryFacts:
    """What happened in one query, as the outcome rules need it."""
    system_error: bool = False
    llm_failed: bool = False
    output_invalid: bool = False
    blocked: bool = False
    conversational: bool = False
    fallback: bool = False            # a fixed "not found" or "cannot answer" text was returned
    tool_needed: bool = False
    tool_failed: bool = False
    citations_valid: int = 0
    citations_total: int = 0
    grounding_score: float = 0.0
    conflict: bool = False


def classify(f: QueryFacts, cfg: AgentConfig) -> tuple[Outcome, str]:
    """11 section 5: the rules in their documented order; the first that matches decides."""
    rules = [
        (f.system_error, ("FAILED", "SYSTEM_ERROR")),
        (f.llm_failed, ("FAILED", "LLM_ERROR")),
        (f.output_invalid, ("FAILED", "OUTPUT_INVALID")),
        (f.blocked, ("PARTIAL", "BLOCKED_SAFETY")),
        # small talk has no evidence to cite, so it must not fall into UNGROUNDED_ANSWER below
        (f.conversational, ("SUCCESS", "OK_SMALLTALK")),
        (f.fallback, ("PARTIAL", "NO_EVIDENCE")),
        (f.tool_needed and f.tool_failed, ("PARTIAL", "TOOL_FAILED")),
        (f.citations_valid == 0, ("FAILED", "UNGROUNDED_ANSWER")),
        (f.grounding_score < cfg.obs_grounding_min or f.citations_valid < f.citations_total,
         ("PARTIAL", "UNSUPPORTED_CLAIMS")),
    ]
    for matched, verdict in rules:
        if matched:
            return verdict
    return ("SUCCESS", "OK_CONFLICT") if f.conflict else ("SUCCESS", "OK")


def confidence(outcome: Outcome, top_score: float, score_kind: str, cfg: AgentConfig) -> Confidence:
    """11 section 5: HIGH for a success with a strong top score, MEDIUM for other successes, LOW otherwise."""
    if outcome != "SUCCESS":
        return "LOW"
    high = cfg.obs_relevance_high if score_kind == "rerank" else cfg.obs_relevance_high_vector
    return "HIGH" if top_score >= high else "MEDIUM"


def has_relevant_evidence(top_score: float, score_kind: str, cfg: AgentConfig) -> bool:
    """04 G1 and 11 section 6: is the best chunk good enough to answer from? Config A uses its own cosine threshold."""
    threshold = cfg.obs_relevance_min if score_kind == "rerank" else cfg.obs_relevance_min_vector
    return top_score >= threshold
