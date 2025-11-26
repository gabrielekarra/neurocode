from __future__ import annotations

from fastapi.testclient import TestClient

from neurocode.llm_client import LLMError
from neurocode.server import create_app


class DummyLLM:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.seen_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.seen_prompt = prompt
        if self.fail:
            raise LLMError("LLM unavailable")
        return "mock explanation"


def test_health_endpoint(sample_repo) -> None:
    app = create_app(default_project_root=sample_repo, llm_client=DummyLLM())
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_explain_symbol_endpoint_success(sample_repo) -> None:
    app = create_app(default_project_root=sample_repo, llm_client=DummyLLM())
    client = TestClient(app)

    resp = client.post(
        "/explain_symbol",
        json={"path": "package/mod_a.py", "line": 10, "column": 1},
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["explanation"] == "mock explanation"
    assert "orchestrator" in payload["symbol"]["qualified_name"]
    assert payload["module"]["module_name"] == "package.mod_a"
    assert payload["range"]["start"] <= payload["range"]["end"]


def test_explain_symbol_llm_error(sample_repo) -> None:
    app = create_app(default_project_root=sample_repo, llm_client=DummyLLM(fail=True))
    client = TestClient(app)

    resp = client.post(
        "/explain_symbol",
        json={"path": "package/mod_a.py", "line": 10, "column": 1},
    )

    assert resp.status_code == 503
    assert "LLM unavailable" in resp.json()["detail"]
