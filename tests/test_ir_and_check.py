from __future__ import annotations

from pathlib import Path

from neurocode.check import check_file
from neurocode.ir_build import build_repository_ir


def test_build_repository_ir_captures_structure(sample_repo: Path) -> None:
    ir = build_repository_ir(sample_repo)

    module_names = {m.module_name for m in ir.modules}
    assert module_names == {"package.mod_a", "package.mod_b", "package.classy"}

    mod_a = next(m for m in ir.modules if m.module_name == "package.mod_a")
    mod_b = next(m for m in ir.modules if m.module_name == "package.mod_b")
    classy = next(m for m in ir.modules if m.module_name == "package.classy")

    assert len(mod_a.functions) >= 13
    orchestrator = next(fn for fn in mod_a.functions if fn.name == "orchestrator")
    helper_local = next(fn for fn in mod_a.functions if fn.name == "helper_local")

    assert len(orchestrator.calls) == 15  # orchestrator fans out heavily
    assert helper_local.calls[0].target == "helper_value"

    import_entries = {(imp.kind, imp.module, imp.name) for imp in mod_a.imports}
    assert ("import", None, "math") in import_entries
    assert ("import", None, "statistics") in import_entries
    assert ("from", "package.mod_b", "run_task") in import_entries

    module_edges = {
        edge.imported_module
        for edge in ir.module_import_edges
        if edge.importer_module_id == mod_a.id
    }
    assert module_edges == {"math", "statistics", "package.mod_b"}

    run_task = next(fn for fn in mod_b.functions if fn.name == "run_task")
    helper_value = next(fn for fn in mod_b.functions if fn.name == "helper_value")
    resolved_edges = {
        edge.callee_function_id
        for edge in ir.call_edges
        if edge.caller_function_id == orchestrator.id and edge.callee_function_id is not None
    }
    assert run_task.id in resolved_edges
    assert helper_value.id in resolved_edges

    unresolved_targets = {
        edge.target
        for edge in ir.call_edges
        if edge.caller_function_id == orchestrator.id and edge.callee_function_id is None
    }
    assert any(target.startswith("math.") for target in unresolved_targets)

    processor_class = next(cls for cls in classy.classes if cls.name == "Processor")
    derived_class = next(cls for cls in classy.classes if cls.name == "Derived")
    processor_add = next(
        fn for fn in classy.functions if fn.qualified_name.endswith("Processor.add")
    )
    processor_compute = next(
        fn for fn in classy.functions if fn.qualified_name.endswith("Processor._compute")
    )
    derived_add = next(
        fn for fn in classy.functions if fn.qualified_name.endswith("Derived.add")
    )

    assert processor_add.parent_class_id == processor_class.id
    assert derived_add.parent_class_id == derived_class.id
    assert "Processor" in derived_class.base_names

    processor_edges = {
        edge.callee_function_id
        for edge in ir.call_edges
        if edge.caller_function_id == processor_add.id
    }
    assert processor_compute.id in processor_edges

    derived_edges = {
        edge.callee_function_id
        for edge in ir.call_edges
        if edge.caller_function_id == derived_add.id
    }
    assert processor_compute.id in derived_edges


def test_check_file_surfaces_unused_imports_dead_code_and_fanout(sample_repo: Path) -> None:
    ir = build_repository_ir(sample_repo)
    file_path = sample_repo / "package" / "mod_a.py"

    results = check_file(ir=ir, repo_root=sample_repo, file=file_path)

    assert any("statistics" in result.message for result in results if result.code == "UNUSED_IMPORT")
    assert any("unused_utility" in result.message for result in results if result.code == "UNUSED_IMPORT")
    assert any("package.mod_a.unused_local" in result.message for result in results if result.code == "UNUSED_FUNCTION")
    assert any("package.mod_a.orchestrator" in result.message for result in results if result.code == "HIGH_FANOUT")
