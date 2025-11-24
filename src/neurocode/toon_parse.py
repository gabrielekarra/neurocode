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
    build_timestamp: str | None = None

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
        if in_repo_header and stripped.startswith("build_timestamp:"):
            _, value = stripped.split(":", 1)
            build_timestamp = value.strip()
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
        file_hash = _unescape_value(row.get("file_hash", ""))
        has_main_guard = row.get("has_main_guard", "0") == "1"
        entry_symbol_id = _unescape_value(row.get("entry_symbol_id", ""))
        path = Path(path_str)
        entrypoints_raw = _unescape_value(row.get("entrypoints", ""))
        entrypoints = [e for e in entrypoints_raw.split("|") if e]
        module = ModuleIR(
            id=module_id,
            path=path,
            module_name=module_name,
            file_hash=file_hash or None,
            has_main_guard=has_main_guard,
            entry_symbol_id=entry_symbol_id or None,
            entrypoints=entrypoints,
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
        module_name = _unescape_value(row.get("module", module.module_name))
        symbol_id = _unescape_value(row.get("symbol_id", ""))
        lineno = int(row["lineno"])
        base_names_raw = _unescape_value(row.get("base_names", ""))
        base_names = [value for value in base_names_raw.split("|") if value]
        cls = ClassIR(
            id=class_id,
            module_id=module_id,
            name=name,
            qualified_name=qualified_name,
            module=module_name or module.module_name,
            symbol_id=symbol_id or "",
            lineno=lineno,
            base_names=base_names,
        )
        if not cls.symbol_id:
            cls.symbol_id = f"{cls.module}:{cls.qualified_name.split('.',1)[-1]}"
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
        module_name = _unescape_value(row.get("module", module.module_name))
        qualname = _unescape_value(row.get("qualname", ""))
        symbol_id = _unescape_value(row.get("symbol_id", ""))
        kind = _unescape_value(row.get("kind", "function"))
        is_entrypoint = row.get("is_entrypoint", "0") == "1"
        lineno = int(row["lineno"])
        signature = _unescape_value(row.get("signature", ""))
        docstring = _unescape_value(row.get("docstring", ""))

        parent_class_raw = row.get("parent_class_id", "")
        parent_class_id = int(parent_class_raw) if parent_class_raw not in {"", None} else None
        parent_class_qual = _unescape_value(row.get("parent_class_qualified_name", ""))
        parent_class_qualified_name = parent_class_qual or None

        if not qualname:
            # Strip module prefix if present
            if qualified_name.startswith(f"{module_name}."):
                qualname = qualified_name[len(module_name) + 1 :]
            else:
                qualname = qualified_name
        fn = FunctionIR(
            id=function_id,
            module_id=module_id,
            name=name,
            qualified_name=qualified_name,
            lineno=lineno,
            module=module_name or module.module_name,
            qualname=qualname,
            symbol_id=symbol_id or "",
            kind=kind or "function",
            is_entrypoint=is_entrypoint,
            parent_class_id=parent_class_id,
            parent_class_qualified_name=parent_class_qualified_name,
            signature=signature,
            docstring=docstring or None,
        )
        if not fn.symbol_id:
            fn.symbol_id = f"{fn.module}:{fn.qualname}"
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
        caller_symbol_id = _unescape_value(row.get("caller_symbol_id", ""))
        callee_symbol_id = _unescape_value(row.get("callee_symbol_id", ""))
        caller_fn = functions_by_id.get(caller_id)
        resolved_caller_symbol = caller_symbol_id or (caller_fn.symbol_id if caller_fn else "")
        resolved_callee_symbol: str | None
        if callee_symbol_id:
            resolved_callee_symbol = callee_symbol_id
        elif callee_id is not None and callee_id in functions_by_id:
            resolved_callee_symbol = functions_by_id[callee_id].symbol_id
        else:
            resolved_callee_symbol = None
        call_edges.append(
            CallEdgeIR(
                caller_function_id=caller_id,
                callee_function_id=callee_id,
                lineno=lineno,
                target=target,
                caller_symbol_id=resolved_caller_symbol,
                callee_symbol_id=resolved_callee_symbol,
            )
        )

    config_paths: list[str] = []
    console_scripts: list[tuple[str, str]] = []
    config_table = tables.get("config", [])
    for row in config_table:
        kind = row.get("kind", "")
        value = _unescape_value(row.get("value", ""))
        if kind == "path":
            config_paths.append(value)
        elif kind == "console_script":
            if "=>" in value:
                name, target = value.split("=>", 1)
                console_scripts.append((name, target))

    return RepositoryIR(
        root=root,
        build_timestamp=build_timestamp,
        modules=modules,
        module_import_edges=module_import_edges,
        call_edges=call_edges,
        test_mappings=[],  # populated elsewhere if needed
        config_paths=config_paths,
        console_scripts=console_scripts,
    )


def load_repository_ir(ir_file: Path) -> RepositoryIR:
    """Load a ``RepositoryIR`` from a ``.toon`` file on disk."""

    text = ir_file.read_text(encoding="utf-8")
    return repository_ir_from_toon(text)
