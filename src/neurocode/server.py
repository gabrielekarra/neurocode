from __future__ import annotations

import ast
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Tuple

from fastapi import FastAPI, HTTPException
from fastapi import status as http_status
from pydantic import BaseModel, Field

from .explain import _find_module_for_file
from .ir_build import build_repository_ir
from .ir_model import FunctionIR, ModuleIR, RepositoryIR
from .llm_client import LLMClient, LLMError
from .symbol_explainer import (
    explain_module_with_issues,
    explain_symbol_with_issues,
    plan_module_patch_with_issues,
    plan_symbol_patch_with_issues,
)
from .toon_parse import load_repository_ir
from .toon_serialize import repository_ir_to_toon


class ExplainSymbolRequest(BaseModel):
    """Request payload for POST /explain_symbol."""

    path: str = Field(..., description="File path to the Python source (absolute or relative to project_root).")
    line: int = Field(..., description="1-based line number of the symbol.")
    column: int = Field(1, description="1-based column number within the line.")
    project_root: str | None = Field(
        None, description="Project root override; defaults to server startup root when omitted."
    )


class ExplainFileRequest(BaseModel):
    """Request payload for POST /explain_file."""

    path: str = Field(..., description="File path to the Python source (absolute or relative to project_root).")
    project_root: str | None = Field(
        None, description="Project root override; defaults to server startup root when omitted."
    )


class PlanPatchFileRequest(BaseModel):
    """Request payload for POST /plan_patch_file."""

    path: str = Field(..., description="File path to the Python source (absolute or relative to project_root).")
    goal: str | None = Field(None, description="Optional natural-language goal for the patch plan.")
    project_root: str | None = Field(
        None, description="Project root override; defaults to server startup root when omitted."
    )


class PlanPatchSymbolRequest(BaseModel):
    """Request payload for POST /plan_patch_symbol."""

    path: str = Field(..., description="File path to the Python source (absolute or relative to project_root).")
    line: int = Field(..., description="1-based line number of the symbol.")
    column: int = Field(1, description="1-based column number within the line.")
    goal: str | None = Field(None, description="Optional natural-language goal for the patch plan.")
    project_root: str | None = Field(
        None, description="Project root override; defaults to server startup root when omitted."
    )


def _load_or_build_ir(project_root: Path, cache: Dict[Path, RepositoryIR]) -> RepositoryIR:
    """Load IR from disk if present; otherwise build and persist it."""

    root = project_root.resolve()
    if root in cache:
        return cache[root]

    ir_path = root / ".neurocode" / "ir.toon"
    if ir_path.is_file():
        ir = load_repository_ir(ir_path)
        cache[root] = ir
        return ir

    try:
        ir = build_repository_ir(root)
        ir.root = root
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to build IR for project_root={root}: {exc}",
        ) from exc

    ir_path.parent.mkdir(parents=True, exist_ok=True)
    ir_path.write_text(repository_ir_to_toon(ir), encoding="utf-8")
    cache[root] = ir
    return ir


def _build_end_lineno_map(file_path: Path) -> Dict[int, int]:
    """Return mapping of start lineno -> end_lineno using AST end positions."""

    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except Exception:
        return {}
    mapping: Dict[int, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is not None and end is not None:
                mapping[start] = end
    return mapping


def _function_by_position(module: ModuleIR, file_path: Path, line: int) -> Tuple[FunctionIR | None, Dict[int, int]]:
    """Select the FunctionIR covering the given line (prefers the smallest containing span)."""

    end_map = _build_end_lineno_map(file_path)
    candidate: FunctionIR | None = None
    candidate_span: int | None = None
    for fn in module.functions:
        if fn.kind == "module":
            continue
        start = fn.lineno
        end = end_map.get(start, start)
        if line < start or line > end:
            continue
        span = end - start
        if candidate_span is None or span < candidate_span:
            candidate = fn
            candidate_span = span
    return candidate, end_map


def _source_snippet(file_path: Path, start: int, end: int) -> str:
    """Return a slice of the source file between start/end lines (inclusive)."""

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    start_idx = max(start - 1, 0)
    end_idx = min(end, len(lines))
    return "\n".join(lines[start_idx:end_idx])


def _file_line_count(file_path: Path) -> int:
    """Return total number of lines in a file."""

    try:
        return len(file_path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def _serialize_function(fn: FunctionIR) -> dict:
    """Minimal dict representation of FunctionIR for responses."""

    data = asdict(fn)
    # Drop noisy keys
    for key in ["calls"]:
        data.pop(key, None)
    return data


def create_app(default_project_root: Path | str | None = None, llm_client: LLMClient | None = None) -> FastAPI:
    """
    Build the ASGI app exposing NeuroCode LLM-backed explain APIs.

    The default project root is used when requests omit project_root.
    A pre-constructed llm_client may be injected for testing.
    """

    app = FastAPI(title="NeuroCode Server", version="0.1")
    app.state.project_root = Path(default_project_root or Path.cwd()).resolve()
    app.state.ir_cache: Dict[Path, RepositoryIR] = {}
    app.state.llm_client = llm_client

    def _get_llm_client() -> LLMClient:
        if getattr(app.state, "llm_client", None) is None:
            try:
                app.state.llm_client = LLMClient()
            except LLMError as exc:
                raise HTTPException(
                    status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(exc),
                ) from exc
        return app.state.llm_client

    @app.get("/health")
    async def health() -> dict:
        """Liveness probe endpoint."""

        return {"status": "ok"}

    @app.post("/explain_symbol")
    async def explain_symbol(payload: ExplainSymbolRequest) -> dict:
        """
        Explain a symbol located at (path, line, column).

        Column is accepted as 1-based for future disambiguation; currently line
        selection is sufficient for function/method resolution.
        """

        if payload.line < 1 or payload.column < 1:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="line and column must be positive integers",
            )

        project_root = Path(payload.project_root or app.state.project_root).resolve()
        file_path = Path(payload.path)
        if not file_path.is_absolute():
            file_path = (project_root / file_path).resolve()

        if not file_path.exists():
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"File not found: {file_path}",
            )

        ir = _load_or_build_ir(project_root, app.state.ir_cache)
        module = _find_module_for_file(ir, project_root, file_path)
        if module is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No module found for file {file_path}",
            )

        fn, end_map = _function_by_position(module, file_path, payload.line)
        if fn is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No function found at {file_path}:{payload.line}",
            )

        start = fn.lineno
        end = end_map.get(start, fn.lineno)
        snippet = _source_snippet(file_path, start, end)

        try:
            explanation, issues = explain_symbol_with_issues(
                fn,
                module=module,
                repository=ir,
                related_symbols=None,
                source_snippet=snippet,
                llm_client=_get_llm_client(),
            )
        except LLMError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

        return {
            "project_root": str(project_root),
            "file": str(file_path),
            "symbol": _serialize_function(fn),
            "module": {"module_name": module.module_name, "path": str(module.path)},
            "explanation": explanation,
            "issues": issues,
            "range": {"start": start, "end": end},
        }

    @app.post("/explain_file")
    async def explain_file(payload: ExplainFileRequest) -> dict:
        """
        Explain a module/file level without selecting a specific symbol.
        """

        project_root = Path(payload.project_root or app.state.project_root).resolve()
        file_path = Path(payload.path)
        if not file_path.is_absolute():
            file_path = (project_root / file_path).resolve()

        if not file_path.exists():
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"File not found: {file_path}",
            )

        ir = _load_or_build_ir(project_root, app.state.ir_cache)
        module = _find_module_for_file(ir, project_root, file_path)
        if module is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No module found for file {file_path}",
            )

        line_count = _file_line_count(file_path)
        snippet = _source_snippet(file_path, 1, max(1, line_count))

        try:
            explanation, issues = explain_module_with_issues(
                module,
                repository=ir,
                source_snippet=snippet,
                llm_client=_get_llm_client(),
            )
        except LLMError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

        return {
            "project_root": str(project_root),
            "file": str(file_path),
            "module": {"module_name": module.module_name, "path": str(module.path)},
            "explanation": explanation,
            "issues": issues,
            "range": {"start": 1, "end": max(1, line_count)},
        }

    @app.post("/plan_patch_file")
    async def plan_patch_file(payload: PlanPatchFileRequest) -> dict:
        """
        Propose a patch plan for a module/file level without selecting a specific symbol.
        """

        project_root = Path(payload.project_root or app.state.project_root).resolve()
        file_path = Path(payload.path)
        if not file_path.is_absolute():
            file_path = (project_root / file_path).resolve()

        if not file_path.exists():
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"File not found: {file_path}",
            )

        ir = _load_or_build_ir(project_root, app.state.ir_cache)
        module = _find_module_for_file(ir, project_root, file_path)
        if module is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No module found for file {file_path}",
            )

        line_count = _file_line_count(file_path)
        snippet = _source_snippet(file_path, 1, max(1, line_count))

        try:
            patch_explanation, issues, patch_plan = plan_module_patch_with_issues(
                module,
                repository=ir,
                source_snippet=snippet,
                issues=None,
                goal=payload.goal,
                llm_client=_get_llm_client(),
            )
        except LLMError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

        return {
            "project_root": str(project_root),
            "file": str(file_path),
            "module": {"module_name": module.module_name, "path": str(module.path)},
            "patch_explanation": patch_explanation,
            "patch_plan": patch_plan,
            "issues": issues,
            "range": {"start": 1, "end": max(1, line_count)},
        }

    @app.post("/plan_patch_symbol")
    async def plan_patch_symbol(payload: PlanPatchSymbolRequest) -> dict:
        """
        Propose a patch plan focused on a single symbol.
        """

        if payload.line < 1 or payload.column < 1:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="line and column must be positive integers",
            )

        project_root = Path(payload.project_root or app.state.project_root).resolve()
        file_path = Path(payload.path)
        if not file_path.is_absolute():
            file_path = (project_root / file_path).resolve()

        if not file_path.exists():
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"File not found: {file_path}",
            )

        ir = _load_or_build_ir(project_root, app.state.ir_cache)
        module = _find_module_for_file(ir, project_root, file_path)
        if module is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No module found for file {file_path}",
            )

        fn, end_map = _function_by_position(module, file_path, payload.line)
        if fn is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No function found at {file_path}:{payload.line}",
            )

        start = fn.lineno
        end = end_map.get(start, fn.lineno)
        snippet = _source_snippet(file_path, start, end)

        try:
            patch_explanation, issues, patch_plan = plan_symbol_patch_with_issues(
                fn,
                module=module,
                repository=ir,
                related_symbols=None,
                source_snippet=snippet,
                issues=None,
                goal=payload.goal,
                llm_client=_get_llm_client(),
            )
        except LLMError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

        return {
            "project_root": str(project_root),
            "file": str(file_path),
            "symbol": _serialize_function(fn),
            "module": {"module_name": module.module_name, "path": str(module.path)},
            "patch_explanation": patch_explanation,
            "patch_plan": patch_plan,
            "issues": issues,
            "range": {"start": start, "end": end},
        }

    return app


# Default app for `uvicorn neurocode.server:app`
app = create_app()


def serve(project_root: Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Start the NeuroCode HTTP server with the given project root."""

    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("uvicorn is required to run the NeuroCode server. Install with `pip install uvicorn`.") from exc

    uvicorn.run(create_app(project_root), host=host, port=port)
