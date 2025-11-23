from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .ir_model import FunctionIR, ModuleIR, RepositoryIR


@dataclass
class QueryResult:
    kind: str
    symbol: str | None
    module_filter: str | None
    payload: dict


class QueryError(RuntimeError):
    """Raised for invalid query requests (missing symbol, unknown kind, etc.)."""


def run_query(
    ir: RepositoryIR,
    repo_root: Path,
    kind: str,
    symbol: str | None = None,
    module_filter: str | None = None,
) -> QueryResult:
    """Execute a structural query over the IR."""

    modules_by_id: Dict[int, ModuleIR] = {m.id: m for m in ir.modules}
    functions: List[FunctionIR] = [fn for m in ir.modules for fn in m.functions]
    fn_by_id: Dict[int, FunctionIR] = {fn.id: fn for fn in functions}

    def _modules_in_scope() -> List[ModuleIR]:
        if not module_filter:
            return list(ir.modules)
        # Match by module name or path suffix.
        scope: List[ModuleIR] = []
        filter_path = Path(module_filter)
        for m in ir.modules:
            if m.module_name == module_filter:
                scope.append(m)
                continue
            if filter_path.exists():
                try:
                    rel = filter_path.resolve().relative_to(repo_root.resolve())
                except ValueError:
                    rel = None
                if rel is not None and m.path == rel:
                    scope.append(m)
                    continue
            if str(m.path).endswith(module_filter):
                scope.append(m)
        if not scope:
            raise QueryError(f"Module not found for filter: {module_filter}")
        return scope

    def _functions_in_scope() -> List[FunctionIR]:
        scope_modules = {m.id for m in _modules_in_scope()}
        return [fn for fn in functions if fn.module_id in scope_modules]

    def _resolve_function(target: str | None) -> FunctionIR:
        if not target:
            raise QueryError("Symbol is required for this query kind")
        candidates = []
        for fn in functions:
            if fn.qualified_name == target:
                candidates.append(fn)
            elif fn.name == target or fn.qualified_name.endswith(f".{target}"):
                candidates.append(fn)
        if not candidates:
            raise QueryError(f"Function not found for symbol: {target}")
        if len(candidates) > 1:
            # Prefer exact match if available
            exact = [fn for fn in candidates if fn.qualified_name == target]
            if len(exact) == 1:
                return exact[0]
            raise QueryError(f"Symbol '{target}' is ambiguous; provide fully qualified name")
        return candidates[0]

    if kind == "callers":
        target_fn = _resolve_function(symbol)
        callers = [
            edge.caller_function_id
            for edge in ir.call_edges
            if edge.callee_function_id == target_fn.id
        ]
        unique_callers = sorted(set(callers))
        items: List[dict] = []
        for fid in unique_callers:
            caller_fn = fn_by_id[fid]
            mod = modules_by_id[caller_fn.module_id]
            items.append(
                {
                    "module": mod.module_name,
                    "function": caller_fn.qualified_name,
                    "location": {
                        "file": str((repo_root / mod.path).resolve()),
                        "lineno": caller_fn.lineno,
                    },
                }
            )
        return QueryResult(
            kind="callers",
            symbol=target_fn.qualified_name,
            module_filter=module_filter,
            payload={"callers": items},
        )

    if kind == "callees":
        target_fn = _resolve_function(symbol)
        edges = [
            edge for edge in ir.call_edges if edge.caller_function_id == target_fn.id
        ]
        unique_callees = sorted(
            {edge.callee_function_id for edge in edges if edge.callee_function_id is not None}
        )
        items: List[dict] = []
        for fid in unique_callees:
            callee_fn = fn_by_id[fid]
            mod = modules_by_id[callee_fn.module_id]
            items.append(
                {
                    "module": mod.module_name,
                    "function": callee_fn.qualified_name,
                    "location": {
                        "file": str((repo_root / mod.path).resolve()),
                        "lineno": callee_fn.lineno,
                    },
                }
            )
        return QueryResult(
            kind="callees",
            symbol=target_fn.qualified_name,
            module_filter=module_filter,
            payload={"callees": items},
        )

    def _fan_counts(reverse: bool) -> List[Tuple[FunctionIR, int]]:
        scope_functions = _functions_in_scope()
        counts: Dict[int, set[int]] = {fn.id: set() for fn in scope_functions}
        for edge in ir.call_edges:
            caller = edge.caller_function_id
            callee = edge.callee_function_id
            if callee is None:
                continue
            if reverse:
                # fan-in: how many distinct callers?
                if callee in counts and caller is not None:
                    counts[callee].add(caller)
            else:
                # fan-out: how many distinct callees?
                if caller in counts and callee is not None:
                    counts[caller].add(callee)
        ordered = sorted(
            ((fn, len(counts[fn.id])) for fn in scope_functions),
            key=lambda item: (-item[1], item[0].qualified_name),
        )
        return ordered

    if kind == "fan-in":
        items = []
        for fn, count in _fan_counts(reverse=True):
            mod = modules_by_id[fn.module_id]
            items.append(
                {
                    "module": mod.module_name,
                    "function": fn.qualified_name,
                    "callers": count,
                }
            )
        return QueryResult(
            kind="fan-in",
            symbol=symbol,
            module_filter=module_filter,
            payload={"functions": items},
        )

    if kind == "fan-out":
        items = []
        for fn, count in _fan_counts(reverse=False):
            mod = modules_by_id[fn.module_id]
            items.append(
                {
                    "module": mod.module_name,
                    "function": fn.qualified_name,
                    "callees": count,
                }
            )
        return QueryResult(
            kind="fan-out",
            symbol=symbol,
            module_filter=module_filter,
            payload={"functions": items},
        )

    raise QueryError(f"Unknown query kind: {kind}")


def render_query_result(result: QueryResult, output_format: str = "text") -> str:
    if output_format == "json":
        import json

        payload = {
            "kind": result.kind,
            "symbol": result.symbol,
            "module": result.module_filter,
            **result.payload,
        }
        return json.dumps(payload, indent=2)

    if result.kind == "callers":
        callers = result.payload.get("callers", [])
        lines = [f"Callers of {result.symbol or ''}:"]
        for entry in callers:
            lines.append(f"- {entry['function']}")
        return "\n".join(lines)

    if result.kind == "callees":
        callees = result.payload.get("callees", [])
        lines = [f"Callees of {result.symbol or ''}:"]
        for entry in callees:
            lines.append(f"- {entry['function']}")
        return "\n".join(lines)

    if result.kind == "fan-in":
        lines = ["Fan-in (callers per function):"]
        for entry in result.payload.get("functions", []):
            lines.append(f"{entry['callers']:>3} {entry['function']}")
        return "\n".join(lines)

    if result.kind == "fan-out":
        lines = ["Fan-out (callees per function):"]
        for entry in result.payload.get("functions", []):
            lines.append(f"{entry['callees']:>3} {entry['function']}")
        return "\n".join(lines)

    return f"[neurocode] unknown query kind: {result.kind}"
