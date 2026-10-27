"""WP-AG3: rules H3, H4, C1 and config A against B (contracts 04, 11 section 8)."""
from decimal import Decimal

from agent.config import AgentConfig
from agent.numbers import numbers_in
from agent.retrieval import find_conflicts, retrieve, rrf_fuse
from agent.stubs import NullRecorder, StubSearch
from agent.types import Hit


def test_rrf_fusion_order():
    """A chunk ranked 2nd in both lists beats one ranked 1st in only one list: 2/(60+2) > 1/(60+1)."""
    vector = [Hit("a", 0.9, 1), Hit("b", 0.8, 2)]
    bm25 = [Hit("c", 12.0, 1), Hit("b", 9.0, 2)]
    fused = rrf_fuse([vector, bm25], k=60, top=3)
    assert [h.chunk_id for h in fused] == ["b", "a", "c"]
    assert abs(fused[0].score - 2 / 62) < 1e-12
    assert [h.rank for h in fused] == [1, 2, 3]


def test_exact_id_bm25_wins(corpus, table_reranker):
    """Vectors miss POL-HR-014; BM25 finds it, fusion keeps it, the reranker puts it first."""
    search = StubSearch(corpus,
                        vector=[Hit("c_v2_perdiem", 0.71, 1), Hit("c_v2_overrun", 0.70, 2)],
                        bm25=[Hit("c_sop_laptop", 14.2, 1)])
    result = retrieve("What does POL-HR-014 say about laptops?", None, AgentConfig(), search,
                      table_reranker({"POL-HR-014": 0.93}), NullRecorder())
    assert result.reranked[0].chunk.chunk_id == "c_sop_laptop"
    assert result.score_kind == "rerank" and result.top_score == 0.93


def test_config_a_is_vector_only(corpus, table_reranker):
    recorder = NullRecorder()
    search = StubSearch(corpus, vector=[Hit("c_v2_perdiem", 0.81, 1)], bm25=[Hit("c_sop_laptop", 14.2, 1)])
    result = retrieve("per diem", None, AgentConfig(config_id="A"), search, table_reranker({}), recorder)
    assert [s.chunk.chunk_id for s in result.reranked] == ["c_v2_perdiem"]
    assert result.score_kind == "cosine" and result.top_score == 0.81
    assert recorder.stages == ["retrieve_vector"]


def test_conflict_shows_both(corpus):
    """C1: v2.0 reached the top, v1.0 did not; the section of v1.0 is still fetched and the numbers differ."""
    conflicts = find_conflicts([corpus["c_v2_perdiem"]], StubSearch(corpus))
    assert len(conflicts) == 1
    assert [c.version for c in conflicts[0].versions] == ["2.0", "1.0"]     # newest effective date first


def test_same_numbers_not_conflict(corpus):
    """Both versions of 4.5 Overruns say the same thing, so there is no conflict to report."""
    assert find_conflicts([corpus["c_v2_overrun"]], StubSearch(corpus)) == []


def test_numbers_indian_grouping_and_brackets():
    assert numbers_in("spent ₹4,35,500 of ₹4,00,000, (1,234.50) loss, 108.9 %") == {
        Decimal("435500"), Decimal("400000"), Decimal("-1234.5"), Decimal("108.9")}
    assert numbers_in("FY2026-27 policy v2 for P-104") == {Decimal("27"), Decimal("104")}
