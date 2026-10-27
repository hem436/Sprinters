"""Contract 14: write financial tables and facts to knowledge.db, and the review services (F6, F7(b), F8).

Runs inside the ingest job, after the pages are extracted, for a document uploaded with a `company` (a financial
report). Re-indexing replaces the document's tables and facts, so nothing is duplicated.

Services the routes call (contract 05):
    list_tables(document_id)                 GET  /documents/{id}/tables
    review_table(table_id, decision, admin)  POST /tables/{id}/review           409 ILLEGAL_MOVE
    list_metric_map(pending)                 GET  /metric-map?pending=true
    approve_mapping(line_label, metric, ...)  POST /metric-map/approve           422 UNKNOWN_METRIC
"""
import json
import logging
import re
from datetime import date

from ingestion import errors
from ingestion.fin_parse import DICTIONARY, STANDARD_METRICS, fy_label, normalise_label, parse_unit, to_base, value_kind
from ingestion.fin_tables import FinTable, TableIn, analyse, collect_tables, join_continuations, needs_vision, table_id_for
from ingestion.store import KnowledgeStore, now
from ingestion.types import OcrUsage, PageResult

log = logging.getLogger(__name__)

FACT_COLUMNS = ("fact_id", "table_id", "report_id", "company", "period", "basis", "metric", "segment", "line_label",
                "label_norm", "value_kind", "value_num", "value_printed", "page", "row_no", "col_no")


# ---- writing ---------------------------------------------------------------------------------------------------------

def report_fiscal_year(effective_date: str) -> str:
    """The fiscal year a report published on this date is about: the year that ended before it (April to March)."""
    d = date.fromisoformat(effective_date)
    return fy_label(d.year if d.month >= 4 else d.year - 1)


def _report_id(store: KnowledgeStore, company: str, fiscal_year: str, report_type: str, document_id: str) -> str:
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", company)).upper()[:6] or "X"
    rid = f"R-{initials}-{fiscal_year[-2:]}" + ("Q" if report_type == "QUARTERLY" else "")
    taken = store.query("SELECT document_id FROM report WHERE report_id = ?", (rid,))
    if taken and taken[0]["document_id"] != document_id:
        rid = f"{rid}-{document_id[4:8]}"
    return rid


def delete_for_document(store: KnowledgeStore, document_id: str) -> None:
    with store.tx() as c:
        rids = [r[0] for r in c.execute("SELECT report_id FROM report WHERE document_id = ?", (document_id,))]
        for rid in rids:
            c.execute("DELETE FROM fin_fact WHERE report_id = ?", (rid,))
            c.execute("DELETE FROM fin_table WHERE report_id = ?", (rid,))
            c.execute("DELETE FROM report WHERE report_id = ?", (rid,))


def extract_financials(k, doc: dict, pages: list[PageResult], progress=None) -> dict | None:
    """F1 to F8 for one document. Returns a summary for the ExtractionReport, or None for a non-financial document."""
    store: KnowledgeStore = k.store
    extra = json.loads(doc.get("extra_json") or "null")
    delete_for_document(store, doc["document_id"])
    if not extra or not extra.get("company"):
        return None
    company = extra["company"]
    report_type = extra.get("report_type") or "ANNUAL"
    fiscal_year = extra.get("fiscal_year") or report_fiscal_year(doc["effective_date"])
    report_id = _report_id(store, company, fiscal_year, report_type, doc["document_id"])

    # F1: tables from the pages, and the vision model for numeric pages without a ruled table
    usages: list[OcrUsage] = []
    errors_seen: list[str] = []
    tables = collect_tables(pages)
    reader = getattr(k, "table_reader", None)
    vision_pages: list[PageResult] = []
    if reader is not None and k.cfg.fin_vision_tables and doc["file_type"] == "pdf":
        vision_pages = [p for p in pages if needs_vision(p)]
        for n, p in enumerate(vision_pages, start=1):
            if progress:
                progress("tables", n, len(vision_pages))
            tables += _vision_tables(k, reader, doc, p, usages, errors_seen)
        tables.sort(key=lambda t: t.page)
    tables = join_continuations(tables)

    # F3 to F7(a)
    approved_map = {r["line_label"]: r["metric"] for r in store.query(
        "SELECT line_label, metric FROM metric_map WHERE approved_by IS NOT NULL")}

    def resolve(norm: str) -> str:
        return DICTIONARY.get(norm) or approved_map.get(norm, "")

    analysed: list[FinTable] = []
    for i, t in enumerate(tables):
        ft = analyse(t, table_id_for(doc["document_id"], t.page, i), resolve, k.cfg.fin_review_unmapped)
        if ft is not None:
            analysed.append(ft)

    # F6: proposals for labels nobody has mapped yet
    proposals = _propose(k, store, analysed, usages)
    # F7(b): the same item in another report with another value is a restatement (the view picks the newest)
    for ft in analysed:
        _restatement_check(store, ft, company, report_id)

    _write(store, doc, report_id, company, report_type, fiscal_year, analysed)
    return {
        "report_id": report_id, "company": company, "fiscal_year": fiscal_year,
        "tables": len(analysed), "approved": sum(ft.status == "APPROVED" for ft in analysed),
        "needs_review": sum(ft.status == "NEEDS_REVIEW" for ft in analysed),
        "facts": sum(len(ft.facts) for ft in analysed),
        "unmapped_labels": sorted({lbl for ft in analysed for c in ft.checks if c["check"] == "UNMAPPED"
                                   for lbl in c["labels"]}),
        "proposals": proposals,
        "vision_pages": len(vision_pages),
        "errors": errors_seen,
        "usage": [u.__dict__ for u in usages],
    }


def _vision_tables(k, reader, doc: dict, page: PageResult, usages: list, errors_seen: list) -> list[TableIn]:
    from ingestion.fin_ai import TableReadFailed
    from ingestion.ocr import render_pdf_page

    image = render_pdf_page(doc["stored_path"], page.page, k.cfg.ocr_max_edge_px)
    try:
        found, usage = reader.read_tables(image)
    except TableReadFailed as e:
        errors_seen.append(f"page {page.page}: {e}")
        if e.usage:
            usages.append(e.usage)
        return []
    finally:
        image.close()
    if usage:
        usages.append(usage)
    context = next((b.section for b in page.blocks if b.section), "")
    out = []
    for i, vt in enumerate(found):
        rows = [list(map(str, r)) for r in vt.header_rows + vt.rows if r]
        if len(rows) >= 2:
            out.append(TableIn(page=page.page, rows=rows, caption=vt.caption, unit=vt.unit_line,
                               context=f"{context} {vt.caption}", source="vision",
                               first_on_page=i == 0, last_on_page=i == len(found) - 1))
    return out


def _propose(k, store: KnowledgeStore, tables: list[FinTable], usages: list) -> dict[str, str]:
    mapper = getattr(k, "label_mapper", None)
    labels = {}
    for ft in tables:
        for c in ft.checks:
            if c["check"] == "UNMAPPED":
                for lbl in c["labels"]:
                    labels.setdefault(normalise_label(lbl), lbl)
    if not labels:
        return {}
    known = {r["line_label"] for r in store.query(
        f"SELECT line_label FROM metric_map WHERE line_label IN ({', '.join('?' for _ in labels)})", list(labels))}
    todo = {n: lbl for n, lbl in labels.items() if n not in known}
    if not todo or mapper is None:
        return {}
    proposed, usage = mapper.propose(list(todo.values()))
    if usage:
        usages.append(usage)
    out = {}
    with store.tx() as c:
        for printed, metric in proposed.items():
            if metric in STANDARD_METRICS:
                norm = normalise_label(printed)
                c.execute("INSERT OR IGNORE INTO metric_map (line_label, metric, proposed_by) VALUES (?, ?, 'LLM')",
                          (norm, metric))
                out[printed] = metric
    return out


def _restatement_check(store: KnowledgeStore, ft: FinTable, company: str, report_id: str) -> None:
    restated = []
    for f in ft.facts:
        if not f.metric:
            continue
        others = store.query(
            "SELECT report_id, value_num, value_printed, page FROM fin_fact WHERE company = ? AND metric = ? "
            "AND period = ? AND basis = ? AND segment = ? AND report_id != ?",
            (company, f.metric, f.period, f.basis, f.segment, report_id))
        for o in others:
            if o["value_num"] != f.value_num:
                restated.append({"metric": f.metric, "period": f.period, "printed": f.value_printed,
                                 "other_report": o["report_id"], "other_printed": o["value_printed"],
                                 "other_page": o["page"]})
    if restated:
        ft.checks.append({"check": "RESTATED", "ok": True, "items": restated})


def _write(store: KnowledgeStore, doc: dict, report_id: str, company: str, report_type: str, fiscal_year: str,
           tables: list[FinTable]) -> None:
    import hashlib

    with store.tx() as c:
        c.execute("INSERT OR REPLACE INTO report (report_id, company, report_type, fiscal_year, published_on, "
                  "document_id) VALUES (?, ?, ?, ?, ?, ?)",
                  (report_id, company, report_type, fiscal_year, doc["effective_date"], doc["document_id"]))
        for ft in tables:
            c.execute("INSERT INTO fin_table (table_id, report_id, pages, statement, basis, currency, scale, "
                      "unit_printed, caption, source, rows_json, checks_passed, checks_json, status, reviewed_by, "
                      "reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (ft.table_id, report_id, json.dumps(ft.pages), ft.statement, ft.basis, ft.unit.currency,
                       ft.unit.scale, ft.unit_printed, ft.caption, ft.source, json.dumps(ft.rows, ensure_ascii=False),
                       int(ft.checks_passed), json.dumps(ft.checks, ensure_ascii=False), ft.status,
                       "checks" if ft.status == "APPROVED" else None, now() if ft.status == "APPROVED" else None))
            for f in ft.facts:
                fact_id = "f_" + hashlib.sha1(f"{ft.table_id}:{f.row_no}:{f.col_no}".encode()).hexdigest()[:12]
                values = (fact_id, ft.table_id, report_id, company, f.period, f.basis, f.metric, f.segment,
                          f.line_label, f.label_norm, f.value_kind, f.value_num, f.value_printed, f.page, f.row_no,
                          f.col_no)
                c.execute(f"INSERT INTO fin_fact ({', '.join(FACT_COLUMNS)}) VALUES ({', '.join('?' * len(values))})",
                          values)
                if f.metric and DICTIONARY.get(f.label_norm) == f.metric:
                    c.execute("INSERT OR IGNORE INTO metric_map (line_label, metric, proposed_by, approved_by, "
                              "approved_on) VALUES (?, ?, 'DICTIONARY', 'dictionary', ?)",
                              (f.label_norm, f.metric, now()))


# ---- services --------------------------------------------------------------------------------------------------------

def _table_out(row: dict, store: KnowledgeStore, with_facts: bool = False) -> dict:
    out = {k: row[k] for k in ("table_id", "report_id", "statement", "basis", "currency", "scale", "unit_printed",
                               "caption", "source", "status", "reviewed_by", "reviewed_at", "review_comment")}
    out["pages"] = json.loads(row["pages"])
    out["checks_passed"] = bool(row["checks_passed"])
    out["checks"] = json.loads(row["checks_json"])
    out["rows"] = json.loads(row["rows_json"])
    out["fact_count"] = store.query("SELECT COUNT(*) AS n FROM fin_fact WHERE table_id = ?", (row["table_id"],))[0]["n"]
    if with_facts:
        out["facts"] = store.query("SELECT * FROM fin_fact WHERE table_id = ? ORDER BY row_no, col_no",
                                   (row["table_id"],))
    return out


def list_tables(store: KnowledgeStore, document_id: str) -> list[dict]:
    rows = store.query("SELECT t.* FROM fin_table t JOIN report r ON r.report_id = t.report_id "
                       "WHERE r.document_id = ? ORDER BY t.pages, t.table_id", (document_id,))
    return [_table_out(r, store) for r in rows]


def get_table(store: KnowledgeStore, table_id: str) -> dict:
    rows = store.query("SELECT * FROM fin_table WHERE table_id = ?", (table_id,))
    if not rows:
        raise errors.not_found(f"Table {table_id}")
    return _table_out(rows[0], store, with_facts=True)


def review_table(store: KnowledgeStore, table_id: str, decision: str, admin: str, comment: str | None = None) -> dict:
    """F8: only a NEEDS_REVIEW table moves. APPROVE makes its mapped facts usable through v_fact_current."""
    decision = (decision or "").upper()
    if decision not in ("APPROVE", "REJECT"):
        raise errors.IngestError("INVALID_DECISION", 422, "decision must be APPROVE or REJECT")
    table = get_table(store, table_id)
    if table["status"] != "NEEDS_REVIEW":
        raise errors.illegal_move(f"Table {table_id} is {table['status']}; only a table in NEEDS_REVIEW can move.")
    store.query("UPDATE fin_table SET status = ?, reviewed_by = ?, reviewed_at = ?, review_comment = ? "
                "WHERE table_id = ?", ("APPROVED" if decision == "APPROVE" else "REJECTED", admin, now(), comment,
                                       table_id))
    return get_table(store, table_id)


def list_metric_map(store: KnowledgeStore, pending: bool = False) -> list[dict]:
    """Mappings with who proposed and approved them. With `pending`, the labels that wait for a person: LLM proposals
    not yet approved, and labels seen in tables with no mapping at all (metric empty)."""
    rows = store.query("SELECT line_label, metric, proposed_by, approved_by, approved_on FROM metric_map "
                       + ("WHERE approved_by IS NULL " if pending else "") + "ORDER BY line_label")
    if pending:
        mapped = {r["line_label"] for r in store.query("SELECT line_label FROM metric_map")}
        waiting: dict[str, str] = {}
        for t in store.query("SELECT checks_json FROM fin_table WHERE status != 'REJECTED'"):
            for chk in json.loads(t["checks_json"]):
                if chk["check"] == "UNMAPPED":
                    for printed in chk["labels"]:
                        waiting.setdefault(normalise_label(printed), printed)
        rows += [{"line_label": norm, "metric": "", "proposed_by": None, "approved_by": None, "approved_on": None,
                  "printed": printed} for norm, printed in sorted(waiting.items()) if norm not in mapped]
    return rows


def approve_mapping(store: KnowledgeStore, line_label: str, metric: str, admin: str) -> dict:
    """F6: a person maps a label to a standard metric. The waiting facts with that label get the metric now."""
    if metric not in STANDARD_METRICS:
        raise errors.IngestError("UNKNOWN_METRIC", 422, f"'{metric}' is not a standard metric.",
                                 allowed=sorted(STANDARD_METRICS))
    norm = normalise_label(line_label)
    if not norm:
        raise errors.invalid_metadata({"line_label": "required"})
    stamp = now()
    with store.tx() as c:
        c.execute("INSERT INTO metric_map (line_label, metric, proposed_by, approved_by, approved_on) "
                  "VALUES (?, ?, 'ADMIN', ?, ?) ON CONFLICT (line_label) DO UPDATE SET metric = excluded.metric, "
                  "approved_by = excluded.approved_by, approved_on = excluded.approved_on", (norm, metric, admin, stamp))
        facts = c.execute("SELECT f.fact_id, f.line_label, f.value_printed, f.table_id, t.scale, t.unit_printed, "
                          "t.caption FROM fin_fact f JOIN fin_table t ON t.table_id = f.table_id "
                          "WHERE f.label_norm = ? AND f.metric = ''", (norm,)).fetchall()
        tables = set()
        for f in facts:
            from ingestion.fin_parse import parse_number
            unit = parse_unit(f["unit_printed"], f["caption"])
            kind = value_kind(f["line_label"], metric, unit)
            num, _ = to_base(parse_number(f["value_printed"]), kind, f["scale"])
            c.execute("UPDATE fin_fact SET metric = ?, value_kind = ?, value_num = ? WHERE fact_id = ?",
                      (metric, kind, num, f["fact_id"]))
            tables.add(f["table_id"])
        for tid in tables:                                     # the label is no longer unmapped in those tables
            checks = json.loads(c.execute("SELECT checks_json FROM fin_table WHERE table_id = ?", (tid,))
                                .fetchone()[0])
            for chk in checks:
                if chk["check"] == "UNMAPPED":
                    chk["labels"] = [x for x in chk["labels"] if normalise_label(x) != norm]
            checks = [chk for chk in checks if not (chk["check"] == "UNMAPPED" and not chk["labels"])]
            c.execute("UPDATE fin_table SET checks_json = ? WHERE table_id = ?", (json.dumps(checks), tid))
    return {"line_label": norm, "metric": metric, "approved_by": admin, "approved_on": stamp,
            "facts_updated": len(facts)}
