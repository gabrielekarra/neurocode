from __future__ import annotations

from pathlib import Path
from typing import List

from .ir_model import RepositoryIR


def _escape_value(value: str) -> str:
    """Escape a scalar value for use in a TOON table cell.

    For now we keep this conservative: commas and newlines are replaced.
    """

    value = value.replace("\n", "\\n")
    value = value.replace(",", "\\,")
    return value


def repository_ir_to_toon(ir: RepositoryIR) -> str:
    """Serialize a RepositoryIR into a TOON document.

    The current encoding focuses on TOON's strength: uniform arrays of objects.
    We expose three primary tables:

    - ``modules``   – one row per module (file)
    - ``functions`` – one row per function/method
    - ``calls``     – one row per call site

    All paths are relative to the repository root when possible.
    """

    root: Path = ir.root

    lines: List[str] = []

    # Header metadata (YAML-like TOON object section).
    lines.append("repo:")
    lines.append(f"  root: {root}")
    lines.append(f"  num_modules: {ir.num_modules}")
    lines.append(f"  num_classes: {ir.num_classes}")
    lines.append(f"  num_functions: {ir.num_functions}")
    lines.append(f"  num_calls: {ir.num_calls}")
    lines.append("")

    # Modules table -------------------------------------------------------

    lines.append(
        "modules[{n}]{{module_id,module_name,path,num_functions,num_imports}}:".format(
            n=ir.num_modules
        )
    )
    for module in ir.modules:
        path_str = str(module.path)
        row = ",".join(
            [
                str(module.id),
                _escape_value(module.module_name),
                _escape_value(path_str),
                str(len(module.functions)),
                str(len(module.imports)),
            ]
        )
        lines.append(f"  {row}")
    lines.append("")

    # Classes table -------------------------------------------------------

    all_classes = [cls for module in ir.modules for cls in module.classes]
    lines.append(
        "classes[{n}]{{class_id,module_id,name,qualified_name,lineno,base_names,num_methods}}:".format(
            n=len(all_classes)
        )
    )
    for cls in all_classes:
        base_names = "|".join(cls.base_names)
        row = ",".join(
            [
                str(cls.id),
                str(cls.module_id),
                _escape_value(cls.name),
                _escape_value(cls.qualified_name),
                str(cls.lineno),
                _escape_value(base_names),
                str(len(cls.methods)),
            ]
        )
        lines.append(f"  {row}")
    lines.append("")

    # Module import statements --------------------------------------------

    all_imports: List[str] = []
    for module in ir.modules:
        for imp in module.imports:
            row = ",".join(
                [
                    str(module.id),
                    _escape_value(imp.kind),
                    _escape_value(imp.module or ""),
                    _escape_value(imp.name),
                    _escape_value(imp.alias or ""),
                ]
            )
            all_imports.append(row)

    lines.append(
        "imports[{n}]{{module_id,kind,module,name,alias}}:".format(
            n=len(all_imports)
        )
    )
    for row in all_imports:
        lines.append(f"  {row}")
    lines.append("")

    # Functions table -----------------------------------------------------

    all_functions = [fn for m in ir.modules for fn in m.functions]
    lines.append(
        "functions[{n}]{{function_id,module_id,name,qualified_name,lineno,parent_class_id,parent_class_qualified_name,num_calls}}:".format(
            n=len(all_functions)
        )
    )
    for fn in all_functions:
        parent_class_id = "" if fn.parent_class_id is None else str(fn.parent_class_id)
        parent_class_name = _escape_value(fn.parent_class_qualified_name or "")
        row = ",".join(
            [
                str(fn.id),
                str(fn.module_id),
                _escape_value(fn.name),
                _escape_value(fn.qualified_name),
                str(fn.lineno),
                parent_class_id,
                parent_class_name,
                str(len(fn.calls)),
            ]
        )
        lines.append(f"  {row}")
    lines.append("")

    # Calls table ---------------------------------------------------------

    all_calls_rows: List[str] = []
    for module in ir.modules:
        for fn in module.functions:
            for call in fn.calls:
                row = ",".join(
                    [
                        str(fn.id),
                        str(module.id),
                        str(call.lineno),
                        _escape_value(call.target),
                    ]
                )
                all_calls_rows.append(row)

    lines.append(
        "calls[{n}]{{function_id,module_id,lineno,target}}:".format(
            n=len(all_calls_rows)
        )
    )
    for row in all_calls_rows:
        lines.append(f"  {row}")

    lines.append("")

    # Module import edges table -------------------------------------------

    lines.append(
        "module_imports[{n}]{{module_id,imported_module}}:".format(
            n=len(ir.module_import_edges)
        )
    )
    for edge in ir.module_import_edges:
        row = ",".join(
            [
                str(edge.importer_module_id),
                _escape_value(edge.imported_module),
            ]
        )
        lines.append(f"  {row}")

    lines.append("")

    # Call graph edges table ----------------------------------------------

    lines.append(
        "call_graph[{n}]{{caller_function_id,callee_function_id,lineno,target}}:".format(
            n=len(ir.call_edges)
        )
    )
    for edge in ir.call_edges:
        callee = "" if edge.callee_function_id is None else str(edge.callee_function_id)
        row = ",".join(
            [
                str(edge.caller_function_id),
                callee,
                str(edge.lineno),
                _escape_value(edge.target),
            ]
        )
        lines.append(f"  {row}")

    lines.append("")

    return "\n".join(lines)
