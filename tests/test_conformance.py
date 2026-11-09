"""Conformance suite: AT-1 to AT-14 of docs/requirements.md section 8.2, end to end.

Each test runs the same path a caller takes: `load_config` reads a YAML file, `build_core`
makes the core and the real adapters, and `complete` calls a mock HTTP layer
(`httpx2.MockTransport`, D31). A fake sleep and a fake clock stand in for real time (AT-1,
AT-11). No test calls a real provider, and every key is fake.

The overflow bodies used here are hand-written. None was captured from a real server, so they
are unverified (requirements F3). The names of the tests are the proposed names in section 8.2.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import formatdate
from pathlib import Path

import anthropic
import httpx2
import openai
import pytest

from llm_adapter.adapters.anthropic import AnthropicAdapter
from llm_adapter.adapters.responses import ResponsesAdapter
from llm_adapter.config import load_config, resolve_alias, validate
from llm_adapter.core import Core
from llm_adapter.factory import build_adapters, build_core
from llm_adapter.types import (
    AuthError,
    ConfigError,
    ContextOverflow,
    ErrorClass,
    InvalidRequest,
    Message,
    ProviderExhausted,
    Request,
    Response,
    UsageEvent,
)

EPOCH = 1_800_000_000.0
ANTHROPIC_HOST = "anthropic.test"
OPENAI_HOST = "openai.test"
CANARY = "canary-key-conformance-0042"
OPENAI_FAKE_KEY = "openai-fake-key-0042"

CONFIG = """\
providers:
  anthropic:
    wire_api: anthropic-messages
    base_url: "https://anthropic.test"
    api_key_env: ANTHROPIC_AUTH_TOKEN
  openai:
    wire_api: responses
    base_url: "https://openai.test/v1"
    api_key_env: OPENAI_API_KEY

allowed_models:
  - "model-a"
  - "model-b"

aliases:
  default:
    context_window: 272000
    primary:  { provider: anthropic, model: "model-a" }
    fallback: { provider: openai,    model: "model-b" }
  solo:
    context_window: 272000
    primary:  { provider: anthropic, model: "model-a" }
    fallback: null
"""

Reply = Callable[[httpx2.Request], httpx2.Response]


# --- Mock gateway --------------------------------------------------------------------------------


class Gateway:
    """Routes each request by host. Replies come from a queue, then from a default handler."""

    def __init__(self) -> None:
        self.queues: dict[str, list[Reply]] = {}
        self.defaults: dict[str, Reply] = {}
        self.requests: list[httpx2.Request] = []
        self.unexpected: list[str] = []
        self._lock = threading.Lock()

    def script(self, host: str, *replies: Reply) -> None:
        self.queues.setdefault(host, []).extend(replies)

    def always(self, host: str, reply: Reply) -> None:
        self.defaults[host] = reply

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        with self._lock:
            self.requests.append(request)
            queue = self.queues.get(host, [])
            reply = queue.pop(0) if queue else self.defaults.get(host)
            if reply is None:
                self.unexpected.append(host)
                return httpx2.Response(599, json={"error": {"message": "unscripted call"}})
        return reply(request)

    def calls(self, host: str) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.host == host]


def anthropic_ok(text: str = "hello") -> Reply:
    body = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "model-a",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 4},
    }
    return lambda _request: httpx2.Response(200, json=body)


def openai_ok(text: str = "hello") -> Reply:
    body = {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "model-b",
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
        "usage": {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
    return lambda _request: httpx2.Response(200, json=body)


def anthropic_error(
    status: int, error_type: str, message: str, headers: dict[str, str] | None = None
) -> Reply:
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    return lambda _request: httpx2.Response(status, json=body, headers=headers)


def openai_error(
    status: int, message: str, code: str | None = None, headers: dict[str, str] | None = None
) -> Reply:
    body = {"error": {"message": message, "type": "invalid_request_error", "code": code}}
    return lambda _request: httpx2.Response(status, json=body, headers=headers)


def timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("slow", request=request)


def refused(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("refused", request=request)


def anthropic_overflow() -> Reply:
    # Hand-written body, unverified against a real server (F3).
    # Phrase verified by a live probe on 2026-11-09 (F3). The numbers are written, not copied.
    return anthropic_error(400, "invalid_request_error", "prompt is too long: 300000 > 200000")


def openai_overflow() -> Reply:
    # Hand-written body, unverified against a real server (F3).
    # Code "400" and the phrase "context window" verified by a live probe on 2026-11-09 (F3).
    return openai_error(400, "Input exceeds the context window of this model.", code="400")


# --- Rig -----------------------------------------------------------------------------------------


@dataclass
class Rig:
    core: Core
    gateway: Gateway
    sleeps: list[float] = field(default_factory=list)
    events: list[UsageEvent] = field(default_factory=list)
    adapters: dict = field(default_factory=dict)


def write_config(tmp_path: Path, text: str = CONFIG, name: str = "llm.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", CANARY)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_FAKE_KEY)


def make_rig(
    tmp_path: Path, gateway: Gateway | None = None, text: str = CONFIG, wall: float = EPOCH
) -> Rig:
    gateway = gateway or Gateway()
    config = load_config(write_config(tmp_path, text))
    client = httpx2.Client(transport=httpx2.MockTransport(gateway.handle))
    adapters = build_adapters(config, http_client=client)
    rig = Rig(core=None, gateway=gateway, adapters=adapters)  # type: ignore[arg-type]
    rig.core = build_core(
        config,
        adapters,
        sleep=rig.sleeps.append,
        clock=lambda: 0.0,
        wall_clock=lambda: wall,
    )
    rig.core.on_usage(rig.events.append)
    return rig


def request(text: str = "hello", alias: str = "default") -> Request:
    return Request(alias=alias, messages=[Message(role="user", text=text)])


# --- AT-1 to AT-3: the retry schedule, exhaustion and usage events ------------------------------


def test_error_sequence_matches_schedule(tmp_path: Path, env: None) -> None:
    # AT-1: 429, 5xx, timeout, then 401 on the primary. Each class waits as section 4 says. The
    # 401 raises at once, so the fallback is never called.
    gw = Gateway()
    gw.script(
        ANTHROPIC_HOST,
        anthropic_error(429, "rate_limit_error", "slow down"),
        anthropic_error(500, "api_error", "broke"),
        timeout,
        anthropic_error(401, "authentication_error", "bad key"),
    )
    rig = make_rig(tmp_path, gw)
    with pytest.raises(AuthError) as info:
        rig.core.complete(request())
    assert [a.outcome for a in info.value.attempts] == [
        ErrorClass.RATE_LIMITED,
        ErrorClass.SERVER_ERROR,
        ErrorClass.TIMEOUT,
        ErrorClass.AUTH,
    ]
    assert rig.sleeps == [5.0]  # only the first 429 waits, the rest have a zero step
    assert len(gw.calls(ANTHROPIC_HOST)) == 4
    assert gw.calls(OPENAI_HOST) == []


def test_exhaustion_raises_once(tmp_path: Path, env: None) -> None:
    # AT-2: both providers fail every time. The library raises once and stops calling.
    gw = Gateway()
    gw.always(ANTHROPIC_HOST, anthropic_error(429, "rate_limit_error", "slow"))
    gw.always(OPENAI_HOST, openai_error(500, "down"))
    rig = make_rig(tmp_path, gw)
    with pytest.raises(ProviderExhausted) as info:
        rig.core.complete(request())
    assert len(info.value.attempts) == 4 + 4  # 429 x4 on the primary, 5xx x4 on the fallback
    assert len(gw.calls(ANTHROPIC_HOST)) == 4
    assert len(gw.calls(OPENAI_HOST)) == 4
    assert gw.unexpected == []


def test_usage_event_per_attempt(tmp_path: Path, env: None) -> None:
    # AT-3: a failed attempt and the successful one each fire `on_usage`, with the right names.
    gw = Gateway()
    gw.always(ANTHROPIC_HOST, anthropic_error(429, "rate_limit_error", "slow"))
    gw.script(OPENAI_HOST, openai_ok("from fallback"))
    rig = make_rig(tmp_path, gw)
    response = rig.core.complete(request())
    assert response.provider_used == "openai"
    # Rate limiting has a budget of 3 retries, so the primary makes 4 attempts before failover.
    assert [(e.provider, e.model, e.outcome) for e in rig.events] == [
        ("anthropic", "model-a", ErrorClass.RATE_LIMITED),
        ("anthropic", "model-a", ErrorClass.RATE_LIMITED),
        ("anthropic", "model-a", ErrorClass.RATE_LIMITED),
        ("anthropic", "model-a", ErrorClass.RATE_LIMITED),
        ("openai", "model-b", "success"),
    ]
    assert rig.events[-1].usage is not None
    assert rig.events[-1].usage.input_tokens == 10
    assert all(e.usage is None for e in rig.events[:-1])  # failed attempts carry no usage


# --- AT-4 to AT-6: config, secrets and SDK retries ---------------------------------------------


def test_model_change_is_config_only(tmp_path: Path, env: None) -> None:
    # AT-4: the model name changes in the YAML file only (the file and allowed_models). The code
    # is the same, and the request goes out with the new name.
    gw = Gateway()
    gw.always(ANTHROPIC_HOST, anthropic_ok())
    changed = CONFIG.replace('model: "model-a"', 'model: "model-c"').replace(
        '  - "model-a"', '  - "model-c"'
    )
    rig = make_rig(tmp_path, gw, text=changed)
    rig.core.complete(request())
    assert json.loads(gw.calls(ANTHROPIC_HOST)[0].content)["model"] == "model-c"


def test_no_secret_in_output(tmp_path: Path, env: None, caplog: pytest.LogCaptureFixture) -> None:
    # AT-5: the canary key appears in no log, usage event or error message, on success or failure.
    gw = Gateway()
    gw.script(ANTHROPIC_HOST, anthropic_error(401, "authentication_error", "bad key"))
    rig = make_rig(tmp_path, gw)
    with caplog.at_level(0), pytest.raises(AuthError) as info:
        rig.core.complete(request())
    assert CANARY not in caplog.text
    assert CANARY not in repr(rig.events)
    assert CANARY not in str(info.value)
    assert CANARY not in repr(info.value)
    assert CANARY not in repr(info.value.attempts)


def test_sdk_retries_disabled(tmp_path: Path, env: None) -> None:
    # AT-6: each adapter builds its SDK client with the SDK's own retries off. One 5xx from the
    # network is one request, not three.
    gw = Gateway()
    gw.always(ANTHROPIC_HOST, anthropic_error(500, "api_error", "broke"))
    gw.always(OPENAI_HOST, openai_error(500, "broke"))
    config = load_config(write_config(tmp_path))
    client = httpx2.Client(transport=httpx2.MockTransport(gw.handle))
    adapters = build_adapters(config, http_client=client)

    anth = adapters["anthropic"]
    oai = adapters["openai"]
    assert isinstance(anth, AnthropicAdapter)
    assert isinstance(oai, ResponsesAdapter)
    assert anth._client().max_retries == 0  # type: ignore[attr-defined]
    assert oai._client().max_retries == 0  # type: ignore[attr-defined]

    with pytest.raises(anthropic.APIStatusError):
        anth.complete(request(), "model-a", 30.0)
    with pytest.raises(openai.APIStatusError):
        oai.complete(request(), "model-b", 30.0)
    assert len(gw.calls(ANTHROPIC_HOST)) == 1
    assert len(gw.calls(OPENAI_HOST)) == 1


# --- AT-7, AT-8 and AT-10: failover rules for auth, overflow and invalid requests --------------


def test_auth_error_on_fallback_raises_auth_error(tmp_path: Path, env: None) -> None:
    # AT-7: the primary fails with 5xx until its retries run out. The fallback answers 401.
    gw = Gateway()
    gw.always(ANTHROPIC_HOST, anthropic_error(500, "api_error", "broke"))
    gw.script(OPENAI_HOST, openai_error(401, "bad key"))
    rig = make_rig(tmp_path, gw)
    with pytest.raises(AuthError) as info:
        rig.core.complete(request())
    assert [a.provider for a in info.value.attempts] == ["anthropic"] * 4 + ["openai"]
    assert info.value.attempts[-1].outcome is ErrorClass.AUTH
    assert len(gw.calls(OPENAI_HOST)) == 1


def test_context_overflow_does_not_fail_over(tmp_path: Path, env: None) -> None:
    # AT-8: a prompt the primary reports as too long raises ContextOverflow. No fallback call.
    gw = Gateway()
    gw.script(ANTHROPIC_HOST, anthropic_overflow())
    rig = make_rig(tmp_path, gw)
    with pytest.raises(ContextOverflow) as info:
        rig.core.complete(request())
    assert info.value.model_limit == 272000
    assert gw.calls(OPENAI_HOST) == []
    assert len(gw.calls(ANTHROPIC_HOST)) == 1


def test_validate_rejects_bad_config(tmp_path: Path, env: None, monkeypatch) -> None:
    # AT-9: an unset variable, an unknown provider, a model outside allowed_models, an unknown
    # alias and a missing context_window each raise ConfigError.
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(ConfigError, match="OPENAI_API_KEY") as unset:
        validate(load_config(write_config(tmp_path)))
    assert "fake" not in str(unset.value)

    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_FAKE_KEY)
    unknown_provider = CONFIG.replace("provider: openai", "provider: nope")
    with pytest.raises(ConfigError, match="nope"):
        validate(load_config(write_config(tmp_path, unknown_provider, "a.yaml")))

    bad_model = CONFIG.replace(
        'fallback: { provider: openai,    model: "model-b" }',
        'fallback: { provider: openai,    model: "model-x" }',
    )
    with pytest.raises(ConfigError, match="allowed_models"):
        validate(load_config(write_config(tmp_path, bad_model, "b.yaml")))

    config = load_config(write_config(tmp_path))
    with pytest.raises(ConfigError, match="unknown alias"):
        resolve_alias(config, "nope")

    no_window = CONFIG.replace("    context_window: 272000\n", "", 1)
    with pytest.raises(ConfigError, match="context_window"):
        validate(load_config(write_config(tmp_path, no_window, "c.yaml")))


def test_invalid_request_raises_at_once(tmp_path: Path, env: None) -> None:
    # AT-10: a 400 that is not an overflow raises InvalidRequest with attempts[], one call only.
    gw = Gateway()
    gw.script(ANTHROPIC_HOST, anthropic_error(400, "invalid_request_error", "messages: required"))
    rig = make_rig(tmp_path, gw)
    with pytest.raises(InvalidRequest) as info:
        rig.core.complete(request())
    assert [a.outcome for a in info.value.attempts] == [ErrorClass.INVALID_REQUEST]
    assert len(gw.calls(ANTHROPIC_HOST)) == 1
    assert gw.calls(OPENAI_HOST) == []


def test_a_400_that_reports_overflow_raises_context_overflow_instead(
    tmp_path: Path, env: None
) -> None:
    # AT-10, second half: the same 400 status with an overflow body is ContextOverflow, not
    # InvalidRequest (D13, D20). It is not failed over.
    gw = Gateway()
    gw.script(ANTHROPIC_HOST, anthropic_overflow())
    rig = make_rig(tmp_path, gw)
    with pytest.raises(ContextOverflow) as info:
        rig.core.complete(request())
    assert not isinstance(info.value, InvalidRequest)
    assert len(gw.calls(ANTHROPIC_HOST)) == 1
    assert gw.calls(OPENAI_HOST) == []


# --- AT-11: Retry-After ------------------------------------------------------------------------


def test_retry_after_is_capped(tmp_path: Path, env: None) -> None:
    # AT-11: a Retry-After of 20 s waits 20 s. The same value in ms or as an HTTP date waits 20 s.
    # Over 60 s fails over with no wait. An unparseable value gives the schedule step (5 s).
    http_date = formatdate(EPOCH + 20, usegmt=True)
    cases = [
        ({"retry-after": "20"}, 20.0),
        ({"retry-after-ms": "20000"}, 20.0),
        ({"retry-after": http_date}, 20.0),
        ({"retry-after": "not-a-number"}, 5.0),
    ]
    for headers, expected in cases:
        gw = Gateway()
        gw.script(
            ANTHROPIC_HOST,
            anthropic_error(429, "rate_limit_error", "slow", headers),
            anthropic_ok("done"),
        )
        rig = make_rig(tmp_path, gw)
        assert rig.core.complete(request()).text == "done"
        assert rig.sleeps == [expected], headers

    gw = Gateway()
    gw.script(
        ANTHROPIC_HOST,
        anthropic_error(429, "rate_limit_error", "slow", {"retry-after": "90"}),
    )
    gw.script(OPENAI_HOST, openai_ok("fallback"))
    rig = make_rig(tmp_path, gw)
    assert rig.core.complete(request()).provider_used == "openai"
    assert rig.sleeps == []


# --- AT-12: concurrency ------------------------------------------------------------------------


def test_concurrent_complete_calls_are_independent(tmp_path: Path, env: None) -> None:
    # AT-12: eight threads at once. Each call's reply names its request. Each call keeps its own
    # attempts. `on_usage` fires once per attempt. Each thread has its own SDK client.
    gw = Gateway()
    seen: set[str] = set()
    guard = threading.Lock()

    def echo_once_then_ok(req: httpx2.Request) -> httpx2.Response:
        text = json.loads(req.content)["messages"][-1]["content"]
        with guard:
            first = text not in seen
            seen.add(text)
        if first:
            return httpx2.Response(
                429,
                json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
            )
        body = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "model-a",
            "content": [{"type": "text", "text": f"echo:{text}"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return httpx2.Response(200, json=body)

    gw.always(ANTHROPIC_HOST, echo_once_then_ok)
    rig = make_rig(tmp_path, gw)
    results: dict[int, Response] = {}
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            results[index] = rig.core.complete(request(f"call-{index}"))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    for index, response in results.items():
        assert response.text == f"echo:call-{index}"
        assert [a.outcome for a in response.attempts] == [ErrorClass.RATE_LIMITED, "success"]
    assert len(rig.events) == 16

    clients: list[object] = []
    adapter = rig.adapters["anthropic"]

    def grab() -> None:
        clients.append(adapter._client())  # type: ignore[attr-defined]

    grabbers = [threading.Thread(target=grab) for _ in range(4)]
    for t in grabbers:
        t.start()
    for t in grabbers:
        t.join()
    assert len({id(c) for c in clients}) == 4


# --- AT-13 and AT-14: config path and the pre-check --------------------------------------------


def test_load_config_reads_yaml_path(tmp_path: Path, env: None, monkeypatch) -> None:
    # AT-13: the file at the given path is read, and ${VAR} resolves. Nothing is searched for.
    monkeypatch.setenv("ANTHROPIC_BASE_URL_TEST", "https://anthropic.test")
    text = CONFIG.replace('"https://anthropic.test"', '"${ANTHROPIC_BASE_URL_TEST}"')
    nested = tmp_path / "some" / "where"
    nested.mkdir(parents=True)
    config = load_config(write_config(nested, text, "custom-name.yaml"))
    assert config.providers["anthropic"].base_url == "https://anthropic.test"
    assert set(config.aliases) == {"default", "solo"}

    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")


def test_prompt_over_window_raises_before_any_provider_call(tmp_path: Path, env: None) -> None:
    # AT-14: a prompt whose estimate is over the window raises ContextOverflow with the limit.
    # No provider sees a request, and `on_usage` does not fire (D34, D37).
    small = CONFIG.replace("context_window: 272000", "context_window: 10")
    gw = Gateway()
    gw.always(ANTHROPIC_HOST, anthropic_ok())
    gw.always(OPENAI_HOST, openai_ok())
    rig = make_rig(tmp_path, gw, text=small)
    with pytest.raises(ContextOverflow) as info:
        rig.core.complete(request("a" * 400))
    assert info.value.model_limit == 10
    assert gw.requests == []
    assert rig.events == []
