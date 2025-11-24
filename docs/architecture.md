# Architecture

NeuroCode treats a repository like a program to be compiled, not text to be searched.

## IR stack
- File-level ASTs capture imports, definitions, and structure.
- Call graph links functions/methods across modules.
- Module dependency graph captures imports and coupling.
- Control/data-flow summaries capture execution paths and value usage.
- Neural IR stores embeddings keyed to IR nodes for semantic recall.

## Flow
1) Build IR with `neurocode ir <repo>`; refresh as code changes.
2) Optionally build embeddings (`neurocode embed`) to power semantic search and LLM bundles.
3) Generate reasoning bundles (`explain-llm`, `plan-patch-llm`) that combine IR, embeddings, checks, and source slices.
4) Apply guarded patches with `neurocode patch`, logging every write to `.neurocode/patch-history.toon`.

## CLI surface
- `ir` / `status` / `check` for structural analysis.
- `embed` / `search` / `query` for semantic and structural navigation.
- `explain-llm` / `plan-patch-llm` to produce JSON bundles for LLMs.
- `patch` / `patch-history` to apply or audit deterministic changes.

## Python API
The CLI wraps the library API in `neurocode.api`:
```python
from neurocode import api

repo = api.open_project(".")
repo.build_ir()
bundle = repo.explain_llm("src/app/module.py", symbol="app.module:handler")
plan = repo.plan_patch_llm("src/app/module.py", fix="add logging")
result = repo.apply_patch_plan(plan.data, dry_run=True)
print(result.diff)
```

See [docs/patch-plan.md](patch-plan.md) for the JSON PatchPlanBundle contract and validation rules.
