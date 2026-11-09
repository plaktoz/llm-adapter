"""Build a working Core from a Config (requirements sections 1 and 3, D40).

`load_config` gives a `Config`. This module turns it into the adapters and the `Core` that
`complete` runs on. A model change in the YAML file needs no code change (AT-4).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping

import httpx2

from .adapters.anthropic import AnthropicAdapter
from .adapters.responses import ResponsesAdapter
from .config import Config, Provider, validate
from .core import AliasSpec, Core, Route
from .types import Adapter, ConfigError

ANTHROPIC_WIRE = "anthropic-messages"
RESPONSES_WIRE = "responses"


def _make_adapter(provider: Provider, http_client: httpx2.Client | None) -> Adapter:
    api_key = os.environ.get(provider.api_key_env)
    if not api_key:
        raise ConfigError(f"environment variable {provider.api_key_env} is not set (D10)")
    if provider.wire_api == ANTHROPIC_WIRE:
        return AnthropicAdapter(
            base_url=provider.base_url, api_key=api_key, http_client=http_client
        )
    if provider.wire_api == RESPONSES_WIRE:
        return ResponsesAdapter(
            provider.name, api_key, base_url=provider.base_url, http_client=http_client
        )
    raise ConfigError(f"provider {provider.name} has an unsupported wire_api (D19)")


def build_adapters(
    config: Config,
    http_client: httpx2.Client | Callable[[str], httpx2.Client | None] | None = None,
) -> dict[str, Adapter]:
    """Make one adapter per provider in the config, choosing the class from `wire_api` (D40).

    `http_client` is for tests (D31). Pass one client for all providers, or a function that
    takes a provider name and returns that provider's client.
    """
    adapters: dict[str, Adapter] = {}
    for name, provider in config.providers.items():
        client = http_client(name) if callable(http_client) else http_client
        adapters[name] = _make_adapter(provider, client)
    return adapters


def build_core(
    config: Config,
    adapters: Mapping[str, Adapter] | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> Core:
    """Check the config, then build a `Core` whose aliases come from it.

    `adapters` defaults to `build_adapters(config)`. The clock arguments go to `Core`, so a test
    passes a fake clock (AT-1, AT-11).
    """
    validate(config)
    specs: dict[str, AliasSpec] = {}
    for alias in config.aliases.values():
        if alias.primary is None or alias.context_window is None:
            raise ConfigError(f"alias {alias.name} is incomplete (D33)")
        targets = [alias.primary] + ([alias.fallback] if alias.fallback else [])
        specs[alias.name] = AliasSpec(
            routes=tuple(Route(t.provider, t.model) for t in targets),
            context_window=alias.context_window,
        )
    if adapters is None:
        adapters = build_adapters(config)
    return Core(specs, adapters, sleep=sleep, clock=clock, wall_clock=wall_clock)
