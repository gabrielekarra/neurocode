# Demo Flow (sample repo)

Use the bundled sample repo to see the IR, checks, explain-llm, and patch-plan flows with the new signatures/docstrings captured in IR.

```bash
# From repo root
export SAMPLE=tests/data/sample_repo
PYTHONPATH=src python -m neurocode.cli ir $SAMPLE
PYTHONPATH=src python -m neurocode.cli status $SAMPLE
```

Explain bundle (watch for real signatures/docstrings in `ir.module_summary.functions` and `source_slices`):
```bash
PYTHONPATH=src python -m neurocode.cli explain-llm \
  $SAMPLE/package/mod_a.py \
  --symbol package.mod_a.orchestrator \
  --format json | jq '.ir.module_summary.functions[0].signature'
```

Patch-plan bundle with LLM-ready operations:
```bash
PYTHONPATH=src python -m neurocode.cli plan-patch-llm \
  $SAMPLE/package/mod_a.py \
  --symbol package.mod_a.orchestrator \
  --fix "Add logging around orchestrator" \
  --format json | jq '.operations[0]'
```

Embeddings/search (uses dummy provider):
```bash
PYTHONPATH=src python -m neurocode.cli embed $SAMPLE --provider dummy
PYTHONPATH=src python -m neurocode.cli search $SAMPLE --text "orchestrator" --provider dummy
```

Checks remain IR-backed:
```bash
PYTHONPATH=src python -m neurocode.cli check $SAMPLE/package/mod_a.py
```
