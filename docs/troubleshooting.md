# Troubleshooting

- **Stale or missing IR**: Regenerate with `neurocode ir .` (or `neurocode ir <path>`) before `check`, `explain`, or `patch`. `neurocode status .` reports stale/missing modules; exit code `1` when any are stale.
- **Exit codes**: `0` = success/applied, `1` = diagnostics found (checks/status) or general error, `3` = no-op patch (already applied). Treat `3` as success in automation when idempotency is expected.
- **`--require-fresh-ir` failures**: The IR timestamp is older than the target file. Rebuild the IR or drop the flag to proceed with a warning.
- **Targeting patches**: Use `--target package.module.func` to constrain where the patch is applied; add `--require-target` to fail if the target cannot be located.
- **JSON output in pipelines**: All CLI commands support `--format json` (where applicable); `check --status` prints JSON diagnostics first and always emits a final status line.
- **IR location**: Commands walk up from the target path to find `.neurocode/ir.toon`. If you move the repo, rebuild IR so path metadata matches.
