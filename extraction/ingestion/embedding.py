"""X9 embeddings (contract 10 section 9, config embed.*).

- GeminiEmbedder: the hosted model the chatbot repo uses, through google-genai; batches, backoff, key rotation.
- LocalEmbedder: sentence-transformers, only when installed and chosen (embed.fallback_model).
- HashingEmbedder: no network, no model; for tests and offline runs only. It finds shared words, not meaning.

Each embedder has a `name` such as "gemini:gemini-embedding-2-preview:3072". The vector index stores it and refuses
a different one, because vectors of two models must never share a collection (a change needs a re-index).
"""
import hashlib
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from typing import Protocol

from ingestion import keys
from ingestion.config import ExtractConfig

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingCountError(RuntimeError):
    """The model returned a different number of vectors than texts: never index such a batch."""


class EmbeddingRateLimited(RuntimeError):
    """A quota the code cannot wait out: a daily cap on every key, or more waiting than embed.max_wait_s."""


class RateLimiter:
    """At most `per_minute` requests in any 60 s, shared by every embedder of the process for one model (the
    ingest worker and the search path count against the same Google quota). `acquire(n)` waits until n fit."""

    def __init__(self, per_minute: int, clock=time.monotonic, sleep=time.sleep):
        self.per_minute = per_minute
        self._clock, self._sleep = clock, sleep
        self._sent: list[tuple[float, int]] = []          # (time, requests)
        self._lock = threading.Lock()

    def acquire(self, n: int) -> float:
        """Returns the seconds waited."""
        if self.per_minute <= 0:
            return 0.0
        n = min(n, self.per_minute)
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                self._sent = [(t, k) for t, k in self._sent if now - t < 60]
                used = sum(k for _, k in self._sent)
                if used + n <= self.per_minute:
                    self._sent.append((now, n))
                    return waited
                # wait until enough of the oldest requests leave the 60 s window
                free, wait = used + n - self.per_minute, 0.0
                for t, k in self._sent:
                    free -= k
                    if free <= 0:
                        wait = 60 - (now - t) + 0.05
                        break
            self._sleep(wait)
            waited += wait


_limiters: dict[str, RateLimiter] = {}
_limiters_lock = threading.Lock()


def limiter_for(model: str, per_minute: int) -> RateLimiter:
    with _limiters_lock:
        if model not in _limiters or _limiters[model].per_minute != per_minute:
            _limiters[model] = RateLimiter(per_minute)
        return _limiters[model]


class GeminiEmbedder:
    def __init__(self, cfg: ExtractConfig, sleep=time.sleep, cache_size: int = 256):
        self.cfg = cfg
        self._sleep = sleep
        self._client = None
        self._key = None
        self._dim = cfg.embed_dim
        self.limiter = limiter_for(cfg.embed_model, cfg.embed_requests_per_minute)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size

    @property
    def name(self) -> str:
        return f"gemini:{self.cfg.embed_model}:{self.dim}"

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self._embed(["dimension probe"], "RETRIEVAL_QUERY")[0])
        return self._dim

    def _client_for(self, key: str):
        if self._client is None or key != self._key:
            from google import genai
            from google.genai import types
            self._client = genai.Client(api_key=key,
                                        http_options=types.HttpOptions(timeout=self.cfg.embed_timeout_s * 1000))
            self._key = key
        return self._client

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import types

        key = keys.current()
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set; embeddings need it (or choose another embedder).")
        config = types.EmbedContentConfig(task_type=task, output_dimensionality=self.cfg.embed_dim)
        # One Content per text. gemini-embedding-2-preview reads a plain list of strings as ONE multimodal input and
        # returns a single vector for all of them (found on the demo corpus, 27 Oct 2026).
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
        attempt = 0
        waited = 0.0
        while True:
            self.limiter.acquire(len(texts))                # each text is one request on Google's side
            try:
                resp = self._client_for(key).models.embed_content(model=self.cfg.embed_model, contents=contents,
                                                                  config=config)
                vectors = [list(e.values) for e in resp.embeddings]
                if len(vectors) != len(texts):
                    raise EmbeddingCountError(f"{self.cfg.embed_model} returned {len(vectors)} vectors for "
                                              f"{len(texts)} texts")
                return vectors
            except EmbeddingCountError:
                raise
            except Exception as e:
                if keys.is_quota_error(e):
                    nxt = keys.rotate()
                    if nxt:
                        key = nxt
                        continue
                    if keys.is_per_minute(e):
                        # issue #51: wait the delay Google asks for (15 s if it gives none) and keep going
                        delay = max(keys.quota_info(e).get("retry_delay_s", 15.0), 5.0) + 1.0
                        if waited + delay > self.cfg.embed_max_wait_s:
                            raise EmbeddingRateLimited(f"{keys.describe_quota(e)}; waited {waited:.0f} s, the "
                                                       f"limit embed.max_wait_s is {self.cfg.embed_max_wait_s} s") from e
                        log.warning("embedding: %s; waiting %.0f s", keys.describe_quota(e), delay)
                        self._sleep(delay)
                        waited += delay
                        continue
                    if keys.is_daily_cap(e):
                        raise EmbeddingRateLimited(f"{keys.describe_quota(e)}: the daily quota is used up on every "
                                                   "key; add GEMINI_FALLBACK_KEY from another project") from e
                attempt += 1
                if attempt < 4 and (keys.is_quota_error(e) or keys.is_transient(e)):
                    self._sleep(2 ** (attempt - 1))
                    continue
                if keys.is_quota_error(e):
                    raise EmbeddingRateLimited(keys.describe_quota(e)) from e
                raise

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # a batch never asks for more than the per-minute pace allows in one go
        size = self.cfg.embed_batch_size
        if self.cfg.embed_requests_per_minute > 0:
            size = min(size, self.cfg.embed_requests_per_minute)
        out: list[list[float]] = []
        for i in range(0, len(texts), size):
            out.extend(self._embed(texts[i:i + size], "RETRIEVAL_DOCUMENT"))
        return out

    def embed_query(self, text: str) -> list[float]:
        """Cached: the eval runs and the demo ask the same questions many times against a daily quota."""
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        vector = self._embed([text], "RETRIEVAL_QUERY")[0]
        self._cache[text] = vector
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return vector


class LocalEmbedder:
    def __init__(self, cfg: ExtractConfig):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("sentence-transformers is not installed (see requirements.txt, optional)") from e
        self._model = SentenceTransformer(cfg.embed_fallback_model)
        self.name = f"local:{cfg.embed_fallback_model}:{self.dim}"

    @property
    def dim(self) -> int:
        return int(self._model.get_sentence_embedding_dimension())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode([text], show_progress_bar=False)[0].tolist()


_WORD = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Bag of words hashed into `dim` buckets, L2-normalised. Deterministic; for tests and offline runs only."""

    def __init__(self, dim: int = 256):
        self._dim = dim
        self.name = f"hashing:{dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        for w in _WORD.findall(text.lower()):
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            v[h % self._dim] += 1.0 if (h >> 64) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def default_embedder(cfg: ExtractConfig) -> Embedder:
    return GeminiEmbedder(cfg)
