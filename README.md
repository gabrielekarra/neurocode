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

## First 5 minutes

1) Install (no runtime deps beyond the Python stdlib):
```bash
pip install -e .[dev]
```
2) Build IR for a repo:
```bash
neurocode ir .
```
3) Check freshness and config:
```bash
neurocode status . --format json
```
4) Run checks on a file:
```bash
neurocode check path/to/file.py --status
```
5) Apply a guarded patch (idempotent; exit code 3 if already applied):
```bash
neurocode patch path/to/file.py --fix "describe fix" --strategy guard --show-diff
```

## Current CLI capabilities

- `neurocode ir <path>` — build IR (`.neurocode/ir.toon`) with per-file hashes and timestamp. `--check` compares hashes to disk and reports staleness without rebuilding.
- `neurocode explain <file> [--format text|json]` — IR-backed module summary (imports, functions, calls) with staleness warnings.
- `neurocode check <file> [--format text|json]` — structural diagnostics: unused imports/functions/params, high fan-out, long functions, call cycles, import cycles, unused returns. Respects config and staleness warnings.
- `neurocode patch <file> --fix "..."`
  - Strategies: `guard`, `todo`, `inject` (NotImplementedError/logging stub).
  - Targeting (`--target`, `--require-target`), inject options (`--inject-kind`, `--inject-message`), dry-run/diff, stale IR enforcement (`--require-fresh-ir`).
  - Idempotent via `# neurocode:*` markers; exit code `3` when no change. `--format json` emits structured result (status, diff, warnings, exit_code).
- `neurocode status [path] [--format text|json]` — summarize IR freshness (hash comparison), build timestamp, and config values in one shot; exit `1` if any module is stale/missing.
- `neurocode query <path> --kind callers|callees|fan-in|fan-out [--symbol ...] [--module ...] [--format text|json]` — IR-backed structural queries (callers/callees and fan-in/out counts).
- `neurocode embed <path> [--provider dummy] [--model dummy-embedding-v0] [--update] [--format text|json]` — build Neural IR embeddings and store them in `.neurocode/ir-embeddings.toon`.
- `neurocode search <path> (--text "…")|(--like package.module:func) [--k 10] [--module ...] [--format text|json]` — semantic search over embeddings stored in `.neurocode/ir-embeddings.toon`.
- `neurocode explain-llm <file> [--symbol package.module:func] [--k-neighbors 10] [--format text|json]` — build an LLM-ready reasoning bundle (IR slice, callers/callees, checks, semantic neighbors, source).

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

# 6) Query structure (callers)
neurocode query . --kind callers --symbol package.mod_b.helper_value --format json | jq .

# 7) Build embeddings
neurocode embed . --provider dummy --format text

# 8) Semantic search (text)
neurocode search . --text "request handler"

# 9) LLM-ready bundle
neurocode explain-llm path/to/file.py --symbol package.mod:orchestrator --format json

# 10) Patch plan for LLM
neurocode plan-patch-llm path/to/file.py --fix "Add logging" --symbol package.mod:orchestrator --format json > plan_draft.json
neurocode patch path/to/file.py --plan plan_filled.json --show-diff
```

### Patch History

NeuroCode records applied patches (non-dry-run) in TOON format at `.neurocode/patch-history.toon`. View recent entries:

```bash
neurocode patch-history .
neurocode patch-history . --format json --limit 5
```

### Patch Plan JSON Protocol

`plan-patch-llm` produces a strict JSON bundle for LLM roundtrips, and `patch --plan` validates it before applying. Storage stays TOON; JSON is **only** the LLM wire format.

- Fields the LLM **MUST NOT** change: `version`, `engine_version`, `repo_root`, `file`, `module`, `target.*`, `operations[*].{id,op,file,symbol,lineno,end_lineno,enabled}`.
- Fields the LLM **MAY** change: `fix` (rarely), `operations[*].description`, `operations[*].code` (fill with the actual patch), `operations[*].enabled` (toggle).
- Validation: unknown/missing fields are rejected; `op` must be one of `insert_before|insert_after|replace_range|append_to_function`; enabled operations must provide non-empty `code` when applying.

Sample prompt snippet:
```
You are completing a NeuroCode PatchPlanBundle JSON. Do not add/remove fields.
Fill `operations[*].code` with the minimal patch. Leave structure untouched.
```

Sample bundle (truncated):
```json
{
  "version": 1,
  "engine_version": "0.1.2",
  "repo_root": "/abs/repo",
  "file": "package/mod_a.py",
  "module": "package.mod_a",
  "fix": "Add logging",
  "target": {"symbol": "package.mod_a:orchestrator", "kind": "function", "lineno": 10},
  "operations": [
    {
      "id": "OP_1",
      "op": "append_to_function",
      "enabled": true,
      "file": "package/mod_a.py",
      "symbol": "package.mod_a:orchestrator",
      "lineno": 10,
      "end_lineno": null,
      "description": "Implement fix: Add logging",
      "code": ""
    }
  ]
}
```

### Library API

NeuroCode can also be used programmatically. The library API wraps the same building blocks as the CLI while raising typed exceptions instead of exiting.

```python
from neurocode.api import open_project

project = open_project(".")
project.build_ir()
project.ensure_embeddings()

summary = project.explain_file("src/app/module.py")
bundle = project.explain_llm("src/app/module.py", symbol="app.module:handler")

results = project.search_code(text="http handler", k=5)
plan = project.plan_patch_llm("src/app/module.py", fix="add logging", symbol="app.module:handler")

# send plan.data to an LLM, then apply the returned plan:
apply_result = project.apply_patch_plan(plan, dry_run=True)
print(apply_result.diff)
```

### Neural IR (Embeddings)

NeuroCode can serialize embeddings for IR entities to a TOON store (`.neurocode/ir-embeddings.toon`) for downstream semantic search and agent reasoning.

Examples:
- `neurocode embed .`
- `neurocode embed . --provider dummy --format json`

Embeddings are written in TOON format (no JSON storage) and can be refreshed with `--update`.

### Semantic Search (Neural IR)

Use embeddings to find related functions:

```bash
# Build IR and embeddings
neurocode ir .
neurocode embed .

# Search by text
neurocode search . --text "http request handler"

# Search for functions similar to an existing symbol
neurocode search . --like package.mod:orchestrator --format json
```

Results reference IR entities (module, function, file/line) and can be consumed in text or JSON for agents.

### LLM-Ready Explain (`explain-llm`)

`neurocode explain-llm` packages a rich reasoning bundle for a file (and optional target symbol) including:
- IR slice (imports/functions/classes)
- Call graph neighborhood (callers/callees)
- Structural diagnostics from `check`
- Semantic neighbors from embeddings/search
- Source code text

Examples:
```bash
# Basic bundle
neurocode explain-llm path/to/file.py --format json

# Focus on a symbol with neighbors
neurocode explain-llm path/to/file.py --symbol package.mod:handle --k-neighbors 8 --format json
```

### LLM Patch Planning (`plan-patch-llm`)

`neurocode plan-patch-llm` builds a patch plan bundle for LLMs to fill, including IR/Neural IR context, checks, and draft operations (`insert_before`, `insert_after`, `replace_range`, `append_to_function`).

Workflow:
```bash
# 1) Generate a draft plan
neurocode plan-patch-llm path/to/file.py \
  --fix "Add logging before DB calls" \
  --symbol mypkg.db:run_query \
  --format json > plan_draft.json

# 2) Send plan_draft.json to an LLM, obtain plan_filled.json (status=ready, code fields filled)

# 3) Apply the plan
neurocode patch path/to/file.py --plan plan_filled.json --diff
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

# Embedding provider (example for OpenAI)
[embedding]
provider = "openai"
model = "text-embedding-3-small"
# api_key can be provided here or via OPENAI_API_KEY environment variable
```

See `docs/troubleshooting.md` for common CLI issues (stale IR, exit codes, targeting).

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

- Version: `0.1.2` (see `CHANGELOG.md`).
- Build artifacts locally with `scripts/release.sh` (wheel + sdist in `dist/`); `make release` wraps it.
- CI: GitHub Actions (`.github/workflows/ci.yml`) runs `ruff check` + `pytest` on push/PR.
- Compatibility: Python 3.10–3.12 (see classifiers). No third-party runtime dependencies; dev tooling pinned in `[project.optional-dependencies]`.
- Install options:
  - Developer install: `pip install -e .[dev]`
  - User install: `pip install neurocode-ai`
  - Build from source: `python -m build` or `./scripts/release.sh` to produce wheels/sdists in `dist/`.

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
