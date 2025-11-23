from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .embedding_model import EmbeddingItem, EmbeddingStore, load_embedding_store
from .embedding_provider import DummyEmbeddingProvider, EmbeddingProvider
from .ir_model import RepositoryIR
from .toon_parse import load_repository_ir


@dataclass
class SearchResult:
    id: str
    kind: str
    module: str
    name: str
    file: str
    lineno: int
    signature: str
    score: float


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _filter_items(items: List[EmbeddingItem], module_filter: str | None) -> List[EmbeddingItem]:
    if not module_filter:
        return items
    return [
        item
        for item in items
        if item.module == module_filter or item.module.startswith(f"{module_filter}.")
    ]


def _resolve_like_symbol(store: EmbeddingStore, symbol: str) -> EmbeddingItem:
    normalized = symbol.replace(":", ".")
    for item in store.items:
        if item.id == normalized:
            return item
    raise RuntimeError(f"Symbol not found in embeddings: {symbol}")


def search_embeddings(
    repository_ir: RepositoryIR,
    embedding_store: EmbeddingStore,
    query_embedding: List[float],
    *,
    module_filter: str | None = None,
    k: int = 10,
) -> List[SearchResult]:
    candidates = [item for item in embedding_store.items if item.kind == "function"]
    candidates = _filter_items(candidates, module_filter)

    scored: List[SearchResult] = []
    for item in candidates:
        score = _cosine_similarity(query_embedding, item.embedding)
        scored.append(
            SearchResult(
                id=item.id,
                kind=item.kind,
                module=item.module,
                name=item.name,
                file=item.file,
                lineno=item.lineno,
                signature=item.signature,
                score=score,
            )
        )

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:k]


def load_ir_and_embeddings(repo_root: Path) -> tuple[RepositoryIR, EmbeddingStore]:
    ir_file = repo_root / ".neurocode" / "ir.toon"
    if not ir_file.is_file():
        raise RuntimeError(
            f"{ir_file} not found. Run `neurocode ir {repo_root}` first."
        )
    ir = load_repository_ir(ir_file)

    emb_file = repo_root / ".neurocode" / "ir-embeddings.toon"
    if not emb_file.is_file():
        raise RuntimeError(
            f"{emb_file} not found. Run `neurocode embed {repo_root}` first."
        )
    store = load_embedding_store(emb_file)
    return ir, store


def build_query_embedding_from_text(text: str, provider: EmbeddingProvider | None = None) -> List[float]:
    provider = provider or DummyEmbeddingProvider()
    vectors = provider.embed_batch([text])
    return vectors[0]


def build_query_embedding_from_symbol(store: EmbeddingStore, symbol: str) -> List[float]:
    item = _resolve_like_symbol(store, symbol)
    if not item.embedding:
        raise RuntimeError(f"No embedding available for symbol: {symbol}")
    return item.embedding
