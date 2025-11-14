import argparse
import sys
from pathlib import Path
from typing import Dict, List

from .check import CheckResult, check_file_from_disk
from .explain import explain_file_from_disk
from .ir_build import build_repository_ir
from .toon_serialize import repository_ir_to_toon


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

    explain_parser = subparsers.add_parser(
        "explain", help="Explain a file using IR-informed reasoning"
    )
    explain_parser.add_argument("file", help="Python file to explain")

    check_parser = subparsers.add_parser(
        "check", help="Run structural checks on a Python file"
    )
    check_parser.add_argument("file", help="Python file to check")

    patch_parser = subparsers.add_parser(
        "patch", help="Apply an IR-informed patch to a Python file"
    )
    patch_parser.add_argument("file", help="Python file to patch")
    patch_parser.add_argument("--fix", required=True, help="High-level fix description")

    args = parser.parse_args()

    if args.command == "ir":
        repo_path = Path(args.path).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            print(
                f"[neurocode] error: path does not exist or is not a directory: {repo_path}",
                file=sys.stderr,
            )
            sys.exit(1)

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
            output = explain_file_from_disk(file_path)
        except RuntimeError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(output)
    elif args.command == "check":
        file_path = Path(args.file).resolve()
        try:
            results = check_file_from_disk(file_path)
        except RuntimeError as exc:
            print(f"[neurocode] error: {exc}", file=sys.stderr)
            sys.exit(1)

        if not results:
            print("[neurocode] no issues found.")
            sys.exit(0)

        print(f"[neurocode] structural diagnostics for {file_path}:")

        grouped: Dict[str, List[CheckResult]] = {}
        for result in results:
            module_name = result.module or "<unknown module>"
            grouped.setdefault(module_name, []).append(result)

        for module_name in sorted(grouped):
            print(f"\nModule {module_name}:")
            module_results = sorted(
                grouped[module_name],
                key=lambda r: (
                    r.lineno or 0,
                    r.function or "",
                    r.code,
                    r.message,
                ),
            )
            for res in module_results:
                location = str(res.file)
                if res.lineno is not None:
                    location = f"{location}:{res.lineno}"
                detail = f"{res.code} {res.message}"
                print(f"  - {detail} [{location}]")
        sys.exit(1)
    elif args.command == "patch":
        print("[neurocode] Patch not implemented yet (MVP Phase 5 stub).")
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
