# Agent / editor integration

## LangChain tools

Install `langchain-core` (optional dependency) and use the helper:

```python
from neurocode.agent_tools import make_langchain_tools

tools = make_langchain_tools("/path/to/repo")
# tools: neurocode_explain_llm, neurocode_plan_patch_llm, neurocode_apply_patch_plan
```

Example LangChain usage:
```python
from langchain.agents import initialize_agent
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4.1-mini")
agent = initialize_agent(
    tools=make_langchain_tools("/path/to/repo"),
    llm=llm,
    agent_type="openai-tools",  # or your preferred LC agent type
)

resp = agent.invoke(
    "Summarize package/mod_a.py and propose a patch plan for orchestrator",
    {"symbol": "package.mod_a:orchestrator"},
)
print(resp)
```

Notes:
- IR/embeddings must already exist (`neurocode ir .`, optionally `neurocode embed .`).
- The apply tool defaults to `dry_run=True` and returns a diff; set `dry_run=False` to write files.

## Editor touchpoint (CLI)

Editors can shell out to the CLI for a minimal integration:
- `neurocode status . --format json` for freshness + config
- `neurocode explain-llm path/to/file.py --symbol pkg.mod:func --format json` for rich bundles
- `neurocode plan-patch-llm ...` to feed an LLM and `neurocode patch --plan filled.json --show-diff` to apply
