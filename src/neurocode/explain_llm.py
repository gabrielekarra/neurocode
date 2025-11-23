from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .check import CheckResult, check_file
from .config import load_config
from .embedding_provider import DummyEmbeddingProvider, make_embedding_provider
from .explain import _find_module_for_file, _find_repo_root_for_file
from .ir_model import FunctionIR, ModuleIR, RepositoryIR
from .search import (
    build_query_embedding_from_symbol,
    build_query_embedding_from_text,
    load_ir_and_embeddings,
    search_embeddings,
)
from .toon_parse import load_repository_ir


@dataclass
class ExplainLLMBundle:
    data: dict


def _function_by_qualified_name(ir: RepositoryIR, name: str) -> FunctionIR | None:
    for module in ir.modules:
        for fn in module.functions:
            if fn.qualified_name == name or fn.qualified_name.endswith(f".{name}"):
                return fn
    return None


def _function_by_symbol_id(ir: RepositoryIR, symbol_id: str) -> FunctionIR | None:
    for module in ir.modules:
        for fn in module.functions:
            if fn.symbol_id == symbol_id:
                return fn
    return None


def _module_summary(ir: RepositoryIR, module: ModuleIR) -> dict:
    # Imports from module_import_edges
    imports = sorted(
        {edge.imported_module for edge in ir.module_import_edges if edge.importer_module_id == module.id}
    )
    functions = []
    for fn in sorted(
        [f for f in module.functions if f.kind != "module"], key=lambda f: f.lineno
    ):
        functions.append(
            {
                "name": fn.name,
                "qualified_name": fn.qualified_name,
                "lineno": fn.lineno,
                "num_calls": len(fn.calls),
            }
        )
    classes = []
    for cls in sorted(module.classes, key=lambda c: c.lineno):
        classes.append(
            {
                "name": cls.name,
                "qualified_name": cls.qualified_name,
                "lineno": cls.lineno,
                "methods": [m.qualified_name for m in cls.methods],
            }
        )
    return {
        "module": module.module_name,
        "imports": imports,
        "functions": functions,
        "classes": classes,
    }


def _callers_and_callees(ir: RepositoryIR, target: FunctionIR) -> dict:
    fn_by_id: Dict[int, FunctionIR] = {}
    for m in ir.modules:
        for fn in m.functions:
            fn_by_id[fn.id] = fn
    callers = []
    callees = []
    for edge in ir.call_edges:
        if edge.callee_function_id == target.id:
            caller_fn = fn_by_id.get(edge.caller_function_id)
            if caller_fn:
                callers.append(
                    {
                        "symbol": caller_fn.symbol_id,
                        "module": caller_fn.module,
                        "file": str(next((m.path for m in ir.modules if m.id == caller_fn.module_id), "")),
                        "lineno": edge.lineno,
                    }
                )
        if edge.caller_function_id == target.id and edge.callee_function_id is not None:
            callee_fn = fn_by_id.get(edge.callee_function_id)
            if callee_fn:
                callees.append(
                    {
                        "symbol": callee_fn.symbol_id,
                        "module": callee_fn.module,
                        "file": str(next((m.path for m in ir.modules if m.id == callee_fn.module_id), "")),
                        "lineno": edge.lineno,
                    }
                )
    return {"callers": callers, "callees": callees}


def _checks_for_file(ir: RepositoryIR, repo_root: Path, file: Path) -> List[dict]:
    config = load_config(repo_root)
    results: List[CheckResult] = check_file(ir=ir, repo_root=repo_root, file=file, config=config)
    checks = []
    for r in results:
        checks.append(
            {
                "code": r.code,
                "severity": r.severity,
                "message": r.message,
                "file": str(r.file),
                "module": r.module,
                "function": r.function,
                "lineno": r.lineno,
            }
        )
    return checks


def _build_end_lineno_map(file_path: Path) -> Dict[int, int]:
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except Exception:
        return {}
    mapping: Dict[int, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is not None and end is not None:
                mapping[start] = end
    return mapping


def _function_source_slice(
    fn: FunctionIR,
    repo_root: Path,
    module_paths: Dict[int, Path],
    end_map_cache: Dict[Path, Dict[int, int]],
) -> Tuple[str, bool]:
    file_path = module_paths.get(fn.module_id)
    if file_path is None:
        file_path = (repo_root / fn.module.replace(".", "/")).with_suffix(".py")
    else:
        file_path = repo_root / file_path
    if not file_path.exists():
        return "", False
    end_map = end_map_cache.get(file_path)
    if end_map is None:
        end_map = _build_end_lineno_map(file_path)
        end_map_cache[file_path] = end_map
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", False
    start = max(fn.lineno - 1, 0)
    end = end_map.get(fn.lineno, len(lines))
    end = min(end, len(lines))
    slice_text = "\n".join(lines[start:end])
    truncated = False
    SOURCE_LIMIT = 40000
    if len(slice_text) > SOURCE_LIMIT:
        slice_text = slice_text[:SOURCE_LIMIT]
        truncated = True
    return slice_text, truncated


def _collect_source_slices(repo_root: Path, symbols: List[FunctionIR], module_paths: Dict[int, Path]) -> tuple[dict, dict]:
    slices: Dict[str, dict] = {}
    truncation = {"applied": False, "reason": "", "functions_included": 0}
    end_map_cache: Dict[Path, Dict[int, int]] = {}
    for fn in symbols:
        text, truncated = _function_source_slice(fn, repo_root, module_paths, end_map_cache)
        if not text:
            continue
        slices[fn.symbol_id or fn.qualified_name] = {
            "file": str(fn.module.replace(".", "/") + ".py"),
            "text": text,
            "truncated": truncated,
        }
        if truncated:
            truncation["applied"] = True
            truncation["reason"] = "slice_truncated"
        truncation["functions_included"] += 1
    return slices, truncation


def build_explain_llm_bundle(
    file_path: Path,
    *,
    symbol: str | None = None,
    k_neighbors: int = 10,
) -> ExplainLLMBundle:
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

    target_fn: FunctionIR | None = None
    if symbol:
        target_fn = _function_by_qualified_name(ir, symbol.replace(":", "."))
        if target_fn is None:
            raise RuntimeError(f"Symbol not found in IR: {symbol}")

    call_graph = {}
    neighbors_symbols: List[FunctionIR] = []
    if target_fn:
        call_graph = _callers_and_callees(ir, target_fn)
        neighbor_ids = {n["symbol"] for n in call_graph.get("callers", []) if n.get("symbol")}
        neighbor_ids.update({n["symbol"] for n in call_graph.get("callees", []) if n.get("symbol")})
        for sid in neighbor_ids:
            fn_obj = _function_by_symbol_id(ir, sid)
            if fn_obj:
                neighbors_symbols.append(fn_obj)

    checks = _checks_for_file(ir, repo_root, file_path)

    # Semantic neighbors via embeddings/search
    semantic_neighbors: List[dict] = []
    embedding_meta: dict = {}
    try:
        config = load_config(repo_root)
        _, store = load_ir_and_embeddings(repo_root)
        embedding_meta = {
            "model": store.model,
            "provider": store.provider,
            "store_path": str(repo_root / ".neurocode" / "ir-embeddings.toon"),
            "available": True,
        }
        if target_fn:
            query_embedding = build_query_embedding_from_symbol(store, target_fn.qualified_name)
        else:
            text = file_path.read_text(encoding="utf-8")
            try:
                provider, _, _ = make_embedding_provider(config, allow_dummy=True)
            except RuntimeError:
                provider = DummyEmbeddingProvider()
            query_embedding = build_query_embedding_from_text(text, provider=provider)
        neighbors = search_embeddings(
            repository_ir=ir,
            embedding_store=store,
            query_embedding=query_embedding,
            module_filter=module.module_name,
            k=k_neighbors,
        )
        for n in neighbors:
            semantic_neighbors.append(
                {
                    "id": n.id,
                    "kind": n.kind,
                    "module": n.module,
                    "name": n.name,
                    "file": n.file,
                    "lineno": n.lineno,
                    "signature": n.signature,
                    "score": n.score,
                }
            )
    except Exception:
        embedding_meta = {"model": None, "provider": None, "store_path": None, "available": False}
        semantic_neighbors = []

    # IR slice
    module_summary = _module_summary(ir, module)

    source_text = ""
    truncated = False
    SOURCE_LIMIT = 20000
    try:
        source_text = file_path.read_text(encoding="utf-8")
        if len(source_text) > SOURCE_LIMIT:
            source_text = source_text[:SOURCE_LIMIT]
            truncated = True
    except OSError:
        source_text = ""

    target_payload = None
    if target_fn:
        target_payload = {
            "symbol": target_fn.qualified_name,
            "kind": "function",
            "lineno": target_fn.lineno,
        }

    module_paths: Dict[int, Path] = {m.id: m.path for m in ir.modules}

    related_files = {str(file_path.relative_to(repo_root))}
    for n in neighbors_symbols:
        try:
            mod_path = module_paths[n.module_id]
            related_files.add(str(mod_path))
        except Exception:
            continue

    slice_symbols: List[FunctionIR] = []
    if target_fn:
        slice_symbols.append(target_fn)
        slice_symbols.extend(neighbors_symbols)
    else:
        slice_symbols.extend([fn for fn in module.functions if fn.kind != "module"])

    source_slices, trunc_info = _collect_source_slices(repo_root, slice_symbols, module_paths)

    bundle = {
        "version": 1,
        "engine_version": "",
        "repo_root": str(repo_root),
        "file": str(file_path.relative_to(repo_root)),
        "module": module.module_name,
        "target": target_payload,
        "ir": {"module_summary": module_summary},
        "call_graph": call_graph,
        "call_graph_neighbors": {
            "target": target_fn.symbol_id if target_fn else None,
            "callers": call_graph.get("callers", []),
            "callees": call_graph.get("callees", []),
        },
        "related_files": [{"path": path} for path in sorted(related_files)],
        "source_slices": source_slices,
        "truncation": trunc_info,
        "checks": checks,
        "semantic_neighbors": semantic_neighbors,
        "source": {"text": source_text, "language": "python", "truncated": truncated},
        "embedding_metadata": embedding_meta,
    }
    try:
        from . import __version__

        bundle["engine_version"] = __version__
    except Exception:
        bundle["engine_version"] = ""

    return ExplainLLMBundle(data=bundle)
