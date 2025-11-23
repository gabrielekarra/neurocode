from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import List, Sequence


class EmbeddingProvider(ABC):
    """Interface for embedding providers."""

    @abstractmethod
    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        """Return embeddings for each text in order."""


class DummyEmbeddingProvider(EmbeddingProvider):
    """Deterministic, offline embeddings for testing and local/dev use only."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in texts:
            h = hashlib.sha256(text.encode("utf-8")).digest()
            data = h * ((self.dim // len(h)) + 1)
            vals = []
            for i in range(self.dim):
                b = data[i]
                vals.append((b % 256) / 255.0)
            vectors.append(vals)
        return vectors


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by OpenAI-compatible API."""

    def __init__(self, model: str, api_key: str, base_url: str | None = None, dim: int | None = None) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url or "https://api.openai.com/v1/embeddings"
        self.dim = dim

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        import json
        import time
        import urllib.error
        import urllib.request

        payload = {"model": self.model, "input": list(texts)}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        attempts = 0
        last_error: Exception | None = None
        while attempts < 3:
            attempts += 1
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_data = resp.read()
                parsed = json.loads(resp_data.decode("utf-8"))
                embeddings = [item["embedding"] for item in parsed.get("data", [])]
                if self.dim:
                    embeddings = [vec[: self.dim] for vec in embeddings]
                return embeddings
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                time.sleep(2**attempts * 0.1)
        raise RuntimeError(f"Failed to fetch embeddings from OpenAI: {last_error}") from last_error


def _resolve_api_key(config, override: str | None) -> str | None:
    if override:
        return override
    if getattr(config, "embedding_api_key", None):
        return config.embedding_api_key
    import os

    return os.getenv("OPENAI_API_KEY")


def make_embedding_provider(
    config,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
    allow_dummy: bool = False,
) -> tuple[EmbeddingProvider, str, str]:
    provider_name = provider_override or getattr(config, "embedding_provider", None) or "dummy"
    model_name = model_override or getattr(config, "embedding_model", None) or "dummy-embedding-v0"

    if provider_name == "dummy":
        if not allow_dummy and not getattr(config, "embedding_allow_dummy", False):
            raise RuntimeError("Dummy embedding provider is disabled; configure a real provider or enable allow_dummy.")
        return DummyEmbeddingProvider(), provider_name, model_name

    if provider_name == "openai":
        api_key = _resolve_api_key(config, getattr(config, "embedding_api_key", None))
        if not api_key:
            raise RuntimeError(
                "OpenAI provider requires an API key (set embedding.api_key in config or OPENAI_API_KEY)."
            )
        base_url = getattr(config, "embedding_base_url", None)
        provider = OpenAIEmbeddingProvider(model=model_name, api_key=api_key, base_url=base_url)
        return provider, provider_name, model_name

    raise RuntimeError(f"Unknown embedding provider: {provider_name}")
