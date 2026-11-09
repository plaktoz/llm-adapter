---
status: accepted
---

# Reach Gemini through the Responses wire format, not a native SDK

ADR-0003 in agentzero-v2-dev says to wrap the provider SDKs directly. The handoff recommended the native `google-genai` SDK for Gemini, unless a spike showed that the compatible endpoint was enough. The owner chose on 2026-11-09 to serve Gemini with the OpenAI SDK on the Responses wire format. The Gemini provider has its own base URL and key variable. The working gateway config in `a2a-poc` already reaches Gemini this way.

## Considered options

- **Native `google-genai` SDK.** It keeps Gemini-specific features. It adds a third SDK, and a third client whose own retries must be turned off.
- **A spike first.** It checks tool calls and usage fields on the compatible endpoint. The owner skipped it, because no v1 caller needs tool calls.

## Consequences

- Version 1 needs no `gemini.py` adapter. One Responses adapter serves OpenAI and Gemini.
- Gemini-specific features are not available in v1. A native adapter is a v2 option.
- No one has checked the usage fields that the Gemini endpoint returns. The requirements list this as open item O7.
