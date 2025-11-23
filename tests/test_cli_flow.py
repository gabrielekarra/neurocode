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


def test_cli_end_to_end_flow(sample_repo: Path, project_root: Path) -> None:
    build = _run_cli(project_root, "ir", str(sample_repo))
    assert build.returncode == 0, build.stderr

    status = _run_cli(project_root, "status", str(sample_repo))
    assert status.returncode == 0, status.stderr

    target_file = sample_repo / "package" / "mod_a.py"
    check = _run_cli(project_root, "check", str(target_file), "--status")
    assert check.returncode == 1, check.stdout  # findings expected in sample_repo
    assert "status exit_code=1" in check.stdout

    patch = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        "flow dry run",
        "--strategy",
        "guard",
        "--dry-run",
        "--show-diff",
    )
    assert patch.returncode == 0, patch.stderr
    assert "---" in patch.stdout and "+++" in patch.stdout
