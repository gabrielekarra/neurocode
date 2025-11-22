# NeuroCode

NeuroCode is an engine for structural understanding and modification of codebases, built around a Neural Intermediate Representation (Neural IR). It is **infrastructure for AI applied to code**, not an IDE, assistant, or AI terminal.

The goal is to let AI models reason about a codebase like a senior engineer with a global view of structure, dependencies, and behavior — not like a text-only LLM reading files in isolation.

## Vision

Traditional LLM-based coding tools:

- read code as plain text, not as structured programs
- lose global context across large repositories
- do not truly understand dependency graphs
- often produce fragile, local patches
- struggle with multi-file refactors
- cannot reliably find complex bugs involving control/data flow or cross-module effects

NeuroCode introduces a **neural IR layer for code** that:

- represents the codebase as rich program structure
- is optimized for AI reasoning
- enables globally coherent patches and refactors

## Core Concepts

NeuroCode builds and operates on a stack of representations:

- **AST per file** – syntactic structure of each source file
- **Call graph** – functions/methods and their invocation relationships
- **Module dependency graph** – imports and higher-level coupling
- **Control-flow graph (CFG)** – possible execution paths
- **Data-flow** – value propagation and usage
- **Neural IR** – a compressed, structured representation suitable as input to LLMs and other models

On top of this IR, NeuroCode will support:

- detection of complex, non-local bugs
- generation of globally coherent patches
- real refactoring (including multi-file refactors in later versions)
- API upgrades and internal interface evolution
- intelligent test generation

## Current CLI capabilities

- `neurocode ir <path>` — build IR (`.neurocode/ir.toon`) with per-file hashes and timestamp. `--check` compares hashes to disk and reports staleness without rebuilding.
- `neurocode explain <file> [--format text|json]` — IR-backed module summary (imports, functions, calls) with staleness warnings.
- `neurocode check <file> [--format text|json]` — structural diagnostics: unused imports/functions/params, high fan-out, long functions, call cycles, import cycles, unused returns. Respects config and staleness warnings.
- `neurocode patch <file> --fix "..."`
  - Strategies: `guard`, `todo`, `inject` (NotImplementedError/logging stub).
  - Targeting (`--target`, `--require-target`), inject options (`--inject-kind`, `--inject-message`), dry-run/diff, stale IR enforcement (`--require-fresh-ir`).
  - Idempotent via `# neurocode:*` markers; exit code `3` when no change. `--format json` emits structured result (status, diff, warnings, exit_code).
- `neurocode status [path] [--format text|json]` — summarize IR freshness (hash comparison), build timestamp, and config values in one shot; exit `1` if any module is stale/missing.

### Examples

Generate IR and check freshness:
```bash
neurocode ir .
neurocode ir . --check   # warns if any module hash is stale
```

Apply a patch with a logging stub:
```bash
neurocode patch src/neurocode/cli.py --fix "trace entry" \
  --strategy inject --inject-kind log --inject-message "enter cli"
```

Quickstart workflow (sample repo):
```bash
# 1) Build IR
neurocode ir .

# 2) Check freshness + config
neurocode status . --format json | jq .

# 3) Run checks with JSON output
neurocode check path/to/file.py --format json --status

# 4) Explain a file
neurocode explain path/to/file.py --format json | jq .

# 5) Apply a patch (dry-run JSON)
neurocode patch path/to/file.py --fix "describe fix" --strategy guard --dry-run --format json --show-diff
```

Custom config example:
```toml
# .neurocoderc or pyproject.toml [tool.neurocode]
fanout_threshold = 20
long_function_threshold = 80
enabled_checks = ["UNUSED_IMPORT", "UNUSED_PARAM", "LONG_FUNCTION"]
severity_overrides = { UNUSED_FUNCTION = "WARNING" }
```

## Configuration

NeuroCode reads settings from `.neurocoderc` or `[tool.neurocode]` in `pyproject.toml`:

```toml
fanout_threshold = 15
long_function_threshold = 80
enabled_checks = ["UNUSED_IMPORT", "UNUSED_PARAM", "LONG_FUNCTION", "CALL_CYCLE"]
severity_overrides = { UNUSED_FUNCTION = "WARNING" }
```

## Python API

Importable helpers in `neurocode.api`:

- `build_ir(root: Path) -> RepositoryIR`
- `load_ir(path: Path) -> RepositoryIR`
- `run_checks(ir, repo_root, file, config=None) -> List[CheckResult]`
- `explain_file(ir, repo_root, file, output_format="text") -> str`
- `plan_patch(ir, repo_root, file, fix_description, **kwargs) -> PatchResult`
- `apply_patch_from_disk(path, fix_description, **kwargs) -> PatchResult`

Example:
```python
from pathlib import Path
from neurocode import api

repo = Path(".")
ir = api.build_ir(repo)
results = api.run_checks(ir, repo_root=repo, file=repo/"src/neurocode/cli.py")
print([r.code for r in results])
```

The CLI uses the same underlying functions; see `docs/ir.md` for the serialized IR schema.

## Releases

- Version: `0.1.0` (see `CHANGELOG.md`).
- Build artifacts locally with `scripts/release.sh` (wheel + sdist in `dist/`).
- CI: GitHub Actions (`.github/workflows/ci.yml`) runs `ruff check` + `pytest` on push/PR.

## High-Level Architecture

```text
CODEBASE
  ↓
AST / CFG / CALL GRAPH / DATA FLOW
  ↓
NEURAL IR
  ↓
LLM REASONING (IR-informed)
  ↓
CHECKS / ANALYSIS / PATCH GENERATION
  ↓
CLI / API / Editor Plugin
```

## Non-Goals

- NeuroCode is **not** a GUI-first tool.
- NeuroCode is **not** a general-purpose chatbot.
- NeuroCode is **not** tied to a single LLM provider or model.

Instead, it aims to be **the infrastructure layer** that other agents, IDEs, and tools can build on to gain deep, structural understanding of code.
