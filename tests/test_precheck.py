import pytest

from llm_adapter.precheck import check_prompt_size, estimate_prompt_tokens
from llm_adapter.types import ContextOverflow, Message, Request


def request(text: str, system: str | None = None) -> Request:
    return Request(alias="default", messages=[Message(role="user", text=text)], system=system)


def test_estimate_is_characters_over_four_plus_ten_percent_rounded_up() -> None:
    assert estimate_prompt_tokens(request("")) == 0
    assert estimate_prompt_tokens(request("a" * 1)) == 1
    assert estimate_prompt_tokens(request("a" * 400)) == 110
    assert estimate_prompt_tokens(request("a" * 401)) == 111


def test_estimate_counts_system_and_every_message() -> None:
    req = Request(
        alias="default",
        messages=[Message(role="user", text="a" * 4), Message(role="assistant", text="b" * 4)],
        system="c" * 4,
    )
    assert estimate_prompt_tokens(req) == 4


def test_prompt_at_the_window_passes() -> None:
    check_prompt_size(request("a" * 360), context_window=99)
    check_prompt_size(request("a" * 364), context_window=101)


def test_prompt_over_the_window_raises_context_overflow_with_the_limit() -> None:
    with pytest.raises(ContextOverflow) as caught:
        check_prompt_size(request("a" * 365), context_window=100)
    assert caught.value.model_limit == 100


def test_overflow_message_holds_counts_and_no_prompt_text() -> None:
    secret = "CANARY-" + "x" * 500
    with pytest.raises(ContextOverflow) as caught:
        check_prompt_size(request(secret, system="SYSTEM-CANARY"), context_window=10)
    assert "CANARY" not in str(caught.value)
