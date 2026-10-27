"""Rules H1 to H4 and C1 (contract 04): hybrid search, fusion, rerank, and version conflicts."""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from agent.config import AgentConfig
from agent.numbers import numbers_in
from agent.ports import RecorderPort, RerankerPort, SearchPort
from agent.types import Chunk, Hit, ScoredChunk


@dataclass(frozen=True)
class RetrievalResult:
    vector: list[Hit]
    bm25: list[Hit]
    fused: list[Hit]
    reranked: list[ScoredChunk]
    score_kind: Literal["rerank", "cosine"]

    @property
    def top_score(self) -> float:
        return self.reranked[0].score if self.reranked else 0.0


@dataclass(frozen=True)
class Conflict:
    """C1: one section of one document whose versions give different numbers. Newest effective date first."""
    doc_key: str
    section: str
    versions: list[Chunk] = field(default_factory=list)


def rrf_fuse(lists: list[list[Hit]], k: int, top: int) -> list[Hit]:
    """04 H3: Reciprocal Rank Fusion, score = sum of 1 / (k + rank). Uses ranks only, so BM25 and cosine scales never mix."""
    scores: dict[str, float] = defaultdict(float)
    best_rank: dict[str, int] = {}
    for hits in lists:
        for hit in hits:
            scores[hit.chunk_id] += 1.0 / (k + hit.rank)
            best_rank[hit.chunk_id] = min(hit.rank, best_rank.get(hit.chunk_id, hit.rank))
    # ties: the better single rank first, then the id, so the order never depends on dict order
    order = sorted(scores, key=lambda c: (-scores[c], best_rank[c], c))[:top]
    return [Hit(chunk_id=c, score=scores[c], rank=i + 1) for i, c in enumerate(order)]


def rerank(query: str, chunks: list[Chunk], top_n: int, reranker: RerankerPort) -> list[ScoredChunk]:
    """04 H4: score each fused chunk against the question with the cross-encoder; keep the best top_n."""
    if not chunks:
        return []
    scores = reranker.score(query, [c.text for c in chunks])
    ranked = sorted(zip(chunks, scores), key=lambda pair: -pair[1])   # stable: equal scores keep the fused order
    return [ScoredChunk(chunk, score) for chunk, score in ranked[:top_n]]


def retrieve(query: str, filters: dict | None, cfg: AgentConfig, search: SearchPort,
             reranker: RerankerPort, recorder: RecorderPort) -> RetrievalResult:
    """04 H1 to H4. Config A (11 section 8): vector top 5 only. Config B: vector + BM25, RRF, rerank."""
    if cfg.config_id == "A":
        with recorder.stage("retrieve_vector"):
            vector = search.vector_search(query, cfg.ret_rerank_top_n, filters)
        recorder.hits("vector", vector)
        chunks = _in_order(search, vector)
        return RetrievalResult(vector, [], [], [ScoredChunk(c, h.score) for c, h in zip(chunks, vector)], "cosine")

    with recorder.stage("retrieve_vector"):
        vector = search.vector_search(query, cfg.ret_vector_k, filters)
    with recorder.stage("retrieve_bm25"):
        bm25 = search.bm25_search(query, cfg.ret_bm25_k, filters)
    with recorder.stage("fuse"):
        fused = rrf_fuse([vector, bm25], cfg.ret_rrf_k, cfg.ret_fused_k)
    with recorder.stage("rerank"):
        reranked = rerank(query, _in_order(search, fused), cfg.ret_rerank_top_n, reranker)
    for name, hits in (("vector", vector), ("bm25", bm25), ("fused", fused)):
        recorder.hits(name, hits)
    recorder.hits("reranked", [Hit(s.chunk.chunk_id, s.score, i + 1) for i, s in enumerate(reranked)])
    return RetrievalResult(vector, bm25, fused, reranked, "rerank")


def find_conflicts(top: list[Chunk], search: SearchPort) -> list[Conflict]:
    """04 C1: for each top chunk, fetch the same section in every version of its document.

    A conflict is reported only when the versions give different numbers; two versions with the same facts are not a
    conflict. Fetching the other versions catches a version that did not reach the top 5 (gap G6).
    """
    conflicts = []
    seen = set()
    for chunk in top:
        key = (chunk.doc_key, chunk.section)
        if key in seen:
            continue
        seen.add(key)
        by_version = _one_text_per_version(search.get_section_versions(chunk.doc_key, chunk.section))
        if len(by_version) < 2:
            continue
        if len({frozenset(numbers_in(c.text)) for c in by_version}) > 1:
            conflicts.append(Conflict(chunk.doc_key, chunk.section, by_version))
    return conflicts


def _one_text_per_version(chunks: list[Chunk]) -> list[Chunk]:
    """Join a section's chunks per version; newest effective date first."""
    grouped: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        grouped[c.version].append(c)
    merged = []
    for parts in grouped.values():
        first = parts[0]
        text = "\n".join(p.text for p in parts)
        merged.append(Chunk(first.chunk_id, first.document_id, first.doc_key, first.title, first.version,
                            first.effective_date, first.page, first.section, first.method, text, first.injection_suspect))
    return sorted(merged, key=lambda c: c.effective_date, reverse=True)


def _in_order(search: SearchPort, hits: list[Hit]) -> list[Chunk]:
    """get_chunks may return in any order; keep the ranked order of the hits."""
    by_id = {c.chunk_id: c for c in search.get_chunks([h.chunk_id for h in hits])}
    return [by_id[h.chunk_id] for h in hits if h.chunk_id in by_id]


class FlashRankReranker:
    """H4 with FlashRank (ms-marco MiniLM, local ONNX), as in the team's chatbot repo. Imported only when used."""

    def __init__(self, cache_dir: str | None = None):
        from flashrank import Ranker   # optional dependency: ~50 MB, so not loaded at import time
        self._ranker = Ranker(cache_dir=cache_dir) if cache_dir else Ranker()

    def score(self, query: str, texts: list[str]) -> list[float]:
        from flashrank import RerankRequest
        results = self._ranker.rerank(RerankRequest(query=query, passages=[{"id": i, "text": t} for i, t in enumerate(texts)]))
        by_id = {int(r["id"]): float(r["score"]) for r in results}
        return [by_id.get(i, 0.0) for i in range(len(texts))]
