"""X9 BM25 index (contract 10 section 9), rebuilt from the `chunk` table after each ingest job or review.

- Built from `index_text` of searchable chunks with rank_bm25. The corpus is small, so a rebuild takes seconds.
- The tokenizer keeps IDs whole: `[A-Za-z0-9]+(?:[-_/.][A-Za-z0-9]+)*`, lower-cased, so POL-HR-014, FY2025-26
  and 4.2 stay single tokens (case scenario "exact ID or acronym").
- IDF is the Lucene form log(1 + (N - n + 0.5) / (n + 0.5)). It is always positive. The classic Okapi form gives 0
  or less to a term in half of a small corpus, so an exact ID could score 0 with only 2 chunks.
"""
import math
import re
import threading

from rank_bm25 import BM25Okapi

from ingestion.types import Hit

TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_/.][A-Za-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text)]


class _LuceneBM25(BM25Okapi):
    def _calc_idf(self, nd):
        self.idf = {w: math.log(1 + (self.corpus_size - n + 0.5) / (n + 0.5)) for w, n in nd.items()}


class BM25Index:
    """In memory. `rebuild` swaps the whole index at once, so a search never sees a half-built one."""

    def __init__(self):
        self._lock = threading.Lock()
        self._bm25: _LuceneBM25 | None = None
        self._meta: list[dict] = []

    def rebuild(self, chunks: list[dict]) -> int:
        """`chunks`: searchable chunk rows with chunk_id, index_text, category, doc_key, version, current."""
        docs = [c for c in chunks if c.get("searchable", True)]
        meta = [{k: c.get(k) for k in ("chunk_id", "category", "doc_key", "version", "current")} for c in docs]
        bm25 = _LuceneBM25([tokenize(c["index_text"]) for c in docs]) if docs else None
        with self._lock:
            self._bm25, self._meta = bm25, meta
        return len(docs)

    def search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]:
        with self._lock:
            bm25, meta = self._bm25, self._meta
        terms = tokenize(query)
        if bm25 is None or not terms:
            return []
        scores = bm25.get_scores(terms)
        ranked = sorted((i for i, s in enumerate(scores) if s > 0 and _passes(meta[i], filters)),
                        key=lambda i: (-scores[i], meta[i]["chunk_id"]))[:k]
        return [Hit(chunk_id=meta[i]["chunk_id"], score=float(scores[i]), rank=r + 1) for r, i in enumerate(ranked)]

    @property
    def size(self) -> int:
        return len(self._meta)


def _passes(m: dict, filters: dict | None) -> bool:
    if not filters:
        return True
    for key in ("category", "doc_key", "version"):
        want = filters.get(key)
        if want:
            allowed = set(want) if isinstance(want, list | tuple) else {want}
            if m.get(key) not in allowed:
                return False
    return not (filters.get("current_only") and not m.get("current"))
