from __future__ import annotations

from neurocode.embedding_provider import DummyEmbeddingProvider


def test_dummy_provider_deterministic() -> None:
    provider = DummyEmbeddingProvider(dim=8)
    text = "hello world"
    first = provider.embed_batch([text])[0]
    second = provider.embed_batch([text])[0]
    assert first == second
    assert len(first) == 8


def test_dummy_provider_differs() -> None:
    provider = DummyEmbeddingProvider(dim=8)
    a = provider.embed_batch(["alpha"])[0]
    b = provider.embed_batch(["beta"])[0]
    assert a != b


def test_make_embedding_provider_allows_dummy_when_enabled() -> None:
    from neurocode.config import Config
    from neurocode.embedding_provider import make_embedding_provider

    cfg = Config()
    cfg.embedding_allow_dummy = True
    provider, name, model = make_embedding_provider(cfg, allow_dummy=True)
    assert name == "dummy"
    assert model == "dummy-embedding-v0"
