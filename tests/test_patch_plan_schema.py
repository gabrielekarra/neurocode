from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurocode.patch_plan import load_patch_plan


def _write_plan(tmp_path: Path, repo_root: Path, **overrides: object) -> Path:
    base = {
        "version": 1,
        "engine_version": "0.1.0",
        "repo_root": str(repo_root),
        "file": "package/mod_a.py",
        "module": "package.mod_a",
        "fix": "add logging",
        "target": {"symbol": "package.mod_a:fn", "kind": "function", "lineno": 1},
        "operations": [
            {
                "id": "OP_1",
                "op": "insert_before",
                "enabled": True,
                "file": "package/mod_a.py",
                "symbol": "package.mod_a:fn",
                "lineno": 1,
                "end_lineno": None,
                "description": "desc",
                "code": "print('hi')",
            }
        ],
    }
    base.update(overrides)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def test_valid_plan_passes(tmp_path: Path, repo_with_ir: Path) -> None:
    plan_path = _write_plan(tmp_path, repo_with_ir)
    plan = load_patch_plan(plan_path, expected_file=repo_with_ir / "package/mod_a.py")
    assert plan.operations


def test_missing_field_fails(tmp_path: Path, repo_with_ir: Path) -> None:
    base = {
        "version": 1,
        "engine_version": "0.1.0",
        "repo_root": str(repo_with_ir),
        "file": "package/mod_a.py",
        # module missing
        "fix": "add logging",
        "target": {"symbol": "x", "kind": "function", "lineno": 1},
        "operations": [],
    }
    plan_path = tmp_path / "bad.json"
    plan_path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_patch_plan(plan_path)


def test_extra_field_rejected(tmp_path: Path, repo_with_ir: Path) -> None:
    plan_path = _write_plan(tmp_path, repo_with_ir, extra="boom")
    with pytest.raises(RuntimeError):
        load_patch_plan(plan_path)


def test_invalid_op_rejected(tmp_path: Path, repo_with_ir: Path) -> None:
    plan_path = _write_plan(tmp_path, repo_with_ir)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["operations"][0]["op"] = "unknown"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_patch_plan(plan_path)


def test_empty_code_rejected_when_applying(tmp_path: Path, repo_with_ir: Path) -> None:
    plan_path = _write_plan(tmp_path, repo_with_ir)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["operations"][0]["code"] = ""
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_patch_plan(plan_path, require_filled=True)
