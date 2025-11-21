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


def test_cli_ir_writes_ir_file(sample_repo: Path, project_root: Path) -> None:
    result = _run_cli(project_root, "ir", str(sample_repo))
    assert result.returncode == 0, result.stderr

    ir_path = sample_repo / ".neurocode" / "ir.toon"
    assert ir_path.exists(), "IR file was not created"
    assert "IR written to" in result.stdout


def test_cli_explain_outputs_summary(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    result = _run_cli(project_root, "explain", str(target_file))

    assert result.returncode == 0, result.stderr
    assert "Module: package.mod_a" in result.stdout
    assert "Imports:" in result.stdout
    assert "Classes:" in result.stdout
    assert "(none)" in result.stdout  # mod_a has no classes
    assert "statistics" in result.stdout
    assert "Functions:" in result.stdout
    assert "package.mod_a.orchestrator" in result.stdout


def test_cli_explain_outputs_classes(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "classy.py"
    result = _run_cli(project_root, "explain", str(target_file))

    assert result.returncode == 0, result.stderr
    assert "Module: package.classy" in result.stdout
    assert "Processor" in result.stdout
    assert "Derived" in result.stdout
    assert "package.classy.Processor.add" in result.stdout


def test_cli_check_reports_findings(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    result = _run_cli(project_root, "check", str(target_file))

    assert result.returncode == 1, result.stdout
    assert "UNUSED_IMPORT" in result.stdout
    assert "UNUSED_FUNCTION" in result.stdout
    assert "HIGH_FANOUT" in result.stdout
    assert "statistics" in result.stdout
