from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set
import ast

from .explain import _find_module_for_file, _find_repo_root_for_file
from .config import Config, load_config
from .ir_model import FunctionIR, ModuleIR, RepositoryIR
from .ir_build import compute_file_hash
from .toon_parse import load_repository_ir


@dataclass
class CheckResult:
    """Represents a single structural check finding.

    ``severity`` is one of "INFO", "WARNING", or "ERROR".
    """

    code: str
    severity: str
    message: str
    file: Path
    module: str | None = None
    function: str | None = None
    lineno: int | None = None


def check_file_from_disk(
    file: Path,
    output_format: str = "text",
    return_status: bool = False,
) -> tuple[str, int] | tuple[str, int, str]:
    """Run structural checks for the module that owns ``file``.

    This is the entrypoint used by the CLI. It locates `.neurocode/ir.toon`
    by walking upwards from the file path, loads the IR, and runs checks that
    are scoped to the corresponding module.
    """

    repo_root = _find_repo_root_for_file(file)
    if repo_root is None:
        raise RuntimeError(
            "Could not find .neurocode/ir.toon. Run `neurocode ir` at the repository root first."
        )

    ir_file = repo_root / ".neurocode" / "ir.toon"
    ir = load_repository_ir(ir_file)
    module = _find_module_for_file(ir, repo_root, file)
    if module is None:
        raise RuntimeError(
            "No module found in IR for file: "
            f"{file.resolve()} (did you run `neurocode ir` on the right root?)"
        )

    config = load_config(repo_root)
    results = check_file(ir=ir, repo_root=repo_root, file=file, config=config)
    warning = _staleness_warning(module, repo_root)
    warnings = [warning] if warning else []
    rendered, exit_code = _render_results(results, output_format=output_format, warnings=warnings)
    status = _build_status(results, warnings, exit_code)
    if return_status:
        return rendered, exit_code, status
    return rendered, exit_code


def check_file(ir: RepositoryIR, repo_root: Path, file: Path, config: Config | None = None) -> List[CheckResult]:
    """Run structural checks on the module that owns ``file`` using an in-memory IR."""

    module = _find_module_for_file(ir, repo_root, file)
    if module is None:
        raise RuntimeError(
            "No module found in IR for file: "
            f"{file.resolve()} (did you run `neurocode ir` on the right root?)"
        )

    cfg = config or Config()

    results: List[CheckResult] = []
    if "UNUSED_IMPORT" in cfg.enabled_checks:
        results.extend(_check_unused_imports(module, file, cfg))
    if "UNUSED_FUNCTION" in cfg.enabled_checks:
        results.extend(_check_functions_without_callers(ir, module, file, cfg))
    if "HIGH_FANOUT" in cfg.enabled_checks:
        results.extend(_check_high_fanout_functions(ir, module, file, cfg))
    if "UNUSED_PARAM" in cfg.enabled_checks:
        results.extend(_check_unused_params(repo_root, module, file, cfg))
    if "LONG_FUNCTION" in cfg.enabled_checks:
        results.extend(_check_long_functions(repo_root, module, file, cfg))
    if "CALL_CYCLE" in cfg.enabled_checks:
        results.extend(_check_call_cycles(ir, module, file, cfg))
    return results


def _check_unused_params(
    repo_root: Path,
    module: ModuleIR,
    file: Path,
    config: Config,
) -> List[CheckResult]:
    """Flag function parameters that are never referenced in the body."""

    abs_path = (repo_root / module.path).resolve()
    try:
        source = abs_path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    results: List[CheckResult] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [arg.arg for arg in node.args.args if arg.arg not in {"self", "cls"}]
        if not params:
            continue
        used: Set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                used.add(child.id)
        for param in params:
            if param not in used and not param.startswith("_"):
                results.append(
                    CheckResult(
                        code="UNUSED_PARAM",
                        severity=config.severity_for("UNUSED_PARAM", "INFO"),
                        message=f"Parameter '{param}' in {module.module_name}.{node.name} is never used",
                        file=file,
                        module=module.module_name,
                        function=node.name,
                        lineno=node.lineno,
                    )
                )

    return results


def _check_long_functions(
    repo_root: Path,
    module: ModuleIR,
    file: Path,
    config: Config,
) -> List[CheckResult]:
    """Flag functions longer than the configured threshold (approx via end_lineno)."""

    abs_path = (repo_root / module.path).resolve()
    try:
        source = abs_path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    results: List[CheckResult] = []
    threshold = config.long_function_threshold
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end_lineno = getattr(node, "end_lineno", None)
        if end_lineno is None:
            continue
        length = end_lineno - node.lineno + 1
        if length >= threshold:
            results.append(
                CheckResult(
                    code="LONG_FUNCTION",
                    severity=config.severity_for("LONG_FUNCTION", "INFO"),
                    message=f"{module.module_name}.{node.name} is {length} lines long (threshold {threshold})",
                    file=file,
                    module=module.module_name,
                    function=node.name,
                    lineno=node.lineno,
                )
            )
    return results


def _check_call_cycles(
    ir: RepositoryIR,
    module: ModuleIR,
    file: Path,
    config: Config,
) -> List[CheckResult]:
    """Detect simple call graph cycles involving functions in this module."""

    # Build adjacency for functions in this module.
    local_fn_ids: Set[int] = {fn.id for fn in module.functions}
    adj: Dict[int, Set[int]] = {}
    for edge in ir.call_edges:
        if edge.caller_function_id in local_fn_ids and edge.callee_function_id is not None:
            adj.setdefault(edge.caller_function_id, set()).add(edge.callee_function_id)

    visited: Set[int] = set()
    stack: Set[int] = set()
    cycles: List[List[int]] = []

    def dfs(node: int, path: List[int]) -> None:
        if node in stack:
            idx = path.index(node)
            cycles.append(path[idx:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        stack.add(node)
        for nxt in adj.get(node, set()):
            dfs(nxt, path + [nxt])
        stack.remove(node)

    for fn_id in local_fn_ids:
        if fn_id not in visited:
            dfs(fn_id, [fn_id])

    if not cycles:
        return []

    fn_by_id: Dict[int, FunctionIR] = {fn.id: fn for fn in module.functions}
    results: List[CheckResult] = []
    for cycle in cycles:
        names = [fn_by_id.get(fid).qualified_name for fid in cycle if fn_by_id.get(fid)]
        message = "Call cycle detected: " + " -> ".join(names)
        first_id = cycle[0]
        fn = fn_by_id.get(first_id)
        lineno = fn.lineno if fn else None
        results.append(
            CheckResult(
                code="CALL_CYCLE",
                severity=config.severity_for("CALL_CYCLE", "WARNING"),
                message=message,
                file=file,
                module=module.module_name,
                function=fn.name if fn else None,
                lineno=lineno,
            )
        )
    return results


def _render_results(results: List[CheckResult], output_format: str = "text", warnings: List[str] | None = None) -> tuple[str, int]:
    warnings = warnings or []
    if output_format == "json":
        import json

        diagnostics = [
            {
                "code": r.code,
                "severity": r.severity,
                "message": r.message,
                "file": str(r.file),
                "module": r.module,
                "function": r.function,
                "lineno": r.lineno,
            }
            for r in results
        ]
        payload = {"diagnostics": diagnostics, "warnings": warnings}
        exit_code = 0
        for r in results:
            if r.severity.upper() in {"WARNING", "ERROR"}:
                exit_code = 1
                break
        return json.dumps(payload, indent=2), exit_code

    if not results:
        if warnings:
            return "\n".join(f"[neurocode] warning: {w}" for w in warnings) + "\n[neurocode] No issues found.", 0
        return "[neurocode] No issues found.", 0

    results_sorted = sorted(
        results,
        key=lambda r: (
            str(r.file),
            r.lineno if r.lineno is not None else -1,
            r.code,
            r.message,
        ),
    )

    lines: List[str] = []
    exit_code = 0
    for res in results_sorted:
        severity = res.severity.upper()
        location = str(res.file)
        if res.lineno is not None:
            location = f"{location}:{res.lineno}"
        lines.append(f"{severity} {res.code} {location} {res.message}")
        if severity in {"WARNING", "ERROR"}:
            exit_code = 1
    if warnings:
        lines = [f"[neurocode] warning: {w}" for w in warnings] + lines
    return "\n".join(lines), exit_code


def _build_status(results: List[CheckResult], warnings: List[str], exit_code: int) -> str:
    """Return a one-line status for automation."""

    warning_count = len(warnings)
    counts = {"INFO": 0, "WARNING": 0, "ERROR": 0}
    for r in results:
        counts[r.severity.upper()] = counts.get(r.severity.upper(), 0) + 1
    return (
        f"status exit_code={exit_code} warnings={warning_count} "
        f"info={counts.get('INFO',0)} warn={counts.get('WARNING',0)} error={counts.get('ERROR',0)}"
    )


def _staleness_warning(module: ModuleIR, repo_root: Path) -> str | None:
    if not module.file_hash:
        return None
    curr_path = (repo_root / module.path).resolve()
    try:
        current_hash = compute_file_hash(curr_path)
    except OSError:
        return f"module file missing on disk: {curr_path}"
    if current_hash != module.file_hash:
        return f"IR hash for {module.module_name} is stale; file changed on disk"
    return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_unused_imports(
    module: ModuleIR,
    file: Path,
    config: Config,
) -> List[CheckResult]:
    """Flag imports within ``module`` that do not appear in any call targets."""

    if not module.imports:
        return []

    used_symbols: Set[str] = set()
    for fn in module.functions:
        for call in fn.calls:
            target = call.target
            if not target:
                continue
            parts = target.split(".")
            for i in range(1, len(parts) + 1):
                used_symbols.add(".".join(parts[:i]))

    results: List[CheckResult] = []

    for imp in module.imports:
        candidate_symbols: List[str] = []
        if imp.alias:
            candidate_symbols.append(imp.alias)
        if imp.kind == "import":
            candidate_symbols.append(imp.name.split(".")[-1])
            candidate_symbols.append(imp.name)
        elif imp.kind == "from":
            candidate_symbols.append(imp.name)
            if imp.module:
                candidate_symbols.append(f"{imp.module}.{imp.name}")
        else:  # pragma: no cover - defensive
            continue

        # Remove empty or duplicate tokens while preserving order.
        seen: Set[str] = set()
        filtered_candidates: List[str] = []
        for symbol in candidate_symbols:
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            filtered_candidates.append(symbol)

        if any(symbol in used_symbols for symbol in filtered_candidates):
            continue

        if imp.kind == "import":
            imported_repr = imp.name
        else:
            imported_repr = f"{imp.module}.{imp.name}" if imp.module else imp.name

        message = f"{imported_repr} imported in {module.module_name} but never used"
        results.append(
            CheckResult(
                code="UNUSED_IMPORT",
                severity=config.severity_for("UNUSED_IMPORT", "WARNING"),
                message=message,
                file=file,
                module=module.module_name,
            )
        )

    return results


def _check_functions_without_callers(
    ir: RepositoryIR,
    module: ModuleIR,
    file: Path,
    config: Config,
) -> List[CheckResult]:
    """Flag functions in ``module`` with no incoming call edges.

    This is a heuristic that can surface dead code but may also flag functions
    that are used externally (e.g., via reflection or as public API).
    """

    called_function_ids: Set[int] = {
        edge.callee_function_id
        for edge in ir.call_edges
        if edge.callee_function_id is not None
    }

    def should_ignore(fn: FunctionIR) -> bool:
        name = fn.name
        # Ignore dunder, private, and pytest-style test functions.
        if name.startswith("__") and name.endswith("__"):
            return True
        if name.startswith("_") and not name.startswith("__"):
            return True
        if name.startswith("test_"):
            return True
        return False

    results: List[CheckResult] = []

    for fn in module.functions:
        if should_ignore(fn):
            continue
        if fn.id not in called_function_ids:
            message = (
                f"{fn.qualified_name} is never called from any other function"
            )
            results.append(
                CheckResult(
                    code="UNUSED_FUNCTION",
                    severity=config.severity_for("UNUSED_FUNCTION", "INFO"),
                    message=message,
                    file=file,
                    module=module.module_name,
                    function=fn.name,
                    lineno=fn.lineno,
                )
            )

    return results


def _check_high_fanout_functions(
    ir: RepositoryIR,
    module: ModuleIR,
    file: Path,
    config: Config,
) -> List[CheckResult]:
    """Flag functions that call many distinct targets (high fan-out).

    This is a simple complexity smell: functions orchestrating too many
    different callees can be hard to understand and test.
    """

    module_fn_ids: Set[int] = {fn.id for fn in module.functions}
    if not module_fn_ids:
        return []

    # Map function -> set of distinct targets (resolved ids when possible).
    targets_by_fn: Dict[int, Set[str]] = {}
    for edge in ir.call_edges:
        caller_fn_id = edge.caller_function_id
        if caller_fn_id not in module_fn_ids:
            continue
        if edge.callee_function_id is not None:
            key = f"id:{edge.callee_function_id}"
        else:
            key = f"name:{edge.target}"
        targets_by_fn.setdefault(caller_fn_id, set()).add(key)

    results: List[CheckResult] = []

    for fn in module.functions:
        targets = targets_by_fn.get(fn.id, set())
        if len(targets) >= config.fanout_threshold:
            message = (
                f"{fn.qualified_name} calls {len(targets)} distinct functions"
            )
            results.append(
                CheckResult(
                    code="HIGH_FANOUT",
                    severity=config.severity_for("HIGH_FANOUT", "INFO"),
                    message=message,
                    file=file,
                    module=module.module_name,
                    function=fn.name,
                    lineno=fn.lineno,
                )
            )

    return results
