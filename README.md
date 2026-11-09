# llm-adapter

An in-process Python library that gives your code one interface for calling LLMs across providers. It applies a defined retry policy, bounded failover and normalised usage reporting. Application code names a model alias, never a vendor SDK or a model ID.

It is a library, not a proxy or gateway server. There is no port, no daemon and no separate process.

> Status: scaffold only. The package holds empty modules. There is no library code, no spec and no release.

## Requirements

| Need | Notes |
|------|-------|
| Python 3.11 or later | |
| `uv` | Installs the environment and runs the tools |

## Quick start

From the repository root:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected result: `pytest` passes 8 import tests, and both `ruff` commands report no problem.

## Layout

| Path | Purpose |
|------|---------|
| `src/llm_adapter/core.py` | `complete()`, the alias table, the retry and failover loop, `on_usage`, `validate()` |
| `src/llm_adapter/types.py` | `Request`, `Response`, `Usage`, `Attempt` and the error classes |
| `src/llm_adapter/adapters/` | One file per provider: `anthropic`, `openai`, `gemini`, `openai_compat` |
| `tests/` | Tests. Provider behaviour is tested against a mock server |
| `docs/requirements.md` | The requirements and the decisions |
| `docs/tasks/` | Task lists, with the state of each task |
| `docs/handoff-from-llm-gateway-2026-11-09.md` | The source requirements, from agentzero-v2-dev |
| `AGENTS.md` | Shared instructions for every coding agent. `CLAUDE.md` imports it |
| `.agents/playbooks/` | Delivery playbooks, copied from agent-garage |

## Next steps

The owner decides streaming in v1 and the Gemini path. Then the requirements and the spec are written, and a task list is made. See `docs/tasks/scaffold-2026-11-09.md`.
