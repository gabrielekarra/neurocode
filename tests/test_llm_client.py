from __future__ import annotations

from pathlib import Path

import pytest

from neurocode.ir_model import CallIR, FunctionIR, ModuleIR, RepositoryIR
from neurocode.llm_client import LLMClient, LLMError
from neurocode.symbol_explainer import build_symbol_explanation_prompt, explain_symbol_with_llm


def _sample_ir():
    target_fn = FunctionIR(
        id=1,
        module_id=1,
        name="add",
        qualified_name="sample.mod.add",
        lineno=3,
        signature="add(a: int, b: int) -> int",
        docstring="Add two integers and return the sum.",
        module="sample.mod",
        symbol_id="sample.mod:add",
        kind="function",
        calls=[CallIR(lineno=5, target="helper(a, b)")],
    )
    helper_fn = FunctionIR(
        id=2,
        module_id=1,
        name="helper",
        qualified_name="sample.mod.helper",
        lineno=10,
        signature="helper(a: int, b: int) -> int",
        docstring=None,
        module="sample.mod",
        symbol_id="sample.mod:helper",
        kind="function",
        calls=[],
    )
    module = ModuleIR(
        id=1,
        path=Path("sample/mod.py"),
        module_name="sample.mod",
        functions=[target_fn, helper_fn],
        classes=[],
    )
    repo = RepositoryIR(root=Path("/repo"), modules=[module])
    return target_fn, helper_fn, module, repo


def test_llm_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMError):
        LLMClient()


def test_build_symbol_explanation_prompt_handles_ir() -> None:
    target_fn, helper_fn, module, repo = _sample_ir()
    prompt = build_symbol_explanation_prompt(
        target_fn,
        module=module,
        repository=repo,
        related_symbols=[helper_fn],
        source_snippet="def add(a, b):\n    return helper(a, b)",
    )

    assert "You are an assistant explaining Python code" in prompt
    assert "sample/mod.py" in prompt
    assert "helper" in prompt  # related symbol included
    assert "Source snippet:" in prompt
    assert "add(a: int, b: int)" in prompt


def test_explain_symbol_with_llm_uses_client() -> None:
    target_fn, helper_fn, module, repo = _sample_ir()

    class DummyClient:
        def __init__(self) -> None:
            self.last_prompt = None

        def generate(self, prompt: str) -> str:
            self.last_prompt = prompt
            return "explanation"

    client = DummyClient()
    result = explain_symbol_with_llm(
        target_fn,
        module=module,
        repository=repo,
        related_symbols=[helper_fn],
        source_snippet="def add(a, b):\n    return helper(a, b)",
        llm_client=client,
    )

    assert result == "explanation"
    assert client.last_prompt is not None
    assert "Target symbol" in client.last_prompt
