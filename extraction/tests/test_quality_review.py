"""WP-EX4: X6 quality score, X7 review gate, page review service, ExtractionReport (contract 10 section 8)."""
import pytest

from ingestion.config import ExtractConfig
from ingestion.errors import IngestError
from ingestion.ocr import OcrFailed
from ingestion.quality import score_page, suspect_number
from ingestion.types import Block, OcrUsage, PageResult
from tests import files
from tests.conftest import META, FakeOCR, ocr_result

CFG = ExtractConfig()


def _ocr_page(result, blocks=None) -> PageResult:
    return PageResult(page=1, page_class="SCANNED", method="ocr", blocks=blocks or [Block("paragraph", "x")],
                      ocr_result=result, ocr=result.usage)


def test_ocr_score_formula():
    p = _ocr_page(ocr_result("w " * 60, words=60, illegible=9, confidence="medium", handwriting=True))
    score_page(p, CFG)
    assert p.quality == 0.75 and p.status == "NEEDS_REVIEW" and "HANDWRITTEN" in p.flags


def test_score_exactly_threshold_passes():
    p = _ocr_page(ocr_result("w", words=100, illegible=15))
    score_page(p, CFG)
    assert p.quality == 0.85 and p.status == "INDEXED"


def test_ocr_page_with_table_always_reviewed():
    """Gap G7: a confident but wrong digit cannot be seen in the score."""
    table = Block("table", "| a | b |", rows=[["Item", "Amount"], ["Per diem", "1,500"]])
    p = _ocr_page(ocr_result("| a |", table=True), [table])
    score_page(p, CFG)
    assert p.quality == 1.0 and p.status == "NEEDS_REVIEW" and "HAS_TABLE" in p.flags


def test_text_layer_table_not_reviewed():
    p = PageResult(page=1, page_class="TABLE_HEAVY", method="text+tables",
                   blocks=[Block("table", "t", rows=[["a", "b"], ["c", "1"]])], signals={"cid_ratio": 0.0})
    score_page(p, CFG)
    assert p.status == "INDEXED" and "HAS_TABLE" in p.flags


def test_number_suspect_lowers_score():
    table = Block("table", "t", rows=[["Item", "Amount"], ["Revenue", "1,23,4S6"]])
    p = _ocr_page(ocr_result("t", table=True), [table])
    score_page(p, CFG)
    assert "NUMBER_SUSPECT" in p.flags and p.quality == 0.8
    assert suspect_number("1,23,4S6") and suspect_number("2O25")
    assert not suspect_number("FY2024-25") and not suspect_number("1,23,456") and not suspect_number("Q2")


def test_low_quality_page_not_searchable(tmp_path, make_knowledge):
    """Page 4 (scanned) has 30 of 100 words illegible: NEEDS_REVIEW, its chunks not searchable; others searchable."""
    k = make_knowledge(FakeOCR(ocr_result("Handwritten margin note about the per diem.", words=100, illegible=30)))
    doc = k.submit_document(files.mixed_pdf(tmp_path / "m.pdf"), META)
    pages = {p["page"]: p for p in k.store.get_pages(doc["document_id"])}
    assert pages[4]["status"] == "NEEDS_REVIEW" and pages[4]["quality"] == 0.7
    assert all(pages[i]["status"] == "INDEXED" for i in (1, 2, 3))
    chunks = k.store.chunk_rows(doc["document_id"])
    assert {c["searchable"] for c in chunks if c["page"] == 4} == {False}
    assert {c["searchable"] for c in chunks if c["page"] != 4} == {True}
    assert k.store.get_document(doc["document_id"])["status"] == "PARTIAL_REVIEW"
    # neither index returns the page under review
    hits = k.bm25.search("handwritten margin note", 10) + k.vector.search("handwritten margin note", 10)
    page4 = {c["chunk_id"] for c in chunks if c["page"] == 4}
    assert not page4 & {h.chunk_id for h in hits}


def test_approve_makes_page_searchable_and_document_indexed(tmp_path, make_knowledge):
    k = make_knowledge(FakeOCR(ocr_result("Handwritten margin note about the per diem.", words=100, illegible=30)))
    doc_id = k.submit_document(files.mixed_pdf(tmp_path / "m.pdf"), META)["document_id"]
    page = k.review_page(doc_id, 4, "APPROVE", admin="myank", comment="checked against the photo")
    assert page["status"] == "APPROVED" and page["reviewed_by"] == "myank"
    assert all(c["searchable"] for c in page["chunks"])
    assert k.store.get_document(doc_id)["status"] == "INDEXED"
    assert k.bm25.search("handwritten margin note", 3)[0].chunk_id == page["chunks"][0]["chunk_id"]
    assert k.vector.search("handwritten margin note per diem", 1)[0].chunk_id == page["chunks"][0]["chunk_id"]
    with pytest.raises(IngestError) as e:
        k.review_page(doc_id, 4, "REJECT", admin="myank")
    assert (e.value.code, e.value.http_status) == ("ILLEGAL_MOVE", 409)


def test_reject_keeps_page_out(tmp_path, make_knowledge):
    k = make_knowledge(FakeOCR(ocr_result("Bad scan words", words=100, illegible=50)))
    doc_id = k.submit_document(files.mixed_pdf(tmp_path / "m.pdf"), META)["document_id"]
    k.review_page(doc_id, 4, "REJECT", admin="myank")
    assert not any(c["searchable"] for c in k.store.chunk_rows(doc_id, 4))
    assert k.store.get_document(doc_id)["status"] == "INDEXED"


def test_review_of_good_page_is_illegal(tmp_path, k):
    doc_id = k.submit_document(files.mixed_pdf(tmp_path / "m.pdf"), META)["document_id"]
    with pytest.raises(IngestError) as e:
        k.review_page(doc_id, 1, "APPROVE", admin="myank")
    assert e.value.code == "ILLEGAL_MOVE"


def test_ocr_failed_page_does_not_reject_document(tmp_path, make_knowledge):
    k = make_knowledge(FakeOCR(OcrFailed("429 quota", OcrUsage(model="m", attempts=3))))
    doc_id = k.submit_document(files.mixed_pdf(tmp_path / "m.pdf"), META)["document_id"]
    report = k.get_report(doc_id)
    assert report["status"] == "PARTIAL_REVIEW"
    p4 = report["pages"][3]
    assert p4["status"] == "NEEDS_REVIEW" and "OCR_FAILED" in p4["flags"] and p4["quality"] == 0.0
    assert all(p["status"] == "INDEXED" for p in report["pages"][:3])


def test_all_pages_unreadable_is_failed(tmp_path, make_knowledge):
    k = make_knowledge(FakeOCR(OcrFailed("503")))
    doc_id = k.submit_document(files.scanned_pdf(tmp_path / "s.pdf", pages=2), META)["document_id"]
    d = k.store.get_document(doc_id)
    assert d["status"] == "FAILED" and d["error"]


def test_extraction_report_shape(tmp_path, k):
    doc_id = k.submit_document(files.mixed_pdf(tmp_path / "m.pdf"), META)["document_id"]
    r = k.get_report(doc_id)
    assert set(r) >= {"document_id", "status", "pages", "chunks", "ocr_cost_usd", "duration_ms"}
    assert {"page", "class", "method", "chars", "tables", "quality", "flags", "status"} <= set(r["pages"][0])
    assert r["pages"][3]["ocr"] == {"model": "fake-vision", "input_tokens": 1290, "output_tokens": 410,
                                    "latency_ms": 10, "cost_usd": "0.0004"}
    assert r["ocr_cost_usd"] == "0.0004"
    page = k.get_page(doc_id, 4)
    assert page["image_url"] == f"/documents/{doc_id}/pages/4/image" and page["method"] == "ocr"
    png = k.page_image(doc_id, 4)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_ocr_cost_unset_is_none_not_zero(tmp_path, make_knowledge):
    from ingestion.types import OcrResult
    unpriced = OcrResult("Scanned text here.", word_count=3, usage=OcrUsage(model="m", cost_usd=None))
    k = make_knowledge(FakeOCR(unpriced))
    doc_id = k.submit_document(files.mixed_pdf(tmp_path / "m.pdf"), META)["document_id"]
    assert k.get_report(doc_id)["ocr_cost_usd"] is None
    k2_doc = k.submit_document(files.text_pdf(tmp_path / "t.pdf", [["Plain text page with words."]]),
                               {**META, "title": "Other"})
    assert k.get_report(k2_doc["document_id"])["ocr_cost_usd"] == "0"
