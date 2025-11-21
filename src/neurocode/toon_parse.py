from __future__ import annotations

from pathlib import Path
from typing import Dict, List

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


def _unescape_value(value: str) -> str:
    """Reverse the escaping used in ``toon_serialize._escape_value``.

    Currently handles newlines and commas.
    """

    # Order matters: first restore escaped commas, then newlines.
    value = value.replace("\\,", ",")
    value = value.replace("\\n", "\n")
    return value


def _parse_row(line: str) -> List[str]:
    """Parse a single TOON row line into fields.

    The writer only escapes commas and newlines via backslash, so we treat
    ``","`` as a separator unless it is escaped by ``\\``.
    """

    fields: List[str] = []
    current: List[str] = []
    escaped = False

    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ",":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)

    fields.append("".join(current))
    return fields


def _parse_table_header(line: str) -> tuple[str, List[str]]:
    """Parse a TOON table header line like ``name[n]{a,b,c}:``.

    Returns (table_name, [field1, field2, ...]).
    """

    line = line.strip()
    # name[...]{...}:
    name_part, rest = line.split("[", 1)
    name = name_part.strip()
    # Skip count between [ and ]
    _, rest_after_bracket = rest.split("]", 1)
    brace_start = rest_after_bracket.index("{")
    brace_end = rest_after_bracket.index("}")
    fields_str = rest_after_bracket[brace_start + 1 : brace_end]
    fields = [field.strip() for field in fields_str.split(",") if field.strip()]
    return name, fields


def repository_ir_from_toon(text: str) -> RepositoryIR:
    """Parse a RepositoryIR from the TOON text emitted by ``repository_ir_to_toon``.

    This parser intentionally understands only the subset of TOON that this
    project writes: a top-level ``repo`` header followed by the ``modules``,
    ``functions``, ``calls``, ``module_imports``, and ``call_graph`` tables.
    """

    lines = text.splitlines()

    root: Path | None = None
    current_table: str | None = None
    current_fields: List[str] = []
    tables: Dict[str, List[Dict[str, str]]] = {}
    in_repo_header = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if not stripped:
            # Blank line ends repo header / table rows.
            if in_repo_header:
                in_repo_header = False
            continue

        # Repo header object.
        if stripped == "repo:":
            in_repo_header = True
            current_table = None
            continue

        if in_repo_header and stripped.startswith("root:"):
            # Format: "root: /abs/path" (no escaping applied when writing).
            _, value = stripped.split(":", 1)
            root = Path(value.strip())
            continue

        # Table header line, e.g. "modules[3]{...}:"
        if not line.startswith(" ") and "[" in line and "{" in line and line.endswith(":"):
            table_name, fields = _parse_table_header(line)
            current_table = table_name
            current_fields = fields
            tables.setdefault(table_name, [])
            continue

        # Table row line: indented with at least one space.
        if current_table is not None and line.startswith(" "):
            row_text = line.strip()
            values = _parse_row(row_text)
            row: Dict[str, str] = {}
            for i, field in enumerate(current_fields):
                row[field] = values[i] if i < len(values) else ""
            tables[current_table].append(row)

    if root is None:
        raise ValueError("TOON IR is missing repo.root header")

    # Reconstruct modules --------------------------------------------------

    modules_table = tables.get("modules", [])
    modules: List[ModuleIR] = []
    modules_by_id: Dict[int, ModuleIR] = {}

    for row in modules_table:
        module_id = int(row["module_id"])
        module_name = _unescape_value(row["module_name"])
        path_str = _unescape_value(row["path"])
        path = Path(path_str)
        module = ModuleIR(
            id=module_id,
            path=path,
            module_name=module_name,
            imports=[],  # Import details are not serialized; use module_import_edges instead.
            functions=[],
        )
        modules.append(module)
        modules_by_id[module_id] = module

    # Reconstruct classes -------------------------------------------------

    classes_table = tables.get("classes", [])
    classes_by_id: Dict[int, ClassIR] = {}

    for row in classes_table:
        class_id = int(row["class_id"])
        module_id = int(row["module_id"])
        module = modules_by_id[module_id]
        name = _unescape_value(row["name"])
        qualified_name = _unescape_value(row["qualified_name"])
        lineno = int(row["lineno"])
        base_names_raw = _unescape_value(row.get("base_names", ""))
        base_names = [value for value in base_names_raw.split("|") if value]
        cls = ClassIR(
            id=class_id,
            module_id=module_id,
            name=name,
            qualified_name=qualified_name,
            lineno=lineno,
            base_names=base_names,
        )
        module.classes.append(cls)
        classes_by_id[class_id] = cls

    # Reconstruct imports -------------------------------------------------

    imports_table = tables.get("imports", [])
    for row in imports_table:
        module_id = int(row["module_id"])
        module = modules_by_id[module_id]
        kind = _unescape_value(row["kind"])
        module_name = _unescape_value(row.get("module", ""))
        name = _unescape_value(row["name"])
        alias = _unescape_value(row.get("alias", ""))
        module.imports.append(
            ImportIR(
                kind=kind,
                module=module_name or None,
                name=name,
                alias=alias or None,
            )
        )

    # Reconstruct functions -----------------------------------------------

    functions_table = tables.get("functions", [])
    functions_by_id: Dict[int, FunctionIR] = {}

    for row in functions_table:
        function_id = int(row["function_id"])
        module_id = int(row["module_id"])
        module = modules_by_id[module_id]
        name = _unescape_value(row["name"])
        qualified_name = _unescape_value(row["qualified_name"])
        lineno = int(row["lineno"])

        parent_class_raw = row.get("parent_class_id", "")
        parent_class_id = int(parent_class_raw) if parent_class_raw not in {"", None} else None
        parent_class_qual = _unescape_value(row.get("parent_class_qualified_name", ""))
        parent_class_qualified_name = parent_class_qual or None

        fn = FunctionIR(
            id=function_id,
            module_id=module_id,
            name=name,
            qualified_name=qualified_name,
            lineno=lineno,
            parent_class_id=parent_class_id,
            parent_class_qualified_name=parent_class_qualified_name,
        )
        module.functions.append(fn)
        if parent_class_id is not None:
            cls = classes_by_id.get(parent_class_id)
            if cls is not None:
                cls.methods.append(fn)
        functions_by_id[function_id] = fn

    # Reconstruct call sites ----------------------------------------------

    calls_table = tables.get("calls", [])
    for row in calls_table:
        function_id = int(row["function_id"])
        lineno = int(row["lineno"])
        target = _unescape_value(row["target"])
        fn = functions_by_id.get(function_id)
        if fn is None:
            continue
        fn.calls.append(CallIR(lineno=lineno, target=target))

    # Module import edges --------------------------------------------------

    module_import_edges: List[ModuleImportEdgeIR] = []
    module_imports_table = tables.get("module_imports", [])
    for row in module_imports_table:
        module_id = int(row["module_id"])
        imported_module = _unescape_value(row["imported_module"])
        module_import_edges.append(
            ModuleImportEdgeIR(importer_module_id=module_id, imported_module=imported_module)
        )

    # Call graph edges -----------------------------------------------------

    call_edges: List[CallEdgeIR] = []
    call_graph_table = tables.get("call_graph", [])
    for row in call_graph_table:
        caller_id = int(row["caller_function_id"])
        callee_raw = row.get("callee_function_id", "")
        callee_id = int(callee_raw) if callee_raw not in {"", None} else None
        lineno = int(row["lineno"])
        target = _unescape_value(row["target"])
        call_edges.append(
            CallEdgeIR(
                caller_function_id=caller_id,
                callee_function_id=callee_id,
                lineno=lineno,
                target=target,
            )
        )

    return RepositoryIR(
        root=root,
        modules=modules,
        module_import_edges=module_import_edges,
        call_edges=call_edges,
    )


def load_repository_ir(ir_file: Path) -> RepositoryIR:
    """Load a ``RepositoryIR`` from a ``.toon`` file on disk."""

    text = ir_file.read_text(encoding="utf-8")
    return repository_ir_from_toon(text)
