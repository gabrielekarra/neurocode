# Changelog

## 0.1.2
- Renamed PyPI distribution to `neurocode-ai` (CLI entrypoint remains `neurocode`); update install docs accordingly.

## 0.1.1
- Hardened CLI behavior: explicit `--require-target` enforcement and richer status JSON (includes IR root/timestamp).
- Added end-to-end flow test and JSON/status/target coverage to ensure CLI contract stability.
- Pinned dev dependencies, added Makefile targets, onboarding docs, and troubleshooting guide.

## 0.1.0
- Initial published version with IR generation (`neurocode ir`), explain/check/patch commands, status command, JSON outputs, and configurable checks.
- New diagnostics: unused imports/functions/params/returns, high fan-out, long functions, call cycles, import cycles.
- Config via `.neurocoderc`/`[tool.neurocode]`.
- Patch strategies (guard/todo/inject) with idempotent markers and JSON output.
- IR freshness hashes/timestamp; `ir --check` and `status` command.
- CI workflow (ruff + pytest) and IR schema docs.
