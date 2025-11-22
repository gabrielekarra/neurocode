from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .ir_build import compute_file_hash
from .ir_model import FunctionIR, ModuleIR, RepositoryIR
from .toon_parse import load_repository_ir


def _find_repo_root_for_file(file_path: Path) -> Path | None:
    """Find the repository root for a file by looking for `.neurocode/ir.toon`.

    Walks upward from the file's parent directory until it finds a directory
    containing `.neurocode/ir.toon`. Returns that directory, or ``None`` if not found.
    """

    current = file_path.resolve().parent
    for directory in (current, *current.parents):
        ir_file = directory / ".neurocode" / "ir.toon"
        if ir_file.is_file():
            return directory
    return None


def _find_module_for_file(ir: RepositoryIR, root: Path, file_path: Path) -> ModuleIR | None:
    """Locate the ModuleIR corresponding to a filesystem path.

    Prefers matching on the path relative to the repository root, with a
    fallback to absolute path comparison.
    """

    root = root.resolve()
    file_path = file_path.resolve()

    rel_path: Path | None
    try:
        rel_path = file_path.relative_to(root)
    except ValueError:
        rel_path = None

    for module in ir.modules:
        if rel_path is not None and module.path == rel_path:
            return module
        if (root / module.path).resolve() == file_path:
            return module
    return None


def _explain_module_json(ir: RepositoryIR, module: ModuleIR, warning: str | None = None) -> str:
    """Return a JSON string summarizing the module using the IR."""

    import json

    fn_by_id: Dict[int, FunctionIR] = {}
    for m in ir.modules:
        for fn in m.functions:
            fn_by_id[fn.id] = fn

    imports = sorted(
        {
            edge.imported_module
            for edge in ir.module_import_edges
            if edge.importer_module_id == module.id
        }
    )

    def call_edges_for(fn: FunctionIR) -> List[dict]:
        edges = [
            edge for edge in ir.call_edges if edge.caller_function_id == fn.id
        ]
        edges_sorted = sorted(edges, key=lambda e: e.lineno)
        items: List[dict] = []
        for edge in edges_sorted:
            callee = fn_by_id.get(edge.callee_function_id) if edge.callee_function_id is not None else None
            items.append(
                {
                    "lineno": edge.lineno,
                    "target": edge.target,
                    "resolved_callee": callee.qualified_name if callee else None,
                }
            )
        return items

    classes_payload: List[dict] = []
    for cls in sorted(module.classes, key=lambda c: c.lineno):
        classes_payload.append(
            {
                "name": cls.name,
                "qualified_name": cls.qualified_name,
                "lineno": cls.lineno,
                "base_names": cls.base_names,
                "methods": [
                    {
                        "name": m.name,
                        "qualified_name": m.qualified_name,
                        "lineno": m.lineno,
                        "calls": call_edges_for(m),
                    }
                    for m in sorted(cls.methods, key=lambda f: f.lineno)
                ],
            }
        )

    functions_payload: List[dict] = []
    for fn in sorted(
        [f for f in module.functions if f.parent_class_id is None],
        key=lambda f: f.lineno,
    ):
        functions_payload.append(
            {
                "name": fn.name,
                "qualified_name": fn.qualified_name,
                "lineno": fn.lineno,
                "calls": call_edges_for(fn),
            }
        )

    payload = {
        "module": module.module_name,
        "path": str(module.path),
        "imports": imports,
        "classes": classes_payload,
        "functions": functions_payload,
        "warning": warning,
    }
    return json.dumps(payload, indent=2)


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


def explain_file_from_disk(file: Path, output_format: str = "text") -> str:
    """High-level helper for the CLI: explain a Python file given its path.

    - Finds the repository root by walking up until `.neurocode/ir.toon` is found.
    - Loads the IR from that TOON file.
    - Renders a human-readable explanation for the module containing ``file``.
    """

    repo_root = _find_repo_root_for_file(file)
    if repo_root is None:
        raise RuntimeError(
            "Could not find .neurocode/ir.toon. Run `neurocode ir` at the repository root first."
        )

    ir_file = repo_root / ".neurocode" / "ir.toon"
    ir = load_repository_ir(ir_file)
    return explain_file(ir=ir, repo_root=repo_root, file=file, output_format=output_format)


def explain_file(
    ir: RepositoryIR,
    repo_root: Path,
    file: Path,
    output_format: str = "text",
) -> str:
    """Render a human-readable explanation for a file using an in-memory IR.

    Output is a plain-text summary including:
    - module name and path
    - imports (via the module import graph)
    - functions in the module and their outbound calls
    """

    module = _find_module_for_file(ir, repo_root, file)
    if module is None:
        return (
            "[neurocode] No module found in IR for file: "
            f"{file.resolve()} (did you run `neurocode ir` on the right root?)"
        )

    warning = _staleness_warning(module, repo_root)

    if output_format == "json":
        return _explain_module_json(ir, module, warning=warning)

    lines: List[str] = []
    if warning:
        lines.append(f"[neurocode] warning: {warning}")
    lines.append(f"Module: {module.module_name}")
    lines.append(f"Path: {module.path}")
    lines.append("")

    # Build lookup for functions by id for resolving call graph edges.
    fn_by_id: Dict[int, FunctionIR] = {}
    for m in ir.modules:
        for fn in m.functions:
            fn_by_id[fn.id] = fn

    # Imports via module_import_edges.
    imported_modules = sorted(
        {
            edge.imported_module
            for edge in ir.module_import_edges
            if edge.importer_module_id == module.id
        }
    )

    lines.append("Imports:")
    if imported_modules:
        for name in imported_modules:
            lines.append(f"  - {name}")
    else:
        lines.append("  (none)")
    lines.append("")

    def _append_function_section(fn: FunctionIR) -> None:
        lines.append(f"    * {fn.qualified_name} (line {fn.lineno})")
        call_edges = [
            edge for edge in ir.call_edges if edge.caller_function_id == fn.id
        ]
        if not call_edges:
            lines.append("        calls: (none)")
            return

        lines.append("        calls:")
        for edge in sorted(call_edges, key=lambda e: e.lineno):
            callee_desc: str
            if edge.callee_function_id is not None:
                callee_fn = fn_by_id.get(edge.callee_function_id)
                if callee_fn is not None:
                    callee_desc = f" -> {callee_fn.qualified_name}"
                else:  # pragma: no cover - very defensive
                    callee_desc = ""
            else:
                callee_desc = ""
            lines.append(
                f"          line {edge.lineno}: {edge.target}{callee_desc}"
            )

    # Classes and methods.
    lines.append("Classes:")
    if module.classes:
        for cls in sorted(module.classes, key=lambda c: c.lineno):
            lines.append(f"- {cls.qualified_name} (line {cls.lineno})")
            methods = sorted(cls.methods, key=lambda f: f.lineno)
            if not methods:
                lines.append("    methods: (none)")
                continue
            for method in methods:
                _append_function_section(method)
    else:
        lines.append("  (none)")

    lines.append("")

    # Module-level functions.
    module_level_functions = [
        fn for fn in module.functions if fn.parent_class_id is None
    ]
    lines.append("Functions:")
    if not module_level_functions:
        lines.append("  (none)")
        return "\n".join(lines)

    for fn in sorted(module_level_functions, key=lambda f: f.lineno):
        lines.append(f"- {fn.qualified_name} (line {fn.lineno})")
        call_edges = [
            edge
            for edge in ir.call_edges
            if edge.caller_function_id == fn.id
        ]

        if not call_edges:
            lines.append("    calls: (none)")
            continue

        lines.append("    calls:")
        for edge in sorted(call_edges, key=lambda e: e.lineno):
            callee_desc: str
            if edge.callee_function_id is not None:
                callee_fn = fn_by_id.get(edge.callee_function_id)
                if callee_fn is not None:
                    callee_desc = f" -> {callee_fn.qualified_name}"
                else:  # pragma: no cover - very defensive
                    callee_desc = ""
            else:
                callee_desc = ""

            lines.append(
                f"      line {edge.lineno}: {edge.target}{callee_desc}"
            )

    return "\n".join(lines)
