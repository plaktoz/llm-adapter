"""Tests for the Responses adapter. Every body here is written by hand, not captured from a
server. The context-overflow bodies in particular are unverified guesses (requirements F3)."""

import json
import threading
from collections.abc import Callable

import httpx2
import openai
import pytest

from llm_adapter.adapters import responses
from llm_adapter.adapters.responses import ResponsesAdapter
from llm_adapter.types import ErrorClass, Message, Request

CANARY = "sk-canary-7f3a91d2"
BASE_URL = "https://provider.example/v1"


def _body(text: str = "hello", usage: object = "default", **extra: object) -> dict:
    # The usage shape T4 recorded on the Gemini endpoint: input_tokens, output_tokens and
    # input_tokens_details.cached_tokens as integers, no cache_write_tokens, plus
    # output_tokens_details.reasoning_tokens.
    if usage == "default":
        usage = {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
    body = {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "served-model",
        "status": "completed",
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }
    if usage is not None:
        body["usage"] = usage
    body.update(extra)
    return body


def _make(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> tuple[ResponsesAdapter, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    client = httpx2.Client(transport=httpx2.MockTransport(wrapped))
    return ResponsesAdapter("gemini", CANARY, BASE_URL, client), seen


def _ok(body: dict) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda request: httpx2.Response(200, json=body)


def _status(code: int, body: object = None, headers: dict | None = None):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(code, json=body or {"error": {"message": "x"}}, headers=headers)

    return handler


REQ = Request(alias="default", messages=[Message("user", "hi")], system="be brief")


def _raised(adapter: ResponsesAdapter) -> BaseException:
    with pytest.raises(openai.OpenAIError) as info:
        adapter.complete(REQ, "m", 30)
    return info.value


def test_sdk_retries_disabled() -> None:
    client = responses.build_client(CANARY, BASE_URL)
    assert client.max_retries == 0
    assert client.timeout == 30


def test_builder_uses_given_http_client_and_base_url() -> None:
    adapter, seen = _make(_ok(_body()))
    adapter.complete(REQ, "m", 30)
    assert str(seen[0].url) == f"{BASE_URL}/responses"


def test_sdk_retries_disabled_one_request_per_attempt() -> None:
    for code in (429, 500, 529, 408, 409):
        adapter, seen = _make(_status(code))
        _raised(adapter)
        assert len(seen) == 1, code


def test_timeout_makes_one_request_and_no_sdk_retry() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    adapter, seen = _make(boom)
    exc = _raised(adapter)
    assert isinstance(exc, openai.APITimeoutError)
    assert len(seen) == 1


def test_request_mapping() -> None:
    adapter, seen = _make(_ok(_body()))
    request = Request(
        alias="a",
        messages=[Message("user", "q"), Message("assistant", "a"), Message("user", "q2")],
        max_output_tokens=50,
        temperature=0.2,
        system="sys",
    )
    adapter.complete(request, "model-x", 30)
    sent = json.loads(seen[0].content)
    assert sent["model"] == "model-x"
    assert sent["instructions"] == "sys"
    assert sent["max_output_tokens"] == 50
    assert sent["temperature"] == 0.2
    assert sent["input"] == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "q2"},
    ]
    assert "store" not in sent
    assert "stream" not in sent


def test_optional_fields_are_left_out() -> None:
    adapter, seen = _make(_ok(_body()))
    adapter.complete(Request(alias="a", messages=[Message("user", "q")]), "m", 30)
    sent = json.loads(seen[0].content)
    assert not {"instructions", "max_output_tokens", "temperature"} & sent.keys()


def test_response_mapping_and_usage_from_t4_shape() -> None:
    adapter, _ = _make(_ok(_body("the answer")))
    result = adapter.complete(REQ, "m", 30)
    assert result.text == "the answer"
    assert result.stop_reason == "stop"
    assert result.model_used == "served-model"
    assert result.provider_used == "gemini"
    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 7)
    assert result.usage.cached_input_tokens == 3
    assert result.usage.cache_write_tokens is None


def test_cache_write_tokens_read_when_present() -> None:
    usage = {
        "input_tokens": 1,
        "output_tokens": 2,
        "input_tokens_details": {
            "cached_tokens": 0,
            "cache_write_tokens": 5,
            "cache_write_tokens_details": {"ttl_12h_tokens": 0, "ttl_30m_tokens": 5},
        },
    }
    adapter, _ = _make(_ok(_body(usage=usage)))
    result = adapter.complete(REQ, "m", 30)
    assert result.usage is not None
    assert result.usage.cache_write_tokens == 5


def test_missing_usage_object_gives_none() -> None:
    adapter, _ = _make(_ok(_body(usage=None)))
    assert adapter.complete(REQ, "m", 30).usage is None


@pytest.mark.parametrize(
    "usage",
    [
        {"output_tokens": 7, "input_tokens_details": {"cached_tokens": 3}},
        {"input_tokens": 7, "input_tokens_details": {"cached_tokens": 3}},
        {"input_tokens": 7, "output_tokens": 7},
        {"input_tokens": 7, "output_tokens": 7, "input_tokens_details": {}},
        {"input_tokens": 7, "output_tokens": None, "input_tokens_details": {"cached_tokens": 1}},
        {},
    ],
)
def test_missing_usage_field_gives_none_not_zero_not_error(usage: dict) -> None:
    adapter, _ = _make(_ok(_body(usage=usage)))
    assert adapter.complete(REQ, "m", 30).usage is None


def test_refusal_item_returns_refusal() -> None:
    body = _body()
    body["output"] = [
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "refusal", "refusal": "no"}],
        }
    ]
    adapter, _ = _make(_ok(body))
    result = adapter.complete(REQ, "m", 30)
    assert result.stop_reason == "refusal"
    assert result.text == ""


def test_content_filter_returns_refusal() -> None:
    body = _body(status="incomplete", incomplete_details={"reason": "content_filter"})
    adapter, _ = _make(_ok(body))
    assert adapter.complete(REQ, "m", 30).stop_reason == "refusal"


def test_max_output_tokens_stop_reason() -> None:
    body = _body(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    adapter, _ = _make(_ok(body))
    assert adapter.complete(REQ, "m", 30).stop_reason == "max_output_tokens"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (429, ErrorClass.RATE_LIMITED),
        (500, ErrorClass.SERVER_ERROR),
        (502, ErrorClass.SERVER_ERROR),
        (503, ErrorClass.SERVER_ERROR),
        (529, ErrorClass.SERVER_ERROR),
        (409, ErrorClass.SERVER_ERROR),
        (408, ErrorClass.TIMEOUT),
        (401, ErrorClass.AUTH),
        (403, ErrorClass.AUTH),
        (400, ErrorClass.INVALID_REQUEST),
        (422, ErrorClass.INVALID_REQUEST),
        (413, ErrorClass.INVALID_REQUEST),
        (404, ErrorClass.INVALID_REQUEST),
    ],
)
def test_classify_status(code: int, expected: ErrorClass) -> None:
    adapter, _ = _make(_status(code))
    assert adapter.classify(_raised(adapter)) is expected


def test_classify_timeout_and_connection_error() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    adapter, _ = _make(refuse)
    exc = _raised(adapter)
    assert isinstance(exc, openai.APIConnectionError)
    assert adapter.classify(exc) is ErrorClass.TIMEOUT
    adapter, _ = _make(slow)
    assert adapter.classify(_raised(adapter)) is ErrorClass.TIMEOUT


@pytest.mark.parametrize("status", [400, 413])
@pytest.mark.parametrize(
    "error",
    [
        {"code": "context_length_exceeded", "message": "too long"},
        {"code": "400", "message": "Input exceeds the context window of this model."},
        {"type": "invalid_request_error", "message": "Input exceeds the context window."},
    ],
)
def test_overflow_body_on_400_and_413(status: int, error: dict) -> None:
    adapter, _ = _make(_status(status, {"error": error}))
    assert adapter.classify(_raised(adapter)) is ErrorClass.CONTEXT_OVERFLOW


def test_other_400_is_invalid_request() -> None:
    body = {"error": {"code": "invalid_value", "message": "bad temperature"}}
    adapter, _ = _make(_status(400, body))
    assert adapter.classify(_raised(adapter)) is ErrorClass.INVALID_REQUEST


def test_non_json_400_body_is_invalid_request() -> None:
    adapter, _ = _make(lambda request: httpx2.Response(400, text="<html>firewall</html>"))
    assert adapter.classify(_raised(adapter)) is ErrorClass.INVALID_REQUEST


def test_classify_does_not_swallow_unknown_exceptions() -> None:
    adapter, _ = _make(_ok(_body()))
    with pytest.raises(KeyError):
        adapter.classify(KeyError("bug"))


def test_one_client_per_thread() -> None:
    adapter, _ = _make(_ok(_body()))
    clients: list[object] = []

    def grab() -> None:
        clients.append(adapter._client())
        clients.append(adapter._client())

    grab()
    thread = threading.Thread(target=grab)
    thread.start()
    thread.join()
    assert clients[0] is clients[1]
    assert clients[2] is clients[3]
    assert clients[0] is not clients[2]


@pytest.mark.parametrize("code", [400, 401, 403, 429, 500])
def test_canary_key_not_in_raised_errors(code: int) -> None:
    adapter, _ = _make(_status(code))
    exc = _raised(adapter)
    assert CANARY not in str(exc)
    assert CANARY not in repr(exc)


def test_canary_key_not_in_connection_error() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    adapter, _ = _make(refuse)
    exc = _raised(adapter)
    assert CANARY not in str(exc)
    assert CANARY not in repr(exc)


def test_adapter_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    adapter, _ = _make(_ok(_body("secret reply text")))
    with caplog.at_level(0):
        adapter.complete(REQ, "m", 30)
    assert CANARY not in caplog.text
    assert "secret reply text" not in caplog.text
    assert "be brief" not in caplog.text
