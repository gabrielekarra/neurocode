# PatchPlanBundle protocol

`plan-patch-llm` returns a JSON PatchPlanBundle that LLMs fill in-place. `patch --plan` validates every field before writing.

## Allowed edits
- Do not change: `version`, `engine_version`, `repo_root`, `file`, `module`, anything under `target`, and each operation's `id`, `op`, `file`, `symbol`, `lineno`, `end_lineno`.
- You may change: `fix`, `operations[*].description`, `operations[*].code`, `operations[*].enabled`.
- Unknown or missing fields cause validation errors; enabled operations must include non-empty `code` when applying.

## Operations
Supported `op` values: `insert_before`, `insert_after`, `replace_range`, `append_to_function`. Each operation targets a specific file/symbol/line range computed from IR.

## Sample bundle
```json
{
  "version": 1,
  "engine_version": "0.2.1",
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

Agents should fill `operations[*].code` with the smallest patch that satisfies the fix, optionally toggling `enabled` for unwanted operations. Keep the JSON structure intact to pass `apply_patch_plan` validation.
