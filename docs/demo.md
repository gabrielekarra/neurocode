# Demo: IR to Patch

Use the bundled sample repo at `tests/data/sample_repo` to see the full flow from IR to patch history.

```bash
export SAMPLE=tests/data/sample_repo

# 1) Build IR and check freshness
neurocode ir $SAMPLE
neurocode status $SAMPLE --format json | jq .

# 2) Explain with IR + Neural IR context (JSON bundle)
neurocode explain-llm $SAMPLE/package/mod_a.py \
  --symbol package.mod_a:orchestrator \
  --format json | jq '.ir.module_summary.functions[0].signature'

# 3) Build embeddings and search (dummy provider for the sample repo)
neurocode embed $SAMPLE --provider dummy
neurocode search $SAMPLE --text "orchestrator" --provider dummy --format json | jq '.results[0]'

# 4) Draft a patch plan for the orchestrator
neurocode plan-patch-llm $SAMPLE/package/mod_a.py \
  --symbol package.mod_a:orchestrator \
  --fix "Add logging around orchestrator" \
  --format json > plan_draft.json

# 5) Apply (or dry-run) the patch plan
echo "fill plan_draft.json.operations[*].code, then:" 
neurocode patch $SAMPLE/package/mod_a.py --plan plan_draft.json --dry-run --show-diff

# 6) Inspect patch history
neurocode patch-history $SAMPLE --format json --limit 5 | jq '.entries[0]'
```

Tip: add `--k-neighbors` to widen the call graph slice, and drop `--dry-run` when you are ready to write files.
