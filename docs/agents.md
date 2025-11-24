# Agents and editor loops

`examples/neurocode_agent.py` is a minimal end-to-end agent:
- Builds/refreshes IR for the repo and ensures embeddings (OpenAI if `OPENAI_API_KEY` is set, or pass `--embed-provider dummy`).
- Uses semantic search to pick a target when `--file/--symbol` are omitted.
- Generates an IR + Neural IR explain bundle and a PatchPlanBundle (`plan_patch_llm`).
- Sends the plan to an LLM with a strict system prompt that locks down allowed fields.
- Dry-runs the patch to validate, prints the diff, then optionally applies it.

Example run:
```bash
OPENAI_API_KEY=... python examples/neurocode_agent.py \
  --repo . \
  --fix "add logging around db calls" \
  --model gpt-4.1-mini \
  --dry-run --show-plan
```

To plug in another model, swap out `get_openai_client`/`client.chat.completions.create` for your provider; keep the JSON PatchPlanBundle contract identical so `apply_patch_plan` passes validation. The script surfaces useful flags: `--embed-provider/--embed-model`, `--no-apply`, `--verbose`, and `--show-plan` for debugging.
