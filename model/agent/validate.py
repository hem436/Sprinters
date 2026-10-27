"""Checks V1 and V2 (contract 04, contract 11 section 6): are the citations real, and are the claims supported?"""
import re
from dataclasses import dataclass

from agent.numbers import numbers_in
from agent.types import AnswerJSON, Claim, Evidence

# Words that carry no meaning for the overlap check.
_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "from", "has", "have", "had", "not", "but",
    "its", "per", "any", "all", "can", "may", "must", "will", "shall", "under", "into", "than", "then", "there",
    "their", "which", "what", "when", "who", "whom", "also", "only", "each", "every", "a", "an", "of", "to", "in",
    "is", "on", "by", "be", "as", "at", "or", "it", "day", "days",
}
MIN_WORD_OVERLAP = 0.5      # 11 section 6: at least half of a claim's content words must be in its cited text


@dataclass(frozen=True)
class CitationCheck:
    id: str
    valid: bool
    reason: str


@dataclass(frozen=True)
class ClaimCheck:
    text: str
    citations: list[str]
    supported: bool
    reason: str


def check_citations(answer: AnswerJSON, evidence_ids: set[str]) -> tuple[AnswerJSON, list[CitationCheck]]:
    """04 V1: an id that is not in this query's evidence is removed from its claim and counted invalid."""
    checks: dict[str, CitationCheck] = {}
    claims = []
    for claim in answer.claims:
        kept = []
        for cid in claim.citations:
            valid = cid in evidence_ids
            checks.setdefault(cid, CitationCheck(cid, valid, "in evidence" if valid else "not in this query's evidence"))
            if valid:
                kept.append(cid)
        claims.append(Claim(text=claim.text, citations=kept))
    return answer.model_copy(update={"claims": claims}), list(checks.values())


def check_grounding(answer: AnswerJSON, evidence: dict[str, Evidence]) -> tuple[float, list[ClaimCheck]]:
    """04 V2, 11 section 6: a claim is supported when it has a valid citation, every number in it appears in the
    cited text (as a value: 4,35,500 = 435500), and at least half of its content words appear there.

    Returns the share of supported claims and the detail per claim (stored as `grounding_detail`).
    """
    if not answer.claims:
        return 0.0, []
    checks = [_check_claim(c, evidence) for c in answer.claims]
    return sum(c.supported for c in checks) / len(checks), checks


def _check_claim(claim: Claim, evidence: dict[str, Evidence]) -> ClaimCheck:
    cited = " ".join(evidence[c].text for c in claim.citations if c in evidence)
    if not cited:
        return ClaimCheck(claim.text, claim.citations, False, "no valid citation")
    missing = numbers_in(claim.text) - numbers_in(cited)
    if missing:
        return ClaimCheck(claim.text, claim.citations, False, f"numbers not in the cited text: {sorted(map(str, missing))}")
    words = _content_words(claim.text)
    overlap = len(words & _content_words(cited)) / len(words) if words else 1.0
    if overlap < MIN_WORD_OVERLAP:
        return ClaimCheck(claim.text, claim.citations, False, f"word overlap {overlap:.2f} below {MIN_WORD_OVERLAP}")
    return ClaimCheck(claim.text, claim.citations, True, "supported")


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in _STOPWORDS}
