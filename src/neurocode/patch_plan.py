from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class PlanTarget:
    symbol: str | None
    kind: str | None
    file: Path
    lineno: int
    end_lineno: int | None = None


@dataclass
class PlanOperation:
    id: str
    op: str
    target: PlanTarget
    code: str
    description: str
    enabled: bool = True


@dataclass
class PatchPlan:
    version: int
    engine_version: str | None
    repo_root: Path
    file: Path
    module: str | None
    fix: str
    status: str
    operations: List[PlanOperation]


SUPPORTED_OPS = {"insert_before", "insert_after", "replace_range", "append_to_function"}


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def load_patch_plan(path: Path, expected_file: Path | None = None) -> PatchPlan:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read patch plan: {exc}") from exc

    _require(isinstance(data, dict), "Patch plan must be a JSON object")
    version = data.get("version")
    _require(isinstance(version, int), "Patch plan missing integer version")

    repo_root = Path(data.get("repo_root", ".")).resolve()
    file_str = data.get("file")
    _require(isinstance(file_str, str), "Patch plan missing file")
    file_path = (repo_root / file_str).resolve()
    if expected_file is not None and file_path != expected_file.resolve():
        raise RuntimeError(f"Patch plan file {file_path} does not match requested file {expected_file}")

    fix = data.get("fix", "")
    _require(isinstance(fix, str) and fix.strip(), "Patch plan missing fix description")

    plan_section = data.get("patch_plan", {})
    _require(isinstance(plan_section, dict), "Patch plan missing patch_plan section")
    status = plan_section.get("status", "draft")
    _require(status in {"draft", "ready"}, "Patch plan status must be draft or ready")

    operations_raw = plan_section.get("operations", [])
    _require(isinstance(operations_raw, list), "patch_plan.operations must be an array")

    operations: List[PlanOperation] = []
    for op_raw in operations_raw:
        _require(isinstance(op_raw, dict), "Each operation must be an object")
        op_type = op_raw.get("op")
        _require(op_type in SUPPORTED_OPS, f"Unsupported op type: {op_type}")
        op_id = op_raw.get("id")
        _require(isinstance(op_id, str) and op_id.strip(), "Operation missing id")
        target_raw = op_raw.get("target", {})
        _require(isinstance(target_raw, dict), "Operation target must be an object")
        target_file = target_raw.get("file")
        _require(isinstance(target_file, str), "Operation target missing file")
        target_file_path = (repo_root / target_file).resolve()
        if expected_file is not None and target_file_path != expected_file.resolve():
            raise RuntimeError(
                f"Operation target file {target_file_path} does not match requested file {expected_file}"
            )
        lineno = target_raw.get("lineno")
        _require(isinstance(lineno, int) and lineno > 0, "Operation target missing lineno")
        end_lineno = target_raw.get("end_lineno")
        if end_lineno is not None:
            _require(isinstance(end_lineno, int) and end_lineno >= lineno, "end_lineno must be >= lineno")
        target = PlanTarget(
            symbol=target_raw.get("symbol"),
            kind=target_raw.get("kind"),
            file=target_file_path,
            lineno=lineno,
            end_lineno=end_lineno,
        )
        code = op_raw.get("code", "")
        _require(isinstance(code, str), "Operation code must be a string")
        enabled = bool(op_raw.get("enabled", True))
        description = op_raw.get("description", "")
        _require(isinstance(description, str), "Operation description must be a string")
        operations.append(
            PlanOperation(
                id=op_id,
                op=op_type,
                target=target,
                code=code,
                description=description,
                enabled=enabled,
            )
        )

    if status == "ready":
        for op in operations:
            if op.enabled:
                _require(op.code.strip(), f"Enabled operation {op.id} has empty code in ready plan")

    return PatchPlan(
        version=version,
        engine_version=data.get("engine_version"),
        repo_root=repo_root,
        file=file_path,
        module=data.get("module"),
        fix=fix,
        status=status,
        operations=operations,
    )
