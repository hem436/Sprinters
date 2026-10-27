"""One document from file to searchable chunks: X2 to X9, then the ExtractionReport (contract 10 sections 2 and 8).

Order of writes: SQLite first (the source of truth), then Qdrant, then the BM25 rebuild. If Qdrant fails, the job
fails and the document's points are removed again, so the two stores never disagree for long.
"""
import json
import logging
import time
from decimal import Decimal
from pathlib import Path

from ingestion.chunker import chunk_document
from ingestion.loaders.docx import extract_docx
from ingestion.loaders.image import extract_image
from ingestion.loaders.pdf import extract_pdf
from ingestion.loaders.text import extract_text
from ingestion.quality import score_page
from ingestion.store import now
from ingestion.types import PageResult

log = logging.getLogger(__name__)


def extract_pages(path: Path | str, file_type: str, k, progress=None) -> list[PageResult]:
    """X2 split and X3 to X5, by file type."""
    if file_type == "pdf":
        return extract_pdf(path, k.cfg, k.ocr, progress)
    if file_type in ("png", "jpg", "tif", "webp"):
        return extract_image(path, k.cfg, k.ocr, progress)
    if file_type == "docx":
        return extract_docx(path, progress)
    if file_type == "txt":
        return extract_text(path, progress)
    raise ValueError(f"no loader for file type {file_type}")


def run_document(k, document_id: str, progress=None) -> dict:
    """Extract, score, chunk and index one QUEUED document. Returns the ExtractionReport."""
    store = k.store
    doc = store.get_document(document_id)
    started = time.monotonic()
    store.update_document(document_id, status="EXTRACTING", error=None)
    try:
        pages = extract_pages(doc["stored_path"], doc["file_type"], k, progress)
        for p in pages:
            score_page(p, k.cfg)
        if progress:
            progress("indexing", 0, 1)
        chunks = chunk_document(doc, pages, k.cfg)
        page_rows = [_page_row(document_id, p) for p in pages]

        k.vector.delete_document(document_id)                 # re-index: old points go first
        store.replace_pages_and_chunks(document_id, page_rows, chunks)
        try:
            k.vector.upsert(chunks)
        except Exception:
            k.vector.delete_document(document_id)
            raise

        readable = [p for p in pages if p.blocks]
        if not readable:
            status = "FAILED"
        elif any(p.status == "NEEDS_REVIEW" for p in pages):
            status = "PARTIAL_REVIEW"
        else:
            status = "INDEXED"
        report = _report(document_id, status, pages, chunks, k, int((time.monotonic() - started) * 1000))
        store.update_document(document_id, status=status, page_count=len(pages), chunk_count=len(chunks),
                              ocr_cost_usd=report["ocr_cost_usd"], indexed_at=now(), report_json=json.dumps(report),
                              error=None if status != "FAILED" else "No page could be read.")
        k.apply_versions(doc["doc_key"])
        k.rebuild_bm25()
        if progress:
            progress("indexing", 1, 1)
        return report
    except Exception as e:
        log.exception("ingest failed for %s", document_id)
        store.update_document(document_id, status="FAILED", error=str(e)[:400])
        raise


def _page_row(document_id: str, p: PageResult) -> dict:
    ocr = None
    if p.ocr is not None:
        ocr = {"model": p.ocr.model, "input_tokens": p.ocr.input_tokens, "output_tokens": p.ocr.output_tokens,
               "latency_ms": p.ocr.latency_ms, "cost_usd": p.ocr.cost_usd, "prompt_version": p.ocr.prompt_version,
               "attempts": p.ocr.attempts}
    return {"document_id": document_id, "page": p.page, "printed_page": p.printed_page,
            "section_label": p.section_label, "class": p.page_class, "method": p.method or "none",
            "quality": p.quality, "flags": json.dumps(p.flags), "status": p.status, "text": p.text,
            "ocr_json": json.dumps(ocr) if ocr else None}


def _report(document_id: str, status: str, pages: list[PageResult], chunks: list[dict], k, duration_ms: int) -> dict:
    """The ExtractionReport of contract 10 section 8 (P1 to P3 and P4)."""
    out_pages = []
    costs: list[str | None] = []
    for p in pages:
        entry = {"page": p.page, "class": p.page_class, "method": p.method or "none", "chars": p.chars,
                 "tables": sum(1 for b in p.blocks if b.type == "table"), "quality": p.quality, "flags": p.flags,
                 "status": p.status}
        if p.printed_page:
            entry["printed_page"] = p.printed_page
        if p.section_label is not None:
            entry["section"] = p.section_label
        if p.signals.get("ocr_error"):
            entry["error"] = p.signals["ocr_error"]
        if p.ocr is not None:
            entry["ocr"] = {"model": p.ocr.model, "input_tokens": p.ocr.input_tokens,
                            "output_tokens": p.ocr.output_tokens, "latency_ms": p.ocr.latency_ms,
                            "cost_usd": p.ocr.cost_usd}
            costs.append(p.ocr.cost_usd)
        out_pages.append(entry)
    removed = sorted({line for p in pages for line in p.removed_lines})
    return {
        "document_id": document_id,
        "status": status,
        "pages": out_pages,
        "chunks": len(chunks),
        "searchable_chunks": sum(1 for c in chunks if c["searchable"]),
        "ocr_cost_usd": _sum_cost(costs),
        "ocr_pages": len(costs),
        "removed_lines": removed,
        "embedder": getattr(k.vector.embedder, "name", None),
        "duration_ms": duration_ms,
    }


def _sum_cost(costs: list[str | None]) -> str | None:
    """No OCR: "0". OCR without a price: None ("price not set"), never 0."""
    if not costs:
        return "0"
    if any(c is None for c in costs):
        return None
    return str(sum((Decimal(c) for c in costs), Decimal(0)))
