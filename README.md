# llm-adapter

An in-process Python library that gives your code one interface for calling LLMs across providers. It applies a defined retry policy, bounded failover and normalised usage reporting. Application code names a model alias, never a vendor SDK or a model ID.

It is a library, not a proxy or gateway server. There is no port, no daemon and no separate process.

> Status: v1 is built and tested against a mock HTTP layer. The conformance suite covers AT-1 to AT-14. It has not been run against a live provider, and the overflow bodies are unverified (requirements F3). There is no release.

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

Expected result: `pytest` passes 156 tests, and both `ruff` commands report no problem.

To use the library, write a YAML config (the shape is in `docs/requirements.md` section 3), set the environment variables it names, then:

```python
from llm_adapter.config import load_config, validate
from llm_adapter.factory import build_core
from llm_adapter.types import Message, Request

config = load_config("llm.yaml")  # the path is yours; there is no search path (D24)
validate(config)  # raises ConfigError before any call
core = build_core(config)
core.on_usage(lambda event: print(event.provider, event.outcome))  # counts only, no content

response = core.complete(Request(alias="default", messages=[Message(role="user", text="Hi")]))
print(response.text, response.attempts)
```

`load_config` reads the file and resolves `${VAR}` from the environment. `build_core` checks the config, creates one adapter per provider and builds the `Core`. Tests pass a fake clock to `build_core`, and an HTTP client to `build_adapters` (D31, D40).

## Layout

| Path | Purpose |
|------|---------|
| `src/llm_adapter/config.py` | `load_config(path)`, `validate()` and `resolve_alias()`: the YAML config, `${VAR}` resolution and the startup checks (D10, D18, D33) |
| `src/llm_adapter/core.py` | `Core.complete()`, the per-class retry schedule, `Retry-After`, failover, `on_usage` and the pre-check call |
| `src/llm_adapter/factory.py` | `build_core(config)` and `build_adapters(config)`: turn a `Config` into a `Core` and its adapters (D40) |
| `src/llm_adapter/types.py` | `Request`, `Response`, `Usage`, `Attempt`, `UsageEvent`, `ErrorClass`, the exceptions and the adapter `Protocol` |
| `src/llm_adapter/precheck.py` | The local prompt-size estimate, with 10% headroom, and the check against the alias's `context_window` (D34, D37) |
| `src/llm_adapter/adapters/anthropic.py` | The Anthropic Messages adapter. The SDK's retries are off (AT-6) |
| `src/llm_adapter/adapters/responses.py` | The one Responses adapter that serves OpenAI and Gemini (ADR 0001). The SDK's retries are off (AT-6) |
| `tests/test_conformance.py` | The end-to-end suite, AT-1 to AT-14 (section 8.2) |
| `tests/` | The other tests. Provider behaviour is tested against a mock HTTP layer |
| `docs/requirements.md` | The requirements and the decisions. This is the single source |
| `docs/adr/` | Architecture decision records |
| `GLOSSARY.md` | The vocabulary of the requirements and the code |
| `docs/tasks/` | Task lists, with the state of each task |
| `AGENTS.md` | Shared instructions for every coding agent. `CLAUDE.md` imports it |
| `.agents/playbooks/` | Delivery playbooks for coding agents |

## Next steps

The owner has decided the v1 scope and the open items. `docs/requirements.md` records them. The build task list is `docs/tasks/build-2026-11-09.md`. Still open: the live overflow probe that replaces the guessed overflow bodies (F3), and a CI workflow.
