# llm-adapter

An in-process Python library that gives your code one interface for calling LLMs across providers. It applies a defined retry policy, bounded failover and normalised usage reporting. Application code names a model alias, never a vendor SDK or a model ID.

It is a library, not a proxy or gateway server. There is no port, no daemon and no separate process.

> Status: build in progress. The shared types and the prompt-size pre-check exist. `complete`, the config loader and the adapters do not. There is no release.

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

Expected result: `pytest` passes 134 tests (the config, core, adapter, type, pre-check and import tests), and both `ruff` commands report no problem.

## Layout

| Path | Purpose |
|------|---------|
| `src/llm_adapter/config.py` | `load_config(path)`, `validate()` and `resolve_alias()`: the YAML config, `${VAR}` resolution and the startup checks (D10, D18, D33) |
| `src/llm_adapter/core.py` | `Core.complete()`, the per-class retry schedule, `Retry-After`, failover, `on_usage` and the pre-check call |
| `src/llm_adapter/types.py` | `Request`, `Response`, `Usage`, `Attempt`, `UsageEvent`, `ErrorClass`, the exceptions and the adapter `Protocol` |
| `src/llm_adapter/precheck.py` | The local prompt-size estimate and the check against the alias's `context_window` (D34) |
| `src/llm_adapter/adapters/anthropic.py` | The Anthropic Messages adapter. The SDK's retries are off (AT-6) |
| `src/llm_adapter/adapters/responses.py` | The one Responses adapter that serves OpenAI and Gemini (ADR 0001). The SDK's retries are off (AT-6) |
| `scripts/check_gemini_usage.py` | Live check, run by hand with a real Gemini key. `--list` shows the Gemini models. It prints usage field names only (task T4) |
| `tests/` | Tests. Provider behaviour is tested against a mock HTTP layer |
| `docs/requirements.md` | The requirements and the decisions. This is the single source |
| `docs/adr/` | Architecture decision records |
| `GLOSSARY.md` | The vocabulary of the requirements and the code |
| `docs/tasks/` | Task lists, with the state of each task |
| `AGENTS.md` | Shared instructions for every coding agent. `CLAUDE.md` imports it |
| `.agents/playbooks/` | Delivery playbooks for coding agents |

## Next steps

The owner has decided the v1 scope and answered the open items O1 to O12. `docs/requirements.md` records both. The owner has approved the requirements as a whole. The caller assessment and the Gemini live check are done. The build task list is `docs/tasks/build-2026-11-09.md`. B1 (dependencies) and B2 (types) are done. B3 to B8 wait for the owner's approval. See `docs/tasks/scaffold-2026-11-09.md`.
