"""WP-EX7: the extraction quality measures, the gold set, and two layout bugs the demo documents found."""
from pathlib import Path

import pytest
import yaml

from ingestion.config import ExtractConfig
from ingestion.extraction_eval import (
    cer,
    edit_distance,
    evaluate,
    normalise,
    numeric_recall,
    table_cell_accuracy,
    wer,
)
from ingestion.loaders.pdf import extract_pdf
from tests import files
from tests.conftest import FakeOCR

ROOT = Path(__file__).resolve().parents[2]


def test_edit_distance_and_rates():
    assert edit_distance("kitten", "sitting") == 3
    assert cer("Mumbai ₹2,000", "Mumbai ₹2,000") == 0
    assert cer("abcd", "abxd") == 0.25
    assert wer("per diem is 2,000", "per diem is 2,600") == 0.25


def test_normalise_ignores_markdown_only():
    md = "# 4.2 Per diem\n| City | Per diem |\n| --- | --- |\n| Mumbai | 2,000 |\n- Book early"
    assert normalise(md) == "4.2 Per diem City Per diem Mumbai 2,000 Book early"
    assert normalise("• Book early") == "Book early"
    assert cer("City Per diem\nMumbai 2,000", "| City | Per diem |\n|---|---|\n| Mumbai | 2,000 |") == 0


def test_numeric_recall_counts_each_printed_number():
    gold = "Revenue 11,256.00 and 10,050.00; EPS 45.67; again 10,050.00"
    assert numeric_recall(gold, gold) == 1.0
    assert numeric_recall(gold, "Revenue 11,256.00 and 10,050.00; EPS 45.67") == 0.75
    assert numeric_recall(gold, "Revenue 11256 and 10050") == 0.0         # not printed the same way
    assert numeric_recall("no numbers here", "x") is None


def test_table_cell_accuracy_best_table():
    gold = [["City", "Per diem"], ["Mumbai", "2,000"]]
    assert table_cell_accuracy(gold, [[["x"]], [["City", "Per diem"], ["Mumbai", "2,600"]]]) == 0.75
    assert table_cell_accuracy(gold, []) == 0.0


def test_gold_set_is_complete():
    gold_dir = ROOT / "evals" / "extraction_gold"
    entries = yaml.safe_load((gold_dir / "gold.yaml").read_text(encoding="utf-8"))
    kinds = {e["kind"] for e in entries}
    assert {"financial_text", "financial_scanned", "scanned", "handwriting"} <= kinds
    for e in entries:
        assert (gold_dir / f"{e['name']}.txt").exists()
        assert (ROOT / "demo" / "documents" / e["file"]).exists()


def test_eval_text_pages_of_demo_corpus():
    """The text-layer gold pages of the demo corpus are read exactly (no model calls)."""
    rows = evaluate(ROOT / "evals" / "extraction_gold", ROOT / "demo" / "documents", ExtractConfig(), None,
                    use_ocr=False)
    assert len(rows) == 3
    assert all(r["cer"] == 0 and r["numeric_recall"] == 1.0 and r["actual_class"] == r["expected_class"] for r in rows)
    assert all(r["table_cell_accuracy"] in (None, 1.0) for r in rows)


def test_unit_line_on_every_page_is_kept(tmp_path):
    """Bug found on the demo report: "(₹ in crore)" at the top of most pages was removed as a running header."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    path = tmp_path / "statements.pdf"
    c = files.canvas.Canvas(str(path), pagesize=files.A4)
    for title in ("Consolidated Statement of Profit and Loss", "Standalone Statement of Profit and Loss",
                  "Consolidated Balance Sheet"):
        c.setFont(files._FONT, 18)
        c.drawString(60, 770, title)
        c.setFont(files._FONT, 10)
        c.drawString(60, 740, "(₹ in crore)")
        t = Table([files.PL_HEADER, *files.PL_ROWS[:3]], colWidths=[200, 40, 130, 130])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                               ("FONTNAME", (0, 0), (-1, -1), files._FONT)]))
        t.wrapOn(c, 595, 842)
        t.drawOn(c, 50, 620)
        c.showPage()
    c.save()
    pages = extract_pdf(path, ExtractConfig(), FakeOCR())
    for p in pages:
        table = next(b for b in p.blocks if b.type == "table")
        assert "₹ in crore" in table.unit and "(₹ in crore)" not in p.removed_lines
        assert p.blocks[0].type == "heading"


def test_wrapped_heading_is_one_heading(tmp_path):
    """Bug found on the demo report: a title wrapped onto two lines became two sections."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "h.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 18)
    c.drawString(72, 760, "Management Discussion")
    c.drawString(72, 738, "and Analysis")
    c.setFont("Helvetica", 10)
    y = 700
    for i in range(8):
        c.drawString(72, y, f"Revenue line {i} explains growth in the payments business this year.")
        y -= 14
    c.showPage()
    c.save()
    blocks = extract_pdf(path, ExtractConfig(), FakeOCR())[0].blocks
    headings = [b.text for b in blocks if b.type == "heading"]
    assert headings == ["Management Discussion and Analysis"]
    assert blocks[-1].section == "Management Discussion and Analysis"


@pytest.mark.parametrize("name", ["travel-policy-v1-scanned.pdf", "company-a-pl-scanned.pdf"])
def test_scanned_demo_pages_are_scanned(name):
    pages = extract_pdf(ROOT / "demo" / "documents" / name, ExtractConfig(), FakeOCR())
    assert {p.page_class for p in pages} == {"SCANNED"}
