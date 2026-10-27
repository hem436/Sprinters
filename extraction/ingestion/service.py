"""The services Sinngam's routes call (contract 01 section 3, contract 05 document endpoints).

Each function returns a dict (the JSON body) or raises `IngestError` with the contract's code and HTTP status.

    from ingestion import service
    service.submit_document("/tmp/upload.pdf", {"title": ..., "category": ..., "version": ..., "effective_date": ...},
                            file_name="policy.pdf", uploaded_by="admin")

`Knowledge` holds the parts (config, store, indexes, OCR, jobs). The module functions use one default instance built
from the environment; tests build their own with fakes.
"""
import json
import logging
import shutil
import threading
from pathlib import Path

from ingestion import errors
from ingestion.config import ExtractConfig, load_config
from ingestion.index_bm25 import BM25Index
from ingestion.index_vector import VectorIndex
from ingestion.jobs import JobQueue
from ingestion.ocr import OcrEngine
from ingestion.pipeline import run_document
from ingestion.store import KnowledgeStore, now
from ingestion.validate import validate_file

log = logging.getLogger(__name__)

LIVE = ("INDEXED", "PARTIAL_REVIEW", "SUPERSEDED")


class Knowledge:
    def __init__(self, cfg: ExtractConfig, store: KnowledgeStore, vector: VectorIndex, ocr: OcrEngine | None,
                 jobs: JobQueue | None = None):
        self.cfg = cfg
        self.store = store
        self.vector = vector
        self.ocr = ocr
        self.jobs = jobs or JobQueue()
        self.bm25 = BM25Index()
        self._bm25_built = False
        self._bm25_lock = threading.Lock()

    # ---- indexes ------------------------------------------------------------------------------------------------
    def rebuild_bm25(self) -> int:
        with self._bm25_lock:
            n = self.bm25.rebuild(self.store.index_rows())
            self._bm25_built = True
            return n

    def ensure_bm25(self) -> None:
        if not self._bm25_built:
            self.rebuild_bm25()

    def apply_versions(self, doc_key: str) -> None:
        """Contract 03: the version with the latest effective date is current; an older INDEXED one is SUPERSEDED.
        Superseded chunks stay searchable with current = false, so conflict rule C1 still sees them."""
        versions = self.store.versions_of(doc_key)
        for i, d in enumerate(versions):
            is_current = i == 0
            self.store.set_chunks_current(d["document_id"], is_current)
            self.vector.set_current(d["document_id"], is_current)
            if not is_current and d["status"] == "INDEXED":
                self.store.update_document(d["document_id"], status="SUPERSEDED")
            elif is_current and d["status"] == "SUPERSEDED":
                # the newer version was deleted: the older one is current again
                self.store.update_document(d["document_id"], status="INDEXED")

    def resume_pending(self) -> int:
        """After a restart: queue again every document left QUEUED or EXTRACTING."""
        pending = [d for d in self.store.list_documents() if d["status"] in ("QUEUED", "EXTRACTING")]
        for d in pending:
            self.store.update_document(d["document_id"], status="QUEUED")
            self._queue(d["document_id"], d["file_name"])
        return len(pending)

    def _queue(self, document_id: str, file_name: str) -> str:
        return self.jobs.submit(document_id, file_name, lambda progress: run_document(self, document_id, progress))

    # ---- X1 and upload ------------------------------------------------------------------------------------------
    def submit_document(self, file_path: str | Path, meta: dict, file_name: str | None = None,
                        uploaded_by: str = "admin") -> dict:
        """POST /documents: validate (X1), keep a copy of the file, queue the job. 202 body."""
        file_path = Path(file_path)
        file_name = file_name or file_path.name
        valid = validate_file(file_path, file_name, meta, self.cfg)
        existing = self.store.find_by_hash(valid.content_hash)
        if existing:
            raise errors.duplicate_document(existing["document_id"], existing["title"])

        document_id = "doc_" + valid.content_hash[:8]
        self.cfg.files_dir.mkdir(parents=True, exist_ok=True)
        stored = self.cfg.files_dir / f"{document_id}.{valid.file_type}"
        shutil.copyfile(file_path, stored)
        self.store.insert_document({
            "document_id": document_id, **valid.meta, "file_name": file_name, "file_type": valid.file_type,
            "size_bytes": valid.size_bytes, "content_hash": valid.content_hash, "status": "QUEUED",
            "page_count": valid.page_count or None, "uploaded_by": uploaded_by, "uploaded_at": now(),
            "stored_path": str(stored),
        })
        job_id = self._queue(document_id, file_name)
        status = self.store.get_document(document_id)["status"]
        return {"document_id": document_id, "job_id": job_id, "status": "QUEUED" if not self.jobs.inline else status}

    # ---- reads --------------------------------------------------------------------------------------------------
    def list_documents(self, category: str | None = None, status: str | None = None) -> list[dict]:
        """GET /documents: status, pages, chunks and OCR cost per document."""
        keys = ("document_id", "doc_key", "title", "category", "version", "effective_date", "file_name", "file_type",
                "size_bytes", "status", "page_count", "chunk_count", "ocr_cost_usd", "uploaded_by", "uploaded_at",
                "indexed_at", "error")
        out = []
        for d in self.store.list_documents(category, status):
            row = {k: d[k] for k in keys}
            row["pages_need_review"] = sum(1 for p in self.store.get_pages(d["document_id"])
                                           if p["status"] == "NEEDS_REVIEW")
            out.append(row)
        return out

    def get_document(self, document_id: str) -> dict:
        """GET /documents/{id}: the document and its ExtractionReport."""
        d = self._doc(document_id)
        out = {k: v for k, v in d.items() if k not in ("report_json", "stored_path", "content_hash")}
        out["report"] = self.get_report(document_id)
        return out

    def get_report(self, document_id: str) -> dict | None:
        """The ExtractionReport, with page statuses as they are now (after reviews)."""
        d = self._doc(document_id)
        if not d["report_json"]:
            return None
        report = json.loads(d["report_json"])
        current = {p["page"]: p for p in self.store.get_pages(document_id)}
        for entry in report["pages"]:
            p = current.get(entry["page"])
            if p:
                entry["status"] = p["status"]
                if p.get("reviewed_by"):
                    entry["reviewed_by"], entry["reviewed_at"] = p["reviewed_by"], p["reviewed_at"]
        report["status"] = d["status"]
        report["searchable_chunks"] = sum(1 for c in self.store.chunk_rows(document_id) if c["searchable"])
        return report

    def get_page(self, document_id: str, page: int) -> dict:
        """GET /documents/{id}/pages/{n}: text, class, method, quality, flags, status, image_url."""
        d = self._doc(document_id)
        p = self.store.get_page(document_id, page)
        if p is None:
            raise errors.not_found(f"Page {page} of {document_id}")
        p["image_url"] = (f"/documents/{document_id}/pages/{page}/image"
                          if d["file_type"] in ("pdf", "png", "jpg", "tif", "webp") else None)
        p["chunks"] = [{"chunk_id": c["chunk_id"], "section": c["section"], "searchable": c["searchable"],
                        "injection_suspect": c["injection_suspect"]}
                       for c in self.store.chunk_rows(document_id, page)]
        return p

    def page_image(self, document_id: str, page: int, max_edge: int = 1400) -> bytes:
        """GET /documents/{id}/pages/{n}/image: a PNG of the page, for the review screen."""
        import io

        from PIL import Image

        from ingestion.ocr import prepare_image, render_pdf_page

        d = self._doc(document_id)
        if self.store.get_page(document_id, page) is None:
            raise errors.not_found(f"Page {page} of {document_id}")
        if d["file_type"] == "pdf":
            img = render_pdf_page(d["stored_path"], page, max_edge)
        elif d["file_type"] in ("png", "jpg", "tif", "webp"):
            with Image.open(d["stored_path"]) as raw:
                img = prepare_image(raw, max_edge)
        else:
            raise errors.not_found(f"An image of a {d['file_type']} section")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def list_jobs(self) -> list[dict]:
        """GET /jobs: each job with stage, done and total."""
        return self.jobs.list()

    # ---- X7 review and lifecycle --------------------------------------------------------------------------------
    def review_page(self, document_id: str, page: int, decision: str, admin: str, comment: str | None = None) -> dict:
        """POST /documents/{id}/pages/{n}/review. Only a page in NEEDS_REVIEW can move (contract 03)."""
        decision = (decision or "").upper()
        if decision not in ("APPROVE", "REJECT"):
            raise errors.IngestError("INVALID_DECISION", 422, "decision must be APPROVE or REJECT")
        d = self._doc(document_id)
        p = self.store.get_page(document_id, page)
        if p is None:
            raise errors.not_found(f"Page {page} of {document_id}")
        if p["status"] != "NEEDS_REVIEW" or d["status"] not in LIVE:
            raise errors.illegal_move(f"Page {page} is {p['status']} in a {d['status']} document; only a page in "
                                      "NEEDS_REVIEW can be approved or rejected.")
        new_status = "APPROVED" if decision == "APPROVE" else "REJECTED"
        self.store.update_page(document_id, page, status=new_status, reviewed_by=admin, reviewed_at=now(),
                               review_comment=comment)
        chunk_ids = self.store.set_chunks_searchable(document_id, page, decision == "APPROVE")
        self.vector.set_searchable(chunk_ids, decision == "APPROVE")
        if d["status"] == "PARTIAL_REVIEW" and not any(x["status"] == "NEEDS_REVIEW"
                                                       for x in self.store.get_pages(document_id)):
            self.store.update_document(document_id, status="INDEXED")
            self.apply_versions(d["doc_key"])
        self.rebuild_bm25()
        return self.get_page(document_id, page)

    def reindex(self, document_id: str) -> dict:
        """POST /documents/{id}/reindex (also the retry of a FAILED document). Same chunk ids, so no duplicates.
        Page reviews are reset: the pages are read again and may come out different."""
        d = self._doc(document_id)
        if d["status"] in ("QUEUED", "EXTRACTING", "DELETED"):
            raise errors.illegal_move(f"A {d['status']} document cannot be re-indexed.")
        self.store.update_document(document_id, status="QUEUED")
        job_id = self._queue(document_id, d["file_name"])
        return {"document_id": document_id, "job_id": job_id, "status": "QUEUED"}

    def delete_document(self, document_id: str) -> None:
        """DELETE /documents/{id}: chunks and vectors removed; the row stays for history."""
        d = self._doc(document_id)
        if d["status"] in ("QUEUED", "EXTRACTING", "DELETED"):
            raise errors.illegal_move(f"A {d['status']} document cannot be deleted now.")
        self.vector.delete_document(document_id)
        self.store.delete_chunks(document_id)
        self.store.update_document(document_id, status="DELETED", chunk_count=0)
        self.apply_versions(d["doc_key"])
        self.rebuild_bm25()

    def _doc(self, document_id: str) -> dict:
        d = self.store.get_document(document_id)
        if d is None:
            raise errors.not_found(f"Document {document_id}")
        return d


# ---- the default instance -------------------------------------------------------------------------------------------

_default: Knowledge | None = None
_default_lock = threading.Lock()


def build(cfg: ExtractConfig | None = None, inline: bool = False) -> Knowledge:
    """Real parts from the environment: Gemini OCR and embeddings, Qdrant (server if QDRANT_URL, else local folder)."""
    from ingestion.embedding import default_embedder
    from ingestion.ocr import GeminiOCR

    cfg = cfg or load_config()
    store = KnowledgeStore(cfg.db_path)
    vector = VectorIndex(default_embedder(cfg), cfg.collection, url=cfg.qdrant_url, api_key=cfg.qdrant_api_key,
                         path=cfg.qdrant_path)
    return Knowledge(cfg, store, vector, GeminiOCR(cfg), JobQueue(inline=inline))


def get_default() -> Knowledge:
    global _default
    with _default_lock:
        if _default is None:
            _default = build()
            _default.resume_pending()
        return _default


def set_default(k: Knowledge | None) -> None:
    """Tests and scripts can install their own instance."""
    global _default
    with _default_lock:
        _default = k


def submit_document(file_path, meta: dict, file_name: str | None = None, uploaded_by: str = "admin") -> dict:
    return get_default().submit_document(file_path, meta, file_name, uploaded_by)


def list_documents(category: str | None = None, status: str | None = None) -> list[dict]:
    return get_default().list_documents(category, status)


def get_document(document_id: str) -> dict:
    return get_default().get_document(document_id)


def get_report(document_id: str) -> dict | None:
    return get_default().get_report(document_id)


def get_page(document_id: str, page: int) -> dict:
    return get_default().get_page(document_id, page)


def page_image(document_id: str, page: int) -> bytes:
    return get_default().page_image(document_id, page)


def review_page(document_id: str, page: int, decision: str, admin: str, comment: str | None = None) -> dict:
    return get_default().review_page(document_id, page, decision, admin, comment)


def reindex(document_id: str) -> dict:
    return get_default().reindex(document_id)


def delete_document(document_id: str) -> None:
    get_default().delete_document(document_id)


def list_jobs() -> list[dict]:
    return get_default().list_jobs()
