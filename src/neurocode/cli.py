import argparse
import sys
from pathlib import Path

from .check import check_file_from_disk
from .embedding_model import EmbeddingItem, EmbeddingStore, load_embedding_store, save_embedding_store
from .embedding_provider import DummyEmbeddingProvider, EmbeddingProvider
from .embedding_text import build_embedding_documents
from .explain import explain_file_from_disk
from .ir_build import build_repository_ir, compute_file_hash
from .patch import apply_patch_from_disk
from .query import QueryError, render_query_result, run_query
from .search import (
    build_query_embedding_from_symbol,
    build_query_embedding_from_text,
    load_ir_and_embeddings,
    search_embeddings,
)
from .status import status_from_disk
from .toon_parse import load_repository_ir
from .toon_serialize import repository_ir_to_toon


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="neurocode",
        description=(
            "NeuroCode – Neural IR engine for structural understanding and "
            "reasoning over codebases."
        ),
    )
    from . import __version__

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Phase 1 — Parsing & Graph
    ir_parser = subparsers.add_parser("ir", help="Generate IR for a repository")
    ir_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the repository (default: current directory)",
    )
    ir_parser.add_argument(
        "--check",
        action="store_true",
        help="Check existing IR freshness without rebuilding",
    )

    explain_parser = subparsers.add_parser(
        "explain", help="Explain a file using IR-informed reasoning"
    )
    explain_parser.add_argument("file", help="Python file to explain")
    explain_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    check_parser = subparsers.add_parser(
        "check", help="Run structural checks on a Python file"
    )
    check_parser.add_argument("file", help="Python file to check")
    check_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    check_parser.add_argument(
        "--status",
        action="store_true",
        help="Print a one-line machine-readable status (exit code still reflects severity)",
    )

    patch_parser = subparsers.add_parser(
        "patch", help="Apply an IR-informed patch to a Python file"
    )
    patch_parser.add_argument("file", help="Python file to patch")
    patch_parser.add_argument("--fix", required=True, help="High-level fix description")
    patch_parser.add_argument(
        "--strategy",
        choices=["guard", "todo", "inject"],
        default="guard",
        help=(
            "Patch strategy: guard inserts a None-check, todo inserts a TODO "
            "comment, inject adds a stub/log (default: guard)"
        ),
    )
    patch_parser.add_argument(
        "--inject-kind",
        choices=["notimplemented", "log"],
        default="notimplemented",
        help=(
            "When using --strategy inject, choose stub type: "
            "NotImplementedError or logging.debug (default: notimplemented)"
        ),
    )
    patch_parser.add_argument(
        "--inject-message",
        help="Override message used for inject strategy (defaults to --fix text)",
    )
    patch_parser.add_argument(
        "--target",
        help="Qualified or simple function name to patch (default: first module-level function)",
    )
    patch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write changes; print the would-be patch summary instead",
    )
    patch_parser.add_argument(
        "--show-diff",
        action="store_true",
        help="After applying, print the unified diff of the change",
    )
    patch_parser.add_argument(
        "--require-fresh-ir",
        action="store_true",
        help="Fail if .neurocode/ir.toon is older than the target file",
    )
    patch_parser.add_argument(
        "--require-target",
        action="store_true",
        help="Fail instead of falling back if no target function can be selected",
    )
    patch_parser.add_argument(
        "--no-noop-note",
        action="store_true",
        help="Suppress note when patch was already present",
    )
    patch_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format for patch result (default: text)",
    )

    status_parser = subparsers.add_parser("status", help="Report IR freshness and config summary")
    status_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the repository (default: current directory)",
    )
    status_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    query_parser = subparsers.add_parser(
        "query", help="Run structural queries against an existing IR"
    )
    query_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the repository root containing .neurocode/ir.toon (default: current directory)",
    )
    query_parser.add_argument(
        "--kind",
        required=True,
        choices=["callers", "callees", "fan-in", "fan-out"],
        help="Query kind to run",
    )
    query_parser.add_argument(
        "--symbol",
        help="Target function symbol (qualified name preferred) for callers/callees",
    )
    query_parser.add_argument(
        "--module",
        dest="module_filter",
        help="Restrict query scope to a module (name or path)",
    )
    query_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    embed_parser = subparsers.add_parser(
        "embed", help="Generate embeddings for the IR and write .neurocode/ir-embeddings.toon"
    )
    embed_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the repository root containing .neurocode/ir.toon (default: current directory)",
    )
    embed_parser.add_argument(
        "--provider",
        default="dummy",
        help="Embedding provider to use (default: dummy)",
    )
    embed_parser.add_argument(
        "--model",
        default="dummy-embedding-v0",
        help="Embedding model identifier (default: dummy-embedding-v0)",
    )
    embed_parser.add_argument(
        "--update",
        action="store_true",
        help="Merge with existing .neurocode/ir-embeddings.toon if present",
    )
    embed_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    search_parser = subparsers.add_parser(
        "search", help="Semantic search over embeddings stored in .neurocode/ir-embeddings.toon"
    )
    search_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the repository root containing .neurocode (default: current directory)",
    )
    query_group = search_parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument(
        "--text",
        help="Text query to search for similar functions",
    )
    query_group.add_argument(
        "--like",
        help="Find functions similar to this symbol (e.g., package.module:func)",
    )
    search_parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Number of results to return (default: 10)",
    )
    search_parser.add_argument(
        "--module",
        dest="module_filter",
        help="Restrict results to a module/package (prefix match)",
    )
    search_parser.add_argument(
        "--provider",
        default="dummy",
        help="Embedding provider to use for text queries (default: dummy)",
    )
    search_parser.add_argument(
        "--model",
        default=None,
        help="Expected embedding model; if set and differs from the store, search fails",
    )
    search_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    if args.command == "ir":
        repo_path = Path(args.path).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            print(
                f"[neurocode] error: path does not exist or is not a directory: {repo_path}",
                file=sys.stderr,
            )
            sys.exit(1)

        if args.check:
            ir_file = repo_path / ".neurocode" / "ir.toon"
            if not ir_file.exists():
                print(
                    "[neurocode] error: {ir_file} does not exist; run `neurocode ir {repo}` first.".format(
                        ir_file=ir_file, repo=repo_path
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            repo_ir = load_repository_ir(ir_file)
            stale: list[str] = []
            for module in repo_ir.modules:
                curr_path = (repo_ir.root / module.path).resolve()
                try:
                    curr_hash = compute_file_hash(curr_path)
                except OSError:
                    stale.append(f"{module.module_name} (missing file {curr_path})")
                    continue
                if module.file_hash and module.file_hash != curr_hash:
                    stale.append(f"{module.module_name} (stale)")
            if stale:
                print("[neurocode] IR is stale for modules:")
                for entry in stale:
                    print(f"  - {entry}")
                sys.exit(1)
            print("[neurocode] IR is fresh.")
            sys.exit(0)

        repo_ir = build_repository_ir(repo_path)
        toon_text = repository_ir_to_toon(repo_ir)

        output_dir = repo_path / ".neurocode"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "ir.toon"
        output_path.write_text(toon_text, encoding="utf-8")

        print(
            "[neurocode] IR written to {path} (modules={modules}, functions={functions}, calls={calls})".format(
                path=output_path,
                modules=repo_ir.num_modules,
                functions=repo_ir.num_functions,
                calls=repo_ir.num_calls,
            )
        )
    elif args.command == "explain":
        file_path = Path(args.file).resolve()
        try:
            output = explain_file_from_disk(file_path, output_format=args.format)
        except RuntimeError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(output)
    elif args.command == "check":
        file_path = Path(args.file).resolve()
        try:
            output, exit_code, status = check_file_from_disk(
                file_path, output_format=args.format, return_status=True
            )
        except RuntimeError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)

        print(output)
        if args.status:
            print(status)
        sys.exit(exit_code)
    elif args.command == "patch":
        file_path = Path(args.file).resolve()
        try:
            result = apply_patch_from_disk(
                file_path,
                args.fix,
                strategy=args.strategy,
                target=args.target,
                dry_run=args.dry_run,
                require_fresh_ir=args.require_fresh_ir,
                require_target=args.require_target,
                inject_kind=args.inject_kind,
                inject_message=args.inject_message,
            )
        except RuntimeError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)

        action = "Planned" if args.dry_run else "Applied"
        for warn in result.warnings:
            print(f"[neurocode] warning: {warn}", file=sys.stderr)

        if args.format == "json":
            import json

            payload = {
                "status": result.status,
                "file": str(result.file),
                "target_function": result.target_function,
                "summary": result.summary,
                "inserted_line": result.inserted_line,
                "inserted_text": result.inserted_text,
                "no_change": result.no_change,
                "warnings": result.warnings,
                "diff": result.diff if (args.dry_run or args.show_diff) else None,
            }
            print(json.dumps(payload, indent=2))
        else:
            print(
                "[neurocode] {action} patch to {path}: {detail} (line {line})".format(
                    action=action,
                    path=file_path,
                    detail=result.summary,
                    line=result.inserted_line,
                )
            )
            if result.no_change and not args.no_noop_note:
                print("[neurocode] note: patch already existed; no change applied.")
            if (args.dry_run or args.show_diff) and result.diff:
                print(result.diff)
            if result.no_change and not args.dry_run:
                sys.exit(3)
    elif args.command == "query":
        repo_path = Path(args.path).resolve()
        ir_file = repo_path / ".neurocode" / "ir.toon"
        if not ir_file.is_file():
            print(
                f"[neurocode] error: {ir_file} not found. Run `neurocode ir {repo_path}` first.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            ir = load_repository_ir(ir_file)
            result = run_query(
                ir=ir,
                repo_root=repo_path,
                kind=args.kind,
                symbol=args.symbol,
                module_filter=args.module_filter,
            )
            output = render_query_result(result, output_format=args.format)
            print(output)
            sys.exit(0)
        except QueryError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[neurocode] unexpected error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "embed":
        repo_path = Path(args.path).resolve()
        ir_file = repo_path / ".neurocode" / "ir.toon"
        if not ir_file.is_file():
            print(
                f"[neurocode] error: {ir_file} not found. Run `neurocode ir {repo_path}` first.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            ir = load_repository_ir(ir_file)
            docs = build_embedding_documents(ir)
            provider: EmbeddingProvider
            if args.provider == "dummy":
                provider = DummyEmbeddingProvider()
            else:
                print(f"[neurocode] error: unknown provider: {args.provider}", file=sys.stderr)
                sys.exit(1)
            vectors = provider.embed_batch([doc.text for doc in docs])
            if len(vectors) != len(docs):
                print("[neurocode] error: provider returned mismatched embedding count", file=sys.stderr)
                sys.exit(1)

            from . import __version__

            new_store = EmbeddingStore.new(repo_root=repo_path, engine_version=__version__, model=args.model)
            new_items = []
            for doc, vec in zip(docs, vectors):
                new_items.append(
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
            new_store.items = new_items

            store_path = repo_path / ".neurocode" / "ir-embeddings.toon"
            store_path.parent.mkdir(parents=True, exist_ok=True)

            if args.update and store_path.exists():
                try:
                    existing = load_embedding_store(store_path)
                    merged = {item.id: item for item in existing.items}
                    for item in new_items:
                        merged[item.id] = item
                    new_store.items = list(merged.values())
                except Exception as exc:  # pragma: no cover - defensive
                    print(
                        f"[neurocode] warning: failed to load existing embeddings, overwriting ({exc})",
                        file=sys.stderr,
                    )

            save_embedding_store(new_store, store_path)

            summary = {
                "path": str(store_path),
                "items": len(new_store.items),
                "model": args.model,
                "provider": args.provider,
            }
            if args.format == "json":
                import json

                print(json.dumps(summary, indent=2))
            else:
                message = (
                    "[neurocode] embeddings written to {path} (items={items}, "
                    "model={model}, provider={provider})"
                ).format(**summary)
                print(message)
            sys.exit(0)
        except RuntimeError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[neurocode] unexpected error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "search":
        repo_path = Path(args.path).resolve()
        try:
            ir, store = load_ir_and_embeddings(repo_path)
            requested_model = args.model
            if requested_model and store.model and store.model != requested_model:
                msg = (
                    f"[neurocode] error: embedding store model '{store.model}' "
                    f"does not match requested '{requested_model}'"
                )
                print(msg, file=sys.stderr)
                sys.exit(1)

            provider: EmbeddingProvider | None = None
            if args.text:
                if args.provider != "dummy":
                    print(f"[neurocode] error: unknown provider: {args.provider}", file=sys.stderr)
                    sys.exit(1)
                provider = DummyEmbeddingProvider()
                query_embedding = build_query_embedding_from_text(args.text, provider=provider)
                query_type = "text"
                query_value = args.text
            else:
                query_embedding = build_query_embedding_from_symbol(store, args.like)
                query_type = "like"
                query_value = args.like

            results = search_embeddings(
                repository_ir=ir,
                embedding_store=store,
                query_embedding=query_embedding,
                module_filter=args.module_filter,
                k=args.k,
            )

            if args.format == "json":
                import json

                payload = {
                    "query_type": query_type,
                    "query": query_value,
                    "k": args.k,
                    "results": [
                        {
                            "id": r.id,
                            "kind": r.kind,
                            "module": r.module,
                            "name": r.name,
                            "file": r.file,
                            "lineno": r.lineno,
                            "signature": r.signature,
                            "score": r.score,
                        }
                        for r in results
                    ],
                }
                print(json.dumps(payload, indent=2))
            else:
                header = f"[neurocode] search ({query_type}) k={args.k}"
                print(header)
                for r in results:
                    print(f"{r.score:.3f} {r.module}:{r.name} ({r.file}:{r.lineno}) {r.signature}")
            sys.exit(0)
        except RuntimeError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[neurocode] unexpected error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "status":
        repo_path = Path(args.path).resolve()
        output, exit_code = status_from_disk(repo_path, output_format=args.format)
        print(output)
        sys.exit(exit_code)
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
