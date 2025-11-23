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


def test_openai_provider_stubbed(monkeypatch) -> None:
    from neurocode.embedding_provider import OpenAIEmbeddingProvider

    class FakeResp:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        import json

        data = {"data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}]}
        return FakeResp(json.dumps(data).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = OpenAIEmbeddingProvider(model="m", api_key="key", dim=2)
    vectors = provider.embed_batch(["a", "b"])
    assert len(vectors) == 2
    assert vectors[0][0] == 1.0
    assert vectors[1][1] == 1.0
