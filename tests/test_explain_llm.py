from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from neurocode.explain_llm import build_explain_llm_bundle


def _run_cli(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "neurocode.cli", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
    )


def test_build_explain_llm_bundle(repo_with_ir: Path) -> None:
    # Ensure embeddings exist
    from neurocode.cli import main as _  # noqa: F401

    # Build embeddings using the CLI
    subprocess.run(
        [sys.executable, "-m", "neurocode.cli", "embed", str(repo_with_ir), "--provider", "dummy"],
        check=True,
        capture_output=True,
        text=True,
    )

    target_file = repo_with_ir / "package" / "mod_a.py"
    bundle = build_explain_llm_bundle(
        target_file,
        symbol="package.mod_a.orchestrator",
        k_neighbors=5,
    ).data

    assert bundle["file"] == "package/mod_a.py"
    assert bundle["module"] == "package.mod_a"
    assert bundle["target"]["symbol"] == "package.mod_a.orchestrator"
    assert bundle["ir"]["module_summary"]["functions"]
    assert bundle["checks"]  # mod_a has known diagnostics
    assert "semantic_neighbors" in bundle
    assert bundle["source"]["text"]
    # Cross-file context
    neighbors = bundle["call_graph_neighbors"]
    assert neighbors["callees"]
    assert any(item["path"].endswith("mod_b.py") for item in bundle["related_files"])
    slices = bundle["source_slices"]
    assert "package.mod_a:orchestrator" in slices
    assert "task_one" in slices["package.mod_a:orchestrator"]["text"]
    assert bundle["config"]["console_scripts"]


def test_cli_explain_llm_json(repo_with_ir: Path, project_root: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "neurocode.cli", "embed", str(repo_with_ir), "--provider", "dummy"],
        check=True,
        capture_output=True,
        text=True,
    )
    target_file = repo_with_ir / "package" / "mod_a.py"
    result = _run_cli(
        project_root,
        "explain-llm",
        str(target_file),
        "--symbol",
        "package.mod_a.orchestrator",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["module"] == "package.mod_a"
    assert "call_graph_neighbors" in payload
    assert payload["call_graph_neighbors"]["callees"]
    assert payload["source_slices"]
