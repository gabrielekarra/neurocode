from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping

from .patch_plan_schema import PATCH_PLAN_SCHEMA


@dataclass
class PlanTarget:
    symbol: str
    kind: str
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
    engine_version: str
    repo_root: Path
    file: Path
    module: str
    fix: str
    operations: List[PlanOperation]


SUPPORTED_OPS = {"insert_before", "insert_after", "replace_range", "append_to_function"}


def _require(cond: bool, msg: str, *, field: str | None = None) -> None:
    if not cond:
        prefix = f"invalid {field}: " if field else ""
        raise RuntimeError(prefix + msg)


def _validate_schema(data: Mapping[str, Any]) -> None:
    def _check_object(obj: Any, schema: Mapping[str, Any], path: str) -> None:
        _require(isinstance(obj, dict), f"{path} must be an object")
        allowed = set(schema.get("properties", {}).keys())
        required = set(schema.get("required", []))
        for key in obj.keys():
            _require(key in allowed, f"{path} has unknown field '{key}'")
        for key in required:
            _require(key in obj, f"{path} missing required field '{key}'")
        for key, value in obj.items():
            subschema = schema["properties"][key]
            subtype = subschema.get("type")
            if isinstance(subtype, list):
                valid_type = any(_matches_type(value, t) for t in subtype)
            else:
                valid_type = _matches_type(value, subtype)
            _require(valid_type, f"{path}.{key} has wrong type")
            if "enum" in subschema:
                _require(value in subschema["enum"], f"{path}.{key} has invalid value")
            if subschema.get("type") == "object":
                _check_object(value, subschema, f"{path}.{key}")
            if subschema.get("type") == "array":
                _require(isinstance(value, list), f"{path}.{key} must be an array")
                item_schema = subschema.get("items", {})
                for idx, item in enumerate(value):
                    _check_object(item, item_schema, f"{path}.{key}[{idx}]")
            if "minimum" in subschema and isinstance(value, int):
                _require(value >= subschema["minimum"], f"{path}.{key} must be >= {subschema['minimum']}")

    def _matches_type(value: Any, expected: str | None) -> bool:
        if expected == "string":
            return isinstance(value, str)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "object":
            return isinstance(value, dict)
        if expected == "array":
            return isinstance(value, list)
        if expected == "null":
            return value is None
        return False

    _check_object(data, PATCH_PLAN_SCHEMA, "patch_plan")


def load_patch_plan(path: Path, expected_file: Path | None = None, *, require_filled: bool = False) -> PatchPlan:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read patch plan: {exc}") from exc

    _require(isinstance(data, dict), "Patch plan must be a JSON object")
    _validate_schema(data)

    version = data["version"]
    repo_root = Path(data["repo_root"]).resolve()
    file_str = data["file"]
    file_path = (repo_root / file_str).resolve()
    if expected_file is not None and file_path != expected_file.resolve():
        raise RuntimeError(f"Patch plan file {file_path} does not match requested file {expected_file}")

    fix = data["fix"]
    target_raw = data["target"]
    _ = target_raw  # validated via schema; kept for symmetry
    operations_raw = data["operations"]

    operations: List[PlanOperation] = []
    for op_raw in operations_raw:
        op_type = op_raw["op"]
        _require(op_type in SUPPORTED_OPS, f"Unsupported op type: {op_type}", field="op")
        op_id = op_raw["id"]
        target_file = op_raw["file"]
        target_file_path = (repo_root / target_file).resolve()
        if expected_file is not None and target_file_path != expected_file.resolve():
            raise RuntimeError(
                f"Operation target file {target_file_path} does not match requested file {expected_file}"
            )
        lineno = op_raw["lineno"]
        end_lineno = op_raw["end_lineno"]
        if end_lineno is not None:
            _require(end_lineno >= lineno, "end_lineno must be >= lineno", field="end_lineno")
        code = op_raw["code"]
        enabled = op_raw["enabled"]
        description = op_raw["description"]
        operations.append(
            PlanOperation(
                id=op_id,
                op=op_type,
                target=PlanTarget(
                    symbol=op_raw["symbol"],
                    kind="function",
                    file=target_file_path,
                    lineno=lineno,
                    end_lineno=end_lineno,
                ),
                code=code,
                description=description,
                enabled=enabled,
            )
        )

    if require_filled:
        for op in operations:
            if op.enabled:
                _require(op.code.strip(), f"Enabled operation {op.id} has empty code")

    return PatchPlan(
        version=version,
        engine_version=data["engine_version"],
        repo_root=repo_root,
        file=file_path,
        module=data["module"],
        fix=fix,
        operations=operations,
    )
