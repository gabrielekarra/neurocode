from __future__ import annotations

from pathlib import Path

from neurocode.embedding_model import (
    EmbeddingItem,
    EmbeddingStore,
    embedding_store_from_toon,
    embedding_store_to_toon,
    load_embedding_store,
    save_embedding_store,
)


def test_embedding_store_roundtrip(tmp_path: Path) -> None:
    store = EmbeddingStore.new(repo_root=tmp_path, engine_version="0.0.0", model="dummy", provider="dummy")
    store.items.append(
        EmbeddingItem(
            kind="function",
            id="package.mod.fn",
            module="package.mod",
            name="fn",
            file="package/mod.py",
            lineno=1,
            signature="def fn()",
            docstring=None,
            text="sample text",
            embedding=[0.1, 0.2, 0.3],
        )
    )
    toon = embedding_store_to_toon(store)
    parsed = embedding_store_from_toon(toon)
    assert parsed.model == "dummy"
    assert parsed.provider == "dummy"
    assert parsed.items[0].id == "package.mod.fn"
    assert parsed.items[0].embedding == [0.1, 0.2, 0.3]

    path = tmp_path / "store.toon"
    save_embedding_store(store, path)
    loaded = load_embedding_store(path)
    assert loaded.items[0].name == "fn"
