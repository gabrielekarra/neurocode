from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from neurocode.embedding_model import EmbeddingItem, EmbeddingStore
from neurocode.ir_build import build_repository_ir
from neurocode.search import (
    build_query_embedding_from_symbol,
    search_embeddings,
)


def test_search_embeddings_rank_order(tmp_path: Path) -> None:
    store = EmbeddingStore.new(repo_root=tmp_path, engine_version="0.0.0", model="dummy", provider="dummy")
    store.items = [
        EmbeddingItem(
            kind="function",
            id="a.one",
            module="a",
            name="one",
            file="a.py",
            lineno=1,
            signature="def one()",
            docstring=None,
            text="one",
            embedding=[1.0, 0.0],
        ),
        EmbeddingItem(
            kind="function",
            id="b.two",
            module="b",
            name="two",
            file="b.py",
            lineno=1,
            signature="def two()",
            docstring=None,
            text="two",
            embedding=[0.0, 1.0],
        ),
    ]
    ir = build_repository_ir(tmp_path)
    query = [1.0, 0.0]
    results = search_embeddings(ir, store, query_embedding=query, k=2)
    assert results[0].id == "a.one"


def test_search_like_uses_existing_embedding(tmp_path: Path) -> None:
    store = EmbeddingStore.new(repo_root=tmp_path, engine_version="0.0.0", model="dummy", provider="dummy")
    store.items.append(
        EmbeddingItem(
            kind="function",
            id="pkg.mod.fn",
            module="pkg.mod",
            name="fn",
            file="pkg/mod.py",
            lineno=1,
            signature="def fn()",
            docstring=None,
            text="fn",
            embedding=[0.5, 0.5],
        )
    )
    emb = build_query_embedding_from_symbol(store, "pkg.mod.fn")
    assert emb == [0.5, 0.5]


def test_cli_search_text(repo_with_ir: Path, project_root: Path) -> None:
    embed = subprocess.run(
        [sys.executable, "-m", "neurocode.cli", "embed", str(repo_with_ir), "--provider", "dummy"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert embed.returncode == 0, embed.stderr

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "search",
            str(repo_with_ir),
            "--text",
            "value helper",
            "--provider",
            "dummy",
            "--format",
            "json",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "results" in payload
    assert payload["results"]


def test_cli_search_missing_store(sample_repo: Path, project_root: Path) -> None:
    ir = subprocess.run(
        [sys.executable, "-m", "neurocode.cli", "ir", str(sample_repo)],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert ir.returncode == 0, ir.stderr

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "search",
            str(sample_repo),
            "--text",
            "value helper",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "ir-embeddings" in result.stderr
