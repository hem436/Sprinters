"""Issue #51: Gemini free-tier rate limits are paced and waited out, not turned into failed documents."""
from types import SimpleNamespace

import pytest
from PIL import Image

from ingestion import keys
from ingestion.config import ExtractConfig
from ingestion.embedding import EmbeddingRateLimited, GeminiEmbedder, RateLimiter
from ingestion.ocr import GeminiOCR, OcrPage

PER_MINUTE = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'Embed content requests per minute limit "
              "exceeded on Free Tier.', 'details': [{'violations': [{'quotaId': "
              "'EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier', 'quotaDimensions': {'model': "
              "'gemini-embedding-2'}, 'quotaValue': '100'}]}, {'retryDelay': '10s'}]}}")
PER_DAY = ("429 RESOURCE_EXHAUSTED. {'quotaId': 'EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier', "
           "'quotaValue': '1000', 'retryDelay': '77428s'}")


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(round(s, 2))
        self.now += s


def test_quota_info_from_the_issue_error():
    info = keys.quota_info(Exception(PER_MINUTE))
    assert info == {"quota_id": "EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier",
                    "quota_value": "100", "model": "gemini-embedding-2", "retry_delay_s": 10.0}
    assert keys.is_per_minute(Exception(PER_MINUTE)) and not keys.is_daily_cap(Exception(PER_MINUTE))
    assert keys.is_daily_cap(Exception(PER_DAY)) and not keys.is_per_minute(Exception(PER_DAY))


def test_limiter_keeps_under_the_per_minute_limit():
    clock = Clock()
    lim = RateLimiter(100, clock=clock.time, sleep=clock.sleep)
    assert lim.acquire(60) == 0
    clock.now = 10
    assert lim.acquire(30) == 0                    # 90 in the window: fits
    clock.now = 20
    waited = lim.acquire(30)                       # 120 would not fit: wait until the first 60 leave (t = 60)
    assert 39.9 < waited < 40.2 and clock.now >= 60
    assert RateLimiter(0).acquire(10_000) == 0     # 0 = pacing off (paid tier)


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.batches = []

    def embed_content(self, model, contents, config):
        self.batches.append(len(contents))
        out = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0]) for _ in contents])


def _embedder(monkeypatch, outcomes, **cfg):
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    monkeypatch.delenv("GEMINI_FALLBACK_KEY", raising=False)
    keys.reset()
    clock = Clock()
    e = GeminiEmbedder(ExtractConfig(**cfg), sleep=clock.sleep)
    e.limiter = RateLimiter(e.cfg.embed_requests_per_minute, clock=clock.time, sleep=clock.sleep)
    models = FakeModels(outcomes)
    e._client_for = lambda key: SimpleNamespace(models=models)
    return e, models, clock


def test_per_minute_429_is_waited_out(monkeypatch):
    e, models, clock = _embedder(monkeypatch, [Exception(PER_MINUTE), Exception(PER_MINUTE)])
    assert len(e.embed_documents(["a", "b", "c"])) == 3
    assert clock.sleeps == [11.0, 11.0]            # Google's 10 s, plus 1 s


def test_long_document_paced_in_batches(monkeypatch):
    e, models, clock = _embedder(monkeypatch, [], embed_requests_per_minute=90, embed_batch_size=32)
    assert len(e.embed_documents([f"chunk {i}" for i in range(200)])) == 200
    assert max(models.batches) <= 32 and sum(models.batches) == 200
    assert clock.now >= 60                         # 200 requests at 90 a minute need more than one minute


def test_waiting_has_a_limit(monkeypatch):
    e, _, _ = _embedder(monkeypatch, [Exception(PER_MINUTE)] * 50, embed_max_wait_s=30)
    with pytest.raises(EmbeddingRateLimited, match="EmbedContentRequestsPerMinute.*limit 100.*waited"):
        e.embed_documents(["a"])


def test_daily_cap_fails_at_once_with_the_quota_named(monkeypatch):
    e, _, clock = _embedder(monkeypatch, [Exception(PER_DAY)])
    with pytest.raises(EmbeddingRateLimited, match="PerDay.*GEMINI_FALLBACK_KEY"):
        e.embed_documents(["a"])
    assert clock.sleeps == []


def test_ocr_waits_out_per_minute_without_using_attempts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    monkeypatch.delenv("GEMINI_FALLBACK_KEY", raising=False)
    keys.reset()
    clock = Clock()
    page = OcrPage(text_markdown="ok", has_handwriting=False, has_table=False, illegible_count=0, word_count=1,
                   self_confidence="high")
    ok = SimpleNamespace(parsed=page, text=page.model_dump_json(), usage_metadata=None)
    gen_429 = Exception(PER_MINUTE.replace("Embed content", "Generate content").replace("EmbedContent", "Generate"))
    models = SimpleNamespace(outcomes=[gen_429, gen_429, gen_429, ok])

    def generate_content(model, contents, config):
        out = models.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
    engine = GeminiOCR(ExtractConfig(ocr_attempts=3), sleep=clock.sleep)
    engine._client_for = lambda key: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    assert engine.read(Image.new("RGB", (10, 10))).text_markdown == "ok"     # 3 waits did not use up 3 attempts
    assert clock.sleeps == [11.0, 11.0, 11.0]


def test_failed_document_names_the_quota(tmp_path, k):
    from tests import files
    from tests.conftest import META

    class LimitedVector:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

        def upsert(self, chunks):
            raise EmbeddingRateLimited(keys.describe_quota(Exception(PER_DAY)) + ": the daily quota is used up")
    k.vector = LimitedVector(k.vector)
    doc = k.submit_document(files.text_pdf(tmp_path / "p.pdf", [["Plain text page with words."]]), META)
    d = k.store.get_document(doc["document_id"])
    assert d["status"] == "FAILED" and "EmbedContentRequestsPerDay" in d["error"] and "limit 1000" in d["error"]
