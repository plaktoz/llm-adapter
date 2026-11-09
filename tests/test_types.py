import dataclasses

import pytest

from llm_adapter.types import (
    Attempt,
    AuthError,
    ConfigError,
    ContextOverflow,
    ErrorClass,
    InvalidRequest,
    Message,
    ProviderExhausted,
    Request,
    Response,
    Usage,
    UsageEvent,
)


def names(cls: type) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def test_data_model_fields_match_requirements_section_2() -> None:
    assert names(Request) == ["alias", "messages", "max_output_tokens", "temperature", "system"]
    assert names(Response) == [
        "text",
        "stop_reason",
        "usage",
        "model_used",
        "provider_used",
        "attempts",
    ]
    assert names(Usage) == [
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
    ]
    assert names(Attempt) == ["provider", "model", "outcome", "latency_ms"]
    assert names(UsageEvent) == ["alias", "provider", "model", "usage", "latency_ms", "outcome"]


def test_request_has_no_metadata() -> None:
    with pytest.raises(TypeError):
        Request(alias="default", messages=[], metadata={})  # type: ignore[call-arg]


def test_build_each_type() -> None:
    usage = Usage(input_tokens=10, output_tokens=5)
    assert usage.cached_input_tokens is None
    assert usage.cache_write_tokens is None
    attempt = Attempt(provider="p", model="m", outcome="success", latency_ms=12)
    request = Request(alias="default", messages=[Message(role="user", text="hi")])
    assert request.system is None
    response = Response(
        text="ok",
        stop_reason="end_turn",
        usage=usage,
        model_used="m",
        provider_used="p",
        attempts=(attempt,),
    )
    assert response.attempts == (attempt,)
    event = UsageEvent(
        alias="default",
        provider="p",
        model="m",
        usage=None,
        latency_ms=12,
        outcome=ErrorClass.TIMEOUT,
    )
    assert event.usage is None


def test_error_class_values_are_the_outcome_names() -> None:
    assert {c.value for c in ErrorClass} == {
        "rate_limited",
        "server_error",
        "timeout",
        "auth",
        "context_overflow",
        "invalid_request",
        "content_filtered",
    }
    assert ErrorClass.RATE_LIMITED == "rate_limited"


@pytest.mark.parametrize("exc_type", [ProviderExhausted, AuthError, InvalidRequest])
def test_exceptions_carry_attempts(exc_type: type[Exception]) -> None:
    attempt = Attempt(provider="p", model="m", outcome=ErrorClass.AUTH, latency_ms=1)
    exc = exc_type("failed", [attempt])  # type: ignore[call-arg]
    assert exc.attempts == (attempt,)  # type: ignore[attr-defined]
    assert str(exc) == "failed"


def test_context_overflow_carries_the_model_limit() -> None:
    exc = ContextOverflow("too big", model_limit=1000)
    assert exc.model_limit == 1000


def test_config_error_is_an_exception() -> None:
    assert issubclass(ConfigError, Exception)
