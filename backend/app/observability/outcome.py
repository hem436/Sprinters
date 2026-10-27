"""Outcome rules (contract 11 section 5): first match wins.

Arka owns these rules (contract 01 section 3: classify(record) -> (outcome, reason_code)).
This file follows the contract table exactly so the recorder works today; Arka reviews it
or replaces it, and the recorder takes any function with the same signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OutcomeFacts:
    """What the agent tells the recorder about the answer, in finish()."""

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
    extra_flags: list[str] = field(default_factory=list)


def classify(facts: OutcomeFacts, grounding_min: float = 0.8) -> tuple[str, str]:
    if facts.system_error:
        return "FAILED", "SYSTEM_ERROR"
    if facts.llm_error:
        return "FAILED", "LLM_ERROR"
    if facts.output_invalid:
        return "FAILED", "OUTPUT_INVALID"
    if facts.blocked:
        return "PARTIAL", "BLOCKED_SAFETY"
    if facts.fallback:
        return "PARTIAL", "NO_EVIDENCE"
    if facts.tool_failed:
        return "PARTIAL", "TOOL_FAILED"
    if facts.citations_valid == 0:
        return "FAILED", "UNGROUNDED_ANSWER"
    some_invalid = facts.citations_valid < facts.citations_total
    if some_invalid or (facts.grounding_score is not None and facts.grounding_score < grounding_min):
        return "PARTIAL", "UNSUPPORTED_CLAIMS"
    return "SUCCESS", "OK_CONFLICT" if facts.conflict else "OK"


def confidence(outcome: str, top_score: float | None, relevance_high: float = 0.7) -> str | None:
    if outcome == "SUCCESS":
        return "HIGH" if top_score is not None and top_score >= relevance_high else "MEDIUM"
    if outcome == "PARTIAL":
        return "LOW"
    return None
