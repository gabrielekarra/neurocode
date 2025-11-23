from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from neurocode.query import QueryError, run_query
from neurocode.toon_parse import load_repository_ir


def _load_ir(repo_root: Path):
    return load_repository_ir(repo_root / ".neurocode" / "ir.toon")


def test_query_callers(repo_with_ir: Path) -> None:
    ir = _load_ir(repo_with_ir)
    result = run_query(
        ir=ir,
        repo_root=repo_with_ir,
        kind="callers",
        symbol="package.mod_b.helper_value",
    )
    callers = {entry["function"] for entry in result.payload["callers"]}
    assert "package.mod_a.orchestrator" in callers
    assert "package.mod_a.helper_local" in callers
    assert "package.mod_b.run_task" in callers
    assert "package.classy.Processor._compute" in callers


def test_query_callees(repo_with_ir: Path) -> None:
    ir = _load_ir(repo_with_ir)
    result = run_query(
        ir=ir,
        repo_root=repo_with_ir,
        kind="callees",
        symbol="package.mod_a.orchestrator",
    )
    callees = {entry["function"] for entry in result.payload["callees"]}
    assert "package.mod_b.run_task" in callees
    assert "package.mod_b.helper_value" in callees
    assert "package.mod_a.task_one" in callees
    assert len(callees) >= 4


def test_query_fan_in_and_out(repo_with_ir: Path) -> None:
    ir = _load_ir(repo_with_ir)
    fan_in = run_query(
        ir=ir,
        repo_root=repo_with_ir,
        kind="fan-in",
    )
    helper_entry = next(
        e
        for e in fan_in.payload["functions"]
        if e["function"] == "package.mod_b.helper_value"
    )
    assert helper_entry["callers"] == 4

    fan_out = run_query(
        ir=ir,
        repo_root=repo_with_ir,
        kind="fan-out",
        module_filter="package.mod_a",
    )
    orchestrator_entry = next(
        e
        for e in fan_out.payload["functions"]
        if e["function"] == "package.mod_a.orchestrator"
    )
    assert orchestrator_entry["callees"] >= 10


def test_query_cli_json(repo_with_ir: Path, project_root: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "neurocode.cli",
            "query",
            str(repo_with_ir),
            "--kind",
            "callers",
            "--symbol",
            "package.mod_b.helper_value",
            "--format",
            "json",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["kind"] == "callers"
    assert payload["symbol"] == "package.mod_b.helper_value"
    callers = {c["function"] for c in payload["callers"]}
    assert "package.mod_a.orchestrator" in callers


def test_query_requires_symbol_when_needed(repo_with_ir: Path) -> None:
    ir = _load_ir(repo_with_ir)
    try:
        run_query(ir=ir, repo_root=repo_with_ir, kind="callers")
    except QueryError as exc:
        assert "Symbol is required" in str(exc)
    else:
        raise AssertionError("Expected QueryError for missing symbol")
