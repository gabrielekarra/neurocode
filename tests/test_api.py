from __future__ import annotations

from pathlib import Path

from neurocode.api import (
    NeurocodeProject,
    open_project,
)


def test_open_project_with_ir(repo_with_ir: Path) -> None:
    project = open_project(repo_with_ir)
    status = project.status()
    assert status.ir_exists


def test_api_build_ir_and_embeddings(sample_repo: Path) -> None:
    project = NeurocodeProject(sample_repo)
    project.build_ir()
    project.ensure_embeddings(provider="dummy")
    status = project.status()
    assert status.embeddings_exists


def test_api_explain_and_checks(repo_with_ir: Path) -> None:
    project = open_project(repo_with_ir)
    explain = project.explain_file(repo_with_ir / "package" / "mod_a.py")
    assert explain.functions
    checks = project.run_checks(repo_with_ir / "package" / "mod_a.py")
    assert checks


def test_api_search_and_plan(repo_with_ir: Path) -> None:
    project = open_project(repo_with_ir)
    project.ensure_embeddings(provider="dummy")
    results = project.search_code(text="value helper", provider="dummy", k=3)
    assert results
    plan = project.plan_patch_llm(repo_with_ir / "package" / "mod_a.py", fix="add logging")
    assert plan.data["patch_plan"]["status"] == "draft"


def test_api_apply_patch_plan(repo_with_ir: Path, tmp_path: Path) -> None:
    project = open_project(repo_with_ir)
    plan = project.plan_patch_llm(repo_with_ir / "package" / "mod_a.py", fix="add comment")
    plan.data["patch_plan"]["status"] = "ready"
    for op in plan.data["patch_plan"]["operations"]:
        op["code"] = "# patched"
    result = project.apply_patch_plan(plan, dry_run=True)
    assert "# patched" in result.diff
