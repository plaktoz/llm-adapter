# Requirements: llm-adapter

Status: skeleton. Fill it from `docs/handoff-from-llm-gateway-2026-11-09.md` sections 4 and 5, once the owner has decided D2 and D3.

## Purpose and scope

### What it does

- **One interface.** Callers name a model alias (`default`, `deep`, `planner`) and send a `Request`. They never name a vendor SDK or a model ID. Aliases map to a primary and an optional fallback provider in config, so swapping a model is a config edit.
- **Providers.** It covers Anthropic, OpenAI, Gemini and a custom HTTP endpoint such as a local model server. It wraps each provider's SDK directly (ADR-0003, no LiteLLM).
- **The core owns the policy.** The core applies a per-error-class retry schedule, then fails over to the fallback. When both providers fail, it raises `ProviderExhausted` once and nothing retries in the background. Auth errors are never retried or failed over.
- **Visible outcomes.** Each `Response` carries an `attempts[]` list, so failover is visible. `on_usage` fires once per attempt, including failed ones, with token counts only. That feeds `token-ledger`.
- **Adapters stay thin.** Each adapter only maps one SDK to the shared types and classifies its exceptions. Adding a provider means one file and one config entry.

### What it is not

- It is not a proxy, gateway server or daemon, and that is a hard requirement.
- It has no agent loops, tool execution, prompt building, memory, spend limits or caching.
- It is not used by Coding Workers or Reviewers, because the external CLI harnesses bypass it.

## Decisions

| ID | Decision | Choice | Date |
|----|----------|--------|------|
| D1 | Name | `llm-adapter` (package `llm_adapter`) | 2026-11-09 |
| D2 | Streaming in v1 | Open | |
| D3 | Gemini path: native SDK or OpenAI-compatible | Open | |
| D4 | Where the project rules live | `AGENTS.md`, adapted from agent-garage | 2026-11-09 |
| D5 | Python version | 3.11 or later (default, not vetoed) | 2026-11-09 |

## 1. Interface

## 2. Data model

## 3. Alias table

## 4. Error classes and policy

## 5. Behaviour

## 6. Security

## 7. Failure modes

## 8. Acceptance criteria

## 9. Callers
