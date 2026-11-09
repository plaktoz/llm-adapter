"""Anthropic adapter tests. Every test uses httpx2.MockTransport and needs no real key (D31).

The response bodies here are written by hand from the SDK's types. None was captured from a
real server. Context-overflow bodies stay unverified (requirements section 4, F3).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from llm_adapter.adapters.anthropic import AnthropicAdapter, build_client
from llm_adapter.types import ErrorClass, Message, Request, Usage

BASE_URL = "https://gateway.test"
CANARY_KEY = "canary-key-7f3a9c"
MODEL = "test-model"

Handler = Callable[[httpx2.Request], httpx2.Response]


def _message_body(
    *, text: str = "hello", stop_reason: str | None = "end_turn", usage: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


def _error_response(status: int, error_type: str, message: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    return httpx2.Response(status, json=body)


def _adapter(handler: Handler) -> tuple[AnthropicAdapter, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    http_client = httpx2.Client(transport=httpx2.MockTransport(recording))
    adapter = AnthropicAdapter(base_url=BASE_URL, api_key=CANARY_KEY, http_client=http_client)
    return adapter, seen


def _request(text: str = "hi") -> Request:
    return Request(alias="default", messages=[Message(role="user", text=text)])


def _classify_status(status: int, error_type: str, message: str) -> ErrorClass:
    adapter, _ = _adapter(lambda _r: _error_response(status, error_type, message))
    with pytest.raises(anthropic.APIStatusError) as info:
        adapter.complete(_request(), MODEL, 30.0)
    assert info.value.status_code == status
    return adapter.classify(info.value)


# --- Client construction (AT-6, D30) -------------------------------------------------------


def test_client_has_sdk_retries_off_and_timeout_30() -> None:
    client = build_client(base_url=BASE_URL, api_key=CANARY_KEY)
    assert client.max_retries == 0
    assert client.timeout == 30.0


def test_one_http_request_per_attempt_for_each_failing_status() -> None:
    # AT-6: the SDK must not retry on its own. Each status is one request, not three.
    for status, error_type in [(429, "rate_limit_error"), (500, "api_error"), (408, "x")]:
        adapter, seen = _adapter(lambda _r, s=status, t=error_type: _error_response(s, t, "x"))
        with pytest.raises(anthropic.APIError):
            adapter.complete(_request(), MODEL, 30.0)
        assert len(seen) == 1, f"status {status} made {len(seen)} requests"


def test_one_http_request_per_attempt_on_connection_error() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    adapter, seen = _adapter(refuse)
    with pytest.raises(anthropic.APIConnectionError):
        adapter.complete(_request(), MODEL, 30.0)
    assert len(seen) == 1


def test_complete_passes_per_call_timeout_to_the_request() -> None:
    adapter, seen = _adapter(lambda _r: httpx2.Response(200, json=_message_body(usage=None)))
    adapter.complete(_request(), MODEL, 7.5)
    assert seen[0].extensions["timeout"]["read"] == 7.5


def test_one_client_per_thread() -> None:
    adapter, _ = _adapter(lambda _r: httpx2.Response(200, json=_message_body(usage=None)))
    clients: dict[str, object] = {}

    def grab(name: str) -> None:
        adapter.complete(_request(), MODEL, 30.0)
        clients[name] = adapter._client()

    threads = [threading.Thread(target=grab, args=(f"t{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    grab("main")
    assert len({id(c) for c in clients.values()}) == 4


# --- Request and response mapping ---------------------------------------------------------


def test_request_maps_to_messages_call_and_reply_to_response() -> None:
    body = _message_body(
        text="reply text",
        usage={"input_tokens": 12, "output_tokens": 5},
    )
    seen_body: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_body.update(json.loads(request.content))
        return httpx2.Response(200, json=body)

    adapter, seen = _adapter(handler)
    request = Request(
        alias="default",
        messages=[Message(role="user", text="question")],
        max_output_tokens=256,
        temperature=0.2,
        system="be brief",
    )
    response = adapter.complete(request, MODEL, 30.0)

    assert seen[0].url.path == "/v1/messages"
    assert seen[0].headers["authorization"] == f"Bearer {CANARY_KEY}"
    assert seen_body == {
        "model": MODEL,
        "max_tokens": 256,
        "messages": [{"role": "user", "content": "question"}],
        "system": "be brief",
        "temperature": 0.2,
    }
    assert response.text == "reply text"
    assert response.stop_reason == "end_turn"
    assert response.model_used == MODEL
    assert response.provider_used == "anthropic"
    assert response.attempts == ()


def test_optional_request_fields_are_omitted_from_the_body() -> None:
    seen_body: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_body.update(json.loads(request.content))
        return httpx2.Response(200, json=_message_body(usage=None))

    adapter, _ = _adapter(handler)
    adapter.complete(_request(), MODEL, 30.0)
    assert "system" not in seen_body
    assert "temperature" not in seen_body
    assert seen_body["max_tokens"] == 4096


# --- Usage (section 2, D14, D25) -----------------------------------------------------------


def test_usage_maps_cache_fields() -> None:
    body = _message_body(
        usage={
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 15,
        }
    )
    adapter, _ = _adapter(lambda _r: httpx2.Response(200, json=body))
    response = adapter.complete(_request(), MODEL, 30.0)
    assert response.usage == Usage(
        input_tokens=100,
        output_tokens=20,
        cached_input_tokens=80,
        cache_write_tokens=15,
    )


def test_missing_cache_fields_leave_those_fields_unset_not_zero() -> None:
    body = _message_body(usage={"input_tokens": 9, "output_tokens": 3})
    adapter, _ = _adapter(lambda _r: httpx2.Response(200, json=body))
    usage = adapter.complete(_request(), MODEL, 30.0).usage
    assert usage == Usage(input_tokens=9, output_tokens=3)
    assert usage is not None
    assert usage.cached_input_tokens is None
    assert usage.cache_write_tokens is None


def test_missing_usage_object_leaves_usage_absent_not_an_error() -> None:
    adapter, _ = _adapter(lambda _r: httpx2.Response(200, json=_message_body(usage=None)))
    response = adapter.complete(_request(), MODEL, 30.0)
    assert response.usage is None
    assert response.text == "hello"


def test_refusal_returns_stop_reason_refusal() -> None:
    body = _message_body(
        text="", stop_reason="refusal", usage={"input_tokens": 4, "output_tokens": 0}
    )
    adapter, _ = _adapter(lambda _r: httpx2.Response(200, json=body))
    response = adapter.complete(_request(), MODEL, 30.0)
    assert response.stop_reason == "refusal"
    assert response.text == ""


def test_missing_stop_reason_is_empty_string() -> None:
    body = _message_body(stop_reason=None, usage=None)
    adapter, _ = _adapter(lambda _r: httpx2.Response(200, json=body))
    assert adapter.complete(_request(), MODEL, 30.0).stop_reason == ""


# --- classify (section 4, D28) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error_type", "expected"),
    [
        (429, "rate_limit_error", ErrorClass.RATE_LIMITED),
        (500, "api_error", ErrorClass.SERVER_ERROR),
        (502, "api_error", ErrorClass.SERVER_ERROR),
        (503, "api_error", ErrorClass.SERVER_ERROR),
        (504, "api_error", ErrorClass.SERVER_ERROR),
        (529, "overloaded_error", ErrorClass.SERVER_ERROR),
        (409, "conflict_error", ErrorClass.SERVER_ERROR),
        (408, "timeout_error", ErrorClass.TIMEOUT),
        (401, "authentication_error", ErrorClass.AUTH),
        (403, "permission_error", ErrorClass.AUTH),
        (422, "invalid_request_error", ErrorClass.INVALID_REQUEST),
        (404, "not_found_error", ErrorClass.INVALID_REQUEST),
        (400, "invalid_request_error", ErrorClass.INVALID_REQUEST),
    ],
)
def test_classify_maps_each_status(status: int, error_type: str, expected: ErrorClass) -> None:
    assert _classify_status(status, error_type, "some reason") is expected


def test_classify_413_without_overflow_body_is_invalid_request() -> None:
    message = "Request body is too large."
    assert _classify_status(413, "request_too_large", message) is ErrorClass.INVALID_REQUEST


def test_classify_413_with_overflow_body_is_context_overflow() -> None:
    # Phrase verified by a live probe on 2026-11-09 (F3). The full text here is written, not copied.
    message = "prompt is too long: 300000 tokens > 200000 maximum"
    assert _classify_status(413, "request_too_large", message) is ErrorClass.CONTEXT_OVERFLOW


def test_classify_400_with_overflow_body_is_context_overflow() -> None:
    # Phrase verified by a live probe on 2026-11-09 (F3). The full text here is written, not copied.
    message = "prompt is too long: 300000 tokens > 200000 maximum"
    assert _classify_status(400, "invalid_request_error", message) is ErrorClass.CONTEXT_OVERFLOW


def test_classify_400_without_overflow_body_is_invalid_request() -> None:
    message = "messages: field required"
    assert _classify_status(400, "invalid_request_error", message) is ErrorClass.INVALID_REQUEST


def test_classify_timeout_error() -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    adapter, _ = _adapter(slow)
    with pytest.raises(anthropic.APITimeoutError) as info:
        adapter.complete(_request(), MODEL, 30.0)
    assert adapter.classify(info.value) is ErrorClass.TIMEOUT


def test_classify_connection_error_is_timeout() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    adapter, _ = _adapter(refuse)
    with pytest.raises(anthropic.APIConnectionError) as info:
        adapter.complete(_request(), MODEL, 30.0)
    assert not isinstance(info.value, anthropic.APITimeoutError)
    assert adapter.classify(info.value) is ErrorClass.TIMEOUT


def test_classify_re_raises_a_non_sdk_exception() -> None:
    adapter, _ = _adapter(lambda _r: httpx2.Response(200, json=_message_body(usage=None)))
    bug = ValueError("bug")
    with pytest.raises(ValueError) as info:
        adapter.classify(bug)
    assert info.value is bug


# --- Secrets (section 6, AT-5) -------------------------------------------------------------


@pytest.mark.parametrize(
    "handler",
    [
        lambda _r: _error_response(401, "authentication_error", "invalid key"),
        lambda _r: _error_response(500, "api_error", "server broke"),
        lambda _r: httpx2.Response(500, text="not json"),
    ],
)
def test_canary_key_is_in_no_error_message(handler: Handler) -> None:
    adapter, _ = _adapter(handler)
    with pytest.raises(anthropic.APIError) as info:
        adapter.complete(_request(), MODEL, 30.0)
    assert CANARY_KEY not in str(info.value)
    assert CANARY_KEY not in repr(info.value)


def test_canary_key_is_in_no_connection_error_message() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    adapter, _ = _adapter(refuse)
    with pytest.raises(anthropic.APIConnectionError) as info:
        adapter.complete(_request(), MODEL, 30.0)
    assert CANARY_KEY not in str(info.value)


def test_request_body_is_not_in_an_error_message() -> None:
    secret_text = "SECRET-PROMPT-TEXT-42"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return _error_response(400, "invalid_request_error", "bad field")

    adapter, _ = _adapter(handler)
    request = Request(alias="default", messages=[Message(role="user", text=secret_text)])
    with pytest.raises(anthropic.APIError) as info:
        adapter.complete(request, MODEL, 30.0)
    assert secret_text not in str(info.value)
