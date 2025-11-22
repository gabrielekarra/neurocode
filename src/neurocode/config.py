from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set

import tomllib


@dataclass
class Config:
    fanout_threshold: int = 10
    long_function_threshold: int = 50
    enabled_checks: Set[str] = field(
        default_factory=lambda: {
            "UNUSED_IMPORT",
            "UNUSED_FUNCTION",
            "HIGH_FANOUT",
            "UNUSED_PARAM",
            "LONG_FUNCTION",
            "CALL_CYCLE",
            "UNUSED_RETURN",
            "IMPORT_CYCLE",
        }
    )
    severity_overrides: Dict[str, str] = field(default_factory=dict)

    def severity_for(self, code: str, default: str) -> str:
        return self.severity_overrides.get(code, default)


def load_config(repo_root: Path) -> Config:
    """Load configuration from .neurocoderc or pyproject.toml."""

    repo_root = repo_root.resolve()
    config = Config()

    # .neurocoderc takes precedence.
    rc_path = repo_root / ".neurocoderc"
    if rc_path.is_file():
        data = _load_toml(rc_path)
        _apply_config_data(config, data)
        return config

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        data = _load_toml(pyproject)
        tool_section = data.get("tool", {}).get("neurocode")
        if tool_section:
            _apply_config_data(config, tool_section)
    return config


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _apply_config_data(config: Config, data: dict) -> None:
    fanout = data.get("fanout_threshold")
    if isinstance(fanout, int) and fanout > 0:
        config.fanout_threshold = fanout

    long_fn = data.get("long_function_threshold")
    if isinstance(long_fn, int) and long_fn > 0:
        config.long_function_threshold = long_fn

    enabled = data.get("enabled_checks")
    if isinstance(enabled, list):
        config.enabled_checks = {str(item) for item in enabled if isinstance(item, str)}

    severity = data.get("severity_overrides")
    if isinstance(severity, dict):
        for k, v in severity.items():
            if isinstance(k, str) and isinstance(v, str):
                config.severity_overrides[k] = v.upper()
