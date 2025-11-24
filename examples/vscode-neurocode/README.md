# NeuroCode VS Code sample extension

Minimal VS Code integration that shells out to the NeuroCode CLI.

## Commands
- `NeuroCode: Explain Current File` — runs `neurocode explain-llm <file> --format json` and shows the bundle.
- `NeuroCode: Plan Patch for Current File` — prompts for a fix (and optional symbol), runs `neurocode plan-patch-llm`, and opens the JSON.
- `NeuroCode: Apply Patch Plan from Editor JSON` — takes the active JSON (PatchPlanBundle), dry-runs `neurocode patch --plan ... --show-diff`, and shows output.

## Usage
1) Ensure `neurocode` CLI is on PATH and `.neurocode/ir.toon` exists for your workspace (run `neurocode ir .`, and optionally `neurocode embed .`).
2) In VS Code, open this folder (`examples/vscode-neurocode`) and run the “Run Extension” launch config, or install it via `code --extensionDevelopmentPath`.
3) Use the commands from the Command Palette (they target the active editor file by default).
4) Built-in tasks: open the VS Code “Run Task” picker to run `NeuroCode: Build IR`, `NeuroCode: Embed (dummy)`, or `NeuroCode: Status`. Tasks are defined in `.vscode/tasks.json` and use the configured `neurocode.cliPath`.

Settings (in VS Code `settings.json`):
```json
{
  "neurocode.cliPath": "neurocode",        // override CLI path if needed
  "neurocode.workspaceRoot": ""            // override cwd; defaults to first workspace folder
}
```

## Packaged vsix
You can build a `.vsix` from this sample:
```bash
cd examples/vscode-neurocode
npm install   # installs dev dependency @vscode/vsce (or install vsce globally)
npm run package
```
Then install with `code --install-extension neurocode-vscode-sample-0.0.2.vsix`.
