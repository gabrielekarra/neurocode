from __future__ import annotations

from neurocode.ir_build import build_repository_ir


def test_call_graph_has_symbol_ids_and_cross_module_edges(sample_repo) -> None:
    ir = build_repository_ir(sample_repo)

    functions = {fn.symbol_id: fn for module in ir.modules for fn in module.functions}

    orchestrator_id = "package.mod_a:orchestrator"
    helper_id = "package.mod_b:helper_value"

    assert orchestrator_id in functions
    assert helper_id in functions

    # entry pseudo-symbol anchors module-level execution
    assert "package.mod_a:<module>" in functions

    edges = [
        (edge.caller_symbol_id, edge.callee_symbol_id)
        for edge in ir.call_edges
        if edge.caller_symbol_id == orchestrator_id
    ]
    assert (orchestrator_id, helper_id) in edges
