"""Load the YAML config and check it (requirements sections 1 and 3, D10, D18, D24, D33).

The caller passes the path. There is no search path (D24). `${VAR}` is read from the
environment when the file loads. An error names a variable or a key, never a value.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from llm_adapter.types import ConfigError

_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    wire_api: str
    base_url: str
    api_key_env: str


@dataclass(frozen=True, slots=True)
class Target:
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class Alias:
    name: str
    primary: Target | None
    fallback: Target | None
    context_window: int | None


@dataclass(frozen=True, slots=True)
class Config:
    providers: Mapping[str, Provider]
    allowed_models: frozenset[str]
    aliases: Mapping[str, Alias]


def load_config(path: str | os.PathLike[str]) -> Config:
    """Read the YAML file at `path` and resolve `${VAR}` from the environment."""
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        raise ConfigError(f"cannot read config file {config_path}") from None
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # Drop the chained error: PyYAML quotes the file line, and a line may hold a value.
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ConfigError(f"{config_path} is not valid YAML{where}") from None
    return _parse(_expand(raw))


def validate(config: Config) -> None:
    """Check the config at startup. Raise `ConfigError` on the first alias that is wrong.

    Then check that each environment variable the config names is set. The error lists
    the names only.
    """
    for alias in config.aliases.values():
        if alias.primary is None:
            raise ConfigError(f"alias {alias.name} has no primary provider")
        if alias.context_window is None:
            raise ConfigError(f"alias {alias.name} has no context_window (D33)")
        if alias.context_window <= 0:
            raise ConfigError(f"alias {alias.name} has a context_window that is not positive")
        for target in (alias.primary, alias.fallback):
            if target is None:
                continue
            if target.provider not in config.providers:
                raise ConfigError(
                    f"alias {alias.name} names provider {target.provider}, "
                    "which is not in providers"
                )
            if target.model not in config.allowed_models:
                raise ConfigError(f"a model of alias {alias.name} is not in allowed_models (D18)")

    unset = sorted(
        {p.api_key_env for p in config.providers.values() if not os.environ.get(p.api_key_env)}
    )
    if unset:
        raise ConfigError("environment variables not set: " + ", ".join(unset) + " (D10)")


def resolve_alias(config: Config, name: str) -> Alias:
    """Return the alias named `name`, or raise `ConfigError` if the table has no such alias."""
    alias = config.aliases.get(name)
    if alias is None:
        raise ConfigError(f"unknown alias {name}")
    return alias


def _expand(value: Any) -> Any:
    """Replace `${VAR}` in every string of the parsed tree."""
    if isinstance(value, str):
        return _VARIABLE.sub(_variable_value, value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def _variable_value(match: re.Match[str]) -> str:
    name = match.group(1)
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"environment variable {name} is not set (D10)")
    return value


def _parse(raw: object) -> Config:
    root = _mapping(raw, "config")
    providers = {
        name: _parse_provider(name, entry)
        for name, entry in _mapping(root.get("providers"), "providers").items()
    }
    allowed = root.get("allowed_models")
    if not isinstance(allowed, list) or not all(isinstance(m, str) for m in allowed):
        raise ConfigError("allowed_models must be a list of model strings")
    aliases = {
        name: _parse_alias(name, entry)
        for name, entry in _mapping(root.get("aliases"), "aliases").items()
    }
    return Config(
        providers=providers,
        allowed_models=frozenset(allowed),
        aliases=aliases,
    )


def _parse_provider(name: str, raw: object) -> Provider:
    where = f"provider {name}"
    entry = _mapping(raw, where)
    return Provider(
        name=name,
        wire_api=_string(entry, "wire_api", where),
        base_url=_string(entry, "base_url", where),
        api_key_env=_string(entry, "api_key_env", where),
    )


def _parse_alias(name: str, raw: object) -> Alias:
    where = f"alias {name}"
    entry = _mapping(raw, where)
    window = entry.get("context_window")
    if window is not None and (isinstance(window, bool) or not isinstance(window, int)):
        raise ConfigError(f"{where}: context_window must be a whole number of tokens")
    primary = entry.get("primary")
    fallback = entry.get("fallback")
    return Alias(
        name=name,
        primary=None if primary is None else _parse_target(primary, f"{where} primary"),
        fallback=None if fallback is None else _parse_target(fallback, f"{where} fallback"),
        context_window=window,
    )


def _parse_target(raw: object, where: str) -> Target:
    entry = _mapping(raw, where)
    return Target(
        provider=_string(entry, "provider", where),
        model=_string(entry, "model", where),
    )


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    return value


def _string(entry: Mapping[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where} needs a non-empty string {key}")
    return value
