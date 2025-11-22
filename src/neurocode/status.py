from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
import json

from .config import Config, load_config
from .ir_build import compute_file_hash
from .ir_model import ModuleIR, RepositoryIR
from .toon_parse import load_repository_ir


@dataclass
class ModuleStatus:
    module: ModuleIR
    status: str  # fresh|stale|missing|unknown
    reason: str | None = None


def _compute_module_status(ir: RepositoryIR) -> List[ModuleStatus]:
    statuses: List[ModuleStatus] = []
    for module in ir.modules:
        curr_path = (ir.root / module.path).resolve()
        if not curr_path.exists():
            statuses.append(ModuleStatus(module=module, status="missing", reason=f"missing file {curr_path}"))
            continue
        if not module.file_hash:
            statuses.append(ModuleStatus(module=module, status="unknown", reason="no file hash in IR"))
            continue
        try:
            current_hash = compute_file_hash(curr_path)
        except OSError:
            statuses.append(ModuleStatus(module=module, status="missing", reason=f"cannot read file {curr_path}"))
            continue
        if current_hash == module.file_hash:
            statuses.append(ModuleStatus(module=module, status="fresh", reason=None))
        else:
            statuses.append(ModuleStatus(module=module, status="stale", reason="hash mismatch"))
    return statuses


def status_from_disk(root: Path, output_format: str = "text") -> Tuple[str, int]:
    root = root.resolve()
    ir_file = root / ".neurocode" / "ir.toon"
    if not ir_file.is_file():
        msg = f"[neurocode] error: {ir_file} not found. Run `neurocode ir {root}` first."
        return msg, 1

    ir = load_repository_ir(ir_file)
    config = load_config(root)
    return render_status(ir, config, output_format=output_format)


def render_status(ir: RepositoryIR, config: Config, output_format: str = "text") -> Tuple[str, int]:
    statuses = _compute_module_status(ir)
    counts = {"fresh": 0, "stale": 0, "missing": 0, "unknown": 0}
    for st in statuses:
        counts[st.status] = counts.get(st.status, 0) + 1

    exit_code = 0 if counts.get("stale", 0) == 0 and counts.get("missing", 0) == 0 else 1

    if output_format == "json":
        payload = {
            "root": str(ir.root),
            "build_timestamp": ir.build_timestamp,
            "counts": counts,
            "modules": [
                {
                    "module": st.module.module_name,
                    "path": str(st.module.path),
                    "status": st.status,
                    "reason": st.reason,
                }
                for st in statuses
            ],
            "config": {
                "fanout_threshold": config.fanout_threshold,
                "long_function_threshold": config.long_function_threshold,
                "enabled_checks": sorted(config.enabled_checks),
                "severity_overrides": config.severity_overrides,
            },
        }
        return json.dumps(payload, indent=2), exit_code

    lines: List[str] = []
    lines.append(f"[neurocode] IR status for {ir.root}")
    if ir.build_timestamp:
        lines.append(f"build_timestamp: {ir.build_timestamp}")
    lines.append(
        f"modules: total={len(statuses)} fresh={counts.get('fresh',0)} stale={counts.get('stale',0)} "
        f"missing={counts.get('missing',0)} unknown={counts.get('unknown',0)}"
    )
    if any(st.status != "fresh" for st in statuses):
        lines.append("issues:")
        for st in statuses:
            if st.status == "fresh":
                continue
            reason = f" ({st.reason})" if st.reason else ""
            lines.append(f"  - {st.module.module_name}: {st.status}{reason}")
    lines.append("config:")
    lines.append(f"  fanout_threshold: {config.fanout_threshold}")
    lines.append(f"  long_function_threshold: {config.long_function_threshold}")
    lines.append(f"  enabled_checks: {', '.join(sorted(config.enabled_checks))}")
    if config.severity_overrides:
        overrides = ", ".join(f"{k}={v}" for k, v in config.severity_overrides.items())
        lines.append(f"  severity_overrides: {overrides}")
    else:
        lines.append("  severity_overrides: (none)")
    return "\n".join(lines), exit_code
