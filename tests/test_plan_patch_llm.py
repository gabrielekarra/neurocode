from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from neurocode.plan_patch_llm import build_patch_plan_bundle


def test_build_patch_plan_bundle(repo_with_ir: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    bundle = build_patch_plan_bundle(
        target_file,
        fix="Add logging",
        symbol="package.mod_a.orchestrator",
        k_neighbors=5,
    )
    assert bundle["file"] == "package/mod_a.py"
    assert bundle["fix"] == "Add logging"
    assert bundle["operations"]
    assert bundle["module"] == "package.mod_a"
    assert bundle["call_graph_neighbors"]["callees"]
    assert any(op["file"].endswith("mod_b.py") for op in bundle["operations"])
    assert "package.mod_a:orchestrator" in bundle["source_slices"]


def test_cli_plan_and_apply_patch_plan(repo_with_ir: Path, project_root: Path, tmp_path: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    plan = build_patch_plan_bundle(
        target_file,
        fix="Add note",
        symbol="package.mod_a.orchestrator",
    )
    # Fill plan
    for op in plan["operations"]:
        op["code"] = "# added by plan"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "patch",
            str(target_file),
            "--plan",
            str(plan_path),
            "--show-diff",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "added by plan" in (target_file.read_text(encoding="utf-8"))


def test_patch_plan_draft_errors(repo_with_ir: Path, project_root: Path, tmp_path: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    plan = build_patch_plan_bundle(target_file, fix="Draft only")
    plan_path = tmp_path / "plan_draft.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "patch",
            str(target_file),
            "--plan",
            str(plan_path),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "empty code" in result.stderr


def test_cli_plan_patch_llm_json(repo_with_ir: Path, project_root: Path) -> None:
    target_file = repo_with_ir / "package" / "mod_a.py"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "plan-patch-llm",
            str(target_file),
            "--fix",
            "sample fix",
            "--format",
            "json",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["operations"]
    assert payload["call_graph_neighbors"]["callees"]
    assert payload["source_slices"]
