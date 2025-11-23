from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from neurocode.api import open_project


def test_patch_history_written_on_apply(repo_with_ir: Path) -> None:
    project = open_project(repo_with_ir)
    target = repo_with_ir / "package" / "mod_b.py"
    result = project.patch_file(target, fix="history test", strategy="inject", dry_run=False)
    assert not result.is_noop

    history = project.list_patch_history(limit=5)
    assert history
    latest = history[0]
    assert latest.fix == "history test"
    assert any(path.endswith("mod_b.py") for path in latest.files_changed)


def test_cli_patch_history(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "patch",
            str(target_file),
            "--fix",
            "history cli",
            "--strategy",
            "guard",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "patch-history",
            str(repo_with_ir),
            "--format",
            "json",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload
    assert any(entry["fix"] == "history cli" for entry in payload)
