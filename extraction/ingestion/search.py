"""What the agent calls (Arka's SearchPort in model/agent/ports.py; contract 10 section 9).

    from ingestion.search import SearchService
    agent = Agent(search=SearchService(), ...)

- vector_search and bm25_search return `Hit(chunk_id, score, rank)`, ranks from 1, only searchable chunks (X7).
- Filters for both: category, doc_key, version (a value or a list), current_only (bool).
- get_chunks returns `Chunk` records (same fields as agent.types.Chunk), in any order.
- get_section_versions returns the same section in every live version of a document (conflict rule C1).
"""
from ingestion.store import to_chunk
from ingestion.types import Chunk, Hit


class SearchService:
    def __init__(self, knowledge=None):
        self._k = knowledge

    @property
    def k(self):
        if self._k is None:
            from ingestion.service import get_default
            self._k = get_default()
        return self._k

    def vector_search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]:
        return self.k.vector.search(query, k, filters)

    def bm25_search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]:
        self.k.ensure_bm25()
        return self.k.bm25.search(query, k, filters)

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        return [to_chunk(r) for r in self.k.store.chunks_by_ids(list(chunk_ids))]

    def get_section_versions(self, doc_key: str, section: str) -> list[Chunk]:
        return [to_chunk(r) for r in self.k.store.section_chunks(doc_key, section)]

    def get_chunk_records(self, chunk_ids: list[str]) -> list[dict]:
        """The full chunk records (category, quality, searchable, current, block types, index_text) for the
        drill-down; the agent needs only get_chunks."""
        return self.k.store.chunks_by_ids(list(chunk_ids))


_default = SearchService()


def vector_search(query: str, k: int, filters: dict | None = None) -> list[Hit]:
    return _default.vector_search(query, k, filters)


def bm25_search(query: str, k: int, filters: dict | None = None) -> list[Hit]:
    return _default.bm25_search(query, k, filters)


def get_chunks(chunk_ids: list[str]) -> list[Chunk]:
    return _default.get_chunks(chunk_ids)


def get_section_versions(doc_key: str, section: str) -> list[Chunk]:
    return _default.get_section_versions(doc_key, section)
