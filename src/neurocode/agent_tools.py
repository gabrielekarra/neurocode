from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List

from .api import PatchApplyResult, PatchPlan, open_project


class AgentToolsError(RuntimeError):
    """Raised when agent/tool integrations cannot be constructed."""


def _require_langchain_tool() -> Callable[..., Any]:
    try:
        from langchain_core.tools import Tool  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise AgentToolsError(
            "langchain-core is required for agent tools. Install with `pip install langchain-core`."
        ) from exc
    return Tool


def make_langchain_tools(repo_root: str | Path) -> List[Any]:
    """
    Build a small set of LangChain Tool objects around NeuroCode primitives.

    Tools returned:
    - neurocode_explain_llm: build LLM-ready reasoning bundle for a file/symbol.
    - neurocode_plan_patch_llm: create a patch plan bundle for a file/symbol/fix.
    - neurocode_apply_patch_plan: apply a JSON-like PatchPlanBundle (dry_run optional).

    Note: langchain-core must be installed separately. IR/embeddings must already exist.
    """

    Tool = _require_langchain_tool()
    project = open_project(repo_root)

    def _explain(file: str, symbol: str | None = None, k_neighbors: int = 10) -> dict[str, Any]:
        return project.explain_llm(file, symbol=symbol, k_neighbors=k_neighbors)

    def _plan_patch(
        file: str,
        fix: str,
        symbol: str | None = None,
        k_neighbors: int = 10,
    ) -> dict[str, Any]:
        plan: PatchPlan = project.plan_patch_llm(file, fix=fix, symbol=symbol, k_neighbors=k_neighbors)
        return plan.data

    def _apply_patch(plan: dict[str, Any], dry_run: bool = True, show_diff: bool = True) -> dict[str, Any]:
        result: PatchApplyResult = project.apply_patch_plan(plan, dry_run=dry_run, show_diff=show_diff)
        return {
            "status": result.status or ("noop" if result.is_noop else "applied"),
            "files_changed": [str(p) for p in result.files_changed],
            "is_noop": result.is_noop,
            "summary": result.summary,
            "warnings": result.warnings,
            "diff": result.diff if (show_diff or dry_run) else None,
        }

    return [
        Tool.from_function(
            func=_explain,
            name="neurocode_explain_llm",
            description="Build an IR/embedding-backed reasoning bundle for a Python file or symbol.",
        ),
        Tool.from_function(
            func=_plan_patch,
            name="neurocode_plan_patch_llm",
            description="Generate a PatchPlanBundle JSON for a file/symbol/fix using NeuroCode IR.",
        ),
        Tool.from_function(
            func=_apply_patch,
            name="neurocode_apply_patch_plan",
            description="Apply a PatchPlanBundle (dict) to the repo. Defaults to dry_run with diff.",
        ),
    ]


__all__ = ["AgentToolsError", "make_langchain_tools"]
