from __future__ import annotations

from dataclasses import dataclass, field
import ast
import difflib
from pathlib import Path
from typing import List

from .explain import _find_module_for_file, _find_repo_root_for_file
from .ir_model import FunctionIR, ModuleIR, RepositoryIR
from .toon_parse import load_repository_ir


@dataclass
class PatchResult:
    """Details about a patch that was applied or planned."""

    file: Path
    description: str
    target_function: str | None
    inserted_line: int
    inserted_text: str
    summary: str
    diff: str | None = None
    warnings: list[str] = field(default_factory=list)
    no_change: bool = False


def apply_patch_from_disk(
    file: Path,
    fix_description: str,
    strategy: str = "guard",
    target: str | None = None,
    dry_run: bool = False,
    require_fresh_ir: bool = False,
    require_target: bool = False,
) -> PatchResult:
    """CLI entrypoint: load IR from disk and apply a simple patch.

    - Finds the repository root by locating `.neurocode/ir.toon`.
    - Loads the IR.
    - Applies a minimal patch to the target file guided by the IR.
    """

    repo_root = _find_repo_root_for_file(file)
    if repo_root is None:
        raise RuntimeError(
            "Could not find .neurocode/ir.toon. Run `neurocode ir` at the repository root first."
        )

    ir_file = repo_root / ".neurocode" / "ir.toon"
    ir = load_repository_ir(ir_file)

    warnings: list[str] = []
    stale = False
    try:
        ir_mtime = ir_file.stat().st_mtime
        file_mtime = file.stat().st_mtime
        stale = ir_mtime < file_mtime
        if stale:
            msg = ".neurocode/ir.toon is older than target file; consider rerunning `neurocode ir`"
            if require_fresh_ir:
                raise RuntimeError(msg)
            warnings.append(msg)
    except OSError:
        pass
    return apply_patch(
        ir=ir,
        repo_root=repo_root,
        file=file,
        fix_description=fix_description,
        strategy=strategy,
        target=target,
        dry_run=dry_run,
        require_target=require_target,
        warnings=warnings,
    )


def apply_patch(
    ir: RepositoryIR,
    repo_root: Path,
    file: Path,
    fix_description: str,
    strategy: str = "guard",
    target: str | None = None,
    dry_run: bool = False,
    require_target: bool = False,
    warnings: list[str] | None = None,
) -> PatchResult:
    """Apply a minimal IR-informed patch to ``file`` using an in-memory IR."""

    warnings = warnings or []

    module = _find_module_for_file(ir, repo_root, file)
    if module is None:
        raise RuntimeError(
            "No module found in IR for file: "
            f"{file.resolve()} (did you run `neurocode ir` on the right root?)"
        )

    target_fn = _select_target_function(module, target)
    if target and target_fn is None:
        raise RuntimeError(
            f"Target function '{target}' not found in module {module.module_name}"
        )
    if require_target and target_fn is None:
        raise RuntimeError(f"No target function found in module {module.module_name}")

    source = file.read_text(encoding="utf-8")
    lines = source.splitlines()
    had_trailing_newline = source.endswith("\n")
    working_lines = list(lines)

    guard_inserted = False

    if strategy == "guard" and target_fn is not None:
        guard_inserted, result, inserted_text = _insert_guard_clause(
            lines=working_lines,
            target_fn=target_fn,
            fix_description=fix_description,
        )
        if guard_inserted:
            summary = f"guard inserted near {target_fn.qualified_name}"
            new_text = "\n".join(working_lines)
            if had_trailing_newline or source == "":
                new_text += "\n"
            diff_text = _render_diff(lines, working_lines, file)
            if not diff_text:
                summary = f"guard already present near {target_fn.qualified_name}"
                return PatchResult(
                    file=file,
                    description=fix_description,
                    target_function=target_fn.qualified_name,
                    inserted_line=result,
                    inserted_text=inserted_text,
                    summary=summary,
                    diff=None,
                    warnings=warnings,
                    no_change=True,
                )
            if not dry_run:
                file.write_text(new_text, encoding="utf-8")
            return PatchResult(
                file=file,
                description=fix_description,
                target_function=target_fn.qualified_name,
                inserted_line=result,
                inserted_text=inserted_text,
                summary=summary,
                diff=diff_text,
                warnings=warnings,
                no_change=False,
            )

    if strategy == "inject" and target_fn is not None:
        inserted, line_num, injected_text = _inject_stub(
            lines=working_lines,
            target_fn=target_fn,
            fix_description=fix_description,
        )
        if inserted:
            summary = f"inject stub near {target_fn.qualified_name}"
            new_text = "\n".join(working_lines)
            if had_trailing_newline or source == "":
                new_text += "\n"
            diff_text = _render_diff(lines, working_lines, file)
            if not diff_text:
                summary = f"inject already present near {target_fn.qualified_name}"
                return PatchResult(
                    file=file,
                    description=fix_description,
                    target_function=target_fn.qualified_name,
                    inserted_line=line_num,
                    inserted_text=injected_text,
                    summary=summary,
                    diff=None,
                    warnings=warnings,
                    no_change=True,
                )
            if not dry_run:
                file.write_text(new_text, encoding="utf-8")
            return PatchResult(
                file=file,
                description=fix_description,
                target_function=target_fn.qualified_name,
                inserted_line=line_num,
                inserted_text=injected_text,
                summary=summary,
                diff=diff_text,
                warnings=warnings,
                no_change=False,
            )

    # Fallback: insert a TODO at the top of the file if no guard was added.
    comment = f"# TODO(neurocode): {fix_description}"

    # If the TODO already exists, report and skip.
    for idx, line in enumerate(working_lines):
        if line.strip() == comment:
            return PatchResult(
                file=file,
                description=fix_description,
                target_function=target_fn.qualified_name if target_fn else None,
                inserted_line=idx + 1,
                inserted_text=comment,
                summary="todo already present",
                diff=None,
                warnings=warnings,
                no_change=True,
            )
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    working_lines.insert(insert_at, comment)

    summary = "todo inserted at top of file"
    new_text = "\n".join(working_lines)
    if had_trailing_newline or source == "":
        new_text += "\n"
    diff_text = _render_diff(lines, working_lines, file)
    if not dry_run:
        file.write_text(new_text, encoding="utf-8")

    return PatchResult(
        file=file,
        description=fix_description,
        target_function=target_fn.qualified_name if target_fn else None,
        inserted_line=insert_at + 1,
        inserted_text=comment,
        summary=summary,
        diff=diff_text,
        warnings=warnings,
        no_change=False,
    )


def _select_target_function(module: ModuleIR, target: str | None) -> FunctionIR | None:
    """Pick a function to anchor the patch (prefers explicit targets, then module-level)."""

    functions = module.functions

    if target:
        for fn in functions:
            if fn.qualified_name == target or fn.name == target or fn.qualified_name.endswith(target):
                return fn
        return None

    module_level: List[FunctionIR] = [fn for fn in functions if fn.parent_class_id is None]
    if module_level:
        return min(module_level, key=lambda f: f.lineno)
    if functions:
        return min(functions, key=lambda f: f.lineno)
    return None


def _insert_guard_clause(
    lines: List[str],
    target_fn: FunctionIR,
    fix_description: str,
) -> tuple[bool, int, str]:
    """Insert a simple guard clause at the top of the target function body."""

    source = "\n".join(lines) + "\n"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False, 0, ""

    func_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno == target_fn.lineno and node.name == target_fn.name:
                func_node = node
                break

    if func_node is None:
        return False, 0, ""

    # Skip property-style functions that likely shouldn't get guard clauses.
    if any(_decorator_name(dec) == "property" for dec in func_node.decorator_list):
        return False, 0, ""

    arg_name = _choose_arg_name(func_node)
    if arg_name is None:
        return False, 0, ""

    def_line_idx = target_fn.lineno - 1
    if def_line_idx < 0 or def_line_idx >= len(lines):
        return False, 0, ""

    if _has_neurocode_guard(func_node):
        return True, def_line_idx + 1, ""

    indent = lines[def_line_idx][: len(lines[def_line_idx]) - len(lines[def_line_idx].lstrip())]

    insert_at = def_line_idx + 1
    insert_at = _body_insert_index(func_node, lines, def_line_idx)

    guard_lines = [
        f"{indent}    if {arg_name} is None:",
        f'{indent}        raise ValueError("neurocode guard: {fix_description}")',
    ]

    insert_at = min(insert_at, len(lines))
    lines[insert_at:insert_at] = guard_lines

    inserted_text = "\n".join(guard_lines)
    return True, insert_at + 1, inserted_text


def _render_diff(old: List[str], new: List[str], file: Path) -> str:
    return "\n".join(
        difflib.unified_diff(
            old,
            new,
            fromfile=str(file),
            tofile=str(file),
            lineterm="",
        )
    )


def _has_neurocode_guard(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(func_node):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # Look for simple "arg is None" checks.
        if isinstance(test, ast.Compare):
            left = test.left
            comparators = test.comparators
            if isinstance(left, ast.Name) and comparators and isinstance(comparators[0], ast.Constant):
                if comparators[0].value is None:
                    # Look for ValueError with neurocode guard text.
                    for stmt in node.body:
                        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
                            func = stmt.exc.func
                            if isinstance(func, ast.Name) and func.id == "ValueError":
                                args = stmt.exc.args
                                if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                                    if "neurocode guard" in args[0].value:
                                        return True
        # Fallback: match on any string constant containing neurocode guard.
        if any(isinstance(child, ast.Constant) and isinstance(child.value, str) and "neurocode guard" in child.value for child in ast.walk(node)):
            return True
    return False


def _body_insert_index(func_node: ast.FunctionDef | ast.AsyncFunctionDef, lines: List[str], def_line_idx: int) -> int:
    insert_at = def_line_idx + 1

    if func_node.decorator_list:
        dec_end = max(getattr(dec, "end_lineno", dec.lineno) for dec in func_node.decorator_list)
        insert_at = max(insert_at, dec_end)

    if func_node.body:
        first_stmt = func_node.body[0]
        insert_at = max(insert_at, first_stmt.lineno - 1)
        if isinstance(first_stmt, ast.Expr) and isinstance(getattr(first_stmt, "value", None), ast.Constant) and isinstance(first_stmt.value.value, str):
            doc_end = getattr(first_stmt, "end_lineno", first_stmt.lineno)
            insert_at = max(insert_at, doc_end)

    while insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if stripped == "" or stripped.startswith("#"):
            insert_at += 1
            continue
        break

    return min(insert_at, len(lines))


def _choose_arg_name(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Choose a meaningful argument name to guard."""

    args = list(func_node.args.args)
    if not args:
        return None

    def _annotation_text(arg: ast.arg) -> str:
        if arg.annotation is None:
            return ""
        try:
            return ast.unparse(arg.annotation)
        except Exception:
            return ""

    def allows_none(arg: ast.arg) -> bool:
        ann_text = _annotation_text(arg)
        lowered = ann_text.lower()
        return "optional" in lowered or "none" in lowered or "any" in lowered

    candidates = [arg for arg in args if arg.arg not in {"self", "cls"}]
    annotated_none = [arg for arg in candidates if allows_none(arg)]
    if annotated_none:
        return annotated_none[0].arg
    if candidates:
        return candidates[0].arg
    return args[0].arg


def _decorator_name(dec: ast.AST) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return ""


def _inject_stub(
    lines: List[str],
    target_fn: FunctionIR,
    fix_description: str,
) -> tuple[bool, int, str]:
    """Inject a stub NotImplementedError at the top of the function."""

    source = "\n".join(lines) + "\n"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False, 0, ""

    func_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno == target_fn.lineno and node.name == target_fn.name:
                func_node = node
                break

    if func_node is None:
        return False, 0, ""

    if any(isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id == "NotImplementedError" for stmt in func_node.body):
        return True, func_node.lineno + 1, ""

    insert_at = _body_insert_index(func_node, lines, target_fn.lineno - 1)
    indent = lines[target_fn.lineno - 1][: len(lines[target_fn.lineno - 1]) - len(lines[target_fn.lineno - 1].lstrip())]
    stub_line = f'{indent}    raise NotImplementedError("neurocode inject: {fix_description}")'

    lines.insert(insert_at, stub_line)
    return True, insert_at + 1, stub_line
