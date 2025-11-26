# NeuroCode VS Code Extension (MVP)

This minimal extension provides a single command to explain the symbol at the current cursor location by calling the local NeuroCode server (`neurocode serve`).

## Features

- Activation on Python files.
- Command: **NeuroCode: Explain symbol here** (`neurocode.explainHere`).
- Sends the active file path and cursor position (1-based line/column) to `http://127.0.0.1:8787/explain_symbol`.
- Displays the returned explanation in a webview panel.

## Usage

1. In your project root, run the NeuroCode server:

   ```bash
   neurocode serve --project-root /path/to/repo --host 127.0.0.1 --port 8787
   ```

2. Open the project in VS Code, open a Python file, place the cursor on a symbol, then run the command **NeuroCode: Explain symbol here**.

If the server is unreachable, the extension shows an error message.
