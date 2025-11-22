from __future__ import annotations

from pathlib import Path
from typing import List

from .check import CheckResult, check_file
from .config import Config, load_config
from .explain import explain_file, explain_file_from_disk
from .ir_build import build_repository_ir
from .ir_model import RepositoryIR
from .patch import PatchResult, apply_patch, apply_patch_from_disk
from .toon_parse import load_repository_ir

__all__ = [
    "load_ir",
    "build_ir",
    "explain_file",
    "explain_file_from_disk",
    "run_checks",
    "plan_patch",
    "apply_patch_from_disk",
]


def build_ir(root: Path) -> RepositoryIR:
    """Build a RepositoryIR from a repository root."""

    return build_repository_ir(root)


def load_ir(ir_path: Path) -> RepositoryIR:
    """Load a RepositoryIR from a TOON file."""

    return load_repository_ir(ir_path)


def run_checks(
    ir: RepositoryIR,
    repo_root: Path,
    file: Path,
    config: Config | None = None,
) -> List[CheckResult]:
    """Run checks on a file using an in-memory IR."""

    cfg = config or load_config(repo_root)
    return check_file(ir=ir, repo_root=repo_root, file=file, config=cfg)


def plan_patch(
    ir: RepositoryIR,
    repo_root: Path,
    file: Path,
    fix_description: str,
    **kwargs,
) -> PatchResult:
    """Apply a patch to a file using an in-memory IR."""

    return apply_patch(
        ir=ir,
        repo_root=repo_root,
        file=file,
        fix_description=fix_description,
        **kwargs,
    )
