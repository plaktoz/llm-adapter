"""Behaviour of `Core.complete` against a fake adapter and a fake clock (requirements 8.2).

No test calls a provider, needs a key or waits in real time. The fake adapter stands in for an
SDK and implements the `Adapter` Protocol. Its `classify` returns the class the fake error was
built with, because mapping HTTP statuses is the adapter's job (B5 and B6), not the core's.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from email.utils import formatdate
from types import SimpleNamespace

import pytest

from llm_adapter.core import AliasSpec, Core, Route
from llm_adapter.types import (
    Adapter,
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

CONTEXT_WINDOW = 1000
EPOCH_NOW = 1_000_000.0


class FakeError(Exception):
    """An error that an SDK would raise, carrying the class the adapter gives it."""

    def __init__(self, kind: ErrorClass, headers: dict[str, str] | None = None) -> None:
        super().__init__(f"fake {kind.value}")
        self.kind = kind
        self.response = SimpleNamespace(headers=headers or {}) if headers is not None else None


class UnexpectedCall(BaseException):
    """Raised when the fake runs out of script. A BaseException, so the core cannot swallow it."""


Reply = Response | FakeError
Respond = Callable[[Request, str], Reply]


class FakeAdapter:
    """Implements the `Adapter` Protocol. `respond` decides each reply, and `calls` records them."""

    def __init__(self, respond: Respond) -> None:
        self._respond = respond
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def complete(self, request: Request, model: str, timeout: float) -> Response:
        with self._lock:
            self.calls.append(model)
        reply = self._respond(request, model)
        if isinstance(reply, FakeError):
            raise reply
        return reply

    def classify(self, exc: BaseException) -> ErrorClass:
        if isinstance(exc, FakeError):
            return exc.kind
        raise TypeError("the fake classifies only FakeError")


def scripted(*replies: Reply) -> Respond:
    """Each call takes the next reply. A call past the end is a test failure."""
    queue = list(replies)

    def respond(_request: Request, _model: str) -> Reply:
        if not queue:
            raise UnexpectedCall("the adapter was called more often than the script allows")
        return queue.pop(0)

    return respond


def ok(text: str = "answer") -> Response:
    return Response(
        text=text,
        stop_reason="end_turn",
        usage=Usage(input_tokens=10, output_tokens=5),
        model_used="",
        provider_used="",
        attempts=(),
    )


def request(text: str = "hello", alias: str = "default") -> Request:
    return Request(alias=alias, messages=[Message(role="user", text=text)])


PRIMARY = "anthropic"
FALLBACK = "openai"


class Harness:
    """A core with a primary and a fallback, a fake sleep and a fake clock."""

    def __init__(
        self,
        primary: Respond,
        fallback: Respond | None = None,
        *,
        context_window: int = CONTEXT_WINDOW,
        with_fallback: bool = True,
    ) -> None:
        self.sleeps: list[float] = []
        self.events: list[UsageEvent] = []
        self.primary = FakeAdapter(primary)
        self.fallback = FakeAdapter(fallback or scripted())
        routes = [Route(PRIMARY, "model-a")]
        if with_fallback:
            routes.append(Route(FALLBACK, "model-b"))
        adapters: dict[str, Adapter] = {PRIMARY: self.primary, FALLBACK: self.fallback}
        self.core = Core(
            {"default": AliasSpec(routes=tuple(routes), context_window=context_window)},
            adapters,
            sleep=self.sleeps.append,
            clock=lambda: 0.0,
            wall_clock=lambda: EPOCH_NOW,
        )
        self.core.on_usage(self.events.append)


def test_error_sequence_matches_schedule() -> None:
    # 429, then 5xx, then timeout, then 401: the 401 is raised at once. The only wait is the 5 s
    # step of the first 429.
    h = Harness(
        scripted(
            FakeError(ErrorClass.RATE_LIMITED),
            FakeError(ErrorClass.SERVER_ERROR),
            FakeError(ErrorClass.TIMEOUT),
            FakeError(ErrorClass.AUTH),
        )
    )
    with pytest.raises(AuthError) as info:
        h.core.complete(request())
    assert [a.outcome for a in info.value.attempts] == [
        ErrorClass.RATE_LIMITED,
        ErrorClass.SERVER_ERROR,
        ErrorClass.TIMEOUT,
        ErrorClass.AUTH,
    ]
    assert h.sleeps == [5.0]
    assert h.fallback.calls == []


def test_rate_limit_schedule_waits_5_15_45_then_fails_over() -> None:
    h = Harness(
        scripted(*[FakeError(ErrorClass.RATE_LIMITED)] * 4),
        scripted(ok("from fallback")),
    )
    response = h.core.complete(request())
    assert h.sleeps == [5.0, 15.0, 45.0]
    assert h.primary.calls == ["model-a"] * 4
    assert response.provider_used == FALLBACK


def test_server_error_retries_three_times_with_no_wait_then_fails_over() -> None:
    h = Harness(
        scripted(*[FakeError(ErrorClass.SERVER_ERROR)] * 4),
        scripted(ok()),
    )
    h.core.complete(request())
    assert h.sleeps == []
    assert len(h.primary.calls) == 4


def test_timeout_retries_twice_with_no_wait_then_fails_over() -> None:
    h = Harness(
        scripted(*[FakeError(ErrorClass.TIMEOUT)] * 3),
        scripted(ok()),
    )
    h.core.complete(request())
    assert h.sleeps == []
    assert len(h.primary.calls) == 3


def test_exhaustion_raises_once() -> None:
    h = Harness(
        scripted(*[FakeError(ErrorClass.SERVER_ERROR)] * 4),
        scripted(*[FakeError(ErrorClass.SERVER_ERROR)] * 4),
    )
    with pytest.raises(ProviderExhausted) as info:
        h.core.complete(request())
    assert len(info.value.attempts) == 8
    assert [a.provider for a in info.value.attempts] == [PRIMARY] * 4 + [FALLBACK] * 4
    # Nothing retries after the raise: the fakes would have raised UnexpectedCall on a ninth call.
    assert h.primary.calls == ["model-a"] * 4
    assert h.fallback.calls == ["model-b"] * 4


def test_usage_event_per_attempt() -> None:
    # Four 429s exhaust the primary's schedule, so the event list covers five attempts.
    h = Harness(
        scripted(*[FakeError(ErrorClass.RATE_LIMITED)] * 4),
        scripted(ok()),
    )
    h.core.complete(request(alias="default"))
    assert [(e.alias, e.provider, e.model, e.outcome) for e in h.events] == [
        ("default", PRIMARY, "model-a", ErrorClass.RATE_LIMITED),
        ("default", PRIMARY, "model-a", ErrorClass.RATE_LIMITED),
        ("default", PRIMARY, "model-a", ErrorClass.RATE_LIMITED),
        ("default", PRIMARY, "model-a", ErrorClass.RATE_LIMITED),
        ("default", FALLBACK, "model-b", "success"),
    ]
    assert h.events[0].usage is None
    assert h.events[-1].usage == Usage(input_tokens=10, output_tokens=5)


def test_auth_error_on_fallback_raises_auth_error() -> None:
    h = Harness(
        scripted(*[FakeError(ErrorClass.SERVER_ERROR)] * 4),
        scripted(FakeError(ErrorClass.AUTH)),
    )
    with pytest.raises(AuthError) as info:
        h.core.complete(request())
    assert [(a.provider, a.outcome) for a in info.value.attempts] == [
        (PRIMARY, ErrorClass.SERVER_ERROR),
        (PRIMARY, ErrorClass.SERVER_ERROR),
        (PRIMARY, ErrorClass.SERVER_ERROR),
        (PRIMARY, ErrorClass.SERVER_ERROR),
        (FALLBACK, ErrorClass.AUTH),
    ]


def test_auth_error_on_primary_is_not_failed_over() -> None:
    h = Harness(scripted(FakeError(ErrorClass.AUTH)), scripted(ok()))
    with pytest.raises(AuthError):
        h.core.complete(request())
    assert h.fallback.calls == []


def test_context_overflow_does_not_fail_over() -> None:
    h = Harness(scripted(FakeError(ErrorClass.CONTEXT_OVERFLOW)), scripted(ok()))
    with pytest.raises(ContextOverflow) as info:
        h.core.complete(request())
    assert info.value.model_limit == CONTEXT_WINDOW
    assert h.fallback.calls == []
    assert len(h.events) == 1


def test_route_without_an_adapter_is_refused_when_the_core_is_built() -> None:
    # AT-9 belongs to B3 (`validate()`). This only covers the one check the core makes itself.
    with pytest.raises(ConfigError):
        Core({"default": AliasSpec(routes=(Route("nope", "m"),), context_window=10)}, {})


def test_invalid_request_raises_at_once() -> None:
    h = Harness(scripted(FakeError(ErrorClass.INVALID_REQUEST)), scripted(ok()))
    with pytest.raises(InvalidRequest) as info:
        h.core.complete(request())
    assert [a.outcome for a in info.value.attempts] == [ErrorClass.INVALID_REQUEST]
    assert h.fallback.calls == []
    assert h.sleeps == []


def test_a_400_that_reports_overflow_raises_context_overflow_instead() -> None:
    # The adapter reads the 400 body and classifies it as context_overflow (D13, D20).
    h = Harness(scripted(FakeError(ErrorClass.CONTEXT_OVERFLOW)), scripted(ok()))
    with pytest.raises(ContextOverflow):
        h.core.complete(request())
    assert h.fallback.calls == []


def test_retry_after_is_capped() -> None:
    # A 429 with Retry-After of 20 s waits 20 s.
    h = Harness(scripted(FakeError(ErrorClass.RATE_LIMITED, {"retry-after": "20"}), ok()))
    h.core.complete(request())
    assert h.sleeps == [20.0]

    # retry-after-ms wins and waits the same time (D29).
    h = Harness(scripted(FakeError(ErrorClass.RATE_LIMITED, {"retry-after-ms": "20000"}), ok()))
    h.core.complete(request())
    assert h.sleeps == [20.0]

    # An HTTP date 20 s after the clock waits the same time (D29).
    http_date = formatdate(EPOCH_NOW + 20, usegmt=True)
    h = Harness(scripted(FakeError(ErrorClass.RATE_LIMITED, {"retry-after": http_date}), ok()))
    h.core.complete(request())
    assert h.sleeps == [20.0]

    # Over 60 s: fail over at once, with no wait (D21).
    h = Harness(
        scripted(FakeError(ErrorClass.RATE_LIMITED, {"retry-after": "61"})),
        scripted(ok("from fallback")),
    )
    response = h.core.complete(request())
    assert h.sleeps == []
    assert response.provider_used == FALLBACK

    # A value that cannot be parsed gives the schedule step (D29).
    h = Harness(scripted(FakeError(ErrorClass.RATE_LIMITED, {"retry-after": "soon"}), ok()))
    h.core.complete(request())
    assert h.sleeps == [5.0]


def test_retry_after_never_shortens_the_schedule_step() -> None:
    h = Harness(scripted(FakeError(ErrorClass.RATE_LIMITED, {"retry-after": "1"}), ok()))
    h.core.complete(request())
    assert h.sleeps == [5.0]


def test_fallback_starts_with_fresh_counters() -> None:
    h = Harness(
        scripted(*[FakeError(ErrorClass.RATE_LIMITED)] * 4),
        scripted(*[FakeError(ErrorClass.RATE_LIMITED)] * 4),
    )
    with pytest.raises(ProviderExhausted):
        h.core.complete(request())
    assert h.sleeps == [5.0, 15.0, 45.0, 5.0, 15.0, 45.0]


def test_counters_do_not_carry_over_between_calls() -> None:
    primary = scripted(
        FakeError(ErrorClass.SERVER_ERROR),
        FakeError(ErrorClass.SERVER_ERROR),
        FakeError(ErrorClass.SERVER_ERROR),
        ok(),
        FakeError(ErrorClass.SERVER_ERROR),
        FakeError(ErrorClass.SERVER_ERROR),
        FakeError(ErrorClass.SERVER_ERROR),
        ok(),
    )
    h = Harness(primary)
    h.core.complete(request())
    h.core.complete(request())
    assert len(h.primary.calls) == 8
    assert h.fallback.calls == []


def test_content_filtered_returns_refusal_without_retry() -> None:
    h = Harness(scripted(FakeError(ErrorClass.CONTENT_FILTERED)), scripted(ok()))
    response = h.core.complete(request())
    assert response.stop_reason == "refusal"
    assert h.primary.calls == ["model-a"]
    assert h.fallback.calls == []
    assert [a.outcome for a in response.attempts] == [ErrorClass.CONTENT_FILTERED]


def test_refusal_response_from_adapter_is_returned_without_retry() -> None:
    refusal = Response(
        text="",
        stop_reason="refusal",
        usage=Usage(input_tokens=3, output_tokens=0),
        model_used="",
        provider_used="",
        attempts=(),
    )
    h = Harness(scripted(refusal), scripted(ok()))
    response = h.core.complete(request())
    assert response.stop_reason == "refusal"
    assert h.fallback.calls == []
    assert h.events[0].outcome == ErrorClass.CONTENT_FILTERED


def test_response_reports_the_provider_and_attempts_that_answered() -> None:
    h = Harness(
        scripted(*[FakeError(ErrorClass.TIMEOUT)] * 3),
        scripted(ok("fallback text")),
    )
    response = h.core.complete(request())
    assert response.text == "fallback text"
    assert response.provider_used == FALLBACK
    assert response.model_used == "model-b"
    assert response.attempts == (
        Attempt(PRIMARY, "model-a", ErrorClass.TIMEOUT, 0),
        Attempt(PRIMARY, "model-a", ErrorClass.TIMEOUT, 0),
        Attempt(PRIMARY, "model-a", ErrorClass.TIMEOUT, 0),
        Attempt(FALLBACK, "model-b", "success", 0),
    )


def test_prompt_over_window_raises_before_any_provider_call() -> None:
    # 100 characters is 25 tokens, over a window of 10 (D34).
    h = Harness(scripted(ok()), scripted(ok()), context_window=10)
    with pytest.raises(ContextOverflow) as info:
        h.core.complete(request("a" * 100))
    assert info.value.model_limit == 10
    assert h.primary.calls == []
    assert h.fallback.calls == []
    assert h.events == []


def test_concurrent_complete_calls_are_independent() -> None:
    # Each request gets one 429 and then a success, so each call makes two attempts on the
    # primary and sleeps once. The reply names the request, so a mix-up would show.
    threads_count = 8
    seen_once: set[str] = set()
    seen_lock = threading.Lock()

    def respond(req: Request, _model: str) -> Reply:
        text = req.messages[0].text
        with seen_lock:
            first_time = text not in seen_once
            seen_once.add(text)
        if first_time:
            return FakeError(ErrorClass.RATE_LIMITED)
        return ok(text)

    h = Harness(respond)
    results: dict[int, Response] = {}
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            results[index] = h.core.complete(request(f"call-{index}"))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == threads_count
    for index, response in results.items():
        assert response.text == f"call-{index}"
        assert response.provider_used == PRIMARY
        assert [a.outcome for a in response.attempts] == [ErrorClass.RATE_LIMITED, "success"]
    assert len(h.events) == 2 * threads_count
    assert h.sleeps == [5.0] * threads_count
    assert h.fallback.calls == []


def test_unknown_alias_is_a_config_error() -> None:
    h = Harness(scripted(ok()))
    with pytest.raises(ConfigError, match="unknown alias"):
        h.core.complete(request(alias="nope"))


def test_alias_without_routes_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        AliasSpec(routes=(), context_window=10)


def test_a_raising_on_usage_callback_does_not_lose_the_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # D38: the callback fails, the response still returns, and the log names the type only.
    h = Harness(scripted(ok("kept")))

    def broken(_event: UsageEvent) -> None:
        raise RuntimeError("SECRET-IN-MESSAGE")

    h.core.on_usage(broken)
    with caplog.at_level("WARNING"):
        response = h.core.complete(request())
    assert response.text == "kept"
    assert len(h.events) == 1
    assert "RuntimeError" in caplog.text
    assert "SECRET-IN-MESSAGE" not in caplog.text
