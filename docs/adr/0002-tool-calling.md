---
status: accepted
---

# Tool calling: typed turns in the history

Date: 2026-11-09. This ADR records the message shape for D44, which supersedes D8. The task list is `docs/tasks/tool-calling-2026-11-09.md`. The owner approved the goal and the design direction under the blanket approval of 2026-11-09.

## Context

Version 1 is text in, text out. The owner decided three things. The caller runs tools. The library has no loop and executes nothing. Tools are set per alias in the YAML.

A history that holds a tool call must finish on a fallback that speaks the other wire. Anthropic keeps calls and results as content blocks of one message. Responses keeps them as separate items. So the history must be neutral, and each adapter maps it to its own wire. Retry and failover stay in the core. Text-only callers keep working.

## Decision

The history is a sequence of turns. Each adapter maps the turns to its own wire.

- `Message(role, text)` is the text turn. It is unchanged.
- `AssistantToolCalls(text, calls)` is one assistant reply's calls and its text. `Response.as_turn()` builds it.
- `ToolResults(results)` is the caller's answers. It holds one `ToolResult` for each call.
- `Request.messages` is `Sequence[Message | AssistantToolCalls | ToolResults]`.
- `ToolCall(id, name, arguments)`. `arguments` is a parsed `Mapping`, or `UnparsedArguments(raw)` when the model's text was not a JSON object. The fields that carry a body have `repr=False`.
- `ToolResult(call_id, text, is_error=False)`.
- `Response` gains `tool_calls: tuple[ToolCall, ...] = ()`. On both wires, `stop_reason` is `"tool_use"` when the model stopped to call tools. The caller acts on that value.
- Tools are a top-level `tools` map. Each entry has `description` and `input_schema`. An alias lists the names it may use. `validate()` raises `ConfigError` for an unknown name, a repeated name, an empty description, or a schema that is not an object.
- `check_history` runs in the core before any provider call. It raises `ValueError` for a call with no result, a result with no call, a duplicate id, or a result outside the turn after its calls. A caller bug is not a provider outcome, so it is not `InvalidRequest`.
- Ids are opaque strings and pass through unchanged.
- `as_turn()` raises `ValueError` when a call's arguments are `UnparsedArguments`. The caller asks the model again. It does not replay the raw text.
- On Anthropic, a `Message` with role user that directly follows `ToolResults` joins the same user message, after the `tool_result` blocks.
- On Responses, `strict` is sent as `false`. A failed result has `Error: ` in front of its text, because the output item has no error flag.
- On Responses, a replayed `function_call` item carries `call_id` and no item `id`.

## Considered options

- **Content blocks inside `Message`.** Rejected. Every text caller changes, and the Responses adapter must split each message into items.
- **Delete `Message` and use `UserText` and `AssistantText`.** Rejected. It renames 11 construction sites and the README for no gain. `Message` already has one spelling for text.
- **Optional `tool_calls` and `tool_results` fields on `Message`.** Rejected. Most values hold neither field. A call can sit on a user turn until a runtime check catches it.
- **Library-minted ids.** Rejected. The core would keep a table of ids per call, which is state. The library keeps none.

## Consequences

- Text-only code does not change. The constructor, `.text`, `Response.text` and the request body are the same.
- The role rule for calls and results is a type rule. Each adapter has one `match` over the turn types that ends in `assert_never`, so a new turn type fails the check.
- The pairing rule is a runtime check. No single type can express it. It lives in one function, and one named test covers it.
- `stop_reason` and `tool_calls` can disagree on a refusal or a max-tokens stop. The docstring of `Response` states the rule.
- The new public names are `Tool`, `ToolCall`, `ToolResult`, `ToolResults`, `AssistantToolCalls`, `UnparsedArguments` and `STOP_TOOL_USE`. The wire dicts, SDK types, argument parsing and error prefix stay private.

## Open questions decided on 2026-11-13

The owner chose one option for each open question. Every choice keeps the design above. No probe has run, so each choice rests on a fact that nobody has checked.

| Question | Choice | Fallback if the probe shows a rejection |
|---|---|---|
| Q1. Must `tool_result` come before text in an Anthropic user message? | Merge a user `Message` that follows `ToolResults` into the same user message. Put the `tool_result` blocks first. | Forbid that sequence in `check_history`. Use separate user messages only if the probe also shows that two user messages in a row are accepted. |
| Q2. Does Anthropic accept a `tool_use` id that another provider minted? | Keep ids unchanged on every wire. | Rewrite ids for the target wire with a pure function. The probe must also find the id format that each wire accepts. Refusing failover would contradict done item 5. |
| Q3. Does Responses accept a replayed `function_call` with no `id`? | Send `call_id` and omit the item `id`. | Send the item `id` with the same value as `call_id`. |
| Q4. What does the Responses tool definition say for `strict`? | Send `strict: false`. | Send `strict: null`, or omit the key. |

- Q2 applies in both directions. A Responses `call_id` that Anthropic minted is the same question as an Anthropic `tool_use` id that Responses minted.
- The `Error: ` prefix on a failed result is not an open question. The ADR fixes it.
- A rejected shape returns HTTP 400. The core classifies that as `invalid_request` and raises `InvalidRequest` at once, with no failover (D20). A rejection is therefore a loud failure, not a silent one.

## Unverified

Only a live probe can check these facts. The probe needs the owner's key. The script is `scripts/check_tool_wire.py`. It is written. It has not been run against any provider.

- Whether the Anthropic Messages wire accepts a `tool_use` id that another provider minted.
- Whether the Responses wire accepts a `call_id` that Anthropic minted.
- Whether the Responses wire accepts a `function_call` item with no `id`.
- Whether the endpoint accepts an explicit `strict: false`. The server default no longer matters, because the adapter always sends the value.
- Whether Anthropic requires `tool_result` blocks first. The merge rule puts them first, so it is safe either way.
- How the Gemini endpoint answers tools on the Responses wire. Until the live check runs, Gemini is not verified. The script does not cover Gemini.

A probe result holds for the endpoint that the probe named. In the owner's environment, `ANTHROPIC_BASE_URL` points at a gateway. A gateway can answer differently from the vendor API. Each result must name its endpoint, and a result must not be applied to another endpoint.

## Source

Three candidate sketches were written in read-only passes. They are in `/tmp/sketch-tools/` and are not committed. The base is the typed-turn candidate (`fable`). Two ideas come from the others. The named `UnparsedArguments` type with `repr=False` comes from the content-blocks candidate (`opus`). The concern that tool arguments and results leak into `repr` and logs comes from the minimal-delta candidate (`sonnet`). This design keeps `Message` for text turns. The typed-turn candidate deleted it, which renames 11 construction sites and the README for no gain.
