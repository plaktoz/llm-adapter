"""Tool-calling live probe (ADR 0002, "Unverified" list).

The owner runs this by hand with a real key. A test never calls a real provider (D31), so this
is a script and not a test. It sends small fixed requests with a made-up weather tool and prints
only verdicts: ACCEPTED, REJECTED or NOT JUDGED, the HTTP status, and the `type`, `param` and
`code` of an error. It never prints a key, a request, a reply or an error message.

It answers four questions, once for each wire:

  Q1  Anthropic: may a user message hold text and tool_result blocks together?
  Q2  Does a wire accept a tool-call id that another provider minted?
  Q3  Responses: is a replayed function_call item accepted with no `id`?
  Q4  Responses: is an explicit `strict: false` accepted? What does the server echo when the
      key is absent?

Each case has a kind. A `control` must be ACCEPTED, or the other results cannot be read.
A `chosen` case is the form the owner chose on 2026-11-13. An `info` case is a neighbouring
form. It tells which fallback to try if a chosen case is REJECTED.

Every result holds for the endpoint named in the header only. A gateway can differ from the
vendor API. Gemini is not covered (done item 9).

Usage:  uv run python scripts/check_tool_wire.py --list
        uv run python scripts/check_tool_wire.py anthropic <model id>
        uv run python scripts/check_tool_wire.py responses <model id>
Reads:  anthropic: ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN
        responses: OPENAI_BASE_URL and OPENAI_API_KEY
Exit:   0 when the baseline, every control and every chosen case is ACCEPTED. 1 otherwise.
        2 for a usage error or an unset variable.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

REQUEST_TIMEOUT_SECONDS = 60
# The version header that the pinned anthropic SDK (2.6.0) sends on every request.
ANTHROPIC_VERSION = "2026-10-21"

TOOL_NAME = "get_weather"
TOOL_DESCRIPTION = "Get the weather for a city."
TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}
PROMPT = "What is the weather in Oslo? Use the tool."
FOLLOW_UP = "And in Bergen?"
RESULT_TEXT = "4 C, light rain"
ARGUMENTS = {"city": "Oslo"}
START_TOKENS = 1024
FOLLOW_UP_TOKENS = 512

# Made-up ids. They have the look of the other provider's ids. No provider minted them.
OPENAI_SHAPED_ID = "call_probe5Kq2mZ8dW1xT7vRb3Hn0Ya"
ANTHROPIC_SHAPED_ID = "toolu_01ProbeK5q2mZ8dW1xT7vRb3"
ODD_CHARACTER_ID = "call:probe.5Kq2mZ8d"

ANTHROPIC_TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": TOOL_DESCRIPTION,
    "input_schema": TOOL_SCHEMA,
}


def responses_tool(strict: Any = False, *, with_strict: bool = True) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": "function",
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "parameters": TOOL_SCHEMA,
    }
    if with_strict:
        tool["strict"] = strict
    return tool


# ---------------------------------------------------------------- transport


@dataclass(frozen=True)
class Reply:
    """What came back. `status` is None when there was no HTTP answer."""

    status: int | None
    payload: dict[str, Any] | None
    error: Mapping[str, str]
    failure: str = ""


def error_fields(raw: bytes) -> dict[str, str]:
    """Return only the type, param and code of a JSON error. Never the message."""
    try:
        error = json.loads(raw.decode("utf-8")).get("error")
    except (ValueError, AttributeError):
        return {"body": "not JSON"}
    if not isinstance(error, dict):
        return {}
    return {k: error[k] for k in ("type", "param", "code") if isinstance(error.get(k), str)}


def post_json(url: str, headers: Mapping[str, str], body: dict[str, Any]) -> Reply:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as reply:
            payload = json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return Reply(err.code, None, error_fields(err.read()))
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        return Reply(None, None, {}, failure=type(err).__name__)
    return Reply(200, payload if isinstance(payload, dict) else None, {})


# ---------------------------------------------------------------- cases


@dataclass
class Context:
    url: str
    headers: Mapping[str, str]
    model: str
    real_id: str = ""
    real_item_id: str | None = None
    # Set to False when q3-A is refused, so that q2-r1 does not fail for the q3 reason.
    omit_item_id_ok: bool = True


@dataclass(frozen=True)
class Case:
    key: str
    item: str
    kind: str
    label: str
    build: Callable[[Context], dict[str, Any]]
    note: Callable[[dict[str, Any]], str] | None = None


@dataclass(frozen=True)
class Result:
    case: Case
    verdict: str
    detail: str


def _user(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"role": "user", "content": list(blocks)}


def _a_call(tool_id: str) -> dict[str, Any]:
    block = {"type": "tool_use", "id": tool_id, "name": TOOL_NAME, "input": ARGUMENTS}
    return {"role": "assistant", "content": [block]}


def _a_result(tool_id: str) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tool_id, "content": RESULT_TEXT}


def _a_text() -> dict[str, Any]:
    return {"type": "text", "text": FOLLOW_UP}


def _a_body(ctx: Context, tool_id: str, *tail: dict[str, Any]) -> dict[str, Any]:
    first = {"role": "user", "content": PROMPT}
    return {
        "model": ctx.model,
        "max_tokens": FOLLOW_UP_TOKENS,
        "messages": [first, _a_call(tool_id), *tail],
        "tools": [ANTHROPIC_TOOL],
    }


def anthropic_baseline(ctx: Context) -> dict[str, Any]:
    return {
        "model": ctx.model,
        "max_tokens": START_TOKENS,
        "messages": [{"role": "user", "content": PROMPT}],
        "tools": [ANTHROPIC_TOOL],
        "tool_choice": {"type": "any"},
    }


ANTHROPIC_CASES: tuple[Case, ...] = (
    Case(
        "a-ctl",
        "control",
        "control",
        "native id, results only, no follow-up text",
        lambda c: _a_body(c, c.real_id, _user(_a_result(c.real_id))),
    ),
    Case(
        "q1-A",
        "Q1",
        "chosen",
        "merged: tool_result first, then text, in one user message",
        lambda c: _a_body(c, c.real_id, _user(_a_result(c.real_id), _a_text())),
    ),
    Case(
        "q1-B",
        "Q1",
        "info",
        "separate: two user messages in a row",
        lambda c: _a_body(c, c.real_id, _user(_a_result(c.real_id)), _user(_a_text())),
    ),
    Case(
        "q1-text-first",
        "Q1",
        "info",
        "text before tool_result in one user message (is results-first required?)",
        lambda c: _a_body(c, c.real_id, _user(_a_text(), _a_result(c.real_id))),
    ),
    Case(
        "q2-1",
        "Q2",
        "chosen",
        "foreign id (OpenAI-shaped) on tool_use and tool_result",
        lambda c: _a_body(c, OPENAI_SHAPED_ID, _user(_a_result(OPENAI_SHAPED_ID))),
    ),
    Case(
        "q2-odd",
        "Q2",
        "info",
        "id with ':' and '.' (is there an id format rule?)",
        lambda c: _a_body(c, ODD_CHARACTER_ID, _user(_a_result(ODD_CHARACTER_ID))),
    ),
)


def _r_call(call_id: str, item_id: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": "function_call",
        "call_id": call_id,
        "name": TOOL_NAME,
        "arguments": json.dumps(ARGUMENTS),
    }
    if item_id is not None:
        item["id"] = item_id
    return item


def _r_body(ctx: Context, call_id: str, item_id: str | None) -> dict[str, Any]:
    output = {"type": "function_call_output", "call_id": call_id, "output": RESULT_TEXT}
    return {
        "model": ctx.model,
        "input": [{"role": "user", "content": PROMPT}, _r_call(call_id, item_id), output],
        "tools": [responses_tool()],
        "max_output_tokens": START_TOKENS,
    }


def _echoed_strict(payload: dict[str, Any]) -> str:
    tools = payload.get("tools")
    if isinstance(tools, list) and tools and isinstance(tools[0], dict) and "strict" in tools[0]:
        value = tools[0]["strict"]
        shown = repr(value) if value is None or isinstance(value, bool) else type(value).__name__
        return f"echoed strict: {shown}"
    return "echoed strict: not in the reply"


def _strict_body(ctx: Context, **tool_args: Any) -> dict[str, Any]:
    return {
        "model": ctx.model,
        "input": PROMPT,
        "tools": [responses_tool(**tool_args)],
        "tool_choice": "required",
        "max_output_tokens": START_TOKENS,
    }


def responses_baseline(ctx: Context) -> dict[str, Any]:
    return _strict_body(ctx, strict=False)


RESPONSES_BASELINE = Case(
    "q4-A",
    "Q4",
    "chosen",
    "tool definition with explicit strict: false (also the baseline)",
    responses_baseline,
    _echoed_strict,
)

RESPONSES_CASES: tuple[Case, ...] = (
    Case(
        "r-ctl",
        "control",
        "control",
        "replay with the original item id and call_id",
        lambda c: _r_body(c, c.real_id, c.real_item_id),
    ),
    Case(
        "q3-A",
        "Q3",
        "chosen",
        "replayed function_call with call_id and no item id",
        lambda c: _r_body(c, c.real_id, None),
    ),
    Case(
        "q3-B",
        "Q3",
        "info",
        "replayed function_call with item id set to the call_id value",
        lambda c: _r_body(c, c.real_id, c.real_id),
    ),
    Case(
        "q2-r1",
        "Q2",
        "chosen",
        "foreign call_id (Anthropic-shaped); no item id, or the original one if q3-A was refused",
        lambda c: _r_body(c, ANTHROPIC_SHAPED_ID, None if c.omit_item_id_ok else c.real_item_id),
    ),
    Case(
        "q4-null",
        "Q4",
        "info",
        "tool definition with strict: null",
        lambda c: _strict_body(c, strict=None),
        _echoed_strict,
    ),
    Case(
        "q4-omit",
        "Q4",
        "info",
        "tool definition with no strict key (shows the server default)",
        lambda c: _strict_body(c, with_strict=False),
        _echoed_strict,
    ),
)


# ---------------------------------------------------------------- reading replies


def first_block(payload: dict[str, Any] | None, field: str, kind: str) -> dict[str, Any] | None:
    """Return the first item of `payload[field]` whose `type` is `kind`."""
    items = payload.get(field) if payload else None
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("type") == kind:
            return item
    return None


def judge(reply: Reply) -> tuple[str, str]:
    """Return (verdict, detail). Only a 4xx other than 401, 403, 408 and 429 is a rejection."""
    if reply.status is None:
        return "NOT JUDGED", f"no HTTP answer ({reply.failure})"
    if reply.status == 200 and reply.payload is not None:
        return "ACCEPTED", "HTTP 200"
    if reply.status == 200:
        return "NOT JUDGED", "HTTP 200 with a body that is not a JSON object"
    if reply.status in (401, 403):
        return "AUTH FAILED", f"HTTP {reply.status}"
    if reply.status in (408, 429) or reply.status >= 500:
        return "NOT JUDGED", f"HTTP {reply.status}: not a verdict on the request shape"
    shown = ", ".join(f"{k}={v}" for k, v in reply.error.items()) or "no error fields"
    return "REJECTED", f"HTTP {reply.status}; {shown}"


def execute(case: Case, ctx: Context) -> tuple[Result, Reply]:
    reply = post_json(ctx.url, ctx.headers, case.build(ctx))
    verdict, detail = judge(reply)
    if verdict == "ACCEPTED" and case.note and reply.payload is not None:
        detail += "; " + case.note(reply.payload)
    return Result(case, verdict, detail), reply


def show(result: Result) -> None:
    case = result.case
    print(f"[{case.key}]".ljust(16) + f"{case.kind:<8}{result.verdict:<12}{result.detail}")
    print(f"        {case.label}")


# ---------------------------------------------------------------- the two runs


@dataclass(frozen=True)
class Wire:
    name: str
    path: str
    url_variable: str
    key_variable: str
    baseline: Case
    cases: tuple[Case, ...]
    headers: Callable[[str], dict[str, str]]
    read_ids: Callable[[Reply, Context], bool]


def _anthropic_headers(key: str) -> dict[str, str]:
    # The adapter builds its client with `auth_token`, so the SDK sends a Bearer header.
    return {"Authorization": f"Bearer {key}", "anthropic-version": ANTHROPIC_VERSION}


def _responses_headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _read_anthropic_ids(reply: Reply, ctx: Context) -> bool:
    block = first_block(reply.payload, "content", "tool_use")
    if block is None or not isinstance(block.get("id"), str):
        return False
    ctx.real_id = block["id"]
    return True


def _read_responses_ids(reply: Reply, ctx: Context) -> bool:
    item = first_block(reply.payload, "output", "function_call")
    if item is None or not isinstance(item.get("call_id"), str):
        return False
    ctx.real_id = item["call_id"]
    item_id = item.get("id")
    ctx.real_item_id = item_id if isinstance(item_id, str) else None
    return True


ANTHROPIC_BASELINE = Case(
    "a-base",
    "control",
    "control",
    "tool definition accepted, and the model returns a tool_use block",
    anthropic_baseline,
)

WIRES: dict[str, Wire] = {
    "anthropic": Wire(
        "Anthropic Messages (POST /v1/messages)",
        "/v1/messages",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        ANTHROPIC_BASELINE,
        ANTHROPIC_CASES,
        _anthropic_headers,
        _read_anthropic_ids,
    ),
    "responses": Wire(
        "OpenAI Responses (POST /responses)",
        "/responses",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        RESPONSES_BASELINE,
        RESPONSES_CASES,
        _responses_headers,
        _read_responses_ids,
    ),
}


def endpoint_name(base_url: str) -> str:
    """Host and port only. No scheme, path, query or user info."""
    parts = urllib.parse.urlparse(base_url)
    host = parts.hostname or "(no host)"
    return f"{host}:{parts.port}" if parts.port else host


def list_cases() -> int:
    print("No request is sent. Cases that each run would try:")
    for name, wire in WIRES.items():
        print(f"\n{name}: {wire.name}")
        for case in (wire.baseline, *wire.cases):
            print(f"  {f'[{case.key}]':<16}{case.item:<9}{case.kind:<8}{case.label}")
    return 0


def run(name: str, model: str) -> int:
    wire = WIRES[name]
    base_url = os.environ.get(wire.url_variable, "").rstrip("/")
    key = os.environ.get(wire.key_variable, "")
    missing = [v for v, x in ((wire.url_variable, base_url), (wire.key_variable, key)) if not x]
    if missing:
        print("not set: " + ", ".join(missing))
        return 2
    if urllib.parse.urlparse(base_url).scheme not in ("http", "https"):
        print(f"{wire.url_variable} must start with http:// or https://")
        return 2

    print("Tool-wire probe (ADR 0002, Unverified list)")
    print(f"endpoint : {endpoint_name(base_url)}")
    print(f"wire     : {wire.name}")
    print(f"model    : {model}")
    print(f"time     : {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%SZ')}")
    print()

    ctx = Context(base_url + wire.path, wire.headers(key), model)
    results: list[Result] = []

    result, reply = execute(wire.baseline, ctx)
    show(result)
    results.append(result)
    if result.verdict == "AUTH FAILED":
        return finish(results, "stopped: the credentials were refused")
    if result.verdict != "ACCEPTED" or not wire.read_ids(reply, ctx):
        reason = "stopped: the baseline gave no tool call to replay"
        return finish(results, reason)

    for case in wire.cases:
        result, _ = execute(case, ctx)
        show(result)
        results.append(result)
        if case.key == "q3-A":
            ctx.omit_item_id_ok = result.verdict == "ACCEPTED"
        if result.verdict == "AUTH FAILED":
            return finish(results, "stopped: the credentials were refused")
    return finish(results, "")


def finish(results: list[Result], stopped: str) -> int:
    print()
    if stopped:
        print(stopped)
    must_pass = [r for r in results if r.case.kind in ("control", "chosen")]
    failed = [r for r in must_pass if r.verdict != "ACCEPTED"]
    controls_failed = [r for r in failed if r.case.kind == "control"]
    print("Summary (control and chosen cases):")
    for r in must_pass:
        print(f"  {r.case.item:<7} [{r.case.key}] {r.verdict}")
    if controls_failed:
        print("A control failed. Read none of the other results as an answer.")
    print("Each result holds for the endpoint named above only.")
    print("Gemini is not covered. Nothing here is a Gemini result.")
    return 1 if stopped or failed else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--list"]:
        return list_cases()
    if len(args) != 2 or args[0] not in WIRES:
        print("usage: check_tool_wire.py --list | anthropic <model id> | responses <model id>")
        return 2
    return run(args[0], args[1])


if __name__ == "__main__":
    sys.exit(main())
