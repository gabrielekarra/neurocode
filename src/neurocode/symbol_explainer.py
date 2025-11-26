from __future__ import annotations

import json
import logging
from textwrap import indent
from typing import Any, Sequence, Tuple

from .ir_model import FunctionIR, ModuleIR, RepositoryIR
from .llm_client import LLMClient

IssueDict = dict[str, Any]
PatchDict = dict[str, Any]
logger = logging.getLogger(__name__)


def _serialize_function_ir(fn: FunctionIR) -> str:
    """Return a readable representation of a FunctionIR block."""

    lines: list[str] = [
        f"name: {fn.name}",
        f"qualified_name: {fn.qualified_name or fn.symbol_id or ''}",
        f"kind: {fn.kind}",
        f"lineno: {fn.lineno}",
    ]
    if fn.signature:
        lines.append(f"signature: {fn.signature}")
    if fn.parent_class_qualified_name:
        lines.append(f"parent_class: {fn.parent_class_qualified_name}")
    if fn.docstring:
        lines.append("docstring:")
        lines.append(indent(fn.docstring.strip(), "  "))
    if fn.calls:
        lines.append("calls:")
        for call in fn.calls:
            lines.append(f"  - line {call.lineno}: {call.target}")
    return "\n".join(lines)


def _module_summary(module: ModuleIR) -> str:
    """Summarize functions/classes inside a module for the prompt."""

    functions = [fn.qualified_name or fn.name for fn in module.functions if fn.kind != "module"]
    classes = [cls.qualified_name or cls.name for cls in module.classes]
    imports = [imp.module or imp.name for imp in module.imports]
    lines = [
        f"module: {module.module_name}",
        f"path: {module.path}",
    ]
    if functions:
        lines.append(f"functions: {', '.join(functions)}")
    if classes:
        lines.append(f"classes: {', '.join(classes)}")
    if imports:
        lines.append(f"imports: {', '.join(imports[:15])}" + (" ..." if len(imports) > 15 else ""))
    return "\n".join(lines)


def _extract_json_block(text: str, marker: str, key: str) -> Tuple[str, list[dict]]:
    """
    Split the LLM response into (remaining_text, payload_list) for a given fenced block marker.

    The block is expected to be a fenced code block labeled with the given marker.
    When absent or malformed, we return the original text and an empty list.
    """

    start = text.rfind(marker)
    if start == -1:
        return text.strip(), []

    end = text.find("```", start + len(marker))
    if end == -1:
        logger.warning("Issues block start found without closing fence.")
        return text.strip(), []

    block_content_start = text.find("\n", start)
    if block_content_start == -1 or block_content_start > end:
        logger.warning("Issues block missing newline after marker.")
        return text.strip(), []

    block_content = text[block_content_start + 1 : end].strip()
    explanation = (text[:start] + text[end + 3 :]).strip()

    try:
        parsed = json.loads(block_content or "{}")
        items = parsed.get(key, [])
        if not isinstance(items, list):
            logger.warning("%s payload is not a list.", key)
            return explanation, []
        return explanation, items
    except json.JSONDecodeError:
        logger.warning("Failed to decode %s JSON block.", key, exc_info=True)
        return explanation, []


def _extract_issues_block(text: str) -> Tuple[str, list[IssueDict]]:
    return _extract_json_block(text, "```json issues", "issues")


def _extract_patch_plan_block(text: str) -> Tuple[str, list[PatchDict]]:
    return _extract_json_block(text, "```json patch_plan", "patch_plan")


def build_symbol_explanation_prompt(
    symbol_ir: FunctionIR,
    *,
    module: ModuleIR | None = None,
    repository: RepositoryIR | None = None,
    related_symbols: Sequence[FunctionIR] | None = None,
    source_snippet: str | None = None,
) -> str:
    """
    Build an English prompt to explain a symbol using structured IR context.

    Args:
        symbol_ir: Target symbol to explain.
        module: Optional module context for paths and neighbors.
        repository: Optional repository IR to surface the root path.
        related_symbols: Additional nearby symbols to list for context.
        source_snippet: Optional source code snippet to include verbatim.

    Returns:
        A prompt string suitable for passing to an LLM client.
    """

    qualified_name = symbol_ir.qualified_name or symbol_ir.symbol_id or symbol_ir.name
    related_symbols = list(related_symbols or [])
    ir_block = indent(_serialize_function_ir(symbol_ir), "  ")

    # The prompt is intentionally opinionated so the model returns structured, concise Markdown.
    lines: list[str] = [
        "You are a senior Python engineer performing a focused code review.",
        "Write a clear, technical explanation in Markdown using at most ## and ### headings.",
        "Be concise (aim for 400-600 words), avoid fluffy language, and use bullet lists where they help.",
        "Use only minimal bolding for a few key terms; do not overuse it.",
        "",
        "Produce these sections exactly in this order:",
        "## Summary - 1-2 short paragraphs on what the symbol does.",
        "## Parameters - bullet list of parameters with one-line descriptions, or state there are none.",
        "## Internal Logic - ordered/unordered list of main steps or control flow.",
        "## Potential Issues - realistic problems or say \"No significant issues detected.\"",
        "## Suggested Improvements - refactors or design tweaks, or a short note if none.",
        "## Dependencies - other modules/classes/functions relied on and why.",
        "",
        "Context for the target symbol (IR = intermediate representation):",
        f"- Target symbol: {qualified_name}",
        f"- Kind: {symbol_ir.kind}",
        f"- Module: {(module.module_name if module else symbol_ir.module) or 'unknown'}",
        f"- File: {module.path if module else 'unknown'}",
        f"- Line: {symbol_ir.lineno}",
    ]
    if symbol_ir.signature:
        lines.append(f"- Signature: {symbol_ir.signature}")
    if symbol_ir.parent_class_qualified_name:
        lines.append(f"- Parent class: {symbol_ir.parent_class_qualified_name}")
    if repository:
        lines.append(f"- Repository root: {repository.root}")

    lines.append("")
    lines.append("IR for the target symbol:")
    lines.append(ir_block)

    if module:
        lines.append("")
        lines.append("Module context (neighbors):")
        lines.append(indent(_module_summary(module), "  "))

    if related_symbols:
        lines.append("")
        lines.append("Related symbols for nearby context:")
        for related in related_symbols:
            lines.append(indent(_serialize_function_ir(related), "  "))

    if source_snippet and source_snippet.strip():
        lines.append("")
        lines.append("Source snippet (trimmed):")
        lines.append(indent(source_snippet.strip(), "  "))

    lines.append("")
    lines.append(
        "Base the explanation only on the information above. Do not invent APIs. Keep the Markdown valid."
    )
    lines.append(
        'After the Markdown sections, append a fenced code block labeled "json issues" containing a JSON object '
        'with an "issues" array of objects: { "severity": "info|warning|error", "message": "...", '
        '"line": <1-based>, "end_line": <1-based>, "column": <1-based or 0>, "end_column": <1-based or 0>, '
        '"code": "NC### optional", "suggestion": "optional fix hint" }.'
    )
    lines.append(
        'Format the block exactly like: ```json issues\\n{ "issues": [ ... ] }\\n```. '
        "If there are no issues, return an empty issues list."
    )

    return "\n".join(lines)


def explain_symbol_with_llm(
    symbol_ir: FunctionIR,
    *,
    module: ModuleIR | None = None,
    repository: RepositoryIR | None = None,
    related_symbols: Sequence[FunctionIR] | None = None,
    source_snippet: str | None = None,
    llm_client: LLMClient | None = None,
) -> str:
    """
    Call the LLM to obtain a natural-language explanation for a symbol.

    The function keeps LLM usage internal; callers only provide IR objects
    and receive the rendered explanation text.
    """

    explanation, _ = explain_symbol_with_issues(
        symbol_ir,
        module=module,
        repository=repository,
        related_symbols=related_symbols,
        source_snippet=source_snippet,
        llm_client=llm_client,
    )
    return explanation


def build_module_explanation_prompt(
    module_ir: ModuleIR,
    *,
    repository: RepositoryIR | None = None,
    source_snippet: str | None = None,
) -> str:
    """
    Build a module-level prompt to explain a Python file using the same structured Markdown format.
    """

    lines: list[str] = [
        "You are a senior Python engineer performing a focused code review.",
        "Explain this Python module in Markdown using at most ## and ### headings.",
        "Be concise (aim for 400-600 words) and avoid fluff. Use bullet lists where they help.",
        "Use minimal bolding; keep Markdown valid.",
        "",
        "Produce these sections exactly in this order:",
        "## Summary - 1-2 short paragraphs on what the module provides.",
        "## Parameters - for module-level entry points/configs (if any), or state there are none.",
        "## Internal Logic - ordered/unordered list of main flows and responsibilities.",
        "## Potential Issues - realistic problems or say \"No significant issues detected.\"",
        "## Suggested Improvements - refactors or design tweaks, or a short note if none.",
        "## Dependencies - key imports and cross-module/class/function dependencies.",
        "",
        "Context for the module (IR = intermediate representation):",
        f"- Module: {module_ir.module_name}",
        f"- File: {module_ir.path}",
    ]
    if repository:
        lines.append(f"- Repository root: {repository.root}")

    lines.append("")
    lines.append("Module summary and members:")
    lines.append(indent(_module_summary(module_ir), "  "))

    if source_snippet and source_snippet.strip():
        lines.append("")
        lines.append("Source snippet (trimmed to module content):")
        lines.append(indent(source_snippet.strip(), "  "))

    lines.append("")
    lines.append("Base the explanation only on the information above. Do not invent APIs. Keep the Markdown valid.")
    lines.append(
        'After the Markdown sections, append a fenced code block labeled "json issues" containing a JSON object '
        'with an "issues" array of objects: { "severity": "info|warning|error", "message": "...", '
        '"line": <1-based>, "end_line": <1-based>, "column": <1-based or 0>, "end_column": <1-based or 0>, '
        '"code": "NC### optional", "suggestion": "optional fix hint" }.'
    )
    lines.append(
        'Format the block exactly like: ```json issues\\n{ "issues": [ ... ] }\\n```. '
        "If there are no issues, return an empty issues list."
    )

    return "\n".join(lines)


def explain_module_with_llm(
    module_ir: ModuleIR,
    *,
    repository: RepositoryIR | None = None,
    source_snippet: str | None = None,
    llm_client: LLMClient | None = None,
) -> str:
    """
    Call the LLM to obtain a natural-language explanation for a module/file.
    """

    explanation, _ = explain_module_with_issues(
        module_ir,
        repository=repository,
        source_snippet=source_snippet,
        llm_client=llm_client,
    )
    return explanation


def _generate_explanation_and_issues(prompt: str, llm_client: LLMClient | None = None) -> Tuple[str, list[IssueDict]]:
    client = llm_client or LLMClient()
    raw = (client.generate(prompt) or "").strip()
    return _extract_issues_block(raw)


def explain_symbol_with_issues(
    symbol_ir: FunctionIR,
    *,
    module: ModuleIR | None = None,
    repository: RepositoryIR | None = None,
    related_symbols: Sequence[FunctionIR] | None = None,
    source_snippet: str | None = None,
    llm_client: LLMClient | None = None,
) -> Tuple[str, list[IssueDict]]:
    """
    Obtain both the Markdown explanation and a structured list of issues for a symbol.
    """

    prompt = build_symbol_explanation_prompt(
        symbol_ir,
        module=module,
        repository=repository,
        related_symbols=related_symbols,
        source_snippet=source_snippet,
    )
    return _generate_explanation_and_issues(prompt, llm_client=llm_client)


def _issues_context_text(issues: Sequence[IssueDict] | None) -> str:
    if not issues:
        return "No structured issues provided; infer any potential issues from context."
    summaries = []
    for issue in issues:
        msg = issue.get("message") or ""
        sev = issue.get("severity") or ""
        line = issue.get("line")
        line_part = f" @ line {line}" if line else ""
        summaries.append(f"- {sev}: {msg}{line_part}".strip())
    return "Known issues:\n" + "\n".join(summaries)


def build_symbol_patch_prompt(
    symbol_ir: FunctionIR,
    *,
    module: ModuleIR | None = None,
    repository: RepositoryIR | None = None,
    related_symbols: Sequence[FunctionIR] | None = None,
    source_snippet: str | None = None,
    issues: Sequence[IssueDict] | None = None,
    goal: str | None = None,
) -> str:
    """Prompt for proposing focused patch operations for a symbol."""

    base_prompt = build_symbol_explanation_prompt(
        symbol_ir,
        module=module,
        repository=repository,
        related_symbols=related_symbols,
        source_snippet=source_snippet,
    )
    lines = [
        base_prompt,
        "",
        "Task: propose a small set of safe, local edits (patch plan) to address the most important issues.",
        "Prefer minimal diffs and avoid wholesale rewrites unless necessary.",
        f"Goal: {goal or 'fix critical issues and improve clarity without changing behavior unnecessarily.'}",
        _issues_context_text(issues),
        "",
        "Include a concise Markdown section ## Patch Plan describing the edits.",
        'After the Markdown, append a fenced code block labeled "json patch_plan" with a JSON object: '
        '{ "patch_plan": [ { "description": "...", "range": { "start_line": <1-based>, '
        '"start_column": <1-based>, "end_line": <1-based>, "end_column": <1-based> }, '
        '"replacement": "..." } ] }. Use \\n for multi-line replacements.',
        "If no concrete edits are needed, return an empty patch_plan array.",
        'Format the block exactly like: ```json patch_plan\\n{ "patch_plan": [ ... ] }\\n```.',
    ]
    return "\n".join(lines)


def build_module_patch_prompt(
    module_ir: ModuleIR,
    *,
    repository: RepositoryIR | None = None,
    source_snippet: str | None = None,
    issues: Sequence[IssueDict] | None = None,
    goal: str | None = None,
) -> str:
    """Prompt for proposing focused patch operations for a module."""

    base_prompt = build_module_explanation_prompt(
        module_ir,
        repository=repository,
        source_snippet=source_snippet,
    )
    lines = [
        base_prompt,
        "",
        "Task: propose a small set of safe, local edits (patch plan) to address the most important issues.",
        "Prefer minimal diffs and avoid wholesale rewrites unless necessary.",
        f"Goal: {goal or 'fix critical issues and improve clarity without changing behavior unnecessarily.'}",
        _issues_context_text(issues),
        "",
        "Include a concise Markdown section ## Patch Plan describing the edits.",
        'After the Markdown, append a fenced code block labeled "json patch_plan" with a JSON object: '
        '{ "patch_plan": [ { "description": "...", "range": { "start_line": <1-based>, '
        '"start_column": <1-based>, "end_line": <1-based>, "end_column": <1-based> }, '
        '"replacement": "..." } ] }. Use \\n for multi-line replacements.',
        "If no concrete edits are needed, return an empty patch_plan array.",
        'Format the block exactly like: ```json patch_plan\\n{ "patch_plan": [ ... ] }\\n```.',
    ]
    return "\n".join(lines)


def _generate_patch_and_issues(prompt: str, llm_client: LLMClient | None = None) -> Tuple[str, list[IssueDict], list[PatchDict]]:
    client = llm_client or LLMClient()
    raw = (client.generate(prompt) or "").strip()
    text_without_patch, patch_plan = _extract_patch_plan_block(raw)
    explanation, issues = _extract_issues_block(text_without_patch)
    return explanation, issues, patch_plan


def plan_symbol_patch_with_issues(
    symbol_ir: FunctionIR,
    *,
    module: ModuleIR | None = None,
    repository: RepositoryIR | None = None,
    related_symbols: Sequence[FunctionIR] | None = None,
    source_snippet: str | None = None,
    issues: Sequence[IssueDict] | None = None,
    goal: str | None = None,
    llm_client: LLMClient | None = None,
) -> Tuple[str, list[IssueDict], list[PatchDict]]:
    """
    Obtain a Markdown patch explanation, issues, and structured patch plan for a symbol.
    """

    prompt = build_symbol_patch_prompt(
        symbol_ir,
        module=module,
        repository=repository,
        related_symbols=related_symbols,
        source_snippet=source_snippet,
        issues=issues,
        goal=goal,
    )
    return _generate_patch_and_issues(prompt, llm_client=llm_client)


def plan_module_patch_with_issues(
    module_ir: ModuleIR,
    *,
    repository: RepositoryIR | None = None,
    source_snippet: str | None = None,
    issues: Sequence[IssueDict] | None = None,
    goal: str | None = None,
    llm_client: LLMClient | None = None,
) -> Tuple[str, list[IssueDict], list[PatchDict]]:
    """
    Obtain a Markdown patch explanation, issues, and structured patch plan for a module.
    """

    prompt = build_module_patch_prompt(
        module_ir,
        repository=repository,
        source_snippet=source_snippet,
        issues=issues,
        goal=goal,
    )
    return _generate_patch_and_issues(prompt, llm_client=llm_client)


def explain_module_with_issues(
    module_ir: ModuleIR,
    *,
    repository: RepositoryIR | None = None,
    source_snippet: str | None = None,
    llm_client: LLMClient | None = None,
) -> Tuple[str, list[IssueDict]]:
    """
    Obtain both the Markdown explanation and a structured list of issues for a module/file.
    """

    prompt = build_module_explanation_prompt(
        module_ir,
        repository=repository,
        source_snippet=source_snippet,
    )
    return _generate_explanation_and_issues(prompt, llm_client=llm_client)
