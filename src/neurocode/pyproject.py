from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import tomllib


def load_console_scripts(repo_root: Path) -> List[Tuple[str, str]]:
    """Extract console script entrypoints from pyproject.toml."""

    path = repo_root / "pyproject.toml"
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    project = data.get("project") or {}
    scripts = project.get("scripts") or project.get("entry-points") or {}
    entries: List[Tuple[str, str]] = []
    for name, target in scripts.items():
        if isinstance(name, str) and isinstance(target, str):
            entries.append((name, target))
    return entries
