from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .check import check_file
from .config import load_config
from .embedding_model import EmbeddingItem, EmbeddingStore, save_embedding_store
from .embedding_provider import make_embedding_provider
from .embedding_text import build_embedding_documents
from .explain import _find_module_for_file, _find_repo_root_for_file
from .explain_llm import build_explain_llm_bundle
from .history_model import append_patch_history, load_patch_history
from .ir_build import build_repository_ir
from .ir_model import RepositoryIR
from .patch import apply_patch_from_disk, apply_patch_plan_from_disk
from .plan_patch_llm import build_patch_plan_bundle
from .search import (
    build_query_embedding_from_symbol,
    build_query_embedding_from_text,
    search_embeddings,
)
from .status import _compute_module_status
from .toon_parse import load_repository_ir
from .toon_serialize import repository_ir_to_toon


class NeurocodeError(Exception):
    """Base exception for all NeuroCode library errors."""


class IRNotFoundError(NeurocodeError):
    """Raised when .neurocode/ir.toon is missing and IR is required."""


class EmbeddingsNotFoundError(NeurocodeError):
    """Raised when .neurocode/ir-embeddings.toon is missing and embeddings are required."""


class ConfigError(NeurocodeError):
    """Raised when NeuroCode configuration is invalid or incomplete."""


class PatchPlanError(NeurocodeError):
    """Raised when a patch plan JSON is invalid or cannot be applied."""


class SymbolNotFoundError(NeurocodeError):
    """Raised when a requested symbol cannot be resolved in the IR."""


@dataclass
class BuildIRResult:
    repo_root: Path
    ir_path: Path
    modules: int
    functions: int
    calls: int
    fresh: bool


@dataclass
class StatusResult:
    repo_root: Path
    ir_exists: bool
    ir_fresh: bool
    ir_timestamp: str | None
    embeddings_exists: bool
    embeddings_model: str | None
    embeddings_provider: str | None


@dataclass
class ExplainResult:
    repo_root: Path
    file: Path
    module: str
    imports: list[dict[str, Any]]
    functions: list[dict[str, Any]]
    classes: list[dict[str, Any]]


@dataclass
class CheckResult:
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    message: str
    file: Path
    lineno: int | None


@dataclass
class SearchResult:
    id: str
    kind: Literal["function", "module", "class"]
    module: str
    name: str
    file: Path
    lineno: int | None
    signature: str | None
    score: float


@dataclass
class PatchPlan:
    data: Mapping[str, Any]


@dataclass
class PatchApplyResult:
    repo_root: Path
    files_changed: list[Path]
    diff: str | None
    is_noop: bool
    summary: str | None = None
    warnings: list[str] | None = None
    status: str | None = None
    target_function: str | None = None
    inserted_line: int | None = None
    inserted_text: str | None = None


@dataclass
class PatchHistoryEntryResult:
    id: str
    timestamp: str
    fix: str
    files_changed: list[str]
    is_noop: bool
    summary: str
    warnings: list[str]
    plan_id: str | None = None


def open_project(path: Path | str = ".") -> "NeurocodeProject":
    path = Path(path).resolve()
    if path.is_file():
        repo_root = _find_repo_root_for_file(path)
    else:
        repo_root = None
        for directory in (path, *path.parents):
            if (directory / ".neurocode" / "ir.toon").is_file():
                repo_root = directory
                break
    if repo_root is None:
        raise IRNotFoundError("Could not find .neurocode/ir.toon; run `neurocode ir` first.")
    return NeurocodeProject(repo_root)


class NeurocodeProject:
    """High-level, library-friendly interface to a NeuroCode-enabled repository."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.config = load_config(self.repo_root)

    # IR / status ---------------------------------------------------------
    def build_ir(self, *, force: bool = False) -> BuildIRResult:
        ir_path = self.repo_root / ".neurocode" / "ir.toon"
        ir_path.parent.mkdir(parents=True, exist_ok=True)
        if ir_path.exists() and not force:
            ir = load_repository_ir(ir_path)
            statuses = _compute_module_status(ir)
            if all(st.status == "fresh" for st in statuses):
                return BuildIRResult(
                    repo_root=self.repo_root,
                    ir_path=ir_path,
                    modules=ir.num_modules,
                    functions=ir.num_functions,
                    calls=ir.num_calls,
                    fresh=True,
                )
        ir = build_repository_ir(self.repo_root)
        ir_path.write_text(repository_ir_to_toon(ir), encoding="utf-8")
        statuses = _compute_module_status(ir)
        return BuildIRResult(
            repo_root=self.repo_root,
            ir_path=ir_path,
            modules=ir.num_modules,
            functions=ir.num_functions,
            calls=ir.num_calls,
            fresh=all(st.status == "fresh" for st in statuses),
        )

    def status(self) -> StatusResult:
        ir_path = self.repo_root / ".neurocode" / "ir.toon"
        emb_path = self.repo_root / ".neurocode" / "ir-embeddings.toon"
        ir_exists = ir_path.is_file()
        ir_fresh = False
        ir_timestamp = None
        if ir_exists:
            try:
                ir = load_repository_ir(ir_path)
                module_statuses = _compute_module_status(ir)
                ir_fresh = all(st.status == "fresh" for st in module_statuses)
                ir_timestamp = getattr(ir, "build_timestamp", None)
            except Exception:
                ir_exists = False
        embeddings_exists = emb_path.is_file()
        model = provider = None
        if embeddings_exists:
            try:
                from .embedding_model import load_embedding_store

                store = load_embedding_store(emb_path)
                model = store.model
                provider = store.provider
            except Exception:
                embeddings_exists = False
        return StatusResult(
            repo_root=self.repo_root,
            ir_exists=ir_exists,
            ir_fresh=ir_fresh,
            ir_timestamp=ir_timestamp,
            embeddings_exists=embeddings_exists,
            embeddings_model=model,
            embeddings_provider=provider,
        )

    # Embeddings ---------------------------------------------------------
    def ensure_embeddings(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        update: bool = False,
    ) -> None:
        ir_path = self.repo_root / ".neurocode" / "ir.toon"
        if not ir_path.is_file():
            raise IRNotFoundError("IR not found; run build_ir first.")
        ir = load_repository_ir(ir_path)
        try:
            provider_obj, provider_name, model_name = make_embedding_provider(
                self.config,
                provider_override=provider,
                model_override=model,
                allow_dummy=(provider == "dummy") or self.config.embedding_allow_dummy,
            )
        except Exception as exc:
            raise ConfigError(str(exc)) from exc
        docs = build_embedding_documents(ir)
        vectors = provider_obj.embed_batch([doc.text for doc in docs])
        if len(vectors) != len(docs):
            raise EmbeddingsNotFoundError("Provider returned mismatched embedding count")
        from . import __version__

        store = EmbeddingStore.new(
            repo_root=self.repo_root,
            engine_version=__version__,
            model=model_name,
            provider=provider_name,
        )
        store.items = []
        for doc, vec in zip(docs, vectors):
            store.items.append(
                EmbeddingItem(
                    kind="function",
                    id=doc.id,
                    module=doc.module,
                    name=doc.name,
                    file=doc.file,
                    lineno=doc.lineno,
                    signature=doc.signature,
                    docstring=doc.docstring,
                    text=doc.text,
                    embedding=vec,
                )
            )
        emb_path = self.repo_root / ".neurocode" / "ir-embeddings.toon"
        emb_path.parent.mkdir(parents=True, exist_ok=True)
        if update and emb_path.exists():
            from .embedding_model import load_embedding_store as _les

            existing = _les(emb_path)
            if existing.model and existing.model != model_name:
                raise ConfigError(f"Existing embeddings use model '{existing.model}'")
            if existing.provider and existing.provider != provider_name:
                raise ConfigError(f"Existing embeddings use provider '{existing.provider}'")
            merged = {item.id: item for item in existing.items}
            for item in store.items:
                merged[item.id] = item
            store.items = list(merged.values())
        save_embedding_store(store, emb_path)

    # Explain -------------------------------------------------------------
    def explain_file(self, file: Path | str) -> ExplainResult:
        file_path = Path(file).resolve()
        ir = self._load_ir_required()
        module = _find_module_for_file(ir, self.repo_root, file_path)
        if module is None:
            raise IRNotFoundError(f"No module found for file {file_path}")
        imports = sorted(
            {
                edge.imported_module
                for edge in ir.module_import_edges
                if edge.importer_module_id == module.id
            }
        )
        functions = [
            {
                "name": fn.name,
                "qualified_name": fn.qualified_name,
                "lineno": fn.lineno,
                "num_calls": len(fn.calls),
            }
            for fn in sorted(
                [f for f in module.functions if f.kind != "module"], key=lambda f: f.lineno
            )
        ]
        classes = [
            {
                "name": cls.name,
                "qualified_name": cls.qualified_name,
                "lineno": cls.lineno,
                "methods": [m.qualified_name for m in cls.methods],
            }
            for cls in sorted(module.classes, key=lambda c: c.lineno)
        ]
        return ExplainResult(
            repo_root=self.repo_root,
            file=file_path,
            module=module.module_name,
            imports=[{"module": imp} for imp in imports],
            functions=functions,
            classes=classes,
        )

    def explain_llm(
        self,
        file: Path | str,
        *,
        symbol: str | None = None,
        k_neighbors: int = 10,
    ) -> dict[str, Any]:
        file_path = Path(file).resolve()
        try:
            bundle = build_explain_llm_bundle(
                file_path,
                symbol=symbol,
                k_neighbors=k_neighbors,
            ).data
        except RuntimeError as exc:
            raise NeurocodeError(str(exc)) from exc
        return bundle

    # Checks --------------------------------------------------------------
    def run_checks(
        self,
        file: Path | str,
        *,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> list[CheckResult]:
        file_path = Path(file).resolve()
        ir = self._load_ir_required()
        config = load_config(self.repo_root)
        results = check_file(ir=ir, repo_root=self.repo_root, file=file_path, config=config)
        filtered = []
        for r in results:
            if include and r.code not in include:
                continue
            if exclude and r.code in exclude:
                continue
            filtered.append(
                CheckResult(
                    code=r.code,
                    severity=r.severity,  # type: ignore[arg-type]
                    message=r.message,
                    file=file_path,
                    lineno=r.lineno,
                )
            )
        return filtered

    # Search --------------------------------------------------------------
    def search_code(
        self,
        *,
        text: str | None = None,
        like: str | None = None,
        module: str | None = None,
        k: int = 10,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[SearchResult]:
        if bool(text) == bool(like):
            raise NeurocodeError("Provide exactly one of text or like")
        ir, store = self._load_ir_and_embeddings_required()
        if text:
            try:
                provider_obj, provider_name, model_name = make_embedding_provider(
                    self.config,
                    provider_override=provider,
                    model_override=model or store.model,
                    allow_dummy=(provider == "dummy") or self.config.embedding_allow_dummy,
                )
            except Exception as exc:
                raise ConfigError(str(exc)) from exc
            query_embedding = build_query_embedding_from_text(text, provider=provider_obj)
        else:
            query_embedding = build_query_embedding_from_symbol(store, like or "")
        neighbors = search_embeddings(
            repository_ir=ir,
            embedding_store=store,
            query_embedding=query_embedding,
            module_filter=module,
            k=k,
        )
        return [
            SearchResult(
                id=n.id,
                kind=n.kind,  # type: ignore[arg-type]
                module=n.module,
                name=n.name,
                file=Path(n.file),
                lineno=n.lineno,
                signature=n.signature,
                score=n.score,
            )
            for n in neighbors
        ]

    # Patch planning / application ----------------------------------------
    def plan_patch_llm(
        self,
        file: Path | str,
        *,
        fix: str,
        symbol: str | None = None,
        k_neighbors: int = 10,
    ) -> PatchPlan:
        file_path = Path(file).resolve()
        try:
            bundle = build_patch_plan_bundle(
                file_path,
                fix=fix,
                symbol=symbol,
                k_neighbors=k_neighbors,
            )
        except RuntimeError as exc:
            raise NeurocodeError(str(exc)) from exc
        return PatchPlan(data=bundle)

    def apply_patch_plan(
        self,
        plan: PatchPlan | Mapping[str, Any],
        *,
        dry_run: bool = False,
        show_diff: bool = False,
    ) -> PatchApplyResult:
        plan_data = plan.data if isinstance(plan, PatchPlan) else plan
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as tmp:
            json.dump(plan_data, tmp)
            tmp_path = Path(tmp.name)
        try:
            file_rel = plan_data.get("file")
            if not file_rel:
                raise PatchPlanError("Patch plan missing file")
            target_file = (self.repo_root / file_rel).resolve()
            result = apply_patch_plan_from_disk(
                target_file,
                tmp_path,
                dry_run=dry_run,
                show_diff=show_diff or dry_run,
            )
        except RuntimeError as exc:
            raise PatchPlanError(str(exc)) from exc
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        result_obj = PatchApplyResult(
            repo_root=self.repo_root,
            files_changed=[result.file],
            diff=result.diff,
            is_noop=result.no_change,
            summary=result.summary,
            warnings=result.warnings,
            status=result.status,
            target_function=result.target_function,
            inserted_line=result.inserted_line,
            inserted_text=result.inserted_text,
        )
        return result_obj

    def patch_file(
        self,
        file: Path | str,
        *,
        fix: str,
        strategy: str = "guard",
        target: str | None = None,
        require_target: bool = False,
        dry_run: bool = False,
        require_fresh_ir: bool = False,
        inject_kind: str = "notimplemented",
        inject_message: str | None = None,
    ) -> PatchApplyResult:
        file_path = Path(file).resolve()
        try:
            result = apply_patch_from_disk(
                file_path,
                fix_description=fix,
                strategy=strategy,
                target=target,
                require_target=require_target,
                dry_run=dry_run,
                require_fresh_ir=require_fresh_ir,
                inject_kind=inject_kind,
                inject_message=inject_message,
            )
        except RuntimeError as exc:
            raise NeurocodeError(str(exc)) from exc
        result_obj = PatchApplyResult(
            repo_root=self.repo_root,
            files_changed=[result.file],
            diff=result.diff,
            is_noop=result.no_change,
            summary=result.summary,
            warnings=result.warnings,
            status=result.status,
            target_function=result.target_function,
            inserted_line=result.inserted_line,
            inserted_text=result.inserted_text,
        )
        if not dry_run and not result_obj.is_noop:
            try:
                append_patch_history(
                    self.repo_root,
                    fix=fix,
                    files_changed=[str(result.file.relative_to(self.repo_root))],
                    is_noop=result_obj.is_noop,
                    summary=result_obj.summary or "",
                    warnings=result_obj.warnings or [],
                )
            except Exception:
                pass
        return result_obj

    def list_patch_history(self, limit: int = 20) -> list[PatchHistoryEntryResult]:
        history = load_patch_history(self.repo_root)
        entries = list(reversed(history.entries))
        if limit is not None and limit > 0:
            entries = entries[:limit]
        return [
            PatchHistoryEntryResult(
                id=entry.id,
                timestamp=entry.timestamp,
                fix=entry.fix,
                files_changed=entry.files_changed,
                is_noop=entry.is_noop,
                summary=entry.summary,
                warnings=entry.warnings,
                plan_id=entry.plan_id,
            )
            for entry in entries
        ]

    def check_ir_freshness(self) -> list[str]:
        """Return a list of staleness issues for the loaded IR."""

        ir = self._load_ir_required()
        statuses = _compute_module_status(ir)
        issues: list[str] = []
        for st in statuses:
            if st.status == "fresh":
                continue
            reason = f" ({st.reason})" if st.reason else ""
            issues.append(f"{st.module.module_name}: {st.status}{reason}")
        return issues

    # Internal helpers ----------------------------------------------------
    def _load_ir_required(self) -> RepositoryIR:
        ir_path = self.repo_root / ".neurocode" / "ir.toon"
        if not ir_path.is_file():
            raise IRNotFoundError("IR not found; run build_ir first.")
        return load_repository_ir(ir_path)

    def _load_ir_and_embeddings_required(self) -> tuple[RepositoryIR, EmbeddingStore]:
        ir = self._load_ir_required()
        emb_path = self.repo_root / ".neurocode" / "ir-embeddings.toon"
        if not emb_path.is_file():
            raise EmbeddingsNotFoundError(
                f"Embeddings not found at {emb_path}; run ensure_embeddings first."
            )
        from .embedding_model import load_embedding_store

        store = load_embedding_store(emb_path)
        return ir, store
