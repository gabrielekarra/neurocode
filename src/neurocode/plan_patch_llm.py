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
            if fn.kind == "module":
                continue
            if fn.qualified_name == sym_norm or fn.qualified_name.endswith(f".{sym_norm}"):
                return fn
    # fallback: first module-level function
    module_level = [fn for fn in module.functions if fn.parent_class_id is None and fn.kind != "module"]
    if module_level:
        return min(module_level, key=lambda f: f.lineno)
    non_entry = [fn for fn in module.functions if fn.kind != "module"]
    if non_entry:
        return min(non_entry, key=lambda f: f.lineno)
    return None


def _initial_operations(target_fn: FunctionIR | None, fix: str, file_rel: str) -> List[dict]:
    ops: List[dict] = []
    symbol = target_fn.qualified_name if target_fn else ""
    lineno = target_fn.lineno if target_fn else 1
    ops.append(
        {
            "op": "append_to_function",
            "id": "OP_1",
            "file": file_rel,
            "symbol": symbol,
            "lineno": lineno,
            "end_lineno": None,
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
                "file": file_rel,
                "symbol": symbol,
                "lineno": lineno,
                "end_lineno": None,
                "code": "",
                "description": f"Optional preamble for {target_fn.qualified_name}",
                "enabled": True,
            }
        )
    return ops


def _call_neighbors(
    ir,
    target_fn: FunctionIR | None,
) -> tuple[list[FunctionIR], list[FunctionIR], dict[tuple[int, int], int]]:
    """Return (callers, callees, callsite_map[(caller_id, callee_id)]=lineno)."""

    if target_fn is None:
        return [], [], {}
    fn_by_id = {fn.id: fn for m in ir.modules for fn in m.functions}
    callers: list[FunctionIR] = []
    callees: list[FunctionIR] = []
    callsite_map: dict[tuple[int, int], int] = {}
    for edge in ir.call_edges:
        if edge.callee_function_id == target_fn.id and edge.caller_function_id in fn_by_id:
            caller = fn_by_id[edge.caller_function_id]
            if caller.kind != "module":
                callers.append(caller)
                callsite_map[(caller.id, target_fn.id)] = edge.lineno
        if edge.caller_function_id == target_fn.id and edge.callee_function_id in fn_by_id:
            callee = fn_by_id[edge.callee_function_id]
            if callee.kind != "module":
                callees.append(callee)
                callsite_map[(target_fn.id, callee.id)] = edge.lineno
    return callers, callees, callsite_map


def _collect_source_slices(
    repo_root: Path,
    symbols: list[FunctionIR],
    module_paths: dict[int, Path],
) -> tuple[dict, dict]:
    from .explain_llm import _collect_source_slices as _collect

    return _collect(repo_root, symbols, module_paths)


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
    else:
        target_payload = {"symbol": "", "kind": "function", "lineno": 1}

    explain_bundle = build_explain_llm_bundle(
        file_path,
        symbol=target_fn.qualified_name if target_fn else None,
        k_neighbors=k_neighbors,
    ).data

    callers, callees, callsite_map = _call_neighbors(ir, target_fn)

    file_rel = str(file_path.relative_to(repo_root))
    operations = _initial_operations(target_fn, fix, file_rel)

    module_paths: dict[int, Path] = {m.id: m.path for m in ir.modules}
    op_counter = len(operations) + 1
    neighbor_ops: list[dict] = []
    for caller in callers:
        caller_path = module_paths.get(caller.module_id)
        if caller_path is None:
            continue
        call_lineno = callsite_map.get((caller.id, target_fn.id if target_fn else -1), caller.lineno)
        neighbor_ops.append(
            {
                "op": "insert_before",
                "id": f"OP_{op_counter}",
                "file": str(caller_path),
                "symbol": caller.symbol_id,
                "lineno": call_lineno,
                "end_lineno": None,
                "code": "",
                "description": f"Update callsite in {caller.symbol_id} for fix: {fix}",
                "enabled": True,
            }
        )
        op_counter += 1
    for callee in callees:
        callee_path = module_paths.get(callee.module_id)
        if callee_path is None:
            continue
        neighbor_ops.append(
            {
                "op": "append_to_function",
                "id": f"OP_{op_counter}",
                "file": str(callee_path),
                "symbol": callee.symbol_id,
                "lineno": callee.lineno,
                "end_lineno": None,
                "code": "",
                "description": f"Consider updating callee {callee.symbol_id} for fix: {fix}",
                "enabled": True,
            }
        )
        op_counter += 1
    operations.extend(neighbor_ops)

    neighbor_symbols = []
    neighbor_symbols.extend(callers)
    neighbor_symbols.extend(callees)
    slice_symbols = []
    if target_fn:
        slice_symbols.append(target_fn)
    slice_symbols.extend(neighbor_symbols)
    source_slices, trunc_info = _collect_source_slices(repo_root, slice_symbols, module_paths)

    plan_bundle = {
        "version": 1,
        "engine_version": explain_bundle.get("engine_version", ""),
        "repo_root": explain_bundle.get("repo_root"),
        "file": file_rel,
        "module": explain_bundle.get("module", ""),
        "fix": fix,
        "target": target_payload,
        "call_graph_neighbors": explain_bundle.get("call_graph_neighbors", {}),
        "related_files": explain_bundle.get("related_files", []),
        "source_slices": source_slices,
        "truncation": trunc_info,
        "operations": operations,
    }
    return plan_bundle
