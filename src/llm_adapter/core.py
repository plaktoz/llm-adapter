"""The core: the retry and failover loop, the usage callbacks and the resolved alias input.

The core owns all retry and failover policy (requirements sections 4 and 5). An adapter maps one
provider's SDK to the shared types and classifies its exceptions. Nothing here names a vendor SDK,
a model ID or a secret.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime

from .precheck import check_prompt_size
from .types import (
    Adapter,
    Attempt,
    AuthError,
    ConfigError,
    ContextOverflow,
    ErrorClass,
    InvalidRequest,
    Outcome,
    ProviderExhausted,
    Request,
    Response,
    Usage,
    UsageEvent,
)

_log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30.0
RETRY_AFTER_CAP_S = 60.0

# Waits before each retry of a class (section 4). The length of a tuple is its retry budget.
# Retry-After only applies to rate_limited (section 4 table, D21).
_SCHEDULE: Mapping[ErrorClass, tuple[float, ...]] = {
    ErrorClass.RATE_LIMITED: (5.0, 15.0, 45.0),
    ErrorClass.SERVER_ERROR: (0.0, 0.0, 0.0),
    ErrorClass.TIMEOUT: (0.0, 0.0),
}


@dataclass(frozen=True, slots=True)
class Route:
    """One step of an alias chain: the provider (a key of the adapters mapping) and its model."""

    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class AliasSpec:
    """One resolved alias, the input the core takes from configuration.

    `routes` holds the primary first, then the fallback when there is one (D17). `context_window`
    is in tokens (D33). `timeout` is in seconds and is passed to each adapter call.
    """

    routes: tuple[Route, ...]
    context_window: int
    timeout: float = DEFAULT_TIMEOUT_S

    def __post_init__(self) -> None:
        if not self.routes:
            raise ConfigError("an alias needs a primary provider")


UsageCallback = Callable[[UsageEvent], None]


def _headers(exc: BaseException) -> Mapping[str, str]:
    """The headers of the HTTP response that an SDK error carries (httpx shape), or none."""
    raw = getattr(getattr(exc, "response", None), "headers", None)
    if raw is None:
        return {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def _parse_seconds(value: str) -> float | None:
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def retry_after_seconds(exc: BaseException, wall_clock: Callable[[], float]) -> float | None:
    """Read `Retry-After` in the order of D29: `retry-after-ms`, seconds, then an HTTP date.

    A form that cannot be parsed is skipped. None means that no form gave a usable value.
    """
    headers = _headers(exc)
    if (ms := headers.get("retry-after-ms")) is not None and (
        parsed := _parse_seconds(ms)
    ) is not None:
        return parsed / 1000.0
    value = headers.get("retry-after")
    if value is None:
        return None
    if (parsed := _parse_seconds(value)) is not None:
        return parsed
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, when.timestamp() - wall_clock())


class Core:
    """Runs `complete` over resolved aliases and registered adapters.

    `sleep` is the only way a wait happens, so a test passes a fake. `clock` (monotonic, for
    latency) and `wall_clock` (for the date form of `Retry-After`) are injectable for the same
    reason.

    Each call keeps its own counters and attempts list (D11), so calls share no state except the
    callback list, which a lock guards (D23).
    """

    def __init__(
        self,
        aliases: Mapping[str, AliasSpec],
        adapters: Mapping[str, Adapter],
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        for name, spec in aliases.items():
            for route in spec.routes:
                if route.provider not in adapters:
                    raise ConfigError(
                        f"alias {name!r} names provider {route.provider!r} with no adapter"
                    )
        self._aliases = dict(aliases)
        self._adapters = dict(adapters)
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock
        self._callbacks: list[UsageCallback] = []
        self._lock = threading.Lock()

    def on_usage(self, callback: UsageCallback) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def complete(self, request: Request) -> Response:
        spec = self._aliases.get(request.alias)
        if spec is None:
            raise ConfigError(f"unknown alias {request.alias!r}")
        check_prompt_size(request, spec.context_window)

        attempts: list[Attempt] = []
        for route in spec.routes:
            response = self._run_route(request, spec, route, attempts)
            if response is not None:
                return response
        raise ProviderExhausted("every provider failed", attempts)

    def _run_route(
        self, request: Request, spec: AliasSpec, route: Route, attempts: list[Attempt]
    ) -> Response | None:
        """Call one provider until it answers, raises at once, or runs out of retries.

        Returns None when the caller should fail over. The retry counters are local to this call,
        so the fallback starts fresh (D11).
        """
        adapter = self._adapters[route.provider]
        used: dict[ErrorClass, int] = {}
        while True:
            started = self._clock()
            try:
                response = adapter.complete(request, route.model, spec.timeout)
            except Exception as exc:
                error = exc
            else:
                latency_ms = self._elapsed_ms(started)
                outcome: Outcome = (
                    ErrorClass.CONTENT_FILTERED if response.stop_reason == "refusal" else "success"
                )
                self._record(request, route, attempts, outcome, latency_ms, response.usage)
                return dataclasses.replace(
                    response,
                    model_used=route.model,
                    provider_used=route.provider,
                    attempts=tuple(attempts),
                )

            latency_ms = self._elapsed_ms(started)
            error_class = adapter.classify(error)
            self._record(request, route, attempts, error_class, latency_ms, None)

            if error_class is ErrorClass.AUTH:
                raise AuthError(f"{route.provider} rejected the credentials", attempts)
            if error_class is ErrorClass.INVALID_REQUEST:
                raise InvalidRequest(f"{route.provider} rejected the request", attempts)
            if error_class is ErrorClass.CONTEXT_OVERFLOW:
                raise ContextOverflow(
                    f"{route.provider} reported that the prompt is over the context window",
                    model_limit=spec.context_window,
                )
            if error_class is ErrorClass.CONTENT_FILTERED:
                return Response(
                    text="",
                    stop_reason="refusal",
                    usage=None,
                    model_used=route.model,
                    provider_used=route.provider,
                    attempts=tuple(attempts),
                )

            waits = _SCHEDULE[error_class]
            retries_used = used.get(error_class, 0)
            if retries_used >= len(waits):
                return None
            wait = waits[retries_used]
            if error_class is ErrorClass.RATE_LIMITED:
                retry_after = retry_after_seconds(error, self._wall_clock)
                if retry_after is not None:
                    if retry_after > RETRY_AFTER_CAP_S:
                        return None
                    wait = max(wait, retry_after)
            used[error_class] = retries_used + 1
            if wait > 0:
                self._sleep(wait)

    def _elapsed_ms(self, started: float) -> int:
        return max(0, round((self._clock() - started) * 1000))

    def _record(
        self,
        request: Request,
        route: Route,
        attempts: list[Attempt],
        outcome: Outcome,
        latency_ms: int,
        usage: Usage | None,
    ) -> None:
        """Append the attempt and fire `on_usage` once for it, on the calling thread."""
        attempts.append(Attempt(route.provider, route.model, outcome, latency_ms))
        event = UsageEvent(request.alias, route.provider, route.model, usage, latency_ms, outcome)
        with self._lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            try:
                callback(event)
            except Exception as exc:
                # A broken observer must not lose a good response (D38). Log the type only.
                _log.warning("on_usage callback raised %s", type(exc).__name__)
