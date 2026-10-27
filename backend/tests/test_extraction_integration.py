"""The document routes against Myank's real ingestion service (extraction/), not a fake.

His pipeline runs for real: validation, page classes, text extraction, chunking and indexing. Only the
outside services are swapped, as in his own tests: a fake OCR, the offline HashingEmbedder and an in-memory
vector index, with jobs run inline. Skipped where extraction/ cannot be imported (it needs Python 3.11+).
"""

from __future__ import annotations

import pytest

pytest.importorskip("ingestion.service")
pytest.importorskip("reportlab")

from fastapi.testclient import TestClient  # noqa: E402
from ingestion import service  # noqa: E402
from ingestion.config import ExtractConfig  # noqa: E402
from ingestion.embedding import HashingEmbedder  # noqa: E402
from ingestion.index_vector import VectorIndex  # noqa: E402
from ingestion.jobs import JobQueue  # noqa: E402
from ingestion.store import KnowledgeStore  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.main import create_app  # noqa: E402

META = {"title": "Travel and Expense Policy", "category": "HR policy", "version": "2.0",
        "effective_date": "2026-04-01", "doc_key": "travel-policy"}
PAGES = [
    ["4.2 Per diem", "The daily allowance for meals in Mumbai is Rs 2,000 a day for all grades.",
     "Delhi is Rs 1,800 a day. Claims above the allowance need a receipt and a reason."],
    ["4.5 Overruns", "Spend above the approved project budget needs approval from the department head.",
     "The finance team checks every overrun before the claim is paid."],
]


class NoOCR:
    def read(self, image):
        raise AssertionError("a text PDF must not need OCR")


def _pdf(path) -> bytes:
    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in PAGES:
        y = 780
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
    c.save()
    return path.read_bytes()


@pytest.fixture
def api(config, tmp_path):
    cfg = ExtractConfig(data_dir=tmp_path / "extraction", qdrant_url=None)
    knowledge = service.Knowledge(cfg, KnowledgeStore(cfg.db_path),
                                  VectorIndex(HashingEmbedder(), "test_kb", path=":memory:"), NoOCR(),
                                  JobQueue(inline=True))
    service.set_default(knowledge)
    yield TestClient(create_app(config), raise_server_exceptions=False)
    service.set_default(None)


def test_upload_index_and_read_back(api, tmp_path):
    pdf = _pdf(tmp_path / "policy.pdf")
    resp = api.post("/documents", files={"file": ("policy.pdf", pdf, "application/pdf")}, data=META)
    assert resp.status_code == 202, resp.text
    doc_id = resp.json()["document_id"]

    listed = api.get("/documents").json()
    assert [d["document_id"] for d in listed] == [doc_id] and listed[0]["status"] == "INDEXED"
    detail = api.get(f"/documents/{doc_id}").json()
    assert len(detail["report"]["pages"]) == 2

    page = api.get(f"/documents/{doc_id}/pages/1").json()
    assert "Mumbai" in page["text"] and page["status"] == "INDEXED"
    image = api.get(f"/documents/{doc_id}/pages/1/image")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert api.get("/jobs").status_code == 200

    assert [d["document_id"] for d in api.get("/library").json()] == [doc_id]
    assert "department head" in api.get(f"/library/{doc_id}/pages/2").json()["text"]


def test_real_errors_come_back_in_the_contract_shape(api, tmp_path):
    pdf = _pdf(tmp_path / "policy.pdf")
    api.post("/documents", files={"file": ("policy.pdf", pdf, "application/pdf")}, data=META)
    again = api.post("/documents", files={"file": ("copy.pdf", pdf, "application/pdf")}, data=META)
    assert again.status_code == 409 and again.json()["error"]["code"] == "DUPLICATE_DOCUMENT"

    exe = api.post("/documents", files={"file": ("policy.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
                   data=META)
    assert exe.status_code == 422 and exe.json()["error"]["code"] in ("UNSUPPORTED_TYPE", "CORRUPT_FILE")

    missing = api.get("/documents/doc_00000000")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
    assert "X-Request-Id" in missing.headers
