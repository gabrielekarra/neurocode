from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from neurocode.api import (  # noqa: E402
    ConfigError,
    EmbeddingsNotFoundError,
    NeurocodeError,
    PatchPlanError,
    open_project,
)


# Function to create and return an OpenAI client instance
def get_openai_client():
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - import error path
        raise RuntimeError("Failed to import openai; install openai>=1.0") from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
    return OpenAI(api_key=api_key)


def extract_json_from_text(text: str) -> Any:
    """Strip common fences and parse JSON."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        fence_end = cleaned.find("\n")
        if fence_end != -1:
            cleaned = cleaned[fence_end + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
    return json.loads(cleaned)


def disable_empty_code_operations(bundle: Mapping[str, Any]) -> list[str]:
    """Disable operations that have no code to avoid validation errors."""
    disabled: list[str] = []
    ops = bundle.get("operations", [])
    if not isinstance(ops, list):
        return disabled
    for op in ops:
        if not isinstance(op, Mapping):
            continue
        if op.get("enabled", True) and (not op.get("code") or str(op.get("code")).strip() == ""):
            op["enabled"] = False
            disabled.append(str(op.get("id", "<unknown>")))
    return disabled


def summarize_build_result(build_result) -> None:
    reused = "reused existing IR" if build_result.fresh else "rebuilt IR"
    print(
        f"[neurocode-agent] repo={build_result.repo_root} ir={build_result.ir_path} "
        f"{reused} modules={build_result.modules} functions={build_result.functions} "
        f"calls={build_result.calls}"
    )


def summarize_explain_bundle(bundle: Mapping[str, Any], symbol: str | None) -> None:
    callers = bundle.get("call_graph_neighbors", {}).get("callers") or []
    callees = bundle.get("call_graph_neighbors", {}).get("callees") or []
    related_files = bundle.get("related_files") or []
    slices = bundle.get("source_slices") or []
    print(
        "[neurocode-agent] explain bundle: "
        f"target={symbol or 'module'} call_graph_neighbors={len(callers) + len(callees)} "
        f"related_files={len(related_files)} source_slices={len(slices)}"
    )


def summarize_patch_plan(bundle: Mapping[str, Any]) -> None:
    operations: Sequence[Mapping[str, Any]] = bundle.get("operations", [])  # type: ignore[assignment]
    files = {op.get("file") for op in operations if isinstance(op, Mapping)}
    print(
        "[neurocode-agent] patch plan: "
        f"operations={len(operations)} files={', '.join(sorted(str(f) for f in files if f)) or 'n/a'} "
        f"multi_file={'yes' if len(files) > 1 else 'no'}"
    )


def build_system_prompt() -> str:
    return (
        "You are an expert code editing model using the NeuroCode PatchPlanBundle protocol. "
        "The bundle already contains full relevant context (call graph, related files, source slices, "
        "and cross-file information). Update the plan in-place.\n"
        "Do NOT change these fields: version, engine_version, repo_root, file, module, "
        "target.*, id, op, file, symbol, lineno, end_lineno.\n"
        "You MAY change only: operations[*].code, operations[*].description, operations[*].enabled.\n"
        "Return ONLY the updated JSON object with no markdown or commentary."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Example NeuroCode agent using JSON PatchPlanBundle.")
    parser.add_argument("--repo", default=".", help="Path to the repository root (default: .)")
    parser.add_argument(
        "--file",
        help=(
            "Target Python file for the change. "
            "If omitted, NeuroCode will infer relevant files from the repository."
        ),
    )
    parser.add_argument("--symbol", help="Fully-qualified symbol, e.g., pkg.module:func")
    parser.add_argument("--fix", required=True, help="High-level description of the desired change.")
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="OpenAI chat model to use for filling the PatchPlanBundle.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only run dry-run application.")
    parser.add_argument("--no-apply", action="store_true", help="Show diff but never write files.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    parser.add_argument(
        "--show-plan",
        action="store_true",
        help="Print initial operations before sending to the LLM.",
    )
    parser.add_argument(
        "--embed-provider",
        help="Embedding provider to use for ensure_embeddings (e.g., openai, dummy).",
    )
    parser.add_argument(
        "--embed-model",
        help="Embedding model identifier to use for ensure_embeddings.",
    )
    parser.add_argument(
        "--embed-update",
        action="store_true",
        help="Update existing embeddings instead of requiring a fresh store.",
    )
    args = parser.parse_args(argv)

    try:
        selected_files: list[str] = []
        project = open_project(args.repo)
        if args.verbose:
            import neurocode  # noqa: WPS433

            print(f"[neurocode-agent] using neurocode from {neurocode.__file__}")
        build_result = project.build_ir(force=False)
        summarize_build_result(build_result)

        embed_provider = args.embed_provider
        embed_model = args.embed_model
        # If not provided explicitly, default to OpenAI when an API key is present.
        if embed_provider is None and os.getenv("OPENAI_API_KEY"):
            embed_provider = "openai"
            if embed_model is None:
                embed_model = "text-embedding-3-small"
        if embed_provider:
            project.config.embedding_provider = embed_provider  # make explicit for downstream helpers
        if embed_model:
            project.config.embedding_model = embed_model
        if embed_provider == "dummy":
            project.config.embedding_allow_dummy = True
        if args.verbose:
            print(
                f"[neurocode-agent] ensure_embeddings provider={embed_provider or '<config>'} "
                f"model={embed_model or '<default>'} update={args.embed_update}"
            )
        try:
            project.ensure_embeddings(
                provider=embed_provider,
                model=embed_model,
                update=args.embed_update,
            )
        except (ConfigError, EmbeddingsNotFoundError) as exc:
            print("[neurocode-agent] Failed to ensure embeddings:", exc)
            return 1

        if not args.file:
            print("[neurocode-agent] No --file provided → repository-wide mode using semantic search.")
            candidates = project.search_code(text=args.fix, k=10)
            if not candidates:
                print("[neurocode-agent] No relevant symbols found in repository for this fix.")
                return 1
            if args.verbose:
                print("[neurocode-agent] Top search candidates for repository-wide mode:")
                for idx, cand in enumerate(candidates, start=1):
                    print(
                        f"  {idx}. {cand.module}:{cand.name} "
                        f"(kind={cand.kind} score={cand.score:.3f} file={cand.file})"
                    )
            selected_files = sorted({str(c.file) for c in candidates if c.file})
            print(
                "[neurocode-agent] Repository-wide mode selected "
                f"{len(selected_files)} files: {selected_files}"
            )
            best = max(candidates, key=lambda c: c.score)
            args.symbol = f"{best.module}:{best.name}"
            args.file = str(best.file)
            print(
                f"[neurocode-agent] Anchor symbol: {args.symbol} "
                f"(score={best.score:.3f}, file={best.file})"
            )

        if not args.symbol:
            candidates = project.search_code(text=args.fix, k=5)
            if not candidates:
                print("[neurocode-agent] No symbols found; please provide --symbol explicitly.")
                return 1
            best = max(candidates, key=lambda c: c.score)
            args.symbol = f"{best.module}:{best.name}"
# The main function calls get_openai_client to obtain an OpenAI client instance
# This client is then used to interact with the OpenAI API for generating completions
            print(
                f"[neurocode-agent] Selected symbol {args.symbol} "
                f"(score={best.score:.3f}, file={best.file})"
            )
            if args.verbose:
                print("[neurocode-agent] Top search candidates:")
                for idx, cand in enumerate(candidates, start=1):
                    print(
                        f"  {idx}. {cand.module}:{cand.name} "
                        f"(kind={cand.kind} score={cand.score:.3f} file={cand.file})"
                    )

        explain_bundle = project.explain_llm(
            args.file,
            symbol=args.symbol,
            k_neighbors=10,
        )
        summarize_explain_bundle(explain_bundle, args.symbol)
        if selected_files:
            explain_bundle["repo_selected_files"] = selected_files
        if args.verbose:
            neighbors = explain_bundle.get("call_graph_neighbors", {})
            print("[neurocode-agent] call graph neighbors (truncated):")
            print(json.dumps(neighbors, indent=2)[:2000])

        patch_plan = project.plan_patch_llm(
            args.file,
            fix=args.fix,
            symbol=args.symbol,
            k_neighbors=10,
        )
        bundle = patch_plan.data
        summarize_patch_plan(bundle)
        if args.show_plan:
            print("[neurocode-agent] initial operations:")
            for op in bundle.get("operations", []):
                file_path = op.get("file", "<unknown>")
                desc = op.get("description", "")
                enabled = op.get("enabled", True)
                print(f"  - {file_path} enabled={enabled} op={op.get('op')} desc={desc}")

        client = get_openai_client()
        system_prompt = build_system_prompt()
        user_content = (
            "You are given a JSON PatchPlanBundle generated by NeuroCode for the following fix:\n"
            f"{args.fix}\n\n"
        )
        if selected_files:
            user_content += f"Repository-selected files: {selected_files}\n\n"
        user_content += (
            "Here is the PatchPlanBundle (JSON):\n"
            f"{json.dumps(bundle, indent=2)}\n\n"
            "Modify ONLY the allowed fields and output ONLY the updated JSON PatchPlanBundle."
        )
        response = client.chat.completions.create(
            model=args.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
        )
        raw_text = response.choices[0].message.content or ""
        try:
            filled_bundle = extract_json_from_text(raw_text)
        except json.JSONDecodeError as exc:
            print("[neurocode-agent] Failed to parse LLM output as JSON.")
            print(raw_text)
            print(exc)
            return 1
        disabled_ops = disable_empty_code_operations(filled_bundle)
        if disabled_ops:
            print(
                "[neurocode-agent] Disabled operations with empty code to satisfy validation: "
                + ", ".join(disabled_ops)
            )

        try:
            dry_result = project.apply_patch_plan(filled_bundle, dry_run=True)
        except PatchPlanError as exc:
            print("[neurocode-agent] Patch plan validation failed:", exc)
            return 1

        changed_files = ", ".join(str(p) for p in dry_result.files_changed) or "<none>"
        print(
            "[neurocode-agent] dry-run apply: "
            f"files={changed_files} noop={'yes' if dry_result.is_noop else 'no'}"
        )
        if dry_result.diff:
            print("----- DRY RUN DIFF -----")
            print(dry_result.diff)
            print("----- END DIFF -----")

        if args.no_apply or args.dry_run:
            return 0

        answer = input("Apply this patch? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("[neurocode-agent] Aborting without applying changes.")
            return 0

        real_result = project.apply_patch_plan(filled_bundle, dry_run=False)
        final_files = ", ".join(str(p) for p in real_result.files_changed) or "<none>"
        print(
            "[neurocode-agent] applied patch: "
            f"files={final_files} noop={'yes' if real_result.is_noop else 'no'}"
        )
        if real_result.summary:
            print("[neurocode-agent] summary:", real_result.summary)
        if real_result.warnings:
            print("[neurocode-agent] warnings:", "; ".join(real_result.warnings))
        return 0

    except NeurocodeError as exc:
        print(f"[neurocode-agent] error: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"[neurocode-agent] runtime error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

    """
    This function initializes and returns an OpenAI client instance.

    How it works:
    1. It attempts to import the OpenAI client class from the 'openai' package.
       If the import fails (e.g., package not installed), it raises a RuntimeError with a helpful message.
    2. It retrieves the OpenAI API key from the environment variable 'OPENAI_API_KEY'.
       If the key is not set, it raises a RuntimeError to inform the user.
    3. It creates and returns an OpenAI client instance using the retrieved API key.

    How to make it better:
    - Add support for passing the API key as a parameter to allow more flexible usage.
    - Cache the client instance to avoid re-initializing it multiple times if called repeatedly.
    - Add more detailed error handling for common issues like invalid API keys.
    - Optionally support configuration of other client parameters (e.g., timeout, base URL).
    """
