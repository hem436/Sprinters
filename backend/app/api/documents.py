"""Document, review and library routes (contract 05). The logic is Myank's `ingestion.service` (extraction/).

Every route is open (no login). Myank's IngestError (code, http_status, message, detail) becomes the
contract error body. Table review and the metric map answer 501 until extraction offers them (WP-EX6).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field

from app.api.errors import ApiError
from app.config import Config, get_config

router = APIRouter(tags=["documents"])

SEARCHABLE_DOCS = ("INDEXED", "PARTIAL_REVIEW")
SEARCHABLE_PAGES = ("INDEXED", "APPROVED")


class Decision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    comment: str | None = Field(default=None, max_length=2000)


class Mapping(BaseModel):
    line_label: str = Field(min_length=1, max_length=200)
    metric: str = Field(min_length=1, max_length=60)


def get_knowledge(config: Config = Depends(get_config)):
    """Myank's service module; its knowledge.db and files live in our data folder."""
    os.environ.setdefault("EXTRACTION_DATA_DIR", str(config.paths.resolve(config.paths.data_dir)))
    try:
        from ingestion import service
    except Exception as exc:                          # extraction/ missing or its packages not installed
        raise ApiError(503, "EXTRACTION_UNAVAILABLE", f"Document processing is not available: {exc}") from exc
    return service


def call(fn, *args: Any, **kwargs: Any) -> Any:
    """Run a service function; turn its IngestError into the contract error."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "http_status"):
            detail = getattr(exc, "detail", {}) or {}
            fields = [{"field": k, "problem": v} for k, v in (detail.get("fields") or {}).items()]
            raise ApiError(exc.http_status, exc.code, getattr(exc, "message", str(exc)), fields) from exc
        raise


def optional(service, name: str):
    fn = getattr(service, name, None)
    if fn is None:
        raise ApiError(501, "NOT_IMPLEMENTED", f"{name} is not offered by extraction yet (WP-EX6).")
    return fn


# Documents and review -------------------------------------------------------------------------------------------

@router.post("/documents", status_code=202)
def upload(file: UploadFile = File(...), title: str = Form(...), category: str = Form(...),
           version: str = Form(...), effective_date: str = Form(...), doc_key: str | None = Form(None),
           service=Depends(get_knowledge)) -> dict:
    meta = {"title": title, "category": category, "version": version, "effective_date": effective_date}
    if doc_key:
        meta["doc_key"] = doc_key
    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        return call(service.submit_document, tmp.name, meta, file_name=file.filename, uploaded_by="admin")
    finally:
        os.unlink(tmp.name)                           # the service keeps its own copy


@router.get("/documents")
def list_documents(category: str | None = None, status: str | None = None, service=Depends(get_knowledge)) -> list:
    return call(service.list_documents, category, status)


@router.get("/documents/{document_id}")
def get_document(document_id: str, service=Depends(get_knowledge)) -> dict:
    return call(service.get_document, document_id)


@router.get("/documents/{document_id}/pages/{page}")
def get_page(document_id: str, page: int, service=Depends(get_knowledge)) -> dict:
    return call(service.get_page, document_id, page)


@router.get("/documents/{document_id}/pages/{page}/image")
def page_image(document_id: str, page: int, service=Depends(get_knowledge)) -> Response:
    return Response(call(service.page_image, document_id, page), media_type="image/png")


@router.post("/documents/{document_id}/pages/{page}/review")
def review_page(document_id: str, page: int, body: Decision, service=Depends(get_knowledge)) -> dict:
    return call(service.review_page, document_id, page, body.decision, "admin", body.comment)


@router.post("/documents/{document_id}/reindex", status_code=202)
def reindex(document_id: str, service=Depends(get_knowledge)) -> dict:
    return call(service.reindex, document_id)


@router.delete("/documents/{document_id}", status_code=204)
def delete(document_id: str, service=Depends(get_knowledge)) -> Response:
    call(service.delete_document, document_id)
    return Response(status_code=204)


@router.get("/jobs")
def list_jobs(service=Depends(get_knowledge)) -> list:
    return call(service.list_jobs)


# Financial tables and the metric map (contract 14; extraction WP-EX6) ---------------------------------------------

@router.get("/documents/{document_id}/tables")
def list_tables(document_id: str, service=Depends(get_knowledge)) -> list:
    return call(optional(service, "list_tables"), document_id)


@router.post("/tables/{table_id}/review")
def review_table(table_id: str, body: Decision, service=Depends(get_knowledge)) -> dict:
    return call(optional(service, "review_table"), table_id, body.decision, "admin", body.comment)


@router.get("/metric-map")
def list_metric_map(pending: bool = False, service=Depends(get_knowledge)) -> list:
    return call(optional(service, "list_metric_map"), pending)


@router.post("/metric-map/approve")
def approve_mapping(body: Mapping, service=Depends(get_knowledge)) -> dict:
    return call(optional(service, "approve_mapping"), body.line_label, body.metric, "admin")


# Library: what a user may read (issue 48). Only searchable documents and pages. -------------------------------------

@router.get("/library")
def library(category: str | None = None, service=Depends(get_knowledge)) -> list:
    keys = ("document_id", "doc_key", "title", "category", "version", "effective_date", "page_count", "status")
    return [{k: d.get(k) for k in keys} for d in call(service.list_documents, category, None)
            if d.get("status") in SEARCHABLE_DOCS]


@router.get("/library/{document_id}/pages/{page}")
def library_page(document_id: str, page: int, service=Depends(get_knowledge)) -> dict:
    doc = call(service.get_document, document_id)
    found = call(service.get_page, document_id, page)
    if doc.get("status") not in SEARCHABLE_DOCS or found.get("status") not in SEARCHABLE_PAGES:
        raise ApiError(404, "NOT_FOUND", f"Page {page} of {document_id} is not in the library.")
    return {"document_id": document_id, "title": doc.get("title"), "version": doc.get("version"), "page": page,
            "text": found.get("text"), "image_url": found.get("image_url")}
