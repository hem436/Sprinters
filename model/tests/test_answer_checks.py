"""WP-AG4: rules A1 to A4, V1, V2, V3 and the outcome rules (contracts 04, 11 section 5)."""
import pytest

from agent.answer import build_evidence, build_prompt, parse_answer
from agent.config import AgentConfig
from agent.outcome import QueryFacts, classify, confidence
from agent.safety import PROMPT_CANARY
from agent.types import AnswerJSON, Claim, ScoredChunk, ToolResult
from agent.validate import check_citations, check_grounding

P104 = ToolResult("budget_status", "OK",
                  summary="P-104 TRAVEL FY2026-27: budget ₹4,00,000, spent ₹4,35,500, over by ₹35,500 (108.9 % used)")


def _evidence(corpus, *ids, tools=()):
    ranked = [ScoredChunk(corpus[i], 0.9) for i in ids]
    return build_evidence(ranked, [], list(tools), max_tokens=6000)


def test_evidence_tools_first_then_chunks(corpus):
    items = _evidence(corpus, "c_v2_overrun", tools=[P104])
    assert [e.id for e in items] == ["T1", "E1"]


def test_evidence_budget_drops_lowest_rank(corpus):
    ranked = [ScoredChunk(corpus["c_v2_perdiem"], 0.9), ScoredChunk(corpus["c_sop_laptop"], 0.5)]
    items = build_evidence(ranked, [], [], max_tokens=20)       # room for the first chunk only
    assert [e.chunk.chunk_id for e in items] == ["c_v2_perdiem"]


def test_prompt_tags_evidence_and_hides_canary_rule(corpus):
    system, user = build_prompt("Per diem in Mumbai?", [], _evidence(corpus, "c_v2_perdiem"))
    assert PROMPT_CANARY in system
    assert '<evidence id="E1" doc="Travel and Expense Policy" version="2.0" effective="2026-04-01" page="7"' in user


def test_parse_answer_and_schema_failure():
    ok = parse_answer('```json\n{"answer_markdown": "x", "claims": [{"text": "x", "citations": ["E1"]}]}\n```')
    assert ok.claims[0].citations == ["E1"]
    with pytest.raises(ValueError):
        parse_answer('{"answer": "missing the required field"}')


def test_citation_not_in_evidence_invalid():
    answer = AnswerJSON(answer_markdown="a", claims=[Claim(text="a", citations=["E1", "E9"])])
    cleaned, checks = check_citations(answer, {"E1", "T1"})
    assert cleaned.claims[0].citations == ["E1"]
    assert {(c.id, c.valid) for c in checks} == {("E1", True), ("E9", False)}


def test_grounding_number_mismatch(corpus):
    """11 section 10: "₹2,500" against cited text "₹2,000" is unsupported."""
    evidence = {e.id: e for e in _evidence(corpus, "c_v2_perdiem")}
    answer = AnswerJSON(answer_markdown="", claims=[Claim(text="Per diem for Mumbai is ₹2,500 a day.", citations=["E1"])])
    score, checks = check_grounding(answer, evidence)
    assert score == 0.0 and "numbers not in the cited text" in checks[0].reason


def test_grounding_accepts_same_value_written_differently(corpus):
    evidence = {e.id: e for e in _evidence(corpus, tools=[P104])}
    claim = Claim(text="Project P-104 has spent ₹435500 against its travel budget of ₹400000.", citations=["T1"])
    score, checks = check_grounding(AnswerJSON(answer_markdown="", claims=[claim]), evidence)
    assert score == 1.0, checks


def test_grounding_needs_word_overlap(corpus):
    evidence = {e.id: e for e in _evidence(corpus, "c_sop_laptop")}
    claim = Claim(text="Employees receive free lunches on Fridays.", citations=["E1"])
    score, checks = check_grounding(AnswerJSON(answer_markdown="", claims=[claim]), evidence)
    assert score == 0.0 and "word overlap" in checks[0].reason


@pytest.mark.parametrize("facts, expected", [
    (QueryFacts(system_error=True), ("FAILED", "SYSTEM_ERROR")),
    (QueryFacts(llm_failed=True), ("FAILED", "LLM_ERROR")),
    (QueryFacts(output_invalid=True), ("FAILED", "OUTPUT_INVALID")),
    (QueryFacts(blocked=True), ("PARTIAL", "BLOCKED_SAFETY")),
    (QueryFacts(conversational=True), ("SUCCESS", "OK_SMALLTALK")),
    (QueryFacts(fallback=True), ("PARTIAL", "NO_EVIDENCE")),
    (QueryFacts(tool_needed=True, tool_failed=True, citations_valid=1, citations_total=1, grounding_score=1.0),
     ("PARTIAL", "TOOL_FAILED")),
    (QueryFacts(citations_valid=0, citations_total=2), ("FAILED", "UNGROUNDED_ANSWER")),
    (QueryFacts(citations_valid=2, citations_total=2, grounding_score=0.5), ("PARTIAL", "UNSUPPORTED_CLAIMS")),
    (QueryFacts(citations_valid=1, citations_total=2, grounding_score=1.0), ("PARTIAL", "UNSUPPORTED_CLAIMS")),
    (QueryFacts(citations_valid=2, citations_total=2, grounding_score=1.0), ("SUCCESS", "OK")),
    (QueryFacts(citations_valid=2, citations_total=2, grounding_score=1.0, conflict=True), ("SUCCESS", "OK_CONFLICT")),
])
def test_outcome_order(facts, expected):
    assert classify(facts, AgentConfig()) == expected


def test_confidence():
    cfg = AgentConfig()
    assert confidence("SUCCESS", 0.93, "rerank", cfg) == "HIGH"
    assert confidence("SUCCESS", 0.5, "rerank", cfg) == "MEDIUM"
    assert confidence("SUCCESS", 0.75, "cosine", cfg) == "MEDIUM"      # config A needs 0.8 for HIGH
    assert confidence("PARTIAL", 0.99, "rerank", cfg) == "LOW"
