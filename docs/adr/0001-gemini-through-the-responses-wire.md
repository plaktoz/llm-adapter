---
status: accepted
---

# Reach Gemini through the Responses wire format, not a native SDK

The library wraps the provider SDKs directly. The first draft of the requirements recommended the native `google-genai` SDK for Gemini, unless a spike showed that the compatible endpoint was enough. The owner chose on 2026-11-09 to serve Gemini with the OpenAI SDK on the Responses wire format. The Gemini provider has its own base URL and key variable.

## Considered options

- **Native `google-genai` SDK.** It keeps Gemini-specific features. It adds a third SDK, and a third client whose own retries must be turned off.
- **A spike first.** It checks tool calls and usage fields on the compatible endpoint. The owner skipped it, because no v1 caller needs tool calls.

## Consequences

- Version 1 needs no `gemini.py` adapter. One Responses adapter serves OpenAI and Gemini.
- Gemini-specific features are not available in v1. A native adapter is a v2 option.
- No one has checked the usage fields that the Gemini endpoint returns (open item O7). On 2026-11-09 the owner accepted the risk (D25). The adapter reads the Responses usage fields, and a missing field leaves usage absent. The live check (T4, `scripts/check_gemini_usage.py`) passed on 2026-11-09. The configured Gemini endpoint returns `input_tokens`, `output_tokens` and `input_tokens_details.cached_tokens` on the Responses wire. It does not return `cache_write_tokens`. The check covers that endpoint only.
