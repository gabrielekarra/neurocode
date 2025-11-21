from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
from typing import Dict, List, Set, Tuple

from .ir_model import (
    CallEdgeIR,
    CallIR,
    ClassIR,
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


@dataclass
class _ClassContext:
    class_ir: ClassIR


class _IRVisitor(ast.NodeVisitor):
    """AST visitor that populates imports, functions, and call sites for a module."""

    def __init__(self, module_id: int, module_name: str) -> None:
        self.module_id = module_id
        self.module_name = module_name
        self.imports: List[ImportIR] = []
        self.functions: List[FunctionIR] = []
        self.classes: List[ClassIR] = []
        self._next_class_id = 0
        self._next_function_id = 0
        self._current_stack: List[_FunctionContext] = []
        self._class_stack: List[_ClassContext] = []

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

    # Classes -------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # type: ignore[override]
        class_id = self._next_class_id
        self._next_class_id += 1

        ancestor_names = [ctx.class_ir.name for ctx in self._class_stack]
        path_parts = [self.module_name, *ancestor_names, node.name]
        qualified_name = ".".join(path_parts)
        base_names = [render_base_name(base) for base in node.bases]

        class_ir = ClassIR(
            id=class_id,
            module_id=self.module_id,
            name=node.name,
            qualified_name=qualified_name,
            lineno=node.lineno,
            base_names=[name for name in base_names if name],
        )
        ctx = _ClassContext(class_ir=class_ir)
        self._class_stack.append(ctx)
        try:
            self.generic_visit(node)
        finally:
            self._class_stack.pop()
            self.classes.append(class_ir)

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
        class_names = [ctx.class_ir.name for ctx in self._class_stack]
        if class_names:
            qualified_name = ".".join([self.module_name, *class_names, name])
            parent_class = self._class_stack[-1].class_ir
            parent_class_id = parent_class.id
            parent_class_qualified = parent_class.qualified_name
        else:
            qualified_name = f"{self.module_name}.{name}"
            parent_class_id = None
            parent_class_qualified = None

        fn_ir = FunctionIR(
            id=func_id,
            module_id=self.module_id,
            name=name,
            qualified_name=qualified_name,
            lineno=node.lineno,  # type: ignore[attr-defined]
            parent_class_id=parent_class_id,
            parent_class_qualified_name=parent_class_qualified,
        )
        if self._class_stack:
            self._class_stack[-1].class_ir.methods.append(fn_ir)
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


def render_base_name(node: ast.AST) -> str:
    """Best-effort textual representation of a class base expression."""

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
    try:
        value = ast.unparse(node)
    except Exception:  # pragma: no cover - very defensive
        return ""
    # Drop generic parameters like Base[T].
    if "[" in value:
        value = value.split("[", 1)[0]
    return value


def build_repository_ir(root: Path) -> RepositoryIR:
    """Build a RepositoryIR for all Python files under ``root``.

    Currently extracts modules, imports, functions, intra-function call sites,
    and derives module import and call graph edges.
    """

    root = root.resolve()
    rel_paths = discover_python_files(root)

    modules: List[ModuleIR] = []
    module_id = 0
    next_class_id = 0

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

        for cls in visitor.classes:
            cls.id = next_class_id
            next_class_id += 1
            for method in cls.methods:
                method.parent_class_id = cls.id
                method.parent_class_qualified_name = cls.qualified_name

        module_ir = ModuleIR(
            id=module_id,
            path=rel_path,
            module_name=mod_name,
            classes=visitor.classes,
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
    class_by_id: Dict[int, ClassIR] = {}
    class_by_qualified_name: Dict[str, ClassIR] = {}
    for module in modules:
        for cls in module.classes:
            class_by_id[cls.id] = cls
            class_by_qualified_name[cls.qualified_name] = cls

    for module in modules:
        # Build simple import alias maps for this module.
        module_aliases: Dict[str, str] = {}
        func_imports: Dict[str, Tuple[str, str]] = {}
        class_lookup: Dict[str, ClassIR] = {}
        for cls in module.classes:
            class_lookup[cls.name] = cls
            qual = cls.qualified_name
            class_lookup[qual] = cls
            if qual.startswith(f"{module.module_name}."):
                local = qual[len(module.module_name) + 1 :]
                class_lookup[local] = cls
        for imp in module.imports:
            if imp.kind == "import":
                imported_module = imp.name
                local_name = imp.alias or imported_module.split(".")[-1]
                module_aliases[local_name] = imported_module
            elif imp.kind == "from":
                imported_module = imp.module or ""
                local_name = imp.alias or imp.name
                func_imports[local_name] = (imported_module, imp.name)

        def _resolve_class_name(name: str) -> ClassIR | None:
            if not name:
                return None
            candidate = class_lookup.get(name)
            if candidate is not None:
                return candidate
            candidate = class_by_qualified_name.get(name)
            if candidate is not None:
                return candidate
            if "." in name:
                tail = name.split(".", 1)[-1]
                candidate = class_lookup.get(tail)
                if candidate is not None:
                    return candidate
                candidate = class_by_qualified_name.get(tail)
                if candidate is not None:
                    return candidate
            return None

        def _iter_class_hierarchy(start_cls: ClassIR) -> List[ClassIR]:
            ordered: List[ClassIR] = []
            stack: List[ClassIR] = [start_cls]
            seen: Set[int] = set()
            while stack:
                cls = stack.pop()
                if cls.id in seen:
                    continue
                seen.add(cls.id)
                ordered.append(cls)
                for base_name in cls.base_names:
                    base_cls = _resolve_class_name(base_name)
                    if base_cls is not None and base_cls.id not in seen:
                        stack.append(base_cls)
            return ordered

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

                # 2b) Methods referenced via self/cls.
                if (
                    callee_id is None
                    and "." in target
                    and fn.parent_class_id is not None
                ):
                    owning_class = class_by_id.get(fn.parent_class_id)
                    if owning_class is not None:
                        prefix, rest = target.split(".", 1)
                        method_name: str | None = None
                        candidate_classes: List[ClassIR] = []
                        hierarchy = _iter_class_hierarchy(owning_class)
                        if prefix in {"self", "cls"}:
                            method_name = rest.split(".", 1)[0]
                            candidate_classes.extend(hierarchy)
                        elif prefix.startswith("super()") or prefix.startswith("super("):
                            method_name = rest.split(".", 1)[0]
                            candidate_classes.extend(hierarchy[1:])
                        if method_name:
                            for candidate_cls in candidate_classes:
                                qualified = f"{candidate_cls.qualified_name}.{method_name}"
                                fn_obj = function_by_qualified.get(qualified)
                                if fn_obj is not None:
                                    callee_id = fn_obj.id
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

                # 5) Direct class reference: ClassName.method
                if callee_id is None and "." in target:
                    class_expr, method_expr = target.rsplit(".", 1)
                    cls = class_lookup.get(class_expr)
                    if cls is not None:
                        method_name = method_expr.split(".", 1)[0]
                        qualified = f"{cls.qualified_name}.{method_name}"
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
