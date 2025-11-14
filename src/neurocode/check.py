from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

from .explain import _find_module_for_file, _find_repo_root_for_file
from .ir_model import FunctionIR, ModuleIR, RepositoryIR
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


def check_file_from_disk(file: Path) -> List[CheckResult]:
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
    return check_file(ir=ir, repo_root=repo_root, file=file)


def check_file(ir: RepositoryIR, repo_root: Path, file: Path) -> List[CheckResult]:
    """Run structural checks on the module that owns ``file`` using an in-memory IR."""

    module = _find_module_for_file(ir, repo_root, file)
    if module is None:
        raise RuntimeError(
            "No module found in IR for file: "
            f"{file.resolve()} (did you run `neurocode ir` on the right root?)"
        )

    results: List[CheckResult] = []
    results.extend(_check_unused_imports(module, file))
    results.extend(_check_functions_without_callers(ir, module, file))
    results.extend(_check_high_fanout_functions(ir, module, file))
    return results


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_unused_imports(
    module: ModuleIR,
    file: Path,
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
                severity="WARNING",
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
                    severity="INFO",
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
    threshold: int = 10,
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
        if len(targets) >= threshold:
            message = (
                f"{fn.qualified_name} calls {len(targets)} distinct functions"
            )
            results.append(
                CheckResult(
                    code="HIGH_FANOUT",
                    severity="INFO",
                    message=message,
                    file=file,
                    module=module.module_name,
                    function=fn.name,
                    lineno=fn.lineno,
                )
            )

    return results
