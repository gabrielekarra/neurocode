from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from neurocode.embedding_model import load_embedding_store


def _run_cli(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "neurocode.cli", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
    )


def test_cli_embed_creates_store(repo_with_ir: Path, project_root: Path) -> None:
    result = _run_cli(project_root, "embed", str(repo_with_ir))
    assert result.returncode == 0, result.stderr

    store_path = repo_with_ir / ".neurocode" / "ir-embeddings.toon"
    assert store_path.exists()
    store = load_embedding_store(store_path)
    assert store.items
    ids = {item.id for item in store.items}
    assert "package.mod_a.orchestrator" in ids


def test_cli_embed_json(repo_with_ir: Path, project_root: Path) -> None:
    store_path = repo_with_ir / ".neurocode" / "ir-embeddings.toon"
    result = _run_cli(
        project_root,
        "embed",
        str(repo_with_ir),
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    assert store_path.exists()
    assert "items" in result.stdout
