# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project overview

NeuroCode is an engine for structural understanding and modification of codebases, built around a Neural Intermediate Representation (Neural IR). It aims to let AI reason about a codebase as structured programs with global context (ASTs, call graphs, module graphs, control/data flow) rather than as isolated text files.

Conceptually, the system follows this stack (from the README):

- Parse the codebase into rich program structure: per-file ASTs, call graph, module dependency graph, control-flow graph (CFG), and data-flow information.
- Build a Neural IR on top of these structures as a compressed, structured representation optimized for AI reasoning.
- Use LLMs over this IR for checks, analysis, and patch generation.
- Expose this functionality via a CLI (and later potentially APIs/editor plugins).

## Repository layout

- `pyproject.toml` – Python project metadata (setuptools backend, `src` layout, Python `>=3.10`). Defines a console script entrypoint: `neurocode = neurocode.cli:main`.
- `src/neurocode/cli.py` – CLI front-end defining high-level commands:
-  - `ir` – Phase 1: generate IR for a repository. Walks Python files, builds a
-    minimal structural IR (modules, functions, call sites, basic graphs), and
-    writes it in TOON format to `.neurocode/ir.toon` under the target path.
-  - `explain` – explain a Python file using IR-informed reasoning. Loads
-    `.neurocode/ir.toon`, locates the module for the given file, and prints its
-    imports and functions with outbound calls.
-  - `check` – run structural checks on a Python file (unused imports/functions/params, high fan-out, long functions, call cycles) with text/JSON output and config support.
-  - `patch` – apply an IR-informed patch to a Python file given a high-level fix description (strategies: guard, todo, inject).
- `src/neurocode/__init__.py` – package module (currently empty; available for public exports as the engine is implemented).
- `tests/` – pytest-based test suite, including IR/TOON tests and a small sample repo under `tests/data/sample_repo`.

## Environment setup & installation

The project uses a `src` layout with setuptools, so installing in editable mode is the most convenient way to develop and run the CLI.

1. (Optional but recommended) Create and activate a virtual environment from the repository root:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install the package in editable mode so that the `neurocode` CLI is available and source changes take effect immediately:

   ```bash
   pip install -e .
   ```

   For users installing the published package from PyPI, use:

   ```bash
   pip install neurocode-ai
   ```

## Running the CLI

After installing in editable mode (or as a regular package), the `neurocode` console script is available on the PATH.

Common commands from the repository root:

- Show CLI help and available subcommands:

  ```bash
  neurocode --help
  ```

- Generate IR for the current repository (Phase 1 – TOON IR output):

  ```bash
  neurocode ir .
  ```

  This command walks the target repository, builds a minimal structural IR
  (modules, functions, and call sites), and writes it in TOON format to
  `.neurocode/ir.toon` under the target path. The CLI prints a short summary
  including counts of modules, functions, and calls.

- Explain a specific Python file using IR-informed reasoning:
+
+  ```bash
+  neurocode explain path/to/file.py
+  ```
+
+  This command looks for `.neurocode/ir.toon` by walking up from the file's
+  directory, loads the IR, and prints a summary of the module that owns the
+  file, including imports and functions with their outbound calls.

- Run structural checks on a Python file:

  ```bash
  neurocode check path/to/file.py
  ```

- Apply an IR-informed patch to a Python file using a high-level fix description. Supported strategies:

  - `guard` (default): insert a None-check guard.
  - `todo`: insert a TODO comment.
  - `inject`: insert a stub (NotImplementedError or logging.debug).

  ```bash
  neurocode patch path/to/file.py --fix "High-level description" \\
    --strategy guard|todo|inject \\
    --target package.module.func \\
    --inject-kind notimplemented|log \\
    --inject-message "Custom message" \\
    --require-target \\
    --require-fresh-ir \\
    --dry-run --show-diff
  ```

  Exit codes: 0 = success/applied, 3 = no-op (patch already present), nonzero otherwise.

## Building distributions

The project declares a PEP 517/518 build configuration using setuptools.

- To build source and wheel distributions (requires the `build` package):

  ```bash
  python -m pip install build
  python -m build
  ```

  Artifacts will be written to the `dist/` directory.

- To install the package without editable mode (e.g., in a clean environment):

  ```bash
  python -m pip install .
  ```

## Tests and linting

- Tests are written with `pytest` and live under the `tests/` directory.
  - Install dev dependencies (pytest + Ruff):

    ```bash
    pip install -e .[dev]
    ```

  - Run the full test suite:

    ```bash
    pytest
    ```

  - Run a single test file (e.g., IR build tests):

    ```bash
    pytest tests/test_ir_build.py
    ```

- Ruff is configured as the linter via `pyproject.toml` (`[tool.ruff]`) and installed as a development extra.
  - Install dev dependencies (including Ruff):

    ```bash
    pip install -e .[dev]
    ```

  - Lint the whole codebase:

    ```bash
    ruff check src
    ```

  - Lint a single file (analogous to running a single test):

    ```bash
    ruff check src/neurocode/cli.py
    ```

## Architecture notes for future implementation

- The CLI in `src/neurocode/cli.py` is organized around phases that correspond to the conceptual pipeline in the README:
  - Phase 1 (`ir`) for building the structural representations (AST, call graph, module graph, CFG, data flow) and Neural IR.
  - Later phases (`explain`, `check`, `patch`) for IR-informed reasoning, analysis, and patch generation.
- As the engine is implemented, expect new modules under `src/neurocode/` to mirror this pipeline: code ingestion/parsing, graph and IR construction, and high-level reasoning operations invoked by the CLI.
- Keep CLI code focused on argument parsing and dispatch; heavy lifting should live in library modules under `neurocode` so it can be reused by other front-ends (e.g., APIs or editor integrations) consistent with the README's vision.
