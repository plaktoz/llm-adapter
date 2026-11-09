"""Drift check for the pinned SDKs (D32, D43).

The spec rests on facts read from the `anthropic` and `openai` SDKs. If a pin bump moves one of
them, a test here fails in the PR that bumps the pin, and the owner decides before it merges.
Each test names the part of `docs/requirements.md` that depends on the fact.
"""

import anthropic
import openai
import pytest
from anthropic import _constants as anthropic_constants
from anthropic.types import Usage as AnthropicUsage
from openai import _constants as openai_constants
from openai.types.responses import ResponseUsage
from openai.types.responses.response_usage import InputTokensDetails

ERROR_NAMES = (
    "APIConnectionError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "InternalServerError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
)


def test_sdk_default_retries_are_two() -> None:
    # Section 5. The adapters turn these off (AT-6). If the default moves, section 5 is stale.
    assert anthropic_constants.DEFAULT_MAX_RETRIES == 2
    assert openai_constants.DEFAULT_MAX_RETRIES == 2


@pytest.mark.parametrize("sdk", [anthropic, openai], ids=["anthropic", "openai"])
@pytest.mark.parametrize("name", ERROR_NAMES)
def test_sdk_exports_the_error_types_classify_maps(sdk: object, name: str) -> None:
    # Section 4 and F2. `classify` in each adapter maps these types to an error class.
    assert isinstance(getattr(sdk, name, None), type)


def test_openai_usage_has_the_fields_the_responses_adapter_reads() -> None:
    # Section 2, D25 and F6.
    assert {"input_tokens", "output_tokens", "input_tokens_details"} <= set(
        ResponseUsage.model_fields
    )
    assert {"cached_tokens", "cache_write_tokens"} <= set(InputTokensDetails.model_fields)


def test_anthropic_usage_has_the_fields_the_anthropic_adapter_reads() -> None:
    # Section 2 and F8.
    assert {
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    } <= set(AnthropicUsage.model_fields)
