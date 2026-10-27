"""Calls the real Gemini models. Skipped by default; run with:  pytest -m live  (needs GEMINI_API_KEY in .env)."""
import os

import pytest
from PIL import Image, ImageDraw

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _needs_key():
    from dotenv import load_dotenv
    load_dotenv()
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set")


def test_live_ocr_returns_json_with_tokens():
    from ingestion.config import load_config
    from ingestion.ocr import GeminiOCR

    img = Image.new("RGB", (1200, 500), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 40), "4.2 Per diem", fill="black")
    d.text((40, 100), "Mumbai: Rs 2,000 per day (1,234)", fill="black")
    out = GeminiOCR(load_config()).read(img)
    assert "2,000" in out.text_markdown
    assert out.usage.input_tokens > 0 and out.usage.output_tokens > 0


def test_live_embedding():
    from ingestion.config import load_config
    from ingestion.embedding import GeminiEmbedder

    e = GeminiEmbedder(load_config())
    v = e.embed_query("per diem in Mumbai")
    assert len(v) == e.dim > 0


def test_live_table_reader(tmp_path):
    from ingestion.config import load_config
    from ingestion.fin_ai import GeminiTableReader
    from ingestion.ocr import render_pdf_page
    from tests import files

    cfg = load_config()
    pdf = files.unruled_numbers_pdf(tmp_path / "v.pdf")
    tables, usage = GeminiTableReader(cfg).read_tables(render_pdf_page(str(pdf), 1, cfg.ocr_max_edge_px))
    cells = [c for t in tables for r in t.header_rows + t.rows for c in r]
    assert "9,000" in cells and "8,190" in cells and usage.input_tokens > 0


def test_live_label_mapper():
    from ingestion.config import load_config
    from ingestion.fin_ai import GeminiLabelMapper

    out, _ = GeminiLabelMapper(load_config()).propose(["Total income from operations", "Staff welfare canteen"])
    assert out.get("Total income from operations") == "revenue"
    assert "Staff welfare canteen" not in out
