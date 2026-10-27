"""WP-EX6 end to end: PDF upload with a company -> fin_table, fin_fact, metric_map and the view v_fact_current
(contract 14 sections 3, 5 and 8)."""
import copy

import pytest

from ingestion.errors import IngestError
from ingestion.fin_ai import VisionTable
from ingestion.types import OcrUsage
from tests import files
from tests.conftest import META

REPORT_META = {"title": "Company A Annual Report", "category": "Financial report", "company": "Company A",
               "report_type": "ANNUAL"}
CRORE = 10_000_000


def _upload(k, path, version: str, effective: str, **extra) -> str:
    meta = {**REPORT_META, "version": version, "effective_date": effective, **extra}
    return k.submit_document(path, meta)["document_id"]


def _view(k, **where) -> list[dict]:
    sql = "SELECT * FROM v_fact_current WHERE 1 = 1" + "".join(f" AND {c} = ?" for c in where)
    return k.store.query(sql + " ORDER BY metric, period", list(where.values()))


def test_report_pdf_to_facts(tmp_path, k):
    doc = _upload(k, files.fin_pdf(tmp_path / "ar25.pdf"), "FY2024-25", "2025-06-01")
    tables = k.list_tables(doc)
    assert len(tables) == 1
    t = tables[0]
    assert (t["statement"], t["basis"], t["scale"], t["status"], t["source"]) == ("PL", "CONSOLIDATED", CRORE,
                                                                                   "APPROVED", "text")
    assert t["unit_printed"] == "(₹ in crore)" and t["pages"] == [1] and t["rows"][0][2] == "Year ended 31 March 2025"
    report = k.store.query("SELECT * FROM report")[0]
    assert (report["report_id"], report["fiscal_year"], report["published_on"]) == ("R-CA-25", "FY2024-25",
                                                                                    "2025-06-01")
    rev = {r["period"]: r for r in _view(k, metric="revenue")}
    assert rev["FY2024-25"]["value_num"] == 11_256 * CRORE and rev["FY2024-25"]["value_printed"] == "11,256.00"
    assert rev["FY2024-25"]["page"] == 1 and rev["FY2024-25"]["row_no"] == 1
    summary = k.get_report(doc)["financial"]
    assert summary["tables"] == 1 and summary["approved"] == 1 and summary["facts"] > 20
    # the dictionary mappings are recorded as approved by the dictionary
    mm = {r["line_label"]: r for r in k.list_metric_map()}
    assert mm["revenue from operations"]["proposed_by"] == "DICTIONARY" and mm["revenue from operations"]["approved_by"]
    # the same table is also a searchable Markdown chunk (contract 14 section 1: stored twice)
    assert any("| Revenue from operations | 21 | 11,256.00 | 10,050.00 |" in c["text"]
               for c in k.store.chunk_rows(doc))


def test_newest_report_wins_and_restated(tmp_path, k):
    """Contract 14: FY2023-24 revenue = 10,050 from the newer report, restated = 1, the old 10,000 kept."""
    old_rows = copy.deepcopy(files.PL_ROWS)
    old_header = ["Particulars", "Note", "Year ended 31 March 2024", "Year ended 31 March 2023"]
    old_rows[0][2:] = ["10,000.00", "9,000.00"]
    old_rows[2][2:] = ["10,150.00", "9,150.00"]                      # keep the totals right
    for r in old_rows[1:]:
        if r[0] == "Other income":
            r[2:] = ["150.00", "150.00"]
    d24 = _upload(k, files.fin_pdf(tmp_path / "ar24.pdf", header=old_header, rows=old_rows,
                                   caption="for the year ended 31 March 2024"), "FY2023-24", "2024-06-01")
    d25 = _upload(k, files.fin_pdf(tmp_path / "ar25.pdf"), "FY2024-25", "2025-06-01")
    assert all(t["status"] == "APPROVED" for d in (d24, d25) for t in k.list_tables(d)), \
        [t["checks"] for d in (d24, d25) for t in k.list_tables(d)]
    fy24 = _view(k, metric="revenue", period="FY2023-24")[0]
    assert fy24["value_num"] == 10_050 * CRORE and fy24["restated"] == 1
    assert (fy24["prev_value_printed"], fy24["prev_report_id"]) == ("10,000.00", "R-CA-24")
    assert _view(k, metric="revenue", period="FY2024-25")[0]["restated"] == 0
    restated = [c for c in k.list_tables(d25)[0]["checks"] if c["name"] == "RESTATED"]
    assert restated and restated[0]["items"][0]["other_printed"] == "10,000.00"
    # growth in SQL with the newest values: (11,256 - 10,050) / 10,050 = 12.0 %
    growth = k.store.query(
        "SELECT ROUND(100.0 * (a.value_num - b.value_num) / b.value_num, 1) AS g FROM v_fact_current a "
        "JOIN v_fact_current b ON a.company = b.company AND a.metric = b.metric AND a.basis = b.basis "
        "WHERE a.metric = 'revenue' AND a.period = 'FY2024-25' AND b.period = 'FY2023-24'")[0]["g"]
    assert growth == 12.0


def test_standalone_not_in_consolidated(tmp_path, k):
    _upload(k, files.fin_pdf(tmp_path / "c.pdf"), "FY2024-25", "2025-06-01")
    rows = copy.deepcopy(files.PL_ROWS)
    rows[0][2] = "9,000.00"
    rows[2][2] = "9,244.00"
    _upload(k, files.fin_pdf(tmp_path / "s.pdf", title="Standalone Statement of Profit and Loss", rows=rows),
            "FY2024-25-S", "2025-06-02", fiscal_year="FY2024-25")
    cons = _view(k, metric="revenue", period="FY2024-25", basis="CONSOLIDATED")
    stand = _view(k, metric="revenue", period="FY2024-25", basis="STANDALONE")
    assert [r["value_printed"] for r in cons] == ["11,256.00"] and [r["value_printed"] for r in stand] == ["9,000.00"]
    assert cons[0]["restated"] == 0


def test_totals_check_flags_review_end_to_end(tmp_path, k):
    rows = copy.deepcopy(files.PL_ROWS)
    rows[0][2] = "11,265.00"
    doc = _upload(k, files.fin_pdf(tmp_path / "bad.pdf", rows=rows), "FY2024-25", "2025-06-01")
    t = k.list_tables(doc)[0]
    assert t["status"] == "NEEDS_REVIEW" and not t["checks_passed"]
    assert _view(k, metric="revenue") == []                             # nothing usable until a person approves
    approved = k.review_table(t["table_id"], "APPROVE", admin="myank", comment="checked against p.1")
    assert approved["status"] == "APPROVED" and approved["reviewed_by"] == "myank"
    assert _view(k, metric="revenue", period="FY2024-25")[0]["value_printed"] == "11,265.00"
    with pytest.raises(IngestError) as e:
        k.review_table(t["table_id"], "REJECT", admin="myank")
    assert (e.value.code, e.value.http_status) == ("ILLEGAL_MOVE", 409)


def test_rejected_table_never_used(tmp_path, k):
    rows = copy.deepcopy(files.PL_ROWS)
    rows[0][2] = "11,265.00"
    doc = _upload(k, files.fin_pdf(tmp_path / "bad.pdf", rows=rows), "FY2024-25", "2025-06-01")
    k.review_table(k.list_tables(doc)[0]["table_id"], "REJECT", admin="myank")
    assert _view(k) == []


class FakeMapper:
    def __init__(self, proposals):
        self.proposals = proposals
        self.asked = []

    def propose(self, labels):
        self.asked.append(labels)
        return {lbl: m for lbl, m in self.proposals.items() if lbl in labels}, OcrUsage(model="fake-text",
                                                                                         cost_usd="0.00001")


def test_unmapped_label_not_used_until_approved(tmp_path, k):
    k.label_mapper = FakeMapper({"Total income from operations": "revenue"})
    rows = copy.deepcopy(files.PL_ROWS)
    rows[0][0] = "Total income from operations"
    doc = _upload(k, files.fin_pdf(tmp_path / "u.pdf", rows=rows), "FY2024-25", "2025-06-01")
    t = k.list_tables(doc)[0]
    assert t["status"] == "NEEDS_REVIEW"
    assert next(c for c in t["checks"] if c["name"] == "UNMAPPED")["labels"] == ["Total income from operations"]
    assert _view(k, metric="revenue") == []
    pending = k.list_metric_map(pending=True)
    assert {"line_label": "total income from operations", "metric": "revenue", "proposed_by": "LLM",
            "approved_by": None, "approved_on": None} in pending
    # a person approves the mapping, then the table
    out = k.approve_mapping("Total income from operations", "revenue", admin="myank")
    assert out["facts_updated"] == 2
    # the label was the table's only open check, so the table is approved by the checks (review D4)
    assert out["tables_approved"] == [t["table_id"]]
    after = k.list_tables(doc)[0]
    assert after["status"] == "APPROVED" and not any(c["name"] == "UNMAPPED" for c in after["checks"])
    assert [r["value_printed"] for r in _view(k, metric="revenue")] == ["10,050.00", "11,256.00"]
    assert k.list_metric_map(pending=True) == []
    # the next report with that label is mapped at once
    k.label_mapper.asked.clear()
    doc2 = _upload(k, files.fin_pdf(tmp_path / "u2.pdf", rows=rows, caption="restated copy"), "FY2024-25b",
                   "2025-07-01")
    assert k.list_tables(doc2)[0]["status"] == "APPROVED" and k.label_mapper.asked == []


def test_unknown_metric_is_422(k):
    with pytest.raises(IngestError) as e:
        k.approve_mapping("Gross margin", "gross_margin", admin="myank")
    assert (e.value.code, e.value.http_status) == ("UNKNOWN_METRIC", 422)


def test_missing_period_not_found(tmp_path, k):
    _upload(k, files.fin_pdf(tmp_path / "ar25.pdf"), "FY2024-25", "2025-06-01")
    assert _view(k, metric="revenue", period="FY2019-20") == []


def test_table_across_two_pages(tmp_path, k):
    doc = _upload(k, files.fin_pdf(tmp_path / "two.pdf", split_at=6), "FY2024-25", "2025-06-01")
    tables = k.list_tables(doc)
    assert len(tables) == 1 and tables[0]["pages"] == [1, 2] and tables[0]["status"] == "APPROVED"
    pat = _view(k, metric="pat", period="FY2024-25")[0]
    assert pat["page"] == 2 and pat["value_printed"] == "5,250.00"


class FakeTableReader:
    def __init__(self):
        self.calls = 0

    def read_tables(self, image):
        self.calls += 1
        return [VisionTable(caption="Standalone Statement of Profit and Loss", unit_line="(₹ in crore)",
                            header_rows=[["Particulars", "FY2024-25", "FY2023-24"]],
                            rows=[["Revenue from operations", "9,000", "8,100"], ["Other income", "100", "90"],
                                  ["Total income", "9,100", "8,190"]])], OcrUsage(model="fake-vision",
                                                                                    cost_usd="0.0003")


def test_unruled_table_goes_to_vision_and_review(tmp_path, k):
    k.table_reader = FakeTableReader()
    doc = _upload(k, files.unruled_numbers_pdf(tmp_path / "v.pdf"), "FY2024-25", "2025-06-01")
    assert k.table_reader.calls == 1
    t = k.list_tables(doc)[0]
    assert (t["source"], t["basis"], t["status"]) == ("vision", "STANDALONE", "NEEDS_REVIEW")
    assert any(c["name"] == "OCR_SOURCE" for c in t["checks"])
    report = k.get_report(doc)
    assert report["financial"]["vision_pages"] == 1 and report["ocr_cost_usd"] == "0.0003"


def test_reindex_and_delete(tmp_path, k):
    doc = _upload(k, files.fin_pdf(tmp_path / "ar25.pdf"), "FY2024-25", "2025-06-01")
    before = k.store.query("SELECT fact_id FROM fin_fact ORDER BY fact_id")
    k.reindex(doc)
    assert k.store.query("SELECT fact_id FROM fin_fact ORDER BY fact_id") == before
    k.delete_document(doc)
    assert k.store.query("SELECT COUNT(*) AS n FROM fin_fact")[0]["n"] == 0 and _view(k) == []


def test_document_without_company_has_no_facts(tmp_path, k):
    doc = k.submit_document(files.fin_pdf(tmp_path / "x.pdf"), META)["document_id"]
    assert k.list_tables(doc) == [] and k.get_report(doc)["financial"] is None


def test_report_fields_validated(tmp_path, k):
    with pytest.raises(IngestError) as e:
        k.submit_document(files.fin_pdf(tmp_path / "x.pdf"), {**META, "company": "A", "fiscal_year": "2024-25"})
    assert e.value.code == "INVALID_METADATA" and "fiscal_year" in e.value.detail["fields"]
