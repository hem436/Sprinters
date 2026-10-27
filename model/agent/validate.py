"""Checks V1 and V2 (contract 04, contract 11 section 6): are the citations real, and are the claims supported?"""
import datetime
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
    items = [evidence[c] for c in claim.citations if c in evidence]
    if not items:
        return ClaimCheck(claim.text, claim.citations, False, "no valid citation")
    text = normalise(claim.text)
    # numbers: only the cited passages count. The claim may name the version, date, page or section of its tag, but
    # those are taken out first, so "page 3" or "version 2.0" never grounds "3 laptops" (review #25, fourth)
    passages = normalise(" ".join(e.text for e in items))
    missing = numbers_in(_without_tag_refs(text, items)) - numbers_in(passages)
    if missing:
        return ClaimCheck(claim.text, claim.citations, False, f"numbers not in the cited text: {sorted(map(str, missing))}")
    cited = normalise(" ".join(cited_text(e) for e in items))
    words = _stems(text)
    overlap = len(words & _stems(cited)) / len(words) if words else 1.0
    if overlap < MIN_WORD_OVERLAP:
        return ClaimCheck(claim.text, claim.citations, False, f"word overlap {overlap:.2f} below {MIN_WORD_OVERLAP}")
    return ClaimCheck(claim.text, claim.citations, True, "supported")


def cited_text(e: Evidence) -> str:
    """What a claim may rely on: the passage and the facts in its evidence tag (title, version, effective date, page,
    section). Found in the first live run: "₹2,000 (version 2.0, effective 2026-04-01)" quotes the tag, not the text."""
    if e.chunk is None:
        return e.text
    c = e.chunk
    return f"{c.title} version {c.version} effective {c.effective_date} page {c.page} section {c.section} {e.text}"


def _without_tag_refs(text: str, items: list[Evidence]) -> str:
    """The claim without the tag facts it names, in the forms a model writes them (review #25, fourth and fifth):
    "version 2.0" or "version 2", the effective date as "2026-04-01" or "1 April 2026", "page 3", "section 4.2", and
    the id-like words of the title and section ("POL-HR-014"). Only these exact facts are taken out."""
    for e in items:
        c = e.chunk
        if c is None:
            continue
        version = str(c.version)
        versions = {version, version[:-2]} if version.endswith(".0") else {version}
        refs = [rf"\b(?:version|ver\.?|v)\s*(?:{'|'.join(map(re.escape, versions))})(?!\d|\.\d)"]
        refs += [re.escape(d) for d in _date_forms(str(c.effective_date))]
        if c.page is not None:
            refs.append(rf"\b(?:page|p\.)\s*{c.page}(?!\d)")
        refs += [rf"\b(?:section|sec\.?|§)\s*{re.escape(n)}(?!\d|\.\d)"
                 for n in re.findall(r"(?:^|>)\s*(\d+(?:\.\d+)*)", str(c.section or ""))]
        refs += [rf"(?<![\w-]){re.escape(w)}(?![\w-])"
                 for w in re.findall(r"[A-Za-z][\w-]*\d[\w-]*", f"{c.title} {c.section}")]
        for ref in refs:
            text = re.sub(ref, " ", text, flags=re.IGNORECASE)
    return text


def _date_forms(iso: str) -> list[str]:
    """2026-04-01 as a model may write it: 1 April 2026, 1 Apr 2026, April 1, 2026, 01/04/2026."""
    try:
        d = datetime.date.fromisoformat(iso)
    except ValueError:
        return [iso]
    month, short = d.strftime("%B"), d.strftime("%b")
    return [iso, f"{d.day} {month} {d.year}", f"{d.day} {short} {d.year}", f"{month} {d.day}, {d.year}",
            f"{short} {d.day}, {d.year}", f"{d.day:02d}/{d.month:02d}/{d.year}", f"{d.day}/{d.month}/{d.year}"]


# Models write non-breaking and typographic hyphens ("P‑104", "FY2026‑27"); compare them as "-" (first live run).
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"} | {" ": " ", " ": " "})
# Light stemming that anyone can check by hand: cut one common ending, then a final "e". It replaced 4-letter
# prefixes, which joined unrelated words such as approval and approximately (review #25, fourth).
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ions", "ion", "ies", "ied", "ed", "es", "s", "ly")
_IRREGULAR = {"spent": "spend", "paid": "pay"}
MIN_STEM = 4


def normalise(text: str) -> str:
    return text.translate(_DASHES)


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in _STOPWORDS}


def stem(word: str) -> str:
    """"spending", "spends" and "spent" give "spend"; "policies" gives "policy"; "approval" stays apart from
    "approximately"."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if re.search(r"(?:s|x|z|ch|sh)es$", word) and len(word) > 4:      # taxes, patches: the plural "es"
        word = word[:-2]
    else:
        for suffix in _SUFFIXES:
            if suffix in ("es", "s"):
                continue
            if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
                word = word[:-len(suffix)] + ("y" if suffix in ("ies", "ied") else "")
                break
        else:
            if word.endswith("s") and not word.endswith("ss") and len(word) > 3:   # uses, laptops: a plain plural
                word = word[:-1]
    return word[:-1] if word.endswith("e") and len(word) > MIN_STEM else word


def _stems(text: str) -> set[str]:
    """Content words as stems, so another form of the same word still counts."""
    return {stem(w) for w in _content_words(text)}
