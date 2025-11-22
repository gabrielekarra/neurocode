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


def test_cli_patch_inserts_todo_comment(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    fix_description = "Handle edge cases in orchestrator"

    result = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        fix_description,
        "--strategy",
        "guard",
    )

    assert result.returncode == 0, result.stderr

    contents = target_file.read_text(encoding="utf-8")
    assert "if value is None:" in contents
    assert f'raise ValueError("neurocode guard: {fix_description}")' in contents
    assert contents.index("if value is None:") > contents.index("def orchestrator")


def test_cli_patch_dry_run_guard(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    fix_description = "dry run guard"

    result = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        fix_description,
        "--strategy",
        "guard",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    contents = target_file.read_text(encoding="utf-8")
    assert "neurocode guard: dry run guard" not in contents
    assert "---" in result.stdout and "+++" in result.stdout


def test_cli_patch_show_diff_applies(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_b.py"
    fix_description = "show diff"

    result = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        fix_description,
        "--strategy",
        "guard",
        "--show-diff",
    )

    assert result.returncode == 0, result.stderr
    assert "---" in result.stdout and "+++" in result.stdout
    contents = target_file.read_text(encoding="utf-8")
    assert "neurocode guard: show diff" in contents


def test_cli_patch_inject_strategy(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_b.py"
    fix_description = "inject stub"

    result = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        fix_description,
        "--strategy",
        "inject",
        "--show-diff",
    )

    assert result.returncode == 0, result.stderr
    contents = target_file.read_text(encoding="utf-8")
    assert "NotImplementedError(\"neurocode inject: inject stub\")" in contents


def test_cli_patch_noop_exit_code(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_b.py"
    fix_description = "guard noop"

    # First apply guard.
    first = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        fix_description,
        "--strategy",
        "guard",
    )
    assert first.returncode == 0, first.stderr

    # Second run should be a noop and exit with 3.
    second = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        fix_description,
        "--strategy",
        "guard",
    )
    assert second.returncode == 3


def test_cli_patch_warns_on_stale_ir(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_b.py"
    # Make file newer than IR.
    target_file.write_text(target_file.read_text(encoding="utf-8") + "\n")

    result = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        "stale",
        "--strategy",
        "todo",
    )

    assert result.returncode == 0, result.stderr
    assert "warning" in result.stderr.lower()
    assert "older than target file" in result.stderr


def test_cli_patch_fails_when_require_fresh_ir(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_b.py"
    target_file.write_text(target_file.read_text(encoding="utf-8") + "\n")

    result = _run_cli(
        project_root,
        "patch",
        str(target_file),
        "--fix",
        "stale required",
        "--strategy",
        "todo",
        "--require-fresh-ir",
    )

    assert result.returncode != 0
    assert "older than target file" in result.stderr
