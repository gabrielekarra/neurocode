from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List


@dataclass
class PatchHistoryEntry:
    id: str
    timestamp: str
    fix: str
    files_changed: List[str]
    is_noop: bool
    summary: str
    warnings: List[str] = field(default_factory=list)
    plan_id: str | None = None


@dataclass
class PatchHistory:
    entries: List[PatchHistoryEntry]


def _history_path(repo_root: Path) -> Path:
    return repo_root / ".neurocode" / "patch-history.toon"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def history_to_toon(history: PatchHistory) -> str:
    lines: list[str] = []
    lines.append("patch_history:")
    lines.append(f"  count: {len(history.entries)}")
    lines.append("")
    lines.append(
        f"entries[{len(history.entries)}]{{id,timestamp,fix,files_changed,is_noop,summary,warnings,plan_id}}:"
    )
    for entry in history.entries:
        files = "|".join(entry.files_changed)
        warns = "|".join(entry.warnings)
        plan_id = entry.plan_id or ""
        row = ",".join(
            [
                entry.id,
                entry.timestamp,
                entry.fix.replace(",", "\\,").replace("\n", "\\n"),
                files.replace(",", "\\,").replace("\n", "\\n"),
                "1" if entry.is_noop else "0",
                entry.summary.replace(",", "\\,").replace("\n", "\\n"),
                warns.replace(",", "\\,").replace("\n", "\\n"),
                plan_id,
            ]
        )
        lines.append(f"  {row}")
    lines.append("")
    return "\n".join(lines)


def history_from_toon(text: str) -> PatchHistory:
    lines = text.splitlines()
    entries: list[PatchHistoryEntry] = []
    current_table: str | None = None
    fields: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("entries["):
            current_table = "entries"
            braces_start = line.index("{")
            braces_end = line.index("}")
            fields = [f.strip() for f in line[braces_start + 1 : braces_end].split(",")]
            continue
        if current_table == "entries" and raw.startswith(" "):
            values = _parse_row(raw.strip())
            row = {fields[i]: values[i] if i < len(values) else "" for i in range(len(fields))}
            files = [f for f in row["files_changed"].split("|") if f]
            warnings = [w for w in row["warnings"].split("|") if w]
            entry = PatchHistoryEntry(
                id=row["id"],
                timestamp=row["timestamp"],
                fix=_unescape(row["fix"]),
                files_changed=files,
                is_noop=row["is_noop"] == "1",
                summary=_unescape(row["summary"]),
                warnings=[_unescape(w) for w in warnings],
                plan_id=row.get("plan_id") or None,
            )
            entries.append(entry)
    return PatchHistory(entries=entries)


def _parse_row(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ",":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def _unescape(value: str) -> str:
    return value.replace("\\,", ",").replace("\\n", "\n")


def load_patch_history(repo_root: Path) -> PatchHistory:
    path = _history_path(repo_root)
    if not path.exists():
        return PatchHistory(entries=[])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return PatchHistory(entries=[])
    return history_from_toon(text)


def save_patch_history(repo_root: Path, history: PatchHistory) -> None:
    path = _history_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(history_to_toon(history), encoding="utf-8")


def append_patch_history(
    repo_root: Path,
    *,
    fix: str,
    files_changed: list[str],
    is_noop: bool,
    summary: str,
    warnings: list[str] | None = None,
    plan_id: str | None = None,
) -> None:
    history = load_patch_history(repo_root)
    entry = PatchHistoryEntry(
        id=_now_iso(),
        timestamp=_now_iso(),
        fix=fix,
        files_changed=files_changed,
        is_noop=is_noop,
        summary=summary,
        warnings=warnings or [],
        plan_id=plan_id,
    )
    history.entries.append(entry)
    try:
        save_patch_history(repo_root, history)
    except Exception:
        # non-fatal
        return
