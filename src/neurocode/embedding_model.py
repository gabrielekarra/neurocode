from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List


def _escape_value(value: str) -> str:
    value = value.replace("\n", "\\n")
    value = value.replace(",", "\\,")
    return value


def _unescape_value(value: str) -> str:
    value = value.replace("\\,", ",")
    value = value.replace("\\n", "\n")
    return value


def _parse_row(line: str) -> List[str]:
    fields: List[str] = []
    current: List[str] = []
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


def _parse_table_header(line: str) -> tuple[str, List[str]]:
    line = line.strip()
    name_part, rest = line.split("[", 1)
    name = name_part.strip()
    _, rest_after_bracket = rest.split("]", 1)
    brace_start = rest_after_bracket.index("{")
    brace_end = rest_after_bracket.index("}")
    fields_str = rest_after_bracket[brace_start + 1 : brace_end]
    fields = [field.strip() for field in fields_str.split(",") if field.strip()]
    return name, fields


@dataclass
class EmbeddingItem:
    kind: str
    id: str
    module: str
    name: str
    file: str
    lineno: int
    signature: str
    docstring: str | None
    text: str
    embedding: List[float] = field(default_factory=list)


@dataclass
class EmbeddingStore:
    version: int
    engine_version: str
    model: str
    created_at: str
    repo_root: Path
    items: List[EmbeddingItem] = field(default_factory=list)

    @classmethod
    def new(cls, repo_root: Path, engine_version: str, model: str, version: int = 1) -> "EmbeddingStore":
        return cls(
            version=version,
            engine_version=engine_version,
            model=model,
            created_at=datetime.now(timezone.utc).isoformat(),
            repo_root=repo_root,
            items=[],
        )


def embedding_store_to_toon(store: EmbeddingStore) -> str:
    lines: List[str] = []
    lines.append("store:")
    lines.append(f"  version: {store.version}")
    lines.append(f"  engine_version: {store.engine_version}")
    lines.append(f"  model: {store.model}")
    lines.append(f"  created_at: {store.created_at}")
    lines.append(f"  repo_root: {store.repo_root}")
    lines.append(f"  num_items: {len(store.items)}")
    lines.append("")

    lines.append(
        "items[{n}]{{kind,id,module,name,file,lineno,signature,docstring,text,embedding}}:".format(
            n=len(store.items)
        )
    )
    for item in store.items:
        emb_str = "|".join(f"{v:.6f}" for v in item.embedding)
        doc = "" if item.docstring is None else item.docstring
        row = ",".join(
            [
                _escape_value(item.kind),
                _escape_value(item.id),
                _escape_value(item.module),
                _escape_value(item.name),
                _escape_value(item.file),
                str(item.lineno),
                _escape_value(item.signature),
                _escape_value(doc),
                _escape_value(item.text),
                _escape_value(emb_str),
            ]
        )
        lines.append(f"  {row}")
    lines.append("")
    return "\n".join(lines)


def embedding_store_from_toon(text: str) -> EmbeddingStore:
    lines = text.splitlines()
    in_header = False
    current_table: str | None = None
    current_fields: List[str] = []
    tables: dict[str, List[dict[str, str]]] = {}
    header: dict[str, str] = {}

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not stripped:
            if in_header:
                in_header = False
            continue

        if stripped == "store:":
            in_header = True
            current_table = None
            continue

        if in_header and ":" in stripped and not stripped.startswith("items"):
            key, value = stripped.split(":", 1)
            header[key.strip()] = value.strip()
            continue

        if not line.startswith(" ") and "[" in line and "{" in line and line.endswith(":"):
            table_name, fields = _parse_table_header(line)
            current_table = table_name
            current_fields = fields
            tables.setdefault(table_name, [])
            continue

        if current_table is not None and line.startswith(" "):
            values = _parse_row(line.strip())
            row: dict[str, str] = {}
            for i, field in enumerate(current_fields):
                row[field] = values[i] if i < len(values) else ""
            tables[current_table].append(row)

    if "repo_root" not in header:
        raise ValueError("TOON embedding store missing repo_root")

    store = EmbeddingStore(
        version=int(header.get("version", "1")),
        engine_version=header.get("engine_version", ""),
        model=header.get("model", ""),
        created_at=header.get("created_at", ""),
        repo_root=Path(header["repo_root"]),
        items=[],
    )

    items_table = tables.get("items", [])
    for row in items_table:
        emb_raw = _unescape_value(row.get("embedding", ""))
        emb = []
        if emb_raw:
            emb = [float(v) for v in emb_raw.split("|") if v]
        doc = _unescape_value(row.get("docstring", ""))
        item = EmbeddingItem(
            kind=_unescape_value(row["kind"]),
            id=_unescape_value(row["id"]),
            module=_unescape_value(row["module"]),
            name=_unescape_value(row["name"]),
            file=_unescape_value(row["file"]),
            lineno=int(row["lineno"]),
            signature=_unescape_value(row["signature"]),
            docstring=doc or None,
            text=_unescape_value(row["text"]),
            embedding=emb,
        )
        store.items.append(item)
    return store


def load_embedding_store(path: Path) -> EmbeddingStore:
    text = path.read_text(encoding="utf-8")
    return embedding_store_from_toon(text)


def save_embedding_store(store: EmbeddingStore, path: Path) -> None:
    path.write_text(embedding_store_to_toon(store), encoding="utf-8")
