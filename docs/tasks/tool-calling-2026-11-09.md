# Task list: tool calling in v1 (D44 supersedes D8)

Date: 2026-11-09
Playbook: `.agents/playbooks/togaf-feature-delivery.md`
Status: Step 1 approved. Step 3 (design) done, see `docs/adr/0002-tool-calling.md`. Step 4 next.

## Approval

| Item | State |
|---|---|
| Step 1: goal, out-of-scope list, done condition (items 1 to 9) | Approved by the owner on 2026-11-09 ("blanket approval given. go") |
| Tasks of this feature (design, build, verify, land) | Blanket approval, given the same day. It covers every task in this file. |
| Defaults in the Step 2 table | Taken, since the owner approved without changing them |
| Merging the final PR | Not covered. The agent asks before it merges. |

## Step 1. Define done

### Goal

A caller can give an alias a set of tools in config, call `complete`, and get the model's tool calls back. The caller runs the tool and sends the result in the next `complete`. Retry, failover and usage work as they do today.

### Decisions already made by the owner (2026-11-09)

| Decision | Choice |
|---|---|
| D44 supersedes D8 | Tool calling moves from v2 into v1. |
| Who runs a tool | The caller. The library does not execute tools and has no loop. |
| Where tools are set | Per alias in the YAML. Tool definitions are listed once, and each alias names the tools it may use. |

### Out of scope

- The library running tools or looping until the model answers.
- Streaming (D2 stands).
- `tool_choice` (forcing a tool), `strict` schemas and tools passed per request.
- Provider-hosted tools such as web search or code execution.
- Images and other non-text content.
- A tool-call limit, a tool timeout or any other agent-loop policy. Those belong to the caller.

### Done condition (pass or fail)

1. **Config.** The YAML has a top-level `tools` map (name, description, JSON Schema). An alias may name tools. `validate()` raises `ConfigError` for an alias that names a tool not in the map, and for a tool with no description or schema.
2. **Types.** A `Request` can carry a tool call (id, name, arguments) in an assistant message and a tool result (id, text, error flag) in a user message. A `Response` carries `tool_calls`, and its `stop_reason` says when the model stopped to call a tool. A text-only request and response behave exactly as before.
3. **Both adapters.** The Anthropic adapter and the Responses adapter send the alias's tools, map the model's tool calls into `Response.tool_calls`, and map tool results in the history back to the provider's wire. Each is tested against `httpx2.MockTransport`.
4. **Core.** Retry, failover, `on_usage` and the pre-check are unchanged in behaviour. The pre-check counts the tool definitions and the tool results in its estimate (D34).
5. **Failover mid-conversation.** A history that holds a tool call and a tool result, started on the primary, completes on the fallback of another provider. The history is neutral, so each adapter maps it.
6. **Acceptance tests.** New named tests are added to section 8.2 of `docs/requirements.md` and pass. The existing 175 tests still pass, apart from tests the new spec changes on purpose.
7. **Spec and docs.** D8 is marked superseded by a new decision. D44, section 9, section 10 and the "no tool execution" line in section 1 are updated. `GLOSSARY.md` defines tool, tool call and tool result. `README.md` matches the code. An ADR records the message shape.
8. **Gates.** `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` pass, and CI passes on Linux, Windows and macOS.
9. **Live check.** The Gemini gateway accepts tools on the Responses wire and returns a function call. This needs the owner's key. If it is not run, the feature is **not** verified for Gemini and the report says so.

## Step 2. What the code does today

Every claim below cites a file.

- **Text only.** `Message` is `role` plus `text`, and `Request` holds `messages`, `max_output_tokens`, `temperature` and `system` (`src/llm_adapter/types.py`). `Response` has `text` and `stop_reason` and no tool field.
- **Adapters map the wire and nothing else.** Anthropic builds `messages.create` with `content` as a plain string (`src/llm_adapter/adapters/anthropic.py:62`) and joins the text blocks of the reply (`:73`). The Responses adapter builds `input` as role and content strings (`src/llm_adapter/adapters/responses.py:113`) and reads `resp.output_text` (`:125`).
- **Retry and failover live in the core.** A tool call is a successful reply, so it needs no new error class (`src/llm_adapter/core.py`).
- **Config.** `Alias` holds `primary`, `fallback` and `context_window`. `_parse_alias` and `validate` are where a `tools` field and its check belong (`src/llm_adapter/config.py:158`, `:69`).
- **Pre-check.** The estimate counts only `system` and message text (`src/llm_adapter/precheck.py:19`). Tool definitions and tool results would be missed, so it must change.
- **Tests that cover the area.** `tests/test_adapter_anthropic.py` (23), `tests/test_adapter_responses.py` (23), `tests/test_core.py` (24), `tests/test_config.py` (8), `tests/test_precheck.py` (5), `tests/test_types.py` (7) and `tests/test_conformance.py` (15).
- **Pattern to reuse.** A frozen dataclass in `types.py`, one mapping function in each adapter, a config field parsed in `_parse_alias` and checked in `validate()`, and a named acceptance test in section 8.2.
- **The wire shapes exist in both pinned SDKs.** Read by importing the types, with no network. Anthropic: a tool is `name`, `description` and `input_schema`. A reply holds a `tool_use` block with `id`, `name` and `input`. A result is a `tool_result` block with `tool_use_id`, `content` and `is_error`. Responses: a tool is a function with `name`, `description` and `parameters`. A reply holds a function call with `call_id`, `name` and `arguments` (a JSON string). A result is a `function_call_output` item with `call_id` and `output`.

## Size and next step

**MEDIUM.** It crosses the types, both adapters, config and the pre-check, and it makes a real decision. The message stops being text only. Step 3 runs `/architect` on the types and the adapter mapping and writes an ADR. Step 4 splits the work into task cards.

Points the design must settle in Step 3. I have picked a default for each.

| Point | Default |
|---|---|
| Arguments in a tool call | Kept as parsed JSON (a dict) in the neutral type. Each adapter converts to its wire form. |
| Several tool calls in one reply | `Response.tool_calls` is a tuple. The caller returns one result for each. |
| A tool call in a `Response` and `text` | Both are kept. `text` may be empty. |
| Tool-call ids across providers | Opaque strings. They are passed back unchanged. |
| A tool result that is an error | An `is_error` flag. Responses has no such field, so that adapter puts the flag in the output text. |
| Tool arguments that are not valid JSON | The Responses adapter sends arguments as a JSON string, so the model can return text that does not parse. The adapter keeps the raw string in the call and does not raise. The caller decides what to do. |

## Tasks

Task cards are written in Step 4, after the design is approved.

- [x] **Step 1. Owner approves the goal, the out-of-scope list and the done condition.**
- [x] Step 2. Understand the affected code. Done above.
- [x] Step 3. Design with `/architect`, ADR, owner approves.
  - Done (2026-11-09). Three candidates were written read-only, each on the session model with a different starting shape: content blocks, typed turns, and the smallest delta. The synthesis is in `docs/adr/0002-tool-calling.md`. It takes the typed-turn base, keeps `Message` for text turns, and grafts `UnparsedArguments` and `repr=False` from the other candidates.
  - The sketches stay in `/tmp/sketch-tools/`, not in the repo. The ADR is the record. This changes the earlier plan to commit the sketch.
  - Owner approval: covered by the blanket approval. No separate checkpoint was asked.
  - Deviations from the Step 2 defaults, decided here: a caller bug raises `ValueError`, not `InvalidRequest`. `as_turn()` refuses unparsed arguments, so the caller re-asks.
  - Next: Step 4, the task cards. It waits for this ADR, because the cards cite its decisions.
- [ ] Step 4. Task cards.
- [ ] Step 5. Build.
- [ ] Step 6. Verify and review.
- [ ] Step 7. Land.
- [ ] Step 8. Learn.
