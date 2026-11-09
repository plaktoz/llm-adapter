"""The shared types, the error classes, the exceptions and the adapter Protocol.

Field names follow docs/requirements.md section 2 (data model) and section 7 (failure modes).
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


class ErrorClass(enum.StrEnum):
    """The error classes of requirements section 4. The value is the name used in `outcome`."""

    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    AUTH = "auth"
    CONTEXT_OVERFLOW = "context_overflow"
    INVALID_REQUEST = "invalid_request"
    CONTENT_FILTERED = "content_filtered"


Outcome = Literal["success"] | ErrorClass


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of text. Version 1 carries text only (requirements section 2)."""

    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True, slots=True)
class Request:
    alias: str
    messages: Sequence[Message]
    max_output_tokens: int | None = None
    temperature: float | None = None
    system: str | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts. The cached fields are optional: providers report them differently."""

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Attempt:
    provider: str
    model: str
    outcome: Outcome
    latency_ms: int


@dataclass(frozen=True, slots=True)
class Response:
    text: str
    stop_reason: str
    usage: Usage | None
    model_used: str
    provider_used: str
    attempts: tuple[Attempt, ...]


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """What `on_usage` receives for each attempt. Counts only, no content (section 6)."""

    alias: str
    provider: str
    model: str
    usage: Usage | None
    latency_ms: int
    outcome: Outcome


class ConfigError(Exception):
    """Bad configuration (requirements section 7): unknown alias, unset variable, and so on."""


class _AttemptsError(Exception):
    def __init__(self, message: str, attempts: Sequence[Attempt]) -> None:
        super().__init__(message)
        self.attempts: tuple[Attempt, ...] = tuple(attempts)


class ProviderExhausted(_AttemptsError):
    """Every provider failed with a retryable error."""


class AuthError(_AttemptsError):
    """HTTP 401 or 403 from any provider. Never retried, never failed over (D12)."""


class InvalidRequest(_AttemptsError):
    """A request the provider rejects as malformed. Never retried, never failed over (D20)."""


class ContextOverflow(Exception):
    """The prompt is larger than the model's context window. It carries the limit (D33, D13)."""

    def __init__(self, message: str, model_limit: int) -> None:
        super().__init__(message)
        self.model_limit = model_limit


class Adapter(Protocol):
    """The contract between the core and one provider's adapter (requirements section 4)."""

    def complete(self, request: Request, model: str, timeout: float) -> Response: ...

    def classify(self, exc: BaseException) -> ErrorClass: ...
