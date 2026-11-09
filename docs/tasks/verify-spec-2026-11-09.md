# Task list: check the spec against the SDKs and the callers

Date: 2026-11-09
Source: `docs/requirements.md` (D1 to D26), `AGENTS.md` sections 3 and 6.

## Goal

Callers can call any alias and trust the retry, failover and usage behaviour. For that, the spec must rest on checked facts, not on an earlier draft or on a research agent's report. These tasks check those facts. The build task list comes after them.

## Approval

| Item | State |
|------|-------|
| Direction: check the spec against SDK source and the callers' design documents, then build the conformance suite before the library | Approved by the owner on 2026-11-09 |
| Go-ahead to run T1 to T6 | Given by the owner on 2026-11-09 in an interactive question: "All tasks T1 to T6". This covers the tasks, not the installs. Each package install still waits for the owner's approval of the package list (T2). T4 needs the owner's own key. |
| Approval of `docs/requirements.md` as a whole | Given by the owner on 2026-11-09 |
| Dependency pins | Rule from the owner on 2026-11-09: use the latest release on PyPI unless it cannot be used. Approved: `anthropic` 2.6.0, `openai` 3.46.0, `PyYAML` 6.0.3, `httpx2` 2.16.0 (D32). Nothing is installed until the build task that needs it starts. |
| Commits, pushes, merges | Not asked |

## Tasks

Mark the state next to each task: `[ ]` open, `[x]` done, `[-]` not done, with the reason.

- [x] **T1. Caller assessment gate.** One assessor subagent checks section 9 of `docs/requirements.md` against the callers' design documents.
  - Parallel: yes. It reads documents outside this repo and needs no output from T2 or T3.
  - Subagent limits: read-only on the caller documents. It does not edit, commit, push or merge. It reports. The parent edits `requirements.md`.
  - Done when: every fact in section 9 is marked confirmed, refuted or not found, with a `file:line`. The report lists every `complete(`, `on_usage` and `validate` call site it found. Each gap is fixed in `requirements.md` or recorded there.
  - State: **done** (2026-11-09). Assessor subagent, read-only. Verified by reading: the parent re-checked six of its claims in the source documents.
  - Result: section 9 of `requirements.md` is rewritten as self-contained text. Confirmed: the caller operations, the alias facts, no tools or images, and the usage ledger shape. Added: the monitoring callers. Caveat: the proposed specialist forms use `read` and `search` tools, which would need v2 tool calling (D8). Gap, not decided: the caller documents disagree on whether the usage glue records the payload's `model` or its `alias`. The `UsageEvent` carries both, and the caller decides.
  - Correction: I first wrote that the architect `default` claim was dropped. That was wrong. The sample in the specialist document does use `default` for the Architect, while the models document uses `deep`. The sample is non-normative.
  - Limits: design documents only, since no caller code exists.

- [x] **T2. Dependency check.** For `anthropic`, `openai`, PyYAML and one mock HTTP server library, report whether `uv` already has it, the latest version on PyPI, the licence and the date of the last release.
  - Parallel: yes. It is independent of T1.
  - Done when: a table is in this file. The owner approves the list and the pins. Nothing is installed before that approval. If PyPI is not reachable from this machine, record that here.
  - State: **done** (2026-11-09). The owner confirmed the check on 2026-11-09. The table and pins below stand as written. The check was read-only, and PyPI was reachable. **Pins approved by the owner on 2026-11-09 ("use the latest versions"): `anthropic` 2.6.0 and `openai` 3.46.0.** This covers only those two. `PyYAML` 6.0.3 was approved the same day (D32). `respx` is dropped (D31). Nothing is added to `pyproject.toml` until the build task that needs it starts.

    | Package | Here | Latest on PyPI | Released | Licence | Requires-python | Last release within 12 months |
    |---|---|---|---|---|---|---|
    | `anthropic` | none | 2.6.0 | 2026-11-05 | Apache-2.0 | >=3.10 | yes |
    | `openai` | none | 3.46.0 | 2026-11-05 | Apache-2.0 | >=3.10 | yes |
    | `PyYAML` | none | 6.0.3 | 2025-09-25 | MIT | >=3.8 | no (about 13.5 months) |
    | `respx` | none | 0.23.1 | 2026-04-08 | BSD-3-Clause | >=3.8 | yes |
    | `pytest-httpserver` | none | 1.2.0 | 2026-10-05 | MIT | >=3.10 | yes |

    - `uv` 0.13.5 is at `/opt/homebrew/bin/uv`. `httpx` is not installed either. The two SDKs bring it in.
    - The latest `anthropic` and `openai` match the versions checked at the start of the project, on 2026-11-09. Both were released 4 days ago. `AGENTS.md` sets no minimum age. A two-week minimum was my own test, not a repo rule. Under it, the newest versions that pass are `anthropic` 2.3.0 and `openai` 3.37.0. I have not checked whether they behave the same, and the retry defaults in section 5 are for 2.6.0 and 3.46.0.
    - `PyYAML` has had no release for about 13.5 months. It is a mature parser, and I recommend accepting it.
    - Mock library: the T2 recommendation of `respx` is **withdrawn** (see T3): the SDKs use `httpx2`, not `httpx`. Checked on 2026-11-09: `httpx2` 2.16.0 ships `httpx2.MockTransport` (a handler function that returns canned responses, no port). It is the chosen mock (D31), so no mock library is needed. Verified by reading the wheel source (sha256 `fd2c5d79...bbf0308d49a`), not run.
    - [x] **T3. SDK facts.** Read the source of the pinned SDK versions and record the answers to F1 to F9 below. Change `requirements.md` where the source disagrees with it.
  - Waits for: T2, for the approved package versions. Without them there is nothing to pin.
  - Method: download the packages into a new empty scratch directory, outside the repo. Run any Python that reads them with `-I`. Treat the files as untrusted data.
  - Done when: each of F1 to F9 has an answer with a source file and line, and a changed or confirmed line in `requirements.md`.
  - State: **done** (2026-11-09). Subagent, read-only. Wheels downloaded to a scratch directory under `/tmp`, read with grep, never imported or run. Verified by reading only. No SDK code was run.
  - Wheels: `anthropic-2.6.0-py3-none-any.whl` sha256 `4325cdf9346fa29183674b6ee6289ebad5b2b0a935758f7350fa504032da1d9b`. `openai-3.46.0-py3-none-any.whl` sha256 `7b650117e9bf539029bf880c2eff94a26f281394f6572284efa5d068d4b1c98e`. `__version__` is `2.6.0` and `3.46.0`.
  - Results (the source file and line for each is in the subagent report; the parent spot-checked the dependency finding only):
    - F1 confirmed: both retry 2 times. Turn off with `max_retries=0`. Section 5 is updated.
    - F2 confirmed: 429 `RateLimitError`, 5xx `InternalServerError`, 401 `AuthenticationError`, 403 `PermissionDeniedError`, 400 `BadRequestError`, any timeout `APITimeoutError`. The SDKs also retry 408 and 409.
    - F3 **gap**: neither SDK separates a context overflow. The adapter reads the body. Section 4 is updated. Unverified against a real server.
    - F4: three forms (`retry-after-ms`, seconds, HTTP date). Answered as D29.
    - F5 **gap**: a spent-quota 429 is not separated. Answered as D27.
    - F6 confirmed: `input_tokens_details.cached_tokens` and `cache_write_tokens` exist. `Response.usage` is optional. This does not settle D25, because Gemini may not fill them.
    - F7 **not stated** in either SDK. Answered as D30.
    - F8 confirmed: Anthropic `cache_read_input_tokens` and `cache_creation_input_tokens`, both optional.
    - F9 confirmed: usage is `None` when absent, with no error unless strict validation is on.
    - Also found: statuses 408, 409, 413, 422 and 529 are missing from section 4 (answered as D28). The SDK default read timeout is 600 s, so the adapter passes 30 s.
  - New finding, affects T2: **both SDKs depend on `httpx2` (2.16.0 on PyPI), not `httpx`.** `openai` needs `httpx2>=2.12.0` and `anthropic` needs `httpx2>=2.0.0`. Both import only `httpx2` and accept an `httpx2.Client` as `http_client`. `respx` (0.23.1) depends on `httpx`, so it would **not** intercept their requests. T2's recommendation of `respx` is withdrawn. I checked the dependency lists and the imports by reading. I have not run anything, and I have not checked whether `httpx2` has its own mock transport.
- [x] **T4. Gemini live check (D25).** `scripts/check_gemini_usage.py` sends one call to `<GOOGLE_GEMINI_BASE_URL>/responses` and prints only usage field names and types.
  - Steps (from the repo root):
    1. Export `GOOGLE_GEMINI_BASE_URL` and `GEMINI_API_KEY` in your shell.
    2. Run `uv run python scripts/check_gemini_usage.py --list` to see the Gemini model ids your key can use.
    3. Run `uv run python scripts/check_gemini_usage.py <one of those ids>`. Exit 0 means the required fields are present.
  - The script prints no key, no value, no request and no reply text. On an HTTP error it prints the status and the error's `type`, `param` and `code` only.
  - State: **done** (2026-11-09). The owner's first runs failed. The agent found two causes and fixed the script:
    1. The edge firewall in front of the configured endpoint returns a plain-text 403 to Python's default `Python-urllib` User-Agent. The script now sends its own User-Agent.
    2. The model id used was not available to the key (`team_model_access_denied`). The script now has `--list`.
  - Result: the agent ran the script with the owner's environment, at the owner's request. All three Gemini models that the key can use returned HTTP 200 with the same usage shape:
    - Present as integers: `input_tokens`, `output_tokens`, `total_tokens`, `input_tokens_details.cached_tokens`, `input_tokens_details.text_tokens`, `output_tokens_details.reasoning_tokens`, `output_tokens_details.text_tokens`.
    - Present but null: `input_tokens_details.audio_tokens`, `image_tokens`, `video_tokens`, `cached_tokens_details`, `output_tokens_details.audio_tokens`, `cost`.
    - Absent: `input_tokens_details.cache_write_tokens`.
  - Limits: one prompt per model, with no cache hit, so a non-zero `cached_tokens` was not seen. The endpoint is the configured gateway, not Google's endpoint directly. The result holds for this endpoint only. Not run on Windows or Linux.
- [x] **T5. Skills copies.** The owner decided on 2026-11-09 to vendor real copies of the 34 files in `.claude/skills/`, not symlinks.
  - Result: the 11 absolute-path symlinks are replaced by real files. Each directory matched its source with `diff -r` at copy time. Four of the files still name their upstream project, because they are unedited copies. They can drift from the source, and nothing updates them.
  - Checked: `block-dangerous-git.sh` keeps its executable bit. Not checked: use on Windows.
- [x] **T6. Write the build task list.** Written on 2026-11-09 as `docs/tasks/build-2026-11-09.md`. Owner approved writing it. B1 to B8 are not started; each waits for the owner's go-ahead. A new file under `docs/tasks/`, with acceptance criteria for each task.
  - Waits for: T1 and T3 are done. O9 to O12 are answered (D27 to D30, 2026-11-09). The mock library (D31) and PyYAML (D32) are settled. T4 is done. Nothing blocks it. T6 is not started.
  - Outline: types and core with a fake adapter; the Anthropic adapter and the Responses adapter, each against a mock server; the usage callback, `validate()` and `load_config`; the conformance suite.
  - Done when: the file exists and the owner approves the tasks they name.

## Facts to check in T3

All are unverified. Several come from memory of the SDKs, not from source.

| # | Fact | Why the spec needs it |
|---|------|-----------------------|
| F1 | The SDK retry default, and how to turn retries off, for each of `anthropic` and `openai` | AT-6, section 5 |
| F2 | The exception type for 429, 5xx, timeout, 401, 403 and 400 in each SDK | The adapter `classify` mapping |
| F3 | How each provider signals a context overflow: a 400 body, or a distinct code | D13, D20, AT-8, AT-10 |
| F4 | The `Retry-After` format: seconds, an HTTP date, or both. And which header the SDK exposes | D21, AT-11 |
| F5 | Whether a 429 that never clears (for example an exhausted quota) can be told apart from a rate limit. Section 4 would otherwise wait up to 65 s for nothing | Section 4. Not in the spec today |
| F6 | The Responses usage object: which fields exist, and where the cached-token count sits | D25 |
| F7 | Whether the SDK clients are safe to use from several threads | D23, AT-12 |
| F8 | Whether the Anthropic usage object reports cached and cache-write tokens, and under which names | Section 2 |
| F9 | What the SDK does when the response has no usage object | D14 |

## Later work, not a task yet

A drift check that reruns the fixture capture when an SDK pin changes, and fails if a retry default, an error type or a usage field has moved. It needs a CI job and a rule that a failing check blocks SDK upgrades. The owner decides this after the conformance suite exists.

## Still unverified

the concurrency question (D23, not stated in any source), the usage glue's `model` versus `alias` (the caller's decision), the Mermaid diagram (`mmdc` is not installed), the worst-case times in section 5 (arithmetic only), and every T3 result (read from source, not run).
