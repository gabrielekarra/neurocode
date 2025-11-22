# Automation status output

`neurocode check --status` emits a one-line summary suitable for scripts/CI in addition to normal output:

```
status exit_code=1 warnings=0 info=2 warn=1 error=0
```

- `exit_code` matches the process exit code (1 if any WARNING/ERROR).
- Counts include INFO/WARNING/ERROR diagnostics and staleness warnings.
- When `--format json` is used, the JSON diagnostics are printed first; status line always appears last.
