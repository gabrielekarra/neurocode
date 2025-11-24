# VS Code integration (minimal)

This is a small command you can paste into an existing VS Code extension to shell out to the NeuroCode CLI and show JSON output.

## Command (TypeScript)
```ts
// package.json snippet
// "activationEvents": ["onCommand:neurocode.explainFile"],
// "contributes": { "commands": [{ "command": "neurocode.explainFile", "title": "NeuroCode: Explain File" }] }

import * as vscode from "vscode";
import { execFile } from "child_process";
import { promisify } from "util";
const execFileAsync = promisify(execFile);

async function runNeurocodeExplain(fileUri?: vscode.Uri) {
  const target = fileUri?.fsPath || vscode.window.activeTextEditor?.document.uri.fsPath;
  if (!target) {
    vscode.window.showErrorMessage("Select a file to explain.");
    return;
  }
  try {
    const { stdout } = await execFileAsync("neurocode", [
      "explain-llm",
      target,
      "--format",
      "json",
    ]);
    const doc = await vscode.workspace.openTextDocument({ language: "json", content: stdout });
    await vscode.window.showTextDocument(doc, { preview: true });
  } catch (err: any) {
    vscode.window.showErrorMessage(`neurocode explain failed: ${err?.stderr || err?.message}`);
  }
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(
    vscode.commands.registerCommand("neurocode.explainFile", runNeurocodeExplain)
  );
}
```

## Command (JavaScript)
```js
const vscode = require("vscode");
const { promisify } = require("util");
const { execFile } = require("child_process");
const execFileAsync = promisify(execFile);

async function runNeurocodeExplain(fileUri) {
  const target =
    (fileUri && fileUri.fsPath) ||
    (vscode.window.activeTextEditor && vscode.window.activeTextEditor.document.uri.fsPath);
  if (!target) {
    vscode.window.showErrorMessage("Select a file to explain.");
    return;
  }
  try {
    const { stdout } = await execFileAsync("neurocode", ["explain-llm", target, "--format", "json"]);
    const doc = await vscode.workspace.openTextDocument({ language: "json", content: stdout });
    await vscode.window.showTextDocument(doc, { preview: true });
  } catch (err) {
    vscode.window.showErrorMessage(`neurocode explain failed: ${err.stderr || err.message}`);
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("neurocode.explainFile", runNeurocodeExplain)
  );
}

exports.activate = activate;
```

Notes:
- Assumes `neurocode` is on PATH and `.neurocode/ir.toon` exists. Run `neurocode ir .` first (and `neurocode embed .` if you want semantic neighbors).
- You can add a second command for `plan-patch-llm` similarly and render the JSON diff in a panel.
- For quick diffs, add `--show-diff` when applying a plan via `neurocode patch --plan ... --show-diff` and display stdout in a new editor tab (see the sample extension below).

## Sample extension

A runnable sample lives in `examples/vscode-neurocode/` with commands to:
- explain the current file,
- plan a patch for the current file (prompting for fix/symbol),
- dry-run/apply a PatchPlanBundle from the active editor, showing the unified diff.

Open that folder in VS Code and launch with “Run Extension”, or install via `code --extensionDevelopmentPath`. Edit `neurocode.cliPath` if `neurocode` isn’t on PATH.

Packaged `.vsix`: inside `examples/vscode-neurocode`, run `npm install` then `npm run package` (uses `vsce`). Install with `code --install-extension neurocode-vscode-sample-0.0.2.vsix`.
