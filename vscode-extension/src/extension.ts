import * as vscode from "vscode";
import fetch from "node-fetch";
import { Buffer } from "buffer";

const SERVER_HOST = "127.0.0.1";
const SERVER_PORT = 8787;
const SERVER_BASE = `http://${SERVER_HOST}:${SERVER_PORT}`;

const output = vscode.window.createOutputChannel("NeuroCode");
type ExplainKind = "symbol" | "file";

type PositionPayload = { line: number; character: number };

interface Issue {
    severity?: string;
    message?: string;
    line?: number;
    end_line?: number;
    column?: number;
    end_column?: number;
    code?: string;
    suggestion?: string;
}

interface PatchRange {
    start_line?: number;
    start_column?: number;
    end_line?: number;
    end_column?: number;
}

interface PatchOperation {
    description: string;
    range: PatchRange;
    replacement: string;
}

interface ExplanationResult {
    explanation: string;
    payload: any;
    symbolName: string;
    fileDisplay: string;
    kind: ExplainKind;
    issues: Issue[];
}

interface PatchPlanResult {
    patchExplanation: string;
    patchPlan: PatchOperation[];
    payload: any;
    fileDisplay: string;
    symbolName: string;
    issues: Issue[];
}

// Simple in-memory cache to avoid re-querying the same symbol on hover/Codelens.
const explanationCache = new Map<string, ExplanationResult>();
const diagnosticCollection = vscode.languages.createDiagnosticCollection("neurocode");

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function getNonce(): string {
    const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    return Array.from({ length: 16 })
        .map(() => possible.charAt(Math.floor(Math.random() * possible.length)))
        .join("");
}

async function renderMarkdownToHtml(markdown: string): Promise<string> {
    const trimmed = (markdown || "").trim();
    if (!trimmed) {
        return "<p>No explanation returned.</p>";
    }

    try {
        // Use VS Code's built-in Markdown renderer to avoid shipping our own parser.
        await vscode.extensions.getExtension("vscode.markdown-language-features")?.activate();
        const rendered = await vscode.commands.executeCommand<string>("markdown.api.render", trimmed);
        if (rendered) {
            return rendered;
        }
    } catch (err) {
        output.appendLine(`Markdown render failed, falling back to escaped text: ${err}`);
    }

    return `<pre>${escapeHtml(trimmed)}</pre>`;
}

async function withNeuroCodeProgress<T>(title: string, task: () => Promise<T>): Promise<T> {
    return vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title,
            cancellable: false,
        },
        async () => task()
    );
}

function cacheKey(document: vscode.TextDocument, kind: ExplainKind, position?: vscode.Position): string {
    const posKey = position ? `${position.line}:${position.character}` : "file";
    return `${kind}:${document.uri.toString()}:${posKey}`;
}

function getProjectRoot(document: vscode.TextDocument): string | undefined {
    const workspace = vscode.workspace.getWorkspaceFolder(document.uri);
    return workspace ? workspace.uri.fsPath : undefined;
}

function parseSymbolName(payload: any, fallback: string): string {
    return (
        payload?.symbol?.qualified_name ||
        payload?.symbol?.name ||
        payload?.module?.module_name ||
        fallback
    );
}

function extractSummary(markdown: string, maxLines = 3): string {
    const lines = (markdown || "").split(/\r?\n/);
    const summaryHeaderIndex = lines.findIndex((line) => line.trim().toLowerCase().startsWith("## summary"));
    let start = summaryHeaderIndex >= 0 ? summaryHeaderIndex + 1 : 0;
    if (start >= lines.length) {
        start = 0;
    }
    const collected: string[] = [];
    for (let i = start; i < lines.length; i++) {
        const line = lines[i];
        if (line.trim().startsWith("## ")) {
            break;
        }
        if (line.trim().length === 0) {
            continue;
        }
        collected.push(line.trim());
        if (collected.length >= maxLines) {
            break;
        }
    }
    return collected.join(" ");
}

async function fetchExplanationFromServer(
    document: vscode.TextDocument,
    kind: ExplainKind,
    position?: vscode.Position
): Promise<ExplanationResult> {
    const key = cacheKey(document, kind, position);
    const cached = explanationCache.get(key);
    if (cached) {
        return cached;
    }

    const serverOk = await checkServerHealth();
    if (!serverOk) {
        throw new Error("NeuroCode server is not reachable. Make sure `neurocode serve` is running.");
    }

    const filePath = document.uri.fsPath;
    const projectRoot = getProjectRoot(document);
    const body: any = { project_root: projectRoot, path: filePath };
    const endpoint = kind === "file" ? "/explain_file" : "/explain_symbol";

    if (kind === "symbol") {
        const targetPos = position ?? new vscode.Position(0, 0);
        body.line = targetPos.line + 1;
        body.column = targetPos.character + 1;
    }

    let responsePayload: any;
    try {
        const resp = await fetch(`${SERVER_BASE}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const text = await resp.text();
        try {
            responsePayload = text ? JSON.parse(text) : {};
        } catch {
            responsePayload = { detail: text || "Unknown error" };
        }
        if (!resp.ok) {
            const detail = responsePayload?.detail || `HTTP ${resp.status}`;
            throw new Error(detail);
        }
    } catch (err: any) {
        output.appendLine(`NeuroCode explain error: ${err}`);
        throw err;
    }

    const explanationMarkdown: string =
        typeof responsePayload?.explanation === "string" ? responsePayload.explanation : "";
    const symbolName = parseSymbolName(
        responsePayload,
        kind === "file" ? document.uri.path.split("/").pop() || "Module" : "Symbol"
    );
    const fileDisplay: string = responsePayload?.file || filePath;
    const issues: Issue[] = Array.isArray(responsePayload?.issues) ? responsePayload.issues : [];

    const result: ExplanationResult = {
        explanation: explanationMarkdown,
        payload: responsePayload,
        symbolName,
        fileDisplay,
        kind,
        issues,
    };
    explanationCache.set(key, result);
    return result;
}

async function showExplanationPanel(result: ExplanationResult, title?: string): Promise<void> {
    const renderedExplanation = await renderMarkdownToHtml(result.explanation);
    const panel = vscode.window.createWebviewPanel(
        "neurocodeExplain",
        title || "NeuroCode - Explanation",
        vscode.ViewColumn.Beside,
        { enableScripts: false, retainContextWhenHidden: false }
    );

    panel.webview.html = buildExplanationHtml({
        renderedExplanation,
        rawMarkdown: result.explanation || "No explanation returned.",
        symbolName: result.symbolName,
        fileDisplay: result.fileDisplay,
        payload: result.payload,
    });
}

async function fetchPatchPlanFromServer(
    document: vscode.TextDocument,
    kind: ExplainKind,
    position?: vscode.Position,
    goal?: string
): Promise<PatchPlanResult> {
    const serverOk = await checkServerHealth();
    if (!serverOk) {
        throw new Error("NeuroCode server is not reachable. Make sure `neurocode serve` is running.");
    }

    const filePath = document.uri.fsPath;
    const projectRoot = getProjectRoot(document);
    const body: any = { project_root: projectRoot, path: filePath };
    const endpoint = kind === "file" ? "/plan_patch_file" : "/plan_patch_symbol";

    if (kind === "symbol") {
        const targetPos = position ?? new vscode.Position(0, 0);
        body.line = targetPos.line + 1;
        body.column = targetPos.character + 1;
    }
    if (goal) {
        body.goal = goal;
    }

    let responsePayload: any;
    try {
        const resp = await fetch(`${SERVER_BASE}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const text = await resp.text();
        try {
            responsePayload = text ? JSON.parse(text) : {};
        } catch {
            responsePayload = { detail: text || "Unknown error" };
        }
        if (!resp.ok) {
            const detail = responsePayload?.detail || `HTTP ${resp.status}`;
            throw new Error(detail);
        }
    } catch (err: any) {
        output.appendLine(`NeuroCode patch plan error: ${err}`);
        throw err;
    }

    const patchExplanation: string =
        typeof responsePayload?.patch_explanation === "string" ? responsePayload.patch_explanation : "";
    const patchPlan: PatchOperation[] = Array.isArray(responsePayload?.patch_plan) ? responsePayload.patch_plan : [];
    const symbolName = parseSymbolName(
        responsePayload,
        kind === "file" ? document.uri.path.split("/").pop() || "Module" : "Symbol"
    );
    const fileDisplay: string = responsePayload?.file || filePath;
    const issues: Issue[] = Array.isArray(responsePayload?.issues) ? responsePayload.issues : [];

    return {
        patchExplanation,
        patchPlan,
        payload: responsePayload,
        fileDisplay,
        symbolName,
        issues,
    };
}

function issuesToDiagnostics(document: vscode.TextDocument, issues: Issue[]): vscode.Diagnostic[] {
    if (!issues || !Array.isArray(issues)) {
        return [];
    }

    const diagnostics: vscode.Diagnostic[] = [];
    for (const issue of issues) {
        const line = typeof issue.line === "number" && issue.line > 0 ? issue.line - 1 : 0;
        const endLine =
            typeof issue.end_line === "number" && issue.end_line > 0 ? issue.end_line - 1 : line;
        if (line >= document.lineCount) {
            continue;
        }
        const startLine = Math.max(0, Math.min(line, document.lineCount - 1));
        const finalEndLine = Math.max(startLine, Math.min(endLine, document.lineCount - 1));
        const lineText = document.lineAt(startLine).text;
        const startCharUnclamped = issue.column && issue.column > 0 ? issue.column - 1 : 0;
        const startChar = Math.min(Math.max(startCharUnclamped, 0), lineText.length);
        const endCharUnclamped =
            issue.end_column && issue.end_column > 0
                ? issue.end_column - 1
                : finalEndLine === startLine
                  ? Math.max(startChar + 1, lineText.length)
                  : document.lineAt(finalEndLine).text.length;
        const finalLineText = document.lineAt(finalEndLine).text;
        const endChar = Math.min(Math.max(endCharUnclamped, startChar + 1), finalLineText.length);

        let severity = vscode.DiagnosticSeverity.Warning;
        const sev = (issue.severity || "").toLowerCase();
        if (sev === "info") severity = vscode.DiagnosticSeverity.Information;
        else if (sev === "error") severity = vscode.DiagnosticSeverity.Error;

        const suggestionText = issue.suggestion ? ` Suggestion: ${issue.suggestion}` : "";
        const message = `${issue.message || "Issue detected."}${suggestionText}`;

        const diagnostic = new vscode.Diagnostic(
            new vscode.Range(startLine, startChar, finalEndLine, endChar),
            message,
            severity
        );
        if (issue.code) {
            diagnostic.code = issue.code;
        }
        diagnostics.push(diagnostic);
    }
    return diagnostics;
}

function updateDiagnostics(document: vscode.TextDocument, issues: Issue[]): void {
    const diagnostics = issuesToDiagnostics(document, issues);
    diagnosticCollection.set(document.uri, diagnostics);
}

function buildExplanationHtml({
    renderedExplanation,
    rawMarkdown,
    symbolName,
    fileDisplay,
    payload,
}: {
    renderedExplanation: string;
    rawMarkdown: string;
    symbolName: string;
    fileDisplay: string;
    payload: any;
}): string {
    const safeSymbol = escapeHtml(symbolName);
    const safeFile = escapeHtml(fileDisplay);
    const safeRawMarkdown = escapeHtml(rawMarkdown || "No explanation returned.");
    const safePayload = escapeHtml(JSON.stringify(payload ?? {}, null, 2));
    const explanationBody = renderedExplanation.trim() || "<p>No explanation returned.</p>";

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fb;
      --surface: #ffffff;
      --text: #1b1d23;
      --muted: #4b5563;
      --border: #dfe3ea;
      --shadow: 0 10px 30px rgba(0, 0, 0, 0.05);
      --code-bg: #f1f3f5;
      --code-text: #111827;
      --accent: #0f62fe;
      --table-stripe: #f9fafb;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        color-scheme: dark;
        --bg: #0f1116;
        --surface: #171b22;
        --text: #e8ecf5;
        --muted: #9ba6b9;
        --border: #262c36;
        --shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
        --code-bg: #1f2633;
        --code-text: #e5e9f2;
        --accent: #67a8ff;
        --table-stripe: #151922;
      }
    }
    * { box-sizing: border-box; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
      margin: 0;
      padding: 24px;
      line-height: 1.6;
    }
    .main { max-width: 960px; margin: 0 auto; }
    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      box-shadow: var(--shadow);
    }
    .header { margin-bottom: 12px; }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 12px;
      color: var(--muted);
    }
    h1 {
      margin: 6px 0 4px;
      font-size: 22px;
      line-height: 1.3;
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--muted);
      font-size: 13px;
    }
    code {
      background: var(--code-bg);
      color: var(--code-text);
      padding: 2px 4px;
      border-radius: 4px;
      font-size: 0.95em;
    }
    pre {
      background: var(--code-bg);
      color: var(--code-text);
      border-radius: 8px;
      padding: 12px;
      overflow: auto;
      line-height: 1.45;
      margin: 0 0 14px;
    }
    .markdown-body h2 {
      font-size: 18px;
      margin: 22px 0 8px;
      padding-bottom: 6px;
      border-bottom: 1px solid var(--border);
    }
    .markdown-body h3 {
      font-size: 16px;
      margin: 16px 0 6px;
    }
    .markdown-body p { margin: 0 0 12px; }
    .markdown-body ul, .markdown-body ol {
      padding-left: 20px;
      margin: 0 0 14px;
    }
    .markdown-body li { margin-bottom: 6px; }
    .markdown-body table {
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
    }
    .markdown-body th,
    .markdown-body td {
      border: 1px solid var(--border);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }
    .markdown-body th {
      background: var(--table-stripe);
      font-weight: 600;
    }
    .markdown-body tr:nth-child(even) td {
      background: var(--table-stripe);
    }
    .markdown-body blockquote {
      border-left: 3px solid var(--border);
      padding-left: 12px;
      margin: 0 0 14px;
      color: var(--muted);
    }
    .markdown-body a { color: var(--accent); }
    .markdown-body > :first-child { margin-top: 0; }
    .markdown-body > :last-child { margin-bottom: 0; }
    details.debug {
      margin-top: 18px;
      border-top: 1px solid var(--border);
      padding-top: 12px;
    }
    details summary {
      cursor: pointer;
      color: var(--muted);
      font-weight: 600;
      margin-bottom: 8px;
    }
    .debug-title {
      font-size: 13px;
      color: var(--muted);
      margin: 6px 0;
    }
    .debug-pre {
      max-height: 260px;
      white-space: pre-wrap;
    }
  </style>
</head>
<body>
  <div class="main">
    <section class="panel">
      <div class="header">
        <div class="eyebrow">NeuroCode - Explanation</div>
        <h1>${safeSymbol}</h1>
        <div class="meta"><code>${safeFile}</code></div>
      </div>
      <article class="markdown-body">${explanationBody}</article>
      <details class="debug">
        <summary>Show raw response</summary>
        <div class="debug-title">Raw Markdown</div>
        <pre class="debug-pre">${safeRawMarkdown}</pre>
        <div class="debug-title">Response JSON</div>
        <pre class="debug-pre">${safePayload}</pre>
      </details>
    </section>
  </div>
</body>
</html>`;
}

function buildPatchPlanHtml({
    renderedPatchExplanation,
    rawMarkdown,
    patchPlan,
    symbolName,
    fileDisplay,
    payload,
}: {
    renderedPatchExplanation: string;
    rawMarkdown: string;
    patchPlan: PatchOperation[];
    symbolName: string;
    fileDisplay: string;
    payload: any;
}): string {
    const nonce = getNonce();
    const patchPlanEncoded = Buffer.from(JSON.stringify(patchPlan || [])).toString("base64");
    const safeSymbol = escapeHtml(symbolName);
    const safeFile = escapeHtml(fileDisplay);
    const safeRawMarkdown = escapeHtml(rawMarkdown || "No patch explanation returned.");
    const safePayload = escapeHtml(JSON.stringify(payload ?? {}, null, 2));
    const planRows = patchPlan
        .map((op, idx) => {
            const preview = (op.replacement || "").replace(/\s+/g, " ").slice(0, 120);
            const range = `${op.range?.start_line ?? "?"}:${op.range?.start_column ?? "?"}-${op.range?.end_line ?? "?"}:${op.range?.end_column ?? "?"}`;
            return `<tr>
                <td>${idx + 1}</td>
                <td>${escapeHtml(op.description || "")}</td>
                <td><code>${escapeHtml(range)}</code></td>
                <td>${escapeHtml(preview)}${preview.length >= 120 ? "..." : ""}</td>
            </tr>`;
        })
        .join("");

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; script-src 'nonce-${nonce}';" />
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fb;
      --surface: #ffffff;
      --text: #1b1d23;
      --muted: #4b5563;
      --border: #dfe3ea;
      --shadow: 0 10px 30px rgba(0, 0, 0, 0.05);
      --code-bg: #f1f3f5;
      --code-text: #111827;
      --accent: #0f62fe;
      --table-stripe: #f9fafb;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        color-scheme: dark;
        --bg: #0f1116;
        --surface: #171b22;
        --text: #e8ecf5;
        --muted: #9ba6b9;
        --border: #262c36;
        --shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
        --code-bg: #1f2633;
        --code-text: #e5e9f2;
        --accent: #67a8ff;
        --table-stripe: #151922;
      }
    }
    * { box-sizing: border-box; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
      margin: 0;
      padding: 24px;
      line-height: 1.6;
    }
    .main { max-width: 960px; margin: 0 auto; }
    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      box-shadow: var(--shadow);
    }
    .header { margin-bottom: 12px; }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 12px;
      color: var(--muted);
    }
    h1 {
      margin: 6px 0 4px;
      font-size: 22px;
      line-height: 1.3;
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--muted);
      font-size: 13px;
    }
    .markdown-body h2 {
      font-size: 18px;
      margin: 22px 0 8px;
      padding-bottom: 6px;
      border-bottom: 1px solid var(--border);
    }
    .markdown-body h3 {
      font-size: 16px;
      margin: 16px 0 6px;
    }
    .markdown-body p { margin: 0 0 12px; }
    .markdown-body ul, .markdown-body ol {
      padding-left: 20px;
      margin: 0 0 14px;
    }
    .markdown-body li { margin-bottom: 6px; }
    table.plan {
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
    }
    table.plan th, table.plan td {
      border: 1px solid var(--border);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }
    table.plan th { background: var(--table-stripe); }
    table.plan tr:nth-child(even) td { background: var(--table-stripe); }
    button.apply {
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 14px;
      cursor: pointer;
      margin: 10px 0 16px;
    }
    button.apply:hover { opacity: 0.9; }
    details.debug {
      margin-top: 18px;
      border-top: 1px solid var(--border);
      padding-top: 12px;
    }
    details summary {
      cursor: pointer;
      color: var(--muted);
      font-weight: 600;
      margin-bottom: 8px;
    }
    .debug-title {
      font-size: 13px;
      color: var(--muted);
      margin: 6px 0;
    }
    pre.debug-pre {
      background: var(--code-bg);
      color: var(--code-text);
      border-radius: 8px;
      padding: 12px;
      white-space: pre-wrap;
      overflow: auto;
    }
  </style>
</head>
<body>
  <div class="main">
    <section class="panel">
      <div class="header">
        <div class="eyebrow">NeuroCode - Patch Plan</div>
        <h1>${safeSymbol}</h1>
        <div class="meta"><code>${safeFile}</code></div>
      </div>
      <article class="markdown-body">${renderedPatchExplanation}</article>
      <h2>Proposed Edits</h2>
      ${
          patchPlan.length
              ? `<table class="plan">
                  <thead><tr><th>#</th><th>Description</th><th>Range</th><th>Replacement preview</th></tr></thead>
                  <tbody>${planRows}</tbody>
                </table>`
              : "<p>No concrete patch operations suggested.</p>"
      }
      <button class="apply" id="applyPatch"${patchPlan.length ? "" : " disabled"}>Apply patch</button>
      <details class="debug">
        <summary>Show raw response</summary>
        <div class="debug-title">Raw Markdown</div>
        <pre class="debug-pre">${safeRawMarkdown}</pre>
        <div class="debug-title">Response JSON</div>
        <pre class="debug-pre">${safePayload}</pre>
      </details>
      <script nonce="${nonce}" id="patch-data" data-plan="${patchPlanEncoded}"></script>
      <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        try {
          const dataEl = document.getElementById('patch-data');
          const encoded = dataEl ? dataEl.getAttribute('data-plan') : '';
          const plan = encoded ? JSON.parse(atob(encoded)) : [];
          const btn = document.getElementById('applyPatch');
          if (btn) {
            btn.addEventListener('click', () => {
              vscode.postMessage({ type: 'neurocode.applyPatch', patchPlan: plan });
            });
          }
        } catch (err) {
          console.error('NeuroCode patch plan parse/apply init failed', err);
          vscode.postMessage({ type: 'neurocode.applyPatch', patchPlan: [] });
        }
      </script>
    </section>
  </div>
</body>
</html>`;
}

async function checkServerHealth(): Promise<boolean> {
    try {
        const resp = await fetch(`${SERVER_BASE}/health`);
        if (!resp.ok) {
            output.appendLine(`NeuroCode server health check failed: ${resp.status} ${resp.statusText}`);
            return false;
        }
        return true;
    } catch (err) {
        output.appendLine(`NeuroCode server health check error: ${err}`);
        return false;
    }
}

function isPythonDocument(document: vscode.TextDocument | undefined): document is vscode.TextDocument {
    return !!document && document.languageId === "python";
}

function positionFromPayload(payload?: PositionPayload): vscode.Position | undefined {
    if (!payload) {
        return undefined;
    }
    return new vscode.Position(payload.line, payload.character);
}

async function explainHere(args?: { uri?: vscode.Uri; position?: PositionPayload } | vscode.Uri): Promise<void> {
    let document: vscode.TextDocument | undefined;
    let position: vscode.Position | undefined;

    if (args instanceof vscode.Uri) {
        document = await vscode.workspace.openTextDocument(args);
    } else if (args && "uri" in (args as any) && (args as any).uri) {
        const uriInput = (args as { uri: vscode.Uri | string }).uri;
        const targetUri = typeof uriInput === "string" ? vscode.Uri.parse(uriInput) : uriInput;
        document = await vscode.workspace.openTextDocument(targetUri);
        position = positionFromPayload((args as { position?: PositionPayload }).position);
    } else if (vscode.window.activeTextEditor) {
        document = vscode.window.activeTextEditor.document;
        position = vscode.window.activeTextEditor.selection.active;
    }

    if (!isPythonDocument(document)) {
        vscode.window.showErrorMessage("NeuroCode: open a Python file to explain a symbol.");
        return;
    }

    try {
        await withNeuroCodeProgress("NeuroCode: Explaining symbol...", async () => {
            const result = await fetchExplanationFromServer(document, "symbol", position);
            await showExplanationPanel(result, "NeuroCode - Explanation");
            updateDiagnostics(document, result.issues);
        });
    } catch (err: any) {
        vscode.window.showErrorMessage(
            err?.message ? `NeuroCode server error: ${err.message}` : "NeuroCode server error while requesting explanation."
        );
    }
}

async function explainFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    const document = editor?.document;
    if (!isPythonDocument(document)) {
        vscode.window.showErrorMessage("NeuroCode: open a Python file to explain this module.");
        return;
    }

    try {
        await withNeuroCodeProgress("NeuroCode: Explaining file...", async () => {
            const result = await fetchExplanationFromServer(document, "file");
            const title = `NeuroCode - File Explanation: ${document.uri.path.split("/").pop()}`;
            await showExplanationPanel(result, title);
            updateDiagnostics(document, result.issues);
        });
    } catch (err: any) {
        vscode.window.showErrorMessage(
            err?.message ? `NeuroCode server error: ${err.message}` : "NeuroCode server error while requesting file explanation."
        );
    }
}

async function analyzeFileIssues(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    const document = editor?.document;
    if (!isPythonDocument(document)) {
        vscode.window.showErrorMessage("NeuroCode: open a Python file to analyze issues.");
        return;
    }

    try {
        await withNeuroCodeProgress("NeuroCode: Analyzing issues...", async () => {
            const result = await fetchExplanationFromServer(document, "file");
            updateDiagnostics(document, result.issues);
            const title = `NeuroCode - File Explanation: ${document.uri.path.split("/").pop()}`;
            await showExplanationPanel(result, title);
        });
    } catch (err: any) {
        vscode.window.showErrorMessage(
            err?.message
                ? `NeuroCode server error: ${err.message}`
                : "NeuroCode server error while analyzing file issues."
        );
    }
}

function toRange(document: vscode.TextDocument, pr: PatchRange): vscode.Range | null {
    const startLine = Math.max(0, (pr.start_line || 1) - 1);
    const endLine = Math.max(0, (pr.end_line || pr.start_line || 1) - 1);
    if (startLine >= document.lineCount) {
        return null;
    }
    const safeEndLine = Math.min(endLine, document.lineCount - 1);
    const startText = document.lineAt(startLine).text;
    const endText = document.lineAt(safeEndLine).text;
    const startCol = pr.start_column && pr.start_column > 0 ? pr.start_column - 1 : 0;
    const endCol =
        pr.end_column && pr.end_column > 0
            ? pr.end_column - 1
            : safeEndLine === startLine
              ? startText.length
              : endText.length;
    const start = new vscode.Position(startLine, Math.min(Math.max(startCol, 0), startText.length));
    const end = new vscode.Position(safeEndLine, Math.min(Math.max(endCol, start.character), endText.length));
    return new vscode.Range(start, end);
}

async function applyPatchOperations(document: vscode.TextDocument, patchPlan: PatchOperation[]): Promise<number> {
    if (!patchPlan || !patchPlan.length) {
        vscode.window.showInformationMessage("NeuroCode: no patch operations to apply.");
        return 0;
    }

    const sorted = [...patchPlan].sort((a, b) => {
        const aStart = a.range?.start_line ?? 0;
        const bStart = b.range?.start_line ?? 0;
        if (aStart !== bStart) return bStart - aStart;
        const aCol = a.range?.start_column ?? 0;
        const bCol = b.range?.start_column ?? 0;
        return bCol - aCol;
    });

    const edit = new vscode.WorkspaceEdit();
    let applied = 0;
    for (const op of sorted) {
        if (!op.range) {
            continue;
        }
        const range = toRange(document, op.range);
        if (!range) {
            continue;
        }
        edit.replace(document.uri, range, op.replacement ?? "");
        applied += 1;
    }

    if (applied === 0) {
        vscode.window.showInformationMessage("NeuroCode: no patch operations were applicable to this file.");
        return 0;
    }

    const success = await vscode.workspace.applyEdit(edit);
    if (!success) {
        vscode.window.showErrorMessage("NeuroCode: failed to apply patch. The file may have changed.");
        return 0;
    }
    return applied;
}

async function showPatchPlanPanel(
    result: PatchPlanResult,
    document: vscode.TextDocument,
    title: string
): Promise<void> {
    const renderedPatchExplanation = await renderMarkdownToHtml(result.patchExplanation);
    const panel = vscode.window.createWebviewPanel(
        "neurocodePatchPlan",
        title,
        vscode.ViewColumn.Beside,
        { enableScripts: true, retainContextWhenHidden: false }
    );

    panel.webview.html = buildPatchPlanHtml({
        renderedPatchExplanation,
        rawMarkdown: result.patchExplanation || "No patch explanation returned.",
        patchPlan: result.patchPlan,
        symbolName: result.symbolName,
        fileDisplay: result.fileDisplay,
        payload: result.payload,
    });

    panel.webview.onDidReceiveMessage(
        async (message) => {
            if (message?.type !== "neurocode.applyPatch") {
                return;
            }
            try {
                const plan: PatchOperation[] = Array.isArray(message?.patchPlan) ? message.patchPlan : result.patchPlan;
                output.appendLine(`NeuroCode: applying patch for ${document.uri.fsPath} with ${plan.length} edits`);
                vscode.window.showInformationMessage(`NeuroCode: applying patch with ${plan.length} edits...`);
                const applied = await applyPatchOperations(document, plan);
                if (applied > 0) {
                    vscode.window.showInformationMessage(
                        `NeuroCode patch applied (${applied} edit${applied === 1 ? "" : "s"}).`
                    );
                    if (result.issues) {
                        updateDiagnostics(document, result.issues);
                    } else {
                        try {
                            const updated = await fetchExplanationFromServer(document, "file");
                            updateDiagnostics(document, updated.issues);
                        } catch (err) {
                            output.appendLine(`Failed to refresh diagnostics after patch: ${err}`);
                        }
                    }
                } else {
                    vscode.window.showInformationMessage("NeuroCode: no patch operations were applied.");
                }
            } catch (err: any) {
                output.appendLine(`NeuroCode: patch apply failed: ${err}`);
                vscode.window.showErrorMessage(
                    err?.message ? `NeuroCode: patch apply failed - ${err.message}` : "NeuroCode: patch apply failed."
                );
            }
        },
        undefined,
        []
    );
}

async function suggestFixesForFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    const document = editor?.document;
    if (!isPythonDocument(document)) {
        vscode.window.showErrorMessage("NeuroCode: open a Python file to suggest fixes.");
        return;
    }

    try {
        await withNeuroCodeProgress("NeuroCode: Planning patch...", async () => {
            const result = await fetchPatchPlanFromServer(document, "file");
            const title = `NeuroCode - Patch Plan for ${document.uri.path.split("/").pop()}`;
            await showPatchPlanPanel(result, document, title);
        });
    } catch (err: any) {
        vscode.window.showErrorMessage(
            err?.message
                ? `NeuroCode server error: ${err.message}`
                : "NeuroCode server error while requesting patch plan."
        );
    }
}

async function suggestFixesForSymbol(args?: { uri?: vscode.Uri; position?: PositionPayload } | vscode.Uri): Promise<void> {
    let document: vscode.TextDocument | undefined;
    let position: vscode.Position | undefined;

    if (args instanceof vscode.Uri) {
        document = await vscode.workspace.openTextDocument(args);
    } else if (args && "uri" in (args as any) && (args as any).uri) {
        const uriInput = (args as { uri: vscode.Uri | string }).uri;
        const targetUri = typeof uriInput === "string" ? vscode.Uri.parse(uriInput) : uriInput;
        document = await vscode.workspace.openTextDocument(targetUri);
        position = positionFromPayload((args as { position?: PositionPayload }).position);
    } else if (vscode.window.activeTextEditor) {
        document = vscode.window.activeTextEditor.document;
        position = vscode.window.activeTextEditor.selection.active;
    }

    if (!isPythonDocument(document)) {
        vscode.window.showErrorMessage("NeuroCode: open a Python file to suggest fixes.");
        return;
    }

    try {
        await withNeuroCodeProgress("NeuroCode: Planning patch...", async () => {
            const result = await fetchPatchPlanFromServer(document, "symbol", position);
            const title = `NeuroCode - Patch Plan for ${result.symbolName}`;
            await showPatchPlanPanel(result, document, title);
        });
    } catch (err: any) {
        vscode.window.showErrorMessage(
            err?.message
                ? `NeuroCode server error: ${err.message}`
                : "NeuroCode server error while requesting patch plan."
        );
    }
}

class NeuroCodeLensProvider implements vscode.CodeLensProvider {
    private readonly defRegex = /^\s*(async\s+)?(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)/;

    public provideCodeLenses(document: vscode.TextDocument, _token: vscode.CancellationToken): vscode.CodeLens[] {
        if (!isPythonDocument(document)) {
            return [];
        }

        const lenses: vscode.CodeLens[] = [];
        for (let line = 0; line < document.lineCount; line++) {
            const text = document.lineAt(line).text;
            const match = this.defRegex.exec(text);
            if (!match) {
                continue;
            }
            const name = match[3];
            const nameIndex = match[0].indexOf(name);
            const range = new vscode.Range(new vscode.Position(line, 0), new vscode.Position(line, text.length));
            const position = new vscode.Position(line, nameIndex);
            const args = { uri: document.uri, position: { line, character: position.character } };
            lenses.push(
                new vscode.CodeLens(range, {
                    title: "NeuroCode: Explain",
                    command: "neurocode.explainHere",
                    arguments: [args],
                })
            );
            lenses.push(
                new vscode.CodeLens(range, {
                    title: "NeuroCode: Fix issues",
                    command: "neurocode.suggestFixesForSymbol",
                    arguments: [args],
                })
            );
        }
        return lenses;
    }
}

function encodeCommandArgs(args: any): string {
    return encodeURIComponent(JSON.stringify(args));
}

async function provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    _token: vscode.CancellationToken
): Promise<vscode.Hover | undefined> {
    if (!isPythonDocument(document)) {
        return undefined;
    }
    const wordRange = document.getWordRangeAtPosition(position);
    if (!wordRange) {
        return undefined;
    }

    try {
        const result = await fetchExplanationFromServer(document, "symbol", position);
        const summary = extractSummary(result.explanation);
        if (!summary) {
            return undefined;
        }
        const commandArgs = encodeCommandArgs({
            uri: document.uri.toString(),
            position: { line: position.line, character: position.character },
        });
        const md = new vscode.MarkdownString(undefined, true);
        md.isTrusted = true;
        md.appendMarkdown(`${summary}\n\n[View full NeuroCode explanation](command:neurocode.explainHere?${commandArgs})`);
        return new vscode.Hover(md, wordRange);
    } catch (err) {
        output.appendLine(`Hover explain failed: ${err}`);
        return undefined;
    }
}

export function activate(context: vscode.ExtensionContext): void {
    const explainHereCommand = vscode.commands.registerCommand("neurocode.explainHere", explainHere);
    const explainFileCommand = vscode.commands.registerCommand("neurocode.explainFile", explainFile);
    const analyzeFileIssuesCommand = vscode.commands.registerCommand("neurocode.analyzeFileIssues", analyzeFileIssues);
    const suggestFixesForFileCommand = vscode.commands.registerCommand("neurocode.suggestFixesForFile", suggestFixesForFile);
    const suggestFixesForSymbolCommand = vscode.commands.registerCommand("neurocode.suggestFixesForSymbol", suggestFixesForSymbol);
    const codeLensProvider = vscode.languages.registerCodeLensProvider({ language: "python" }, new NeuroCodeLensProvider());
    const hoverProvider = vscode.languages.registerHoverProvider({ language: "python" }, { provideHover });
    context.subscriptions.push(
        explainHereCommand,
        explainFileCommand,
        analyzeFileIssuesCommand,
        suggestFixesForFileCommand,
        suggestFixesForSymbolCommand,
        codeLensProvider,
        hoverProvider,
        diagnosticCollection,
        output
    );
}

export function deactivate(): void {
    diagnosticCollection.clear();
    diagnosticCollection.dispose();
}
