import argparse
import sys
from pathlib import Path

from .check import check_file_from_disk
from .explain import explain_file_from_disk
from .ir_build import build_repository_ir, compute_file_hash
from .patch import apply_patch_from_disk
from .toon_serialize import repository_ir_to_toon
from .toon_parse import load_repository_ir


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="neurocode",
        description=(
            "NeuroCode – Neural IR engine for structural understanding and "
            "reasoning over codebases."
        ),
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
        help="Patch strategy: guard inserts a None-check, todo inserts a TODO comment, inject adds a stub/log (default: guard)",
    )
    patch_parser.add_argument(
        "--inject-kind",
        choices=["notimplemented", "log"],
        default="notimplemented",
        help="When using --strategy inject, choose stub type: NotImplementedError or logging.debug (default: notimplemented)",
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
                print(f"[neurocode] error: {ir_file} does not exist; run `neurocode ir {repo_path}` first.", file=sys.stderr)
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

        target = result.target_function or "file"
        action = "Planned" if args.dry_run else "Applied"
        for warn in result.warnings:
            print(f"[neurocode] warning: {warn}", file=sys.stderr)
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
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
