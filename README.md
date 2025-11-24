# NeuroCode

NeuroCode is a structural IR engine for code. It builds a persistent Intermediate Representation (IR + Neural IR) of your Python codebase and lets AI reason and patch code like a compiler + LLM hybrid, not like a text-only autocomplete. It is infrastructure for AI applied to code — the layer your agents, editors, and tools can build on.

## Why NeuroCode?
- Most tools see only a small window of code at a time.
- No persistent model of the repository.
- Patches rely on fragile, local patterns.
- Cross-file refactors and call-graph reasoning often fail.
- Non-local bugs slip through.

## What NeuroCode adds
- Structural IR (AST, modules, classes, functions, call graph, tests, entrypoints).
- Neural IR: embeddings attached to IR nodes.
- LLM-ready bundles for explanation and patch planning.
- Strict PatchPlan JSON protocol for deterministic patch execution.
- Structured patch history.

## Installation
- User install: `pip install neurocode-ai`
- Dev install: `pip install -e .[dev]`

```bash
pip install neurocode-ai
neurocode --help
```

## Try it in 60 seconds
Inside any Python project:
```bash
# 1) Build IR
neurocode ir .

# 2) Inspect IR freshness / config
neurocode status . --format text

# 3) Structural checks
neurocode check path/to/file.py --format text

# 4) LLM-ready explanation bundle
neurocode explain-llm path/to/file.py --format json

# 5) Patch plan for LLMs
neurocode plan-patch-llm path/to/file.py \
  --fix "add logging before DB calls" \
  --format json

# 6) Patch history
neurocode patch-history . --format text
```

For a reproducible walkthrough, see [docs/demo.md](docs/demo.md).

## What NeuroCode can do
- IR & status: `neurocode ir <path>`, `neurocode status`
- Structural analysis: `neurocode explain <file>`, `neurocode check <file>`, `neurocode query`
- Neural IR: `neurocode embed`, `neurocode search`
- LLM reasoning: `neurocode explain-llm`, `neurocode plan-patch-llm`
- Patch & history: `neurocode patch`, `neurocode patch --plan ...`, `neurocode patch-history`

## Agent example
`examples/neurocode_agent.py` demonstrates the full loop (IR + embeddings → explain-llm/plan-patch-llm → LLM fill → apply → history). Example:
```bash
python examples/neurocode_agent.py \
  --repo . \
  --file path/to/file.py \
  --fix "add logging before DB calls" \
  --embed-provider openai \
  --embed-model text-embedding-3-small \
  --dry-run
```
More details in [docs/agents.md](docs/agents.md).

## How is this different from Copilot / Cursor / Cody?
- Those tools operate on sliding windows or heuristic parsing and patch text directly.
- NeuroCode builds and persists structural IR + Neural IR, enforces a strict PatchPlan schema, applies patches deterministically, and records machine-readable history.

## Configuration
NeuroCode reads `.neurocoderc` or `[tool.neurocode]` in `pyproject.toml`.
```toml
[tool.neurocode]
fanout_threshold = 20
long_function_threshold = 80
enabled_checks = ["UNUSED_IMPORT", "UNUSED_PARAM", "LONG_FUNCTION"]

[tool.neurocode.embedding]
provider = "openai"
model = "text-embedding-3-small"
```
For common issues, see [docs/troubleshooting.md](docs/troubleshooting.md).

## Python API
```python
from neurocode.api import open_project

project = open_project(".")
project.build_ir()
project.ensure_embeddings()

bundle = project.explain_llm("src/app/module.py", symbol="app.module:handler")
results = project.search_code(text="http handler", k=5)

plan = project.plan_patch_llm(
    "src/app/module.py",
    fix="add logging",
    symbol="app.module:handler",
)
apply_result = project.apply_patch_plan(plan, dry_run=True)
print(apply_result.diff)
```

## Contributing & License
- Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
- Licensed under Apache-2.0.

Further docs:
- [docs/demo.md](docs/demo.md)
- [docs/agents.md](docs/agents.md)
- [docs/vscode.md](docs/vscode.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/patch-plan.md](docs/patch-plan.md)
