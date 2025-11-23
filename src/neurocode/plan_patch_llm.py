from __future__ import annotations

from pathlib import Path
from typing import List

from .explain import _find_module_for_file, _find_repo_root_for_file
from .explain_llm import build_explain_llm_bundle
from .ir_model import FunctionIR
from .toon_parse import load_repository_ir


def _find_target_function(ir, module, symbol: str | None) -> FunctionIR | None:
    if symbol:
        sym_norm = symbol.replace(":", ".")
        for fn in module.functions:
            if fn.qualified_name == sym_norm or fn.qualified_name.endswith(f".{sym_norm}"):
                return fn
    # fallback: first module-level function
    module_level = [fn for fn in module.functions if fn.parent_class_id is None]
    if module_level:
        return min(module_level, key=lambda f: f.lineno)
    if module.functions:
        return min(module.functions, key=lambda f: f.lineno)
    return None


def _initial_operations(target_fn: FunctionIR | None, fix: str, file_rel: str) -> List[dict]:
    ops: List[dict] = []
    base_target = {
        "symbol": target_fn.qualified_name if target_fn else None,
        "kind": "function" if target_fn else None,
        "file": file_rel,
        "lineno": target_fn.lineno if target_fn else 1,
    }
    ops.append(
        {
            "op": "append_to_function",
            "id": "OP_1",
            "target": base_target,
            "code": "",
            "description": f"Implement fix: {fix}",
            "enabled": True,
        }
    )
    if target_fn:
        ops.append(
            {
                "op": "insert_before",
                "id": "OP_2",
                "target": {**base_target},
                "code": "",
                "description": f"Optional preamble for {target_fn.qualified_name}",
                "enabled": True,
            }
        )
    return ops


def build_patch_plan_bundle(
    file_path: Path,
    *,
    fix: str,
    symbol: str | None = None,
    k_neighbors: int = 10,
) -> dict:
    if not fix or not fix.strip():
        raise RuntimeError("fix description must be provided")

    file_path = file_path.resolve()
    repo_root = _find_repo_root_for_file(file_path)
    if repo_root is None:
        raise RuntimeError("Could not find .neurocode/ir.toon. Run `neurocode ir` first.")

    ir_file = repo_root / ".neurocode" / "ir.toon"
    if not ir_file.is_file():
        raise RuntimeError(f"{ir_file} not found. Run `neurocode ir {repo_root}` first.")

    ir = load_repository_ir(ir_file)
    module = _find_module_for_file(ir, repo_root, file_path)
    if module is None:
        raise RuntimeError(f"No module found in IR for file {file_path}")

    target_fn = _find_target_function(ir, module, symbol)
    target_payload = None
    if symbol and target_fn is None:
        raise RuntimeError(f"Symbol not found in IR: {symbol}")
    if target_fn:
        target_payload = {
            "symbol": target_fn.qualified_name,
            "kind": "function",
            "lineno": target_fn.lineno,
        }

    explain_bundle = build_explain_llm_bundle(
        file_path,
        symbol=target_fn.qualified_name if target_fn else None,
        k_neighbors=k_neighbors,
    ).data

    file_rel = str(file_path.relative_to(repo_root))
    operations = _initial_operations(target_fn, fix, file_rel)

    plan_bundle = {
        "version": 1,
        "engine_version": explain_bundle.get("engine_version", ""),
        "repo_root": explain_bundle.get("repo_root"),
        "file": explain_bundle.get("file"),
        "module": explain_bundle.get("module"),
        "fix": fix,
        "target": target_payload,
        "context": explain_bundle,
        "patch_plan": {
            "status": "draft",
            "operations": operations,
        },
    }
    return plan_bundle
