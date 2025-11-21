from __future__ import annotations

from pathlib import Path

from neurocode.ir_build import build_repository_ir
from neurocode.toon_parse import load_repository_ir
from neurocode.toon_serialize import repository_ir_to_toon


def test_toon_roundtrip_preserves_structure(sample_repo: Path, tmp_path: Path) -> None:
    ir = build_repository_ir(sample_repo)

    toon_text = repository_ir_to_toon(ir)
    toon_path = tmp_path / "ir.toon"
    toon_path.write_text(toon_text, encoding="utf-8")

    parsed = load_repository_ir(toon_path)

    assert parsed.num_modules == ir.num_modules
    assert parsed.num_classes == ir.num_classes
    assert parsed.num_functions == ir.num_functions
    assert parsed.num_calls == ir.num_calls

    parsed_modules = {(m.module_name, m.path) for m in parsed.modules}
    original_modules = {(m.module_name, m.path) for m in ir.modules}
    assert parsed_modules == original_modules

    parsed_classes = {
        (module.module_name, cls.name, cls.qualified_name)
        for module in parsed.modules
        for cls in module.classes
    }
    original_classes = {
        (module.module_name, cls.name, cls.qualified_name)
        for module in ir.modules
        for cls in module.classes
    }
    assert parsed_classes == original_classes

    parsed_class_bases = {
        (module.module_name, cls.name, tuple(cls.base_names))
        for module in parsed.modules
        for cls in module.classes
    }
    original_class_bases = {
        (module.module_name, cls.name, tuple(cls.base_names))
        for module in ir.modules
        for cls in module.classes
    }
    assert parsed_class_bases == original_class_bases

    parsed_imports = {
        (
            module.module_name,
            imp.kind,
            imp.module,
            imp.name,
            imp.alias,
        )
        for module in parsed.modules
        for imp in module.imports
    }
    original_imports = {
        (
            module.module_name,
            imp.kind,
            imp.module,
            imp.name,
            imp.alias,
        )
        for module in ir.modules
        for imp in module.imports
    }
    assert parsed_imports == original_imports

    parsed_edges = {
        (edge.caller_function_id, edge.callee_function_id, edge.target)
        for edge in parsed.call_edges
    }
    original_edges = {
        (edge.caller_function_id, edge.callee_function_id, edge.target)
        for edge in ir.call_edges
    }
    assert parsed_edges == original_edges
