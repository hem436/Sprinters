"""X9 vector index in Qdrant (contract 10 section 9).

- Point id = uuid5(chunk_id), so indexing the same chunk again overwrites it.
- Payload = the chunk record without `text` (SQLite holds it; `index_text` is enough to read a point by hand).
- Payload indexes on doc_key, category, version, searchable, current and document_id.
- The collection stores the embedder name; a different embedder is refused (vectors must never mix).
- Local mode (a folder on disk, or ":memory:") needs no Docker; the same code talks to a Qdrant server.
"""
import logging
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models

from ingestion.embedding import Embedder
from ingestion.types import Hit

log = logging.getLogger(__name__)

KEYWORD_FIELDS = ("doc_key", "category", "version", "document_id")
BOOL_FIELDS = ("searchable", "current")
_EMBEDDER_MARK = "__embedder__"      # one point in the collection that records the embedder name


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


class VectorIndex:
    def __init__(self, embedder: Embedder, collection: str, url: str | None = None, api_key: str | None = None,
                 path: Path | str | None = None):
        self.server = bool(url)
        if url:
            self.client = QdrantClient(url=url, api_key=api_key)
        elif path is None or str(path) == ":memory:":
            self.client = QdrantClient(location=":memory:")
        else:
            Path(path).mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
        self.embedder = embedder
        self.collection = collection
        self._ready = False

    # ---- collection --------------------------------------------------------------------------------------------
    def ensure(self) -> None:
        if self._ready:
            return
        dim = self.embedder.dim
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(self.collection,
                                          vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
            if self.server:                    # local mode filters without indexes and warns if asked to make them
                for f in KEYWORD_FIELDS:
                    self.client.create_payload_index(self.collection, f, models.PayloadSchemaType.KEYWORD)
                for f in BOOL_FIELDS:
                    self.client.create_payload_index(self.collection, f, models.PayloadSchemaType.BOOL)
            self.client.upsert(self.collection, [models.PointStruct(
                id=point_id(_EMBEDDER_MARK), vector=[1.0] + [0.0] * (dim - 1),
                payload={"embedder": self.embedder.name, "searchable": False, "current": False})])
        else:
            marks = self.client.retrieve(self.collection, [point_id(_EMBEDDER_MARK)], with_payload=True)
            stored = marks[0].payload.get("embedder") if marks else None
            if stored and stored != self.embedder.name:
                raise RuntimeError(f"Collection '{self.collection}' holds vectors of '{stored}', not "
                                   f"'{self.embedder.name}'. Re-index into a new collection (index.collection).")
        self._ready = True

    def wipe(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self._ready = False

    # ---- writes ------------------------------------------------------------------------------------------------
    def upsert(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        self.ensure()
        vectors = self.embedder.embed_documents([c["index_text"] for c in chunks])
        points = [models.PointStruct(id=point_id(c["chunk_id"]), vector=v, payload=_payload(c))
                  for c, v in zip(chunks, vectors, strict=True)]
        for i in range(0, len(points), 256):
            self.client.upsert(self.collection, points[i:i + 256], wait=True)

    def delete_document(self, document_id: str) -> None:
        if not self.client.collection_exists(self.collection):
            return
        self.client.delete(self.collection, points_selector=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])), wait=True)

    def set_searchable(self, chunk_ids: list[str], searchable: bool) -> None:
        if chunk_ids and self.client.collection_exists(self.collection):
            self.client.set_payload(self.collection, {"searchable": searchable},
                                    points=[point_id(c) for c in chunk_ids], wait=True)

    def set_current(self, document_id: str, current: bool) -> None:
        if self.client.collection_exists(self.collection):
            self.client.set_payload(self.collection, {"current": current}, points=models.Filter(must=[
                models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]), wait=True)

    # ---- search ------------------------------------------------------------------------------------------------
    def search(self, query: str, k: int, filters: dict | None = None) -> list[Hit]:
        if not self.client.collection_exists(self.collection):
            return []
        self.ensure()
        vector = self.embedder.embed_query(query)
        resp = self.client.query_points(self.collection, query=vector, limit=k, with_payload=["chunk_id"],
                                        query_filter=qdrant_filter(filters))
        return [Hit(chunk_id=p.payload["chunk_id"], score=float(p.score), rank=i + 1)
                for i, p in enumerate(resp.points)]

    def count(self) -> int:
        if not self.client.collection_exists(self.collection):
            return 0
        return self.client.count(self.collection, count_filter=models.Filter(must=[
            models.FieldCondition(key="searchable", match=models.MatchValue(value=True))]), exact=True).count


def qdrant_filter(filters: dict | None) -> models.Filter:
    """Only searchable chunks (X7), plus the contract filters: category, doc_key, version, current_only."""
    must = [models.FieldCondition(key="searchable", match=models.MatchValue(value=True))]
    for key in ("category", "doc_key", "version"):
        value = (filters or {}).get(key)
        if value:
            match = models.MatchAny(any=list(value)) if isinstance(value, list | tuple) else models.MatchValue(value=value)
            must.append(models.FieldCondition(key=key, match=match))
    if (filters or {}).get("current_only"):
        must.append(models.FieldCondition(key="current", match=models.MatchValue(value=True)))
    return models.Filter(must=must)


def _payload(c: dict) -> dict:
    p = {k: v for k, v in c.items() if k != "text"}
    for key in ("searchable", "current", "injection_suspect", "pii_found"):
        p[key] = bool(p[key])
    if isinstance(p.get("block_types"), str):
        import json
        p["block_types"] = json.loads(p["block_types"])
    return p
