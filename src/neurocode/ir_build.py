from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
from typing import Dict, List, Tuple

from .ir_model import (
    CallEdgeIR,
    CallIR,
    FunctionIR,
    ImportIR,
    ModuleImportEdgeIR,
    ModuleIR,
    RepositoryIR,
)


def discover_python_files(root: Path) -> List[Path]:
    """Recursively discover Python source files under ``root``.

    Returns paths relative to ``root``.
    """

    root = root.resolve()
    paths: List[Path] = []
    for path in root.rglob("*.py"):
        # Skip virtual environments and typical build artifacts by convention.
        if any(part in {".venv", "venv", "dist", "build", "__pycache__"} for part in path.parts):
            continue
        paths.append(path.relative_to(root))
    return sorted(paths)


def module_name_from_path(root: Path, rel_path: Path) -> str:
    """Derive a Python module name from a file path relative to ``root``.

    For example ``src/neurocode/cli.py`` -> ``neurocode.cli``.
    """

    # Prefer stripping a leading ``src/`` if present.
    parts = list(rel_path.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


@dataclass
class _FunctionContext:
    function: FunctionIR


class _IRVisitor(ast.NodeVisitor):
    """AST visitor that populates imports, functions, and call sites for a module."""

    def __init__(self, module_id: int, module_name: str) -> None:
        self.module_id = module_id
        self.module_name = module_name
        self.imports: List[ImportIR] = []
        self.functions: List[FunctionIR] = []
        self._next_function_id = 0
        self._current_stack: List[_FunctionContext] = []

    # Imports -------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:  # type: ignore[override]
        for alias in node.names:
            self.imports.append(
                ImportIR(
                    kind="import",
                    module=None,
                    name=alias.name,
                    alias=alias.asname,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # type: ignore[override]
        module_name = node.module or ""
        for alias in node.names:
            self.imports.append(
                ImportIR(
                    kind="from",
                    module=module_name,
                    name=alias.name,
                    alias=alias.asname,
                )
            )
        self.generic_visit(node)

    # Functions & calls ---------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # type: ignore[override]
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # type: ignore[override]
        self._handle_function(node)

    def _handle_function(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        func_id = self._next_function_id
        self._next_function_id += 1

        name = node.name  # type: ignore[attr-defined]
        qualified_name = f"{self.module_name}.{name}"
        fn_ir = FunctionIR(
            id=func_id,
            module_id=self.module_id,
            name=name,
            qualified_name=qualified_name,
            lineno=node.lineno,  # type: ignore[attr-defined]
        )
        ctx = _FunctionContext(function=fn_ir)
        self._current_stack.append(ctx)
        try:
            self.generic_visit(node)
        finally:
            self._current_stack.pop()
            self.functions.append(fn_ir)

    def visit_Call(self, node: ast.Call) -> None:  # type: ignore[override]
        if self._current_stack:
            target = render_call_target(node.func)
            self._current_stack[-1].function.calls.append(
                CallIR(lineno=node.lineno, target=target)
            )
        self.generic_visit(node)


def render_call_target(node: ast.AST) -> str:
    """Best-effort string representation of a call target.

    Examples: ``foo``, ``module.func``, ``obj.method``.
    """

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: List[str] = []
        curr: ast.AST | None = node
        while isinstance(curr, ast.Attribute):
            parts.append(curr.attr)
            curr = curr.value
        if isinstance(curr, ast.Name):
            parts.append(curr.id)
            parts.reverse()
            return ".".join(parts)
        # Fallback to ``ast.unparse`` if available.
        try:
            return ast.unparse(node)
        except Exception:  # pragma: no cover - very defensive
            return "<attr>"
    try:
        return ast.unparse(node)  # type: ignore[no-any-return]
    except Exception:  # pragma: no cover - very defensive
        return "<expr>"


def build_repository_ir(root: Path) -> RepositoryIR:
    """Build a RepositoryIR for all Python files under ``root``.

    Currently extracts modules, imports, functions, intra-function call sites,
    and derives module import and call graph edges.
    """

    root = root.resolve()
    rel_paths = discover_python_files(root)

    modules: List[ModuleIR] = []
    module_id = 0

    # First pass: build per-module IR (imports, functions, call sites).
    for rel_path in rel_paths:
        abs_path = root / rel_path
        try:
            source = abs_path.read_text(encoding="utf-8")
        except OSError:
            # Skip unreadable files; we may want to surface these later.
            continue

        try:
            tree = ast.parse(source, filename=str(abs_path))
        except SyntaxError:
            # Skip files that fail to parse; we may want to log these later.
            continue

        mod_name = module_name_from_path(root, rel_path)
        visitor = _IRVisitor(module_id=module_id, module_name=mod_name)
        visitor.visit(tree)

        module_ir = ModuleIR(
            id=module_id,
            path=rel_path,
            module_name=mod_name,
            imports=visitor.imports,
            functions=visitor.functions,
        )
        modules.append(module_ir)
        module_id += 1

    # Second pass: assign repository-wide unique function IDs.
    next_function_id = 0
    for module in modules:
        for fn in module.functions:
            fn.id = next_function_id
            next_function_id += 1

    # Build indexes for resolution.
    function_by_qualified: Dict[str, FunctionIR] = {}
    for module in modules:
        for fn in module.functions:
            function_by_qualified[fn.qualified_name] = fn

    # Module import edges (module -> imported module name).
    module_import_edge_pairs: set[Tuple[int, str]] = set()
    for module in modules:
        for imp in module.imports:
            imported_module: str | None
            if imp.kind == "import":
                imported_module = imp.name
            elif imp.kind == "from":
                imported_module = imp.module or ""
            else:  # pragma: no cover - defensive
                imported_module = None
            if imported_module:
                module_import_edge_pairs.add((module.id, imported_module))

    module_import_edges = [
        ModuleImportEdgeIR(importer_module_id=mod_id, imported_module=mod_name)
        for (mod_id, mod_name) in sorted(module_import_edge_pairs, key=lambda pair: pair)
    ]

    # Call graph edges (caller function -> callee function when resolvable).
    call_edges: List[CallEdgeIR] = []
    for module in modules:
        # Build simple import alias maps for this module.
        module_aliases: Dict[str, str] = {}
        func_imports: Dict[str, Tuple[str, str]] = {}
        for imp in module.imports:
            if imp.kind == "import":
                imported_module = imp.name
                local_name = imp.alias or imported_module.split(".")[-1]
                module_aliases[local_name] = imported_module
            elif imp.kind == "from":
                imported_module = imp.module or ""
                local_name = imp.alias or imp.name
                func_imports[local_name] = (imported_module, imp.name)

        for fn in module.functions:
            for call in fn.calls:
                target = call.target
                callee_id: int | None = None

                # 1) Fully-qualified function name.
                fn_obj = function_by_qualified.get(target)
                if fn_obj is not None:
                    callee_id = fn_obj.id

                # 2) Local function in the same module.
                if callee_id is None:
                    for candidate in module.functions:
                        if candidate.name == target:
                            callee_id = candidate.id
                            break

                # 3) Imported function via "from module import name".
                if callee_id is None and target in func_imports:
                    imported_module, original_name = func_imports[target]
                    if imported_module:
                        qualified = f"{imported_module}.{original_name}"
                        fn_obj = function_by_qualified.get(qualified)
                        if fn_obj is not None:
                            callee_id = fn_obj.id

                # 4) Module alias + attribute: alias.func
                if callee_id is None and "." in target:
                    prefix, rest = target.split(".", 1)
                    if prefix in module_aliases:
                        imported_module = module_aliases[prefix]
                        func_name = rest.split(".", 1)[0]
                        qualified = f"{imported_module}.{func_name}"
                        fn_obj = function_by_qualified.get(qualified)
                        if fn_obj is not None:
                            callee_id = fn_obj.id

                call_edges.append(
                    CallEdgeIR(
                        caller_function_id=fn.id,
                        callee_function_id=callee_id,
                        lineno=call.lineno,
                        target=target,
                    )
                )

    return RepositoryIR(
        root=root,
        modules=modules,
        module_import_edges=module_import_edges,
        call_edges=call_edges,
    )
