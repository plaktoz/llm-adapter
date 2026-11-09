"""Prompt-size pre-check (D34): a local estimate against the alias's context_window."""

from __future__ import annotations

from .types import ContextOverflow, Request

CHARS_PER_TOKEN = 4
# Headroom of 10% (D37), because characters over 4 undercounts code and non-English text.
HEADROOM_PERCENT = 10


def estimate_prompt_tokens(request: Request) -> int:
    """Estimate input tokens as characters divided by 4, plus 10% headroom, rounded up (D34, D37).

    The arithmetic is integer, so there is no float rounding: ceil(chars * 110 / 400). The count
    covers the system prompt and every message. It is a rough local figure, never a
    usage figure (D14), and it is not sent to `on_usage`.
    """
    chars = len(request.system or "") + sum(len(m.text) for m in request.messages)
    return -(-chars * (100 + HEADROOM_PERCENT) // (100 * CHARS_PER_TOKEN))


def check_prompt_size(request: Request, context_window: int) -> None:
    """Raise ContextOverflow when the estimate is over the window. The message holds counts only."""
    estimated = estimate_prompt_tokens(request)
    if estimated > context_window:
        raise ContextOverflow(
            f"estimated prompt of {estimated} tokens is over the context window of "
            f"{context_window} tokens",
            model_limit=context_window,
        )
