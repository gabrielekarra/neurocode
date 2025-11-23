from __future__ import annotations

from pathlib import Path

from neurocode.embedding_text import build_embedding_documents
from neurocode.ir_build import build_repository_ir


def test_embedding_documents_include_calls(sample_repo: Path) -> None:
    ir = build_repository_ir(sample_repo)
    docs = build_embedding_documents(ir)
    by_id = {d.id: d for d in docs}
    orchestrator = by_id["package.mod_a.orchestrator"]
    assert "calls:" in orchestrator.text
    assert "package.mod_b.run_task" in orchestrator.text
    assert orchestrator.file == "package/mod_a.py"
