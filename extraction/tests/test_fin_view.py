"""Contract 14 section 3: the view v_fact_current that Sinngam's facts tools read. (F1 to F8 come in WP-EX6.)"""
from ingestion.store import KnowledgeStore


def _seed(store: KnowledgeStore, table_status: str = "APPROVED"):
    with store.tx() as c:
        c.executemany("INSERT INTO report VALUES (?,?,?,?,?,NULL)", [
            ("R-A-24", "Company A", "ANNUAL", "FY2023-24", "2024-06-01"),
            ("R-A-25", "Company A", "ANNUAL", "FY2024-25", "2025-06-01")])
        c.executemany("INSERT INTO fin_table (table_id, report_id, pages, statement, basis, scale, status) "
                      "VALUES (?,?,?,?,?,?,?)", [
                          ("T24", "R-A-24", "[48]", "PL", "CONSOLIDATED", 10_000_000, "APPROVED"),
                          ("T25", "R-A-25", "[52]", "PL", "CONSOLIDATED", 10_000_000, table_status),
                          ("T25S", "R-A-25", "[60]", "PL", "STANDALONE", 10_000_000, "APPROVED")])
        crore = 10_000_000
        c.executemany("INSERT INTO fin_fact (fact_id, table_id, report_id, company, period, basis, metric, line_label, "
                      "value_kind, value_num, value_printed, page, row_no, col_no) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                          ("f1", "T24", "R-A-24", "Company A", "FY2023-24", "CONSOLIDATED", "revenue",
                           "Revenue from operations", "AMOUNT", 10_000 * crore, "10,000", 48, 3, 1),
                          ("f2", "T25", "R-A-25", "Company A", "FY2023-24", "CONSOLIDATED", "revenue",
                           "Revenue from operations", "AMOUNT", 10_050 * crore, "10,050", 52, 3, 2),
                          ("f3", "T25", "R-A-25", "Company A", "FY2024-25", "CONSOLIDATED", "revenue",
                           "Revenue from operations", "AMOUNT", 11_256 * crore, "11,256", 52, 3, 1),
                          ("f4", "T25S", "R-A-25", "Company A", "FY2024-25", "STANDALONE", "revenue",
                           "Revenue from operations", "AMOUNT", 9_000 * crore, "9,000", 60, 3, 1),
                          ("f5", "T25", "R-A-25", "Company A", "FY2024-25", "CONSOLIDATED", "",
                           "Income from new ventures", "AMOUNT", 5 * crore, "5", 52, 9, 1)])


def test_newest_report_wins_and_restated(tmp_path):
    store = KnowledgeStore(tmp_path / "k.db")
    _seed(store)
    rows = {(r["period"], r["basis"]): r for r in store.query("SELECT * FROM v_fact_current WHERE metric='revenue'")}
    fy24 = rows[("FY2023-24", "CONSOLIDATED")]
    assert fy24["value_printed"] == "10,050" and fy24["restated"] == 1
    assert fy24["prev_value_printed"] == "10,000" and fy24["prev_report_id"] == "R-A-24" and fy24["prev_page"] == 48
    fy25 = rows[("FY2024-25", "CONSOLIDATED")]
    assert fy25["restated"] == 0 and fy25["prev_value_num"] is None
    assert rows[("FY2024-25", "STANDALONE")]["value_printed"] == "9,000"


def test_unmapped_and_unapproved_not_in_view(tmp_path):
    store = KnowledgeStore(tmp_path / "k.db")
    _seed(store, table_status="NEEDS_REVIEW")
    labels = {r["line_label"] for r in store.query("SELECT line_label FROM v_fact_current")}
    assert "Income from new ventures" not in labels
    rows = store.query("SELECT period, value_printed, restated FROM v_fact_current WHERE basis='CONSOLIDATED'")
    assert rows == [{"period": "FY2023-24", "value_printed": "10,000", "restated": 0}]
