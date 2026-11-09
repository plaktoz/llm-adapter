"""Responses adapter: one adapter for OpenAI and Gemini (ADR 0001, D3, D9).

It maps `Request` to the Responses call and the reply to `Response`, and classifies SDK
exceptions. It owns no retry and no failover (requirements section 4). It logs nothing.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx2
import openai

from llm_adapter.types import ErrorClass, Request, Response, Usage

SDK_TIMEOUT = 30.0

# The SDK does not separate a context overflow from any other 400 (requirements section 4, F3).
# A live probe on 2026-11-09 showed that OpenAI sends HTTP 400 with code "400" (not
# context_length_exceeded) and a message that contains "context window". That marker is verified.
# The code and the other markers are guesses. Gemini accepted a 4 MB prompt, so its overflow
# shape is still unknown.
_OVERFLOW_CODES = frozenset({"context_length_exceeded"})
_OVERFLOW_MARKERS = ("context window", "context length", "maximum context", "too many tokens")


def build_client(
    api_key: str,
    base_url: str | None = None,
    http_client: httpx2.Client | None = None,
) -> openai.OpenAI:
    """Build an SDK client with the SDK's own retries off (AT-6) and the 30 s timeout."""
    return openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        max_retries=0,
        timeout=SDK_TIMEOUT,
    )


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _map_usage(usage: Any) -> Usage | None:
    """Read the three fields of D25. A missing or non-integer field leaves usage absent (D14)."""
    if usage is None:
        return None
    details = getattr(usage, "input_tokens_details", None)
    input_tokens = _int_or_none(getattr(usage, "input_tokens", None))
    output_tokens = _int_or_none(getattr(usage, "output_tokens", None))
    cached = _int_or_none(getattr(details, "cached_tokens", None))
    if input_tokens is None or output_tokens is None or cached is None:
        return None
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached,
        cache_write_tokens=_int_or_none(getattr(details, "cache_write_tokens", None)),
    )


def _stop_reason(resp: Any) -> str:
    """`refusal` for a refusal item or a content filter (section 4); else a plain reason."""
    incomplete = getattr(resp, "incomplete_details", None)
    reason = getattr(incomplete, "reason", None)
    if reason == "content_filter":
        return "refusal"
    for item in getattr(resp, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return "refusal"
    return reason if isinstance(reason, str) else "stop"


def _is_context_overflow(exc: openai.APIStatusError) -> bool:
    code = exc.code
    if code is not None and code in _OVERFLOW_CODES:
        return True
    message = (exc.message or "").lower()
    return any(marker in message for marker in _OVERFLOW_MARKERS)


class ResponsesAdapter:
    """Serves one provider (OpenAI or Gemini) on the Responses wire."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str | None = None,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self._provider = provider
        self._api_key = api_key
        self._base_url = base_url
        self._http_client = http_client
        self._local = threading.local()

    def _client(self) -> openai.OpenAI:
        """One SDK client per thread (D30)."""
        client = getattr(self._local, "client", None)
        if client is None:
            client = build_client(self._api_key, self._base_url, self._http_client)
            self._local.client = client
        return client

    def complete(self, request: Request, model: str, timeout: float) -> Response:
        params: dict[str, Any] = {
            "model": model,
            "input": [{"role": m.role, "content": m.text} for m in request.messages],
            "timeout": timeout,
        }
        if request.system is not None:
            params["instructions"] = request.system
        if request.max_output_tokens is not None:
            params["max_output_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            params["temperature"] = request.temperature
        resp = self._client().responses.create(**params)
        used = getattr(resp, "model", None)
        return Response(
            text=resp.output_text,
            stop_reason=_stop_reason(resp),
            usage=_map_usage(getattr(resp, "usage", None)),
            model_used=used if isinstance(used, str) and used else model,
            provider_used=self._provider,
            attempts=(),
        )

    def classify(self, exc: BaseException) -> ErrorClass:
        if isinstance(exc, openai.APITimeoutError):
            return ErrorClass.TIMEOUT
        if isinstance(exc, openai.APIConnectionError):
            return ErrorClass.TIMEOUT
        if isinstance(exc, openai.APIStatusError):
            status = exc.status_code
            if status in (401, 403):
                return ErrorClass.AUTH
            if status == 429:
                return ErrorClass.RATE_LIMITED
            if status == 408:
                return ErrorClass.TIMEOUT
            if status == 409 or status >= 500:
                return ErrorClass.SERVER_ERROR
            if status in (400, 413) and _is_context_overflow(exc):
                return ErrorClass.CONTEXT_OVERFLOW
            return ErrorClass.INVALID_REQUEST
        if isinstance(exc, openai.APIError):
            return ErrorClass.INVALID_REQUEST
        raise exc
