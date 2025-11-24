from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class ImportIR:
    """Represents a single import statement in a module."""

    kind: str  # "import" or "from"
    module: str | None  # for "from x import y"; None for bare imports
    name: str  # imported name or module for bare imports
    alias: str | None


@dataclass
class CallIR:
    """Represents a single call site inside a function."""

    lineno: int
    target: str  # textual representation like "foo", "mod.func", "obj.method"
    in_entrypoint: bool = False  # True when call is from module-level/__main__


@dataclass
class ModuleImportEdgeIR:
    """Represents a module-level import edge: importer -> imported module name."""

    importer_module_id: int
    imported_module: str


@dataclass
class CallEdgeIR:
    """Represents a resolved call graph edge between functions.

    ``callee_function_id`` may be ``None`` when the target cannot be resolved
    to a known function in the repository (e.g., stdlib calls).
    """

    caller_function_id: int
    callee_function_id: int | None
    lineno: int
    target: str
    caller_symbol_id: str
    callee_symbol_id: str | None


@dataclass
class FunctionIR:
    """Represents a function or method within a module."""

    id: int
    module_id: int
    name: str
    qualified_name: str
    lineno: int
    signature: str = ""
    docstring: str | None = None
    module: str = ""
    qualname: str = ""
    symbol_id: str = ""
    kind: str = "function"  # function|method|module
    is_entrypoint: bool = False
    parent_class_id: int | None = None
    parent_class_qualified_name: str | None = None
    calls: List[CallIR] = field(default_factory=list)


@dataclass
class ClassIR:
    """Represents a class defined within a module."""

    id: int
    module_id: int
    name: str
    qualified_name: str
    lineno: int
    module: str = ""
    symbol_id: str = ""
    base_names: List[str] = field(default_factory=list)
    methods: List[FunctionIR] = field(default_factory=list)


@dataclass
class ModuleIR:
    """Represents a single Python module (file) in the repository."""

    id: int
    path: Path  # path relative to the repository root
    module_name: str
    file_hash: str | None = None
    has_main_guard: bool = False
    entry_symbol_id: str | None = None
    entrypoints: List[str] = field(default_factory=list)
    classes: List[ClassIR] = field(default_factory=list)
    imports: List[ImportIR] = field(default_factory=list)
    functions: List[FunctionIR] = field(default_factory=list)


@dataclass
class RepositoryIR:
    """Top-level IR for a repository.

    In addition to per-module IR, this exposes graph layers:
    - ``module_import_edges``: module -> imported module name
    - ``call_edges``: caller function -> callee function (when resolvable)
    """

    root: Path
    build_timestamp: str | None = None
    modules: List[ModuleIR] = field(default_factory=list)
    module_import_edges: List[ModuleImportEdgeIR] = field(default_factory=list)
    call_edges: List[CallEdgeIR] = field(default_factory=list)
    test_mappings: List[tuple[str, str]] = field(default_factory=list)  # (test_symbol_id, target_symbol_id)
    config_paths: List[str] = field(default_factory=list)
    console_scripts: List[tuple[str, str]] = field(default_factory=list)  # (name, target_symbol)

    @property
    def num_modules(self) -> int:
        return len(self.modules)

    @property
    def num_classes(self) -> int:
        return sum(len(m.classes) for m in self.modules)

    @property
    def num_functions(self) -> int:
        return sum(len([fn for fn in m.functions if fn.kind != "module"]) for m in self.modules)

    @property
    def num_calls(self) -> int:
        return sum(len(f.calls) for m in self.modules for f in m.functions)
