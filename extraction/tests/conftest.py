import pytest

from ingestion.config import ExtractConfig
from ingestion.embedding import HashingEmbedder
from ingestion.index_vector import VectorIndex
from ingestion.jobs import JobQueue
from ingestion.service import Knowledge
from ingestion.store import KnowledgeStore
from ingestion.types import OcrResult, OcrUsage


class FakeOCR:
    """Returns prepared results in order (the last one repeats); records how often it was called."""

    def __init__(self, *results: OcrResult | Exception):
        self.results = list(results) or [ocr_result("Scanned text of the page.")]
        self.calls = 0
        self.images = []

    def read(self, image) -> OcrResult:
        self.calls += 1
        self.images.append(image.size)
        r = self.results[min(self.calls - 1, len(self.results) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


def ocr_result(text: str, *, words: int | None = None, illegible: int = 0, confidence: str = "high",
               handwriting: bool = False, table: bool = False) -> OcrResult:
    return OcrResult(text_markdown=text, has_handwriting=handwriting, has_table=table, illegible_count=illegible,
                     word_count=words if words is not None else len(text.split()), self_confidence=confidence,
                     usage=OcrUsage(model="fake-vision", input_tokens=1290, output_tokens=410, latency_ms=10,
                                    cost_usd="0.0004"))


META = {"title": "Travel and Expense Policy", "category": "HR policy", "version": "2.0",
        "effective_date": "2026-04-01"}


@pytest.fixture
def cfg(tmp_path) -> ExtractConfig:
    return ExtractConfig(data_dir=tmp_path / "data", qdrant_url=None)


@pytest.fixture
def fake_ocr() -> FakeOCR:
    return FakeOCR()


@pytest.fixture
def make_knowledge(cfg):
    def make(ocr=None) -> Knowledge:
        store = KnowledgeStore(cfg.db_path)
        vector = VectorIndex(HashingEmbedder(), "test_kb", path=":memory:")
        return Knowledge(cfg, store, vector, ocr if ocr is not None else FakeOCR(), JobQueue(inline=True))
    return make


@pytest.fixture
def k(make_knowledge, fake_ocr) -> Knowledge:
    return make_knowledge(fake_ocr)
