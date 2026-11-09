"""Anthropic adapter: SDK client, type conversion, usage and exception mapping.

The adapter maps the Messages wire to the shared types and nothing else. Retry and failover
belong to the core (requirements sections 4 and 5).
"""

from __future__ import annotations

import threading

import anthropic
import httpx2

from llm_adapter.types import ErrorClass, Request, Response, Usage

PROVIDER = "anthropic"
CLIENT_TIMEOUT_SECONDS = 30.0
# The Messages API requires max_tokens. Requirements section 2 makes max_output_tokens optional
# and gives no default, so this is the smallest safe choice (listed in the B5 report).
DEFAULT_MAX_OUTPUT_TOKENS = 4096

# Verified by a live probe on 2026-11-09 (requirements F3): an over-window prompt returns HTTP
# 400, type invalid_request_error, and a message that contains "prompt is too long". The probe
# recorded the shape only, not the text. No other phrase is confirmed.
_OVERFLOW_PHRASES = ("prompt is too long",)


def build_client(
    *, base_url: str, api_key: str, http_client: httpx2.Client | None = None
) -> anthropic.Anthropic:
    """Build an SDK client with the SDK's own retries off (requirements section 5, AT-6)."""
    return anthropic.Anthropic(
        base_url=base_url,
        auth_token=api_key,
        max_retries=0,
        timeout=CLIENT_TIMEOUT_SECONDS,
        http_client=http_client,
    )


class AnthropicAdapter:
    """Calls the Messages API. Each thread builds and keeps its own SDK client (D30)."""

    def __init__(
        self, *, base_url: str, api_key: str, http_client: httpx2.Client | None = None
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._http_client = http_client
        self._local = threading.local()

    def _client(self) -> anthropic.Anthropic:
        client: anthropic.Anthropic | None = getattr(self._local, "client", None)
        if client is None:
            client = build_client(
                base_url=self._base_url, api_key=self._api_key, http_client=self._http_client
            )
            self._local.client = client
        return client

    def complete(self, request: Request, model: str, timeout: float) -> Response:
        message = self._client().messages.create(
            model=model,
            max_tokens=request.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
            messages=[{"role": m.role, "content": m.text} for m in request.messages],
            system=request.system if request.system is not None else anthropic.omit,
            # This SDK version has no named `temperature` argument, so it goes in the body.
            extra_body=None
            if request.temperature is None
            else {"temperature": request.temperature},
            timeout=timeout,
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return Response(
            text=text,
            stop_reason=message.stop_reason or "",
            usage=_usage(message.usage),
            model_used=model,
            provider_used=PROVIDER,
            attempts=(),
        )

    def classify(self, exc: BaseException) -> ErrorClass:
        if isinstance(exc, anthropic.APIStatusError):
            return _classify_status(exc)
        # APITimeoutError subclasses APIConnectionError, so it is tested first.
        if isinstance(exc, anthropic.APITimeoutError):
            return ErrorClass.TIMEOUT
        if isinstance(exc, anthropic.APIConnectionError):
            # Refused or reset connections. Section 4 has no class for them, so they take
            # timeout (D36), as the Responses adapter does.
            return ErrorClass.TIMEOUT
        # Not an SDK error means a bug elsewhere. Re-raise it as it is (D39).
        raise exc


def _usage(usage: anthropic.types.Usage | None) -> Usage | None:
    """Map the usage object. A missing count leaves usage absent, not zero (D14, D25)."""
    if usage is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cache_read_input_tokens,
        cache_write_tokens=usage.cache_creation_input_tokens,
    )


def _classify_status(exc: anthropic.APIStatusError) -> ErrorClass:
    status = exc.status_code
    if status == 429:
        return ErrorClass.RATE_LIMITED
    if status == 408:
        return ErrorClass.TIMEOUT
    if status in (401, 403):
        return ErrorClass.AUTH
    if status == 409 or status >= 500:
        return ErrorClass.SERVER_ERROR
    if status in (400, 413) and _body_reports_overflow(exc):
        return ErrorClass.CONTEXT_OVERFLOW
    return ErrorClass.INVALID_REQUEST


def _body_reports_overflow(exc: anthropic.APIStatusError) -> bool:
    message = (exc.api_message or "").lower()
    return any(phrase in message for phrase in _OVERFLOW_PHRASES)
