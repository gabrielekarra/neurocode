# NeuroCode IR Schema

This document summarizes the serialized IR stored in `.neurocode/ir.toon`. The TOON format is stable within the 0.x series; new fields are added in a backward-compatible way (readers should ignore unknown columns).

## Repository metadata
- `repo.root` – absolute repository root path
- `repo.build_timestamp` – UTC timestamp of IR build (ISO8601)
- Counts: `num_modules`, `num_classes`, `num_functions`, `num_calls`

## Tables
### modules
- `module_id` (int) – stable index
- `module_name` (str) – dotted path
- `path` (str) – path relative to repo root
- `file_hash` (str|empty) – sha256 of file contents at build time
- `num_functions` (int)
- `num_imports` (int)

### classes
- `class_id` (int)
- `module_id` (int)
- `name` (str)
- `qualified_name` (str)
- `lineno` (int)
- `base_names` (pipe-separated str, e.g., `Base|Mixin`)
- `num_methods` (int)

### imports
- `module_id` (int)
- `kind` (str) – `import` or `from`
- `module` (str) – imported module (empty for bare import)
- `name` (str) – imported symbol or module
- `alias` (str|empty)

### functions
- `function_id` (int)
- `module_id` (int)
- `name` (str)
- `qualified_name` (str)
- `signature` (str) – best-effort rendered signature including annotations/defaults
- `docstring` (str|empty)
- `lineno` (int)
- `parent_class_id` (int|empty)
- `parent_class_qualified_name` (str|empty)
- `num_calls` (int)

### calls
- `function_id` (int) – caller
- `module_id` (int)
- `lineno` (int)
- `target` (str) – textual target (may be unresolved)

### module_imports
- `module_id` (int) – importer
- `imported_module` (str) – imported module name

### call_graph
- `caller_function_id` (int)
- `callee_function_id` (int|empty) – resolved callee; empty if unresolved
- `lineno` (int)
- `target` (str) – textual target

## Stability notes
- File hashes and build_timestamp are advisory for freshness checks.
- Future versions may add columns; consumers should ignore unknown fields.
- IDs are stable within a single IR build but not guaranteed across builds.
