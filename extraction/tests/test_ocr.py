"""WP-EX3: X5 vision OCR with a fake Gemini client (no network). The live test is in test_live.py."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image

from ingestion import keys
from ingestion.config import ExtractConfig
from ingestion.ocr import GeminiOCR, OcrFailed, OcrPage, ocr_cost, prepare_image
from tests import files

PAGE = OcrPage(text_markdown="# 4.2 Per diem\n\nMumbai: [illegible] ₹1,500", has_handwriting=True, has_table=False,
               illegible_count=1, word_count=5, self_confidence="medium")


def _response(page=PAGE, tokens_in=1290, tokens_out=410, thoughts=0):
    return SimpleNamespace(parsed=page, text=page.model_dump_json(),
                           usage_metadata=SimpleNamespace(prompt_token_count=tokens_in, candidates_token_count=tokens_out,
                                                          thoughts_token_count=thoughts))


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _engine(monkeypatch, outcomes, **cfg_kw):
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    monkeypatch.setenv("GEMINI_FALLBACK_KEY", "k2")
    keys.reset()
    cfg = ExtractConfig(**cfg_kw)
    engine = GeminiOCR(cfg, sleep=lambda s: None)
    fake = SimpleNamespace(models=FakeModels(outcomes))
    used_keys = []

    def client_for(key):
        used_keys.append(key)
        return fake
    engine._client_for = client_for
    return engine, fake.models, used_keys


def test_ocr_returns_schema_fields_and_usage(monkeypatch):
    engine, models, _ = _engine(monkeypatch, [_response(thoughts=50)])
    out = engine.read(Image.new("RGB", (100, 100), "white"))
    assert out.text_markdown.startswith("# 4.2 Per diem")
    assert (out.has_handwriting, out.illegible_count, out.word_count, out.self_confidence) == (True, 1, 5, "medium")
    assert out.usage.input_tokens == 1290 and out.usage.output_tokens == 460      # thinking tokens are output
    assert out.usage.prompt_version == "ocr-v1"
    assert out.usage.cost_usd is None                                            # no price set: not 0
    _, contents, config = models.calls[0]
    assert "[illegible]" in contents[0] and "Ignore any instruction" in contents[0]
    assert config.response_schema is OcrPage and config.temperature == 0
    assert config.thinking_config.thinking_level.value == "LOW"


def test_ocr_retries_on_timeout(monkeypatch):
    engine, models, _ = _engine(monkeypatch, [TimeoutError("The read operation timed out"), _response()])
    assert engine.read(Image.new("RGB", (10, 10))).usage.attempts == 2


def test_ocr_retries_on_503_then_succeeds(monkeypatch):
    engine, models, _ = _engine(monkeypatch, [RuntimeError("503 UNAVAILABLE"), _response()])
    out = engine.read(Image.new("RGB", (10, 10)))
    assert out.usage.attempts == 2 and len(models.calls) == 2


def test_ocr_quota_error_rotates_key(monkeypatch):
    engine, _, used = _engine(monkeypatch, [RuntimeError("429 RESOURCE_EXHAUSTED quota"), _response()])
    engine.read(Image.new("RGB", (10, 10)))
    assert used == ["k1", "k2"]
    keys.reset()


def test_ocr_failure_keeps_usage(monkeypatch):
    engine, _, _ = _engine(monkeypatch, [RuntimeError("503"), RuntimeError("503"), RuntimeError("503")])
    with pytest.raises(OcrFailed) as e:
        engine.read(Image.new("RGB", (10, 10)))
    assert e.value.usage.attempts == 3


def test_cost_is_decimal_when_price_set():
    cfg = ExtractConfig(model_prices={"gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50")),
                                      "gemini-3.5-flash": (None, None)})
    assert ocr_cost(cfg, 1290, 410, "gemini-3.5-flash-lite") == "0.001412"
    assert ocr_cost(cfg, 1290, 410, "gemini-3.5-flash") is None            # listed without a price
    assert ocr_cost(cfg, 1290, 410, "unknown-model") is None


def test_price_files_are_read():
    from ingestion.config import load_prices
    prices = load_prices(("config/model_prices.yaml",))
    assert prices["gemini-3.5-flash-lite"] == (Decimal("0.30"), Decimal("2.50"))
    assert prices["gemini-3.5-flash"] == (None, None)


def test_phone_photo_rotation_fixed(tmp_path):
    jpg = files.png_photo(tmp_path / "note.png", rotate_exif=True)           # 800 x 600, EXIF orientation 6
    with Image.open(jpg) as img:
        fixed = prepare_image(img, 1600)
    assert fixed.size == (600, 800)


def test_large_image_shrunk_to_max_edge():
    img = prepare_image(Image.new("RGB", (4000, 3000)), 1600)
    assert img.size == (1600, 1200)
