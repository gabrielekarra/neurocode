# VS Code integration

NeuroCode works in VS Code by shelling out to the CLI—no custom language server required.

**Flow**
- Ensure `neurocode` is on PATH and run `neurocode ir .` (and `neurocode embed .` if you want semantic neighbors).
- Wire a command that calls `neurocode explain-llm <file> --format json` for the active file and show the JSON in a new editor tab.
- Add a second command for `plan-patch-llm` and apply filled plans with `neurocode patch --plan ... --show-diff`.

**Sample extension**
A minimal extension lives in `examples/vscode-neurocode/` with commands for explain, plan, and apply (dry-run or write). Open that folder in VS Code and launch “Run Extension”, or package/install the `.vsix` produced by `npm run package`.

**Tips**
- Surface the `neurocode.cliPath` setting if `neurocode` is not on PATH.
- Guard commands with an IR freshness check (`neurocode status . --format json`) to prompt users to rebuild when stale.
