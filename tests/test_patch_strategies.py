from __future__ import annotations

from pathlib import Path

from neurocode.ir_build import build_repository_ir
from neurocode.patch import apply_patch


def test_todo_strategy_inserts_comment(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "mod_a.py"
    ir = build_repository_ir(sample_repo)

    result = apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="note for later",
        strategy="todo",
    )

    contents = file_path.read_text(encoding="utf-8")
    comment = "# TODO(neurocode): note for later  # neurocode:todo"
    assert comment in contents
    assert result.inserted_text == comment


def test_target_selection_by_name(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "classy.py"
    ir = build_repository_ir(sample_repo)

    result = apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="guard derived add",
        strategy="guard",
        target="Derived.add",
    )

    contents = file_path.read_text(encoding="utf-8")
    assert "neurocode guard: guard derived add" in contents
    assert "Derived.add" in (result.target_function or "")


def test_guard_skips_property_and_falls_back_to_todo(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "classy.py"
    file_path.write_text(
        "class Holder:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n"
    )
    ir = build_repository_ir(sample_repo)

    result = apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="property skip",
        strategy="guard",
        target="Holder.value",
    )

    contents = file_path.read_text(encoding="utf-8")
    assert "# TODO(neurocode): property skip" in contents
    assert "neurocode guard" not in contents
    assert result.summary.startswith("todo")


def test_guard_noop_when_already_present(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "mod_b.py"
    ir = build_repository_ir(sample_repo)

    apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="initial",
        strategy="guard",
        target="run_task",
    )
    contents_after_first = file_path.read_text(encoding="utf-8")
    assert "neurocode guard: initial" in contents_after_first

    second = apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="initial",
        strategy="guard",
        target="run_task",
    )

    contents_after_second = file_path.read_text(encoding="utf-8")
    assert contents_after_second == contents_after_first
    assert "already present" in second.summary
    assert second.diff is None
    assert second.no_change is True


def test_target_not_found_raises(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "mod_b.py"
    ir = build_repository_ir(sample_repo)

    try:
        apply_patch(
            ir=ir,
            repo_root=sample_repo,
            file=file_path,
            fix_description="missing",
            strategy="guard",
            target="missing_function",
        )
    except RuntimeError as exc:
        assert "Target function 'missing_function' not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError for missing target")


def test_require_target_raises_on_module_without_functions(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "nofunc.py"
    file_path.write_text("VALUE = 1\n")
    ir = build_repository_ir(sample_repo)

    try:
        apply_patch(
            ir=ir,
            repo_root=sample_repo,
            file=file_path,
            fix_description="no funcs",
            strategy="todo",
            require_target=True,
        )
    except RuntimeError as exc:
        assert "No target function found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError for missing target function")


def test_guard_inserts_after_docstring_and_blanks(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "docstring_mod.py"
    file_path.write_text(
        "def doc_fn(x):\n"
        "    \"\"\"doc\"\"\"\n"
        "    \n"
        "    # leading comment\n"
        "    return x\n"
    )
    ir = build_repository_ir(sample_repo)

    apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="doc guard",
        strategy="guard",
        target="doc_fn",
    )

    contents = file_path.read_text(encoding="utf-8")
    assert '"""doc"""' in contents
    guard_index = contents.index("neurocode guard: doc guard")
    assert guard_index > contents.index('"""doc"""')


def test_guard_in_decorated_function(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "decorated.py"
    file_path.write_text(
        "@decorate\n"
        "def deco_fn(x):\n"
        '    """docstring"""  \n'
        "    return x\n"
    )
    ir = build_repository_ir(sample_repo)

    apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="decorated guard",
        strategy="guard",
        target="deco_fn",
    )

    contents = file_path.read_text(encoding="utf-8")
    assert "neurocode guard: decorated guard" in contents
    assert contents.index("neurocode guard: decorated guard") > contents.index('"""docstring"""')


def test_guard_in_multi_line_decorator(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "decorated2.py"
    file_path.write_text(
        "@decorator(\n"
        "    option=True,\n"
        ")\n"
        "def fancy(x):\n"
        "    return x\n"
    )
    ir = build_repository_ir(sample_repo)

    apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="multi deco guard",
        strategy="guard",
        target="fancy",
    )

    contents = file_path.read_text(encoding="utf-8")
    assert "neurocode guard: multi deco guard" in contents
    assert contents.index("neurocode guard: multi deco guard") > contents.index("decorator(")


def test_inject_strategy_inserts_stub(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "mod_b.py"
    ir = build_repository_ir(sample_repo)

    result = apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="inject stub",
        strategy="inject",
        target="helper_value",
    )

    contents = file_path.read_text(encoding="utf-8")
    assert "NotImplementedError(\"neurocode inject: inject stub\")" in contents
    assert result.summary.startswith("inject stub")
    assert result.no_change is False


def test_inject_logging_strategy_with_custom_message(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "mod_b.py"
    ir = build_repository_ir(sample_repo)

    result = apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="inject log default",
        strategy="inject",
        inject_kind="log",
        inject_message="custom log",
        target="run_task",
    )

    contents = file_path.read_text(encoding="utf-8")
    assert 'logging.debug("neurocode inject: custom log")' in contents
    assert result.no_change is False


def test_inject_noop_when_present(sample_repo: Path) -> None:
    file_path = sample_repo / "package" / "mod_b.py"
    file_path.write_text(
        "def foo(x):\n"
        "    raise NotImplementedError(\"neurocode inject: inject stub\")\n"
        "    return x\n"
    )
    ir = build_repository_ir(sample_repo)

    result = apply_patch(
        ir=ir,
        repo_root=sample_repo,
        file=file_path,
        fix_description="inject stub",
        strategy="inject",
        target="foo",
    )

    assert result.no_change is True
    assert "inject already present" in result.summary
