from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import List, Sequence


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        """Return embeddings for each text in order."""


class DummyEmbeddingProvider(EmbeddingProvider):
    """Deterministic, offline embeddings for testing and local use."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in texts:
            h = hashlib.sha256(text.encode("utf-8")).digest()
            # Expand hash deterministically to requested dimension.
            data = h * ((self.dim // len(h)) + 1)
            vals = []
            for i in range(self.dim):
                b = data[i]
                vals.append((b % 256) / 255.0)
            vectors.append(vals)
        return vectors
