from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .ir_model import FunctionIR, RepositoryIR


@dataclass
class EmbeddingDocument:
    id: str
    module: str
    name: str
    file: str
    lineno: int
    signature: str
    docstring: str | None
    text: str


def build_embedding_documents(repository_ir: RepositoryIR) -> List[EmbeddingDocument]:
    """Build deterministic embedding documents from the structural IR."""

    docs: List[EmbeddingDocument] = []

    fn_by_id: Dict[int, FunctionIR] = {}
    for module in repository_ir.modules:
        for fn in module.functions:
            fn_by_id[fn.id] = fn

    outgoing: Dict[int, List[str]] = {}
    for edge in repository_ir.call_edges:
        caller = edge.caller_function_id
        if caller not in outgoing:
            outgoing[caller] = []
        if edge.callee_function_id is not None and edge.callee_function_id in fn_by_id:
            outgoing[caller].append(fn_by_id[edge.callee_function_id].qualified_name)
        else:
            outgoing[caller].append(edge.target)

    for module in sorted(repository_ir.modules, key=lambda m: m.module_name):
        for fn in sorted(
            [f for f in module.functions if f.kind != "module"],
            key=lambda f: f.lineno,
        ):
            signature = f"def {fn.qualified_name}(...)"  # args not in IR; placeholder
            docstring = None
            calls = sorted(set(outgoing.get(fn.id, [])))

            lines = [
                f"module: {module.module_name}",
                f"function: {fn.qualified_name}",
                f"lineno: {fn.lineno}",
                f"signature: {signature}",
            ]
            if docstring:
                lines.append(f"docstring: {docstring}")
            if calls:
                lines.append("calls: " + ", ".join(calls))

            canonical_text = "\n".join(lines)

            docs.append(
                EmbeddingDocument(
                    id=fn.symbol_id or fn.qualified_name,
                    module=module.module_name,
                    name=fn.name,
                    file=str(module.path),
                    lineno=fn.lineno,
                    signature=signature,
                    docstring=docstring,
                    text=canonical_text,
                )
            )

    return docs
