"""X9 embeddings with a fake Gemini client (no network)."""
from types import SimpleNamespace

import pytest

from ingestion import keys
from ingestion.config import ExtractConfig
from ingestion.embedding import EmbeddingCountError, GeminiEmbedder


class FakeModels:
    def __init__(self, join_strings: bool = False):
        self.join_strings = join_strings
        self.calls = []

    def embed_content(self, model, contents, config):
        self.calls.append(contents)
        n = 1 if self.join_strings else len(contents)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(i), 1.0]) for i in range(n)])


def _embedder(monkeypatch, models):
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    keys.reset()
    e = GeminiEmbedder(ExtractConfig(embed_batch_size=2), sleep=lambda s: None)
    e._client_for = lambda key: SimpleNamespace(models=models)
    return e


def test_each_text_is_its_own_content(monkeypatch):
    """gemini-embedding-2-preview joins a plain list of strings into one input; we send one Content per text."""
    from google.genai import types

    models = FakeModels()
    vectors = _embedder(monkeypatch, models).embed_documents(["a", "b", "c"])
    assert len(vectors) == 3
    assert [len(c) for c in models.calls] == [2, 1]                       # batches of embed.batch_size
    assert all(isinstance(c, types.Content) and c.parts[0].text for batch in models.calls for c in batch)


def test_vector_count_mismatch_is_an_error(monkeypatch):
    with pytest.raises(EmbeddingCountError, match="returned 1 vectors for 2 texts"):
        _embedder(monkeypatch, FakeModels(join_strings=True)).embed_documents(["a", "b"])
