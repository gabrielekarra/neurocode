from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .check import CheckResult, check_file
from .config import load_config
from .embedding_provider import DummyEmbeddingProvider
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


def _module_summary(ir: RepositoryIR, module: ModuleIR) -> dict:
    # Imports from module_import_edges
    imports = sorted(
        {edge.imported_module for edge in ir.module_import_edges if edge.importer_module_id == module.id}
    )
    functions = []
    for fn in sorted(module.functions, key=lambda f: f.lineno):
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
                callers.append({"function": caller_fn.qualified_name, "lineno": edge.lineno})
        if edge.caller_function_id == target.id and edge.callee_function_id is not None:
            callee_fn = fn_by_id.get(edge.callee_function_id)
            if callee_fn:
                callees.append({"function": callee_fn.qualified_name, "lineno": edge.lineno})
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
    if target_fn:
        call_graph = _callers_and_callees(ir, target_fn)

    checks = _checks_for_file(ir, repo_root, file_path)

    # Semantic neighbors via embeddings/search
    semantic_neighbors: List[dict] = []
    embedding_meta: dict = {}
    try:
        _, store = load_ir_and_embeddings(repo_root)
        embedding_meta = {
            "model": store.model,
            "store_path": str(repo_root / ".neurocode" / "ir-embeddings.toon"),
        }
        if target_fn:
            query_embedding = build_query_embedding_from_symbol(store, target_fn.qualified_name)
        else:
            # fallback to embedding file content
            text = file_path.read_text(encoding="utf-8")
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
        # Missing embeddings or load failure; degrade gracefully.
        embedding_meta = {"model": None, "store_path": None}
        semantic_neighbors = []

    # IR slice
    module_summary = _module_summary(ir, module)

    source_text = ""
    try:
        source_text = file_path.read_text(encoding="utf-8")
    except OSError:
        source_text = ""

    target_payload = None
    if target_fn:
        target_payload = {
            "symbol": target_fn.qualified_name,
            "kind": "function",
            "lineno": target_fn.lineno,
        }

    bundle = {
        "version": 1,
        "engine_version": "",
        "repo_root": str(repo_root),
        "file": str(file_path.relative_to(repo_root)),
        "module": module.module_name,
        "target": target_payload,
        "ir": {"module_summary": module_summary},
        "call_graph": call_graph,
        "checks": checks,
        "semantic_neighbors": semantic_neighbors,
        "source": {"text": source_text, "language": "python"},
        "embedding_metadata": embedding_meta,
    }
    try:
        from . import __version__

        bundle["engine_version"] = __version__
    except Exception:
        bundle["engine_version"] = ""

    return ExplainLLMBundle(data=bundle)
