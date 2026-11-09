# llm-adapter: handoff from agentzero-v2-dev

Status: **not started.** Requirements are drafted here. No code, no spec, and no task list exist yet. The next step is the owner's go-ahead on the decisions in section 7.

Date: 2026-11-09
Source: `agentzero-v2-dev/libs/llm-gateway/README.md` (last committed at `c6a1695`, with an uncommitted two-line edit to sections 2 and 9 that only renames `budget-meter` to `token-ledger`).

## 1. What this is

A Python library that gives UMAS's own code one interface for calling LLMs across providers: Anthropic, OpenAI, Google Gemini, and a custom HTTP endpoint (for example a local model server). It applies a defined retry policy, bounded failover, and normalised usage reporting. Application code names a model alias, never a vendor SDK or a model ID.

It is an **in-process library, not a proxy or gateway server.** There is no port, no daemon, and no separate process.

## 2. Decision already on record

- ADR-0003 (in agentzero-v2-dev): wrap the provider SDKs directly. No LiteLLM. The spec's section 6 is the acceptance checklist.
- The name `llm-gateway` is a leftover from the spec. Renaming to `llm-adapter` is open (section 7, D1).

## 3. Who calls it

Only Python callers in UMAS (`TECHNICAL-DESIGN-SPEC.md` lines 205, 614, 1363):

| Caller | Operations used | Source |
|---|---|---|
| Coordinator, Router | `complete` | orchestration-spec line 215 |
| Triage Agent | `complete` | monitoring-spec line 118 |
| Patrol (Coordinator-side model calls) | `complete` | A.4.8 table, TECHNICAL-DESIGN-SPEC |
| Non-editing Specialists (open) | `complete` | agent-execution-spec line 248, Open 7 |
| Usage glue to `token-ledger` | `on_usage` | models-and-usage-spec lines 112–114 |
| Startup check | `validate()` | models-and-usage-spec line 258 |

Nothing calls `stream`, `health`, or `provider_override` today.

Coding Workers and Reviewers run as external CLI harnesses (Claude Code, Codex) and **bypass** this library (A.4.8, TECHNICAL-DESIGN-SPEC).

Callers reference model aliases `default`, `deep` and `planner`. `default` and `deep` are decided (models-and-usage D2, D20).

## 4. Requirements

### 4.1 Interface

| Operation | Description |
|---|---|
| `complete(request) -> Response` | Blocking call that applies the retry and failover policy. |
| `stream(request)` | Streaming. A mid-stream failure is an error event. The library never restarts a partly delivered stream on another provider. |
| `health()` | Last-seen status per provider. |
| `on_usage(callback)` | Called once per attempt, successful or failed, with `{alias, provider, model, usage, latency_ms, outcome}`. |
| `validate()` | Checks aliases and credentials at startup. Raises `ConfigError`. |

### 4.2 Data model

```
Request:  { alias, messages[], tools[]?, max_output_tokens?, temperature?, system?, metadata{} }
Response: { text, tool_calls[], stop_reason, usage, model_used, provider_used, attempts[] }
Usage:    { input_tokens, output_tokens, cached_input_tokens?, cache_write_tokens? }
```

`attempts[]` lists every provider call and its outcome, so failover is visible to the caller.

### 4.3 Alias table (configuration, not code)

```yaml
aliases:
  default:  { primary: {provider: anthropic, model: "<from config>"},
              fallback: {provider: openai, model: "<from config>"} }
  planner:  { primary: ..., fallback: null }
  deep:     { primary: {provider: anthropic, model: "<from config>"},
              fallback: {provider: openai, model: "<from config>"} }
```

- Replacing a provider or model is a config edit. No code change or rebuild.
- **No model IDs in code or in the spec.** The old spec pinned `claude-3-5-sonnet-20241022`. Do not repeat that.

### 4.4 Error classes and default policy

| Class | Trigger | Policy |
|---|---|---|
| `rate_limited` | HTTP 429 | Backoff 5 s, 15 s, 45 s (honour `Retry-After`), then failover |
| `server_error` | 5xx | 3 immediate retries, then failover |
| `timeout` | No response within `timeout` (default 30 s; streaming uses first-token timeout) | 2 retries, then failover |
| `auth` | 401/403 | **Never retried, never failed over.** Raise at once |
| `context_overflow` | Prompt over the model limit | No retry. Raise. The caller shrinks the input |
| `invalid_request` | 400 | No retry. Raise |
| `content_filtered` | Refusal or safety stop | No retry. Return with `stop_reason=refusal` |

The library keeps this taxonomy. A consumer can express it as `error-classifier` catalog entries (data only). The library does not depend on `error-classifier`.

### 4.5 Behaviour

- **Retry and failover:** for each provider in `[primary, fallback]`, apply the schedule for the error class. On success, return. On a non-retryable error, raise at once. After both fail, raise `ProviderExhausted(attempts)` once.
- **No blind retry loops.** After exhaustion, nothing retries in the background. Recovery is the caller's or a human's decision.
- **Circuit breaker (nice-to-have):** after 5 consecutive failures a provider is open for 60 s. Calls skip it and go to the fallback. Then one probe decides whether to close.
- **Resume after failover:** the library does not rebuild context. The caller re-supplies the conversation or checkpoint. (Consider `provider_override` in v2.)
- **Rate limiting (nice-to-have):** token buckets per provider and per alias (RPM and TPM). Wait up to 30 s, then raise `RateLimitedLocal`. Provider headers adjust the buckets.
- **Non-goals:** agent loops, tool execution, prompt construction, memory, spend limits, caching, evaluation, prompt management, task-level resume.

### 4.6 Security

- API keys come from environment variables or a secrets provider. Never from committed files. Never logged.
- Request and response bodies are not logged by default. The usage callback carries counts only.
- TLS is required for every non-localhost endpoint.
- No secret appears in logs, usage events, or error messages.

### 4.7 Failure modes (exceptions)

| Exception | Cause |
|---|---|
| `ProviderExhausted` | All providers failed. Carries `attempts[]` |
| `AuthError` | 401/403 on the first provider |
| `ContextOverflow` | Prompt too large. Carries the model limit |
| `RateLimitedLocal` | Local bucket wait exceeded. Carries `retry_after` |
| `ConfigError` | Unknown alias or missing credentials, found by `validate()` |

## 5. Acceptance criteria

### 5.1 Wrapper checklist (from the old spec section 6)

| # | Criterion | Must pass |
|---|---|---|
| 1 | Anthropic, OpenAI, Google Gemini and a custom HTTP endpoint | yes |
| 2 | Unified tool calling and streaming | yes (see D2) |
| 3 | Per-class retry schedule (4.4), configurable | yes |
| 4 | Ordered fallback with a visible attempts list | yes |
| 5 | Usage callback with input, output and cached tokens | yes |
| 6 | Auth errors never retried or failed over | yes |
| 7 | Circuit breaker | nice-to-have |
| 8 | Client-side TPM/RPM limiting | nice-to-have |
| 9 | No proxy server process | **must, not just preferred** (see 6.1) |
| 10 | Active maintenance, permissive licence | yes |

### 5.2 Behaviour tests (from the old spec section 8)

1. A mock server returns 429, 5xx, timeout and 401 in turn. The attempts list and total wait match 4.4. 401 is never retried.
2. When both providers fail, the library raises once and makes no further calls.
3. `on_usage` fires for every attempt, failed ones included, with the right provider and model.
4. Changing a model ID in config needs no code change or rebuild.
5. No secret appears in logs, usage events or error messages (canary key test).
6. With the primary breaker open, calls go to the fallback with no added latency.

## 6. Design notes for the new project

### 6.1 Layout (proposed)

```
llm_adapter/
  core.py          complete(), alias table, retry and failover loop, on_usage, validate()
  types.py         Request, Response, Usage, Attempt, error classes
  adapters/
    anthropic.py   SDK client, request and response conversion, usage mapping, exception mapping
    openai.py
    gemini.py
    openai_compat.py   custom endpoint (base_url)
```

Each adapter implements `complete(request, model, timeout) -> Response` and `classify(exc) -> ErrorClass`. The core owns all retry and failover logic. Adding a provider means one file and one config entry.

### 6.2 SDK retries must be turned off (a trap)

The current SDKs retry on their own, and this will stack on the library's schedule:

- `anthropic` 2.6.0: `DEFAULT_MAX_RETRIES = 2` (`_constants.py`)
- `openai` 3.46.0: `DEFAULT_MAX_RETRIES = 2` (`_constants.py`)
- `google-genai` 3.0.0: `HttpRetryOptions.attempts` defaults to 5 when set (`types.py`)

Each adapter must build its client with SDK retries disabled. Otherwise test 5.2.1 fails, and charged timeouts get retried without the library's knowledge. Write this into the spec as a rule and test it.

Versions above were checked against PyPI on 2026-11-09. Re-check when the project starts.

### 6.3 Other points

- Cached-token fields differ by provider. The usage schema keeps them as optional. Consumers that record totals add only input and output tokens.
- The Gemini endpoint may be native or OpenAI-compatible. This is open (see D3).
- Python version: 3.11 or later is proposed as a default (D5).

## 7. Decisions for the owner

Nothing here is decided. The defaults below apply unless vetoed.

**Defaults taken**
- D1 keep the name `llm-gateway` for now, or rename to `llm-adapter` (see below).
- D2 streaming is in v1 (criterion 2 says yes). Otherwise the checklist changes.
- D5 Python 3.11+.
- Circuit breaker and rate limiting are v2.

**D1. Name.** Rename to `llm-adapter`, or keep `llm-gateway`.
- Rename: matches the design. Costs one pass over about 25 docs in agentzero-v2-dev. Could be done with the `budget-meter` → `token-ledger` rename already in progress.
- Keep: no cost now. The name keeps suggesting a server, which was the wrong model.
- Recommendation: rename in the new project, and leave the old docs for the UMAS repo to update.

**D2. Streaming in v1.** No caller uses it today. v1 can skip it and keep the checklist's criterion 2 for v2.
- Gain of including it now: no later API change for callers. Cost: the most complex path (first-token timeout, mid-stream errors, a streaming form of each adapter). Risk: more code to test for no current caller.
- Recommendation: defer to v2, and say so in the spec. This changes criterion 2 from yes to later.

**D3. Gemini path.** Native Google SDK, or OpenAI-compatible endpoint?
- Native: keeps Gemini-specific features and uses a maintained SDK (`google-genai`). Cost: a fourth SDK.
- OpenAI-compatible: reuses the `openai` adapter and the custom endpoint. Cost: loses Gemini-specific features, and Gemini's compatibility layer may differ.
- ADR-0002 uses the Gemini alias for Codex as well. The Codex path bypasses this library.
- Recommendation: native SDK, unless a spike shows the compatible endpoint covers tool calls and usage.

**D4. Where the project's rules live.** The new project has no `AGENTS.md`. The agentzero-v2-dev repo's task-management rules (agree requirements, caller assessment gate, task list in `docs/`, one commit per task once commits are asked for) should be copied in or referenced.

**D5. Python version.** 3.11+ is the default. Confirm.

## 8. Next steps (once the owner gives a go-ahead)

1. Owner decides D1–D5.
2. Write `docs/requirements.md` from section 4 and 5, with the decisions recorded.
3. Write the spec, `llm_adapter/README.md` or `docs/spec.md`, using the contract in 4.
4. Run the caller assessment gate: one assessor subagent checks the spec against the callers in section 3.
5. Write the task list in `docs/tasks.md`, each task with acceptance criteria from section 5.
6. Build in order: types and core with a fake adapter, then each provider adapter with a mock server, then the usage callback and `validate()`.

## 9. Source references

| Topic | Location in agentzero-v2-dev |
|---|---|
| Full old spec | `libs/llm-gateway/README.md` |
| Build decision | `docs/decisions/ADR-0003-llm-gateway-wraps-provider-sdks.md` |
| Gemini via Codex | `docs/decisions/ADR-0002-gemini-and-openai-via-codex-cli.md` |
| Usage rule | `docs/decisions/ADR-0005-track-token-usage-only.md` |
| Caller map | `umas/modules/{orchestration,monitoring,agent-execution,models-and-usage,exception-flows}/*-spec.md` |
| Process layout and agent model | `umas/TECHNICAL-DESIGN-SPEC.md` lines ~205, ~614, ~1363, A.4.8 |
| Token ledger contract | `libs/token-ledger/README.md` |
