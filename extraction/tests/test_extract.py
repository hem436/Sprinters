"""WP-EX2: X3 page classes, X4 cleaning, text and tables; DOCX and TXT sections (contract 10 sections 4 to 6)."""
from ingestion.classify import PageSignals, classify
from ingestion.config import ExtractConfig
from ingestion.loaders.docx import extract_docx
from ingestion.loaders.pdf import extract_pdf
from ingestion.loaders.text import extract_text
from tests import files
from tests.conftest import FakeOCR

CFG = ExtractConfig()


def _signals(**kw) -> PageSignals:
    base = {"chars": 500, "cid_ratio": 0.0, "image_cover": 0.0, "tables": 0, "num_ratio": 0.0}
    return PageSignals(**{**base, **kw})


def test_class_rules_in_order():
    assert classify(_signals(chars=2, image_cover=0.0), CFG) == "BLANK"
    assert classify(_signals(cid_ratio=0.2), CFG) == "GARBLED"
    assert classify(_signals(chars=10, image_cover=0.9), CFG) == "SCANNED"
    assert classify(_signals(chars=300, image_cover=0.6), CFG) == "MIXED"
    assert classify(_signals(tables=1), CFG) == "TABLE_HEAVY"
    assert classify(_signals(num_ratio=0.4), CFG) == "TABLE_HEAVY"
    assert classify(_signals(), CFG) == "TEXT"
    # GARBLED is checked before SCANNED: broken fonts on an image page still go to OCR as GARBLED
    assert classify(_signals(chars=10, image_cover=0.9, cid_ratio=0.5), CFG) == "GARBLED"


def test_mixed_pdf_ocrs_only_scanned_pages(tmp_path):
    ocr = FakeOCR()
    pages = extract_pdf(files.mixed_pdf(tmp_path / "m.pdf"), CFG, ocr)
    assert [p.page_class for p in pages] == ["TEXT", "TEXT", "TEXT", "SCANNED"]
    assert ocr.calls == 1
    assert [p.method for p in pages] == ["text", "text", "text", "ocr"]
    assert all(b.method == "ocr" for b in pages[3].blocks)


def test_ocr_render_is_1600_px(tmp_path):
    ocr = FakeOCR()
    extract_pdf(files.scanned_pdf(tmp_path / "s.pdf"), CFG, ocr)
    assert abs(max(ocr.images[0]) - 1600) <= 2


def test_table_kept_whole_with_unit(tmp_path):
    pages = extract_pdf(files.table_pdf(tmp_path / "t.pdf"), CFG, FakeOCR())
    tables = [b for b in pages[0].blocks if b.type == "table"]
    assert len(tables) == 1
    t = tables[0]
    assert "₹ in crore" in t.unit
    assert t.caption.startswith("Statement of profit and loss")
    assert t.rows[0] == ["Particulars", "FY2024-25", "FY2023-24"]
    assert "| Revenue from operations | 11,256 | 10,050 |" in t.text
    # the table numbers are not repeated as loose text
    loose = " ".join(b.text for b in pages[0].blocks if b.type != "table")
    assert "11,256" not in loose
    assert pages[0].page_class == "TABLE_HEAVY" and pages[0].method == "text+tables"


def test_numbers_unchanged(tmp_path):
    pages = extract_pdf(files.table_pdf(tmp_path / "t.pdf"), CFG, FakeOCR())
    text = pages[0].text
    for printed in ("(1,234)", "1,23,456", "2,345.50", "98,765"):
        assert printed in text


def test_running_header_footer_removed_and_page_number_kept(tmp_path):
    pdf = files.text_pdf(tmp_path / "h.pdf", [["# 4 Travel", "", "Para one of page.", "manage-", "ment continues."],
                                              ["# 4.2 Per diem", "", "Mumbai per diem is ₹2,000 a day."],
                                              ["Third page text body here."]],
                         header="Arka Fintech Services - Confidential", footer=True)
    pages = extract_pdf(pdf, CFG, FakeOCR())
    all_text = " ".join(p.text for p in pages)
    assert "Confidential" not in all_text and "Page 2 of 3" not in all_text
    assert pages[1].printed_page == "2"
    assert "Arka Fintech Services - Confidential" in pages[0].removed_lines
    # hyphen join and line join inside a paragraph
    assert "Para one of page. management continues." in pages[0].text
    # the section path carries over to the next page
    assert pages[1].blocks[0].section == "4 Travel > 4.2 Per diem"
    assert pages[2].blocks[0].section == "4 Travel > 4.2 Per diem"


def test_heading_with_changing_number_is_not_a_header(tmp_path):
    pages = extract_pdf(files.mixed_pdf(tmp_path / "m.pdf"), CFG, FakeOCR())
    assert pages[0].blocks[0].type == "heading" and pages[0].blocks[0].text == "Section 1 Travel rules"
    assert "Line 0 of the travel" in pages[1].text


def test_two_column_page_reads_left_then_right(tmp_path):
    pages = extract_pdf(files.two_column_pdf(tmp_path / "c.pdf"), CFG, FakeOCR())
    text = pages[0].text
    assert "TWO_COLUMN" in pages[0].flags
    assert text.index("Left column sentence number 29") < text.index("Right column sentence number 00")


def test_docx_sections_and_table(tmp_path):
    units = extract_docx(files.docx_file(tmp_path / "a.docx"))
    labels = [u.section_label for u in units]
    assert labels == ["IT Security Standard Operating Procedure", "1 Scope", "2 Laptop controls > 2.1 Encryption"]
    last = units[-1]
    table = next(b for b in last.blocks if b.type == "table")
    assert table.unit == "(in %)" and table.rows[1] == ["Q1", "92"]
    assert any(b.type == "list" for b in last.blocks)
    assert all(u.page == i + 1 for i, u in enumerate(units))


def test_txt_sections_and_line_ranges(tmp_path):
    faq = tmp_path / "faq.txt"
    faq.write_text("ONBOARDING FAQ\n\n1 Laptops\nYou get a laptop on day one.\n\n2 Leave\nLeave rules are here.\n",
                   encoding="utf-8")
    units = extract_text(faq)
    # the ALL-CAPS title and "1 Laptops" are both level 1, so the title joins the first unit
    assert [u.section_label for u in units] == ["1 Laptops", "2 Leave"]
    assert units[0].blocks[0].text == "ONBOARDING FAQ"

    plain = tmp_path / "plain.txt"
    plain.write_text("\n".join(f"plain line {i} without any heading at all." for i in range(1, 91)), encoding="cp1252")
    units = extract_text(plain)
    assert units[0].section_label == "lines 1-40"
    assert units[-1].section_label.endswith("-90")


def test_garbled_page_goes_to_ocr(tmp_path):
    """A text layer full of (cid:NN) is unusable; the page is read by OCR instead."""
    from ingestion.classify import page_signals

    class FakePage:
        width, height = 595, 842
        images: list = []

        def extract_text(self):
            return "(cid:12)(cid:13)(cid:14) ab " * 20

        def find_tables(self):
            return []

    s = page_signals(FakePage())
    assert s.cid_ratio > 0.5 and classify(s, CFG) == "GARBLED"
