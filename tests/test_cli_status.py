from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_cli(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "neurocode.cli", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
    )


def test_cli_status_fresh(repo_with_ir: Path, project_root: Path) -> None:
    result = _run_cli(project_root, "status", str(repo_with_ir))
    assert result.returncode == 0, result.stderr
    assert "IR is fresh" in result.stdout or "fresh=" in result.stdout


def test_cli_status_stale_detected(sample_repo: Path, project_root: Path) -> None:
    # Build IR
    build = _run_cli(project_root, "ir", str(sample_repo))
    assert build.returncode == 0, build.stderr

    target_file = sample_repo / "package" / "mod_a.py"
    target_file.write_text(target_file.read_text(encoding="utf-8") + "\n")

    result = _run_cli(project_root, "status", str(sample_repo))
    assert result.returncode == 1
    assert "stale" in result.stdout or "missing" in result.stdout
