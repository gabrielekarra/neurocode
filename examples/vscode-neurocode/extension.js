const vscode = require("vscode");
const { promisify } = require("util");
const { execFile } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const execFileAsync = promisify(execFile);

function getConfig() {
  const cfg = vscode.workspace.getConfiguration("neurocode");
  return {
    cliPath: cfg.get("cliPath") || "neurocode",
    workspaceRoot: cfg.get("workspaceRoot") || "",
  };
}

function guessRepoRoot(fspath) {
  const cfg = getConfig();
  if (cfg.workspaceRoot) {
    return cfg.workspaceRoot;
  }
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    return folders[0].uri.fsPath;
  }
  return path.dirname(fspath);
}

async function runCli(args, cwd) {
  const cfg = getConfig();
  return execFileAsync(cfg.cliPath, args, { cwd });
}

async function explainCurrentFile(fileUri) {
  const target =
    (fileUri && fileUri.fsPath) ||
    (vscode.window.activeTextEditor &&
      vscode.window.activeTextEditor.document.uri.fsPath);
  if (!target) {
    vscode.window.showErrorMessage("Select a file to explain.");
    return;
  }
  const cwd = guessRepoRoot(target);
  try {
    const { stdout } = await runCli(
      ["explain-llm", target, "--format", "json"],
      cwd
    );
    const doc = await vscode.workspace.openTextDocument({
      language: "json",
      content: stdout,
    });
    await vscode.window.showTextDocument(doc, { preview: true });
  } catch (err) {
    vscode.window.showErrorMessage(
      `neurocode explain failed: ${err.stderr || err.message}`
    );
  }
}

async function planPatchForCurrentFile(fileUri) {
  const target =
    (fileUri && fileUri.fsPath) ||
    (vscode.window.activeTextEditor &&
      vscode.window.activeTextEditor.document.uri.fsPath);
  if (!target) {
    vscode.window.showErrorMessage("Select a file to plan a patch for.");
    return;
  }
  const fix = await vscode.window.showInputBox({
    prompt: "High-level fix description",
    placeHolder: "e.g., Add logging around orchestrator",
    ignoreFocusOut: true,
  });
  if (!fix) {
    vscode.window.showInformationMessage("Patch plan cancelled (no fix provided).");
    return;
  }
  const symbol = await vscode.window.showInputBox({
    prompt: "Optional symbol (package.module:func)",
    placeHolder: "package.mod:func (leave blank for module-level default)",
    ignoreFocusOut: true,
  });
  const cwd = guessRepoRoot(target);
  const args = ["plan-patch-llm", target, "--fix", fix, "--format", "json"];
  if (symbol) {
    args.push("--symbol", symbol);
  }
  try {
    const { stdout } = await runCli(args, cwd);
    const doc = await vscode.workspace.openTextDocument({
      language: "json",
      content: stdout,
    });
    await vscode.window.showTextDocument(doc, { preview: true });
  } catch (err) {
    vscode.window.showErrorMessage(
      `neurocode plan-patch-llm failed: ${err.stderr || err.message}`
    );
  }
}

async function applyPlanFromEditor() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage("Open a PatchPlanBundle JSON to apply.");
    return;
  }
  const text = editor.document.getText();
  let plan;
  try {
    plan = JSON.parse(text);
  } catch (err) {
    vscode.window.showErrorMessage("Active editor does not contain valid JSON.");
    return;
  }
  const fileRel = plan.file;
  if (!fileRel) {
    vscode.window.showErrorMessage("Patch plan is missing the 'file' field.");
    return;
  }
  const repoRoot = guessRepoRoot(editor.document.uri.fsPath);
  const planPath = path.join(
    await fs.promises.mkdtemp(path.join(os.tmpdir(), "neurocode-plan-")),
    "plan.json"
  );
  await fs.promises.writeFile(planPath, text, "utf-8");
  const fileAbs = path.resolve(repoRoot, fileRel);
  const args = [
    "patch",
    fileAbs,
    "--plan",
    planPath,
    "--show-diff",
    "--format",
    "json",
    "--dry-run",
  ];
  try {
    const { stdout } = await runCli(args, repoRoot);
    let payload;
    try {
      payload = JSON.parse(stdout);
    } catch (err) {
      vscode.window.showErrorMessage("Dry-run succeeded but JSON parse failed.");
      return;
    }
    const diff = payload.diff || "";
    if (diff) {
      const doc = await vscode.workspace.openTextDocument({
        language: "diff",
        content: diff,
      });
      await vscode.window.showTextDocument(doc, { preview: true });
    }
    const choice = await vscode.window.showInformationMessage(
      `Dry-run ok: ${payload.summary || payload.status || ""}. Apply for real?`,
      "Apply",
      "Cancel"
    );
    if (choice !== "Apply") {
      return;
    }
    const applyArgs = [
      "patch",
      fileAbs,
      "--plan",
      planPath,
      "--show-diff",
      "--format",
      "json",
    ];
    const applied = await runCli(applyArgs, repoRoot);
    let appliedPayload;
    try {
      appliedPayload = JSON.parse(applied.stdout);
    } catch (err) {
      vscode.window.showErrorMessage("Apply returned non-JSON output.");
      return;
    }
  const applyDiff = appliedPayload.diff || diff;
  if (applyDiff) {
    const doc = await vscode.workspace.openTextDocument({
      language: "diff",
      content: applyDiff,
    });
    await vscode.window.showTextDocument(doc, { preview: true });
  }
  vscode.window.showInformationMessage(
    `NeuroCode patch applied: ${appliedPayload.summary || appliedPayload.status}`
  );
  } catch (err) {
    vscode.window.showErrorMessage(
      `neurocode patch --plan failed: ${err.stderr || err.message}`
    );
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("neurocode.explainCurrent", explainCurrentFile),
    vscode.commands.registerCommand("neurocode.planCurrent", planPatchForCurrentFile),
    vscode.commands.registerCommand("neurocode.applyPlanFromEditor", applyPlanFromEditor)
  );

  // Task provider: neurocode command runner (ir | embed | status)
  context.subscriptions.push(
    vscode.tasks.registerTaskProvider("neurocode", {
      provideTasks() {
        const cfg = getConfig();
        if (!cfg.tasks?.enabled && cfg.tasks !== undefined) {
          return [];
        }
        const repoRoot = guessRepoRoot("");
        const defs = [
          { label: "NeuroCode: Build IR", command: ["ir", repoRoot] },
          { label: "NeuroCode: Embed (dummy)", command: ["embed", repoRoot, "--provider", "dummy"] },
          { label: "NeuroCode: Status", command: ["status", repoRoot, "--format", "json"] },
        ];
        return defs.map((def) => {
          const task = new vscode.Task(
            { type: "neurocode", command: def.command[0] },
            vscode.TaskScope.Workspace,
            def.label,
            "neurocode",
            new vscode.ShellExecution(`${getConfig().cliPath} ${def.command.join(" ")}`)
          );
          return task;
        });
      },
      resolveTask(_task) {
        return undefined;
      },
    })
  );
}

function deactivate() {}

module.exports = {
  activate,
  deactivate,
};
