from pathlib import Path

import pytest

from llm_adapter.config import load_config, resolve_alias, validate
from llm_adapter.types import ConfigError

# The sample from docs/requirements.md section 3, with fake environment values.
SAMPLE = """\
providers:
  anthropic:
    wire_api: anthropic-messages
    base_url: "${ANTHROPIC_BASE_URL}"
    api_key_env: ANTHROPIC_AUTH_TOKEN
  openai:
    wire_api: responses
    base_url: "${OPENAI_BASE_URL}"
    api_key_env: OPENAI_API_KEY
  gemini:
    wire_api: responses
    base_url: "${GOOGLE_GEMINI_BASE_URL}"
    api_key_env: GEMINI_API_KEY

allowed_models:
  - "${ANTHROPIC_MODEL}"
  - "<model id>"

aliases:
  default:
    context_window: 1000000
    primary:  { provider: anthropic, model: "${ANTHROPIC_MODEL}" }
    fallback: { provider: openai,    model: "<model id>" }
  deep:
    context_window: 1000000
    primary:  { provider: anthropic, model: "${ANTHROPIC_MODEL}" }
    fallback: { provider: openai,    model: "<model id>" }
  planner:
    context_window: 1000000
    primary:  { provider: anthropic, model: "${ANTHROPIC_MODEL}" }
    fallback: null
"""

FAKE_ENV = {
    "ANTHROPIC_BASE_URL": "https://fake-anthropic.example.test",
    "ANTHROPIC_AUTH_TOKEN": "fake-anthropic-token",
    "ANTHROPIC_MODEL": "fake-model",
    "OPENAI_BASE_URL": "https://fake-openai.example.test",
    "OPENAI_API_KEY": "fake-openai-key",
    "GOOGLE_GEMINI_BASE_URL": "https://fake-gemini.example.test",
    "GEMINI_API_KEY": "fake-gemini-key",
}


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in FAKE_ENV.items():
        monkeypatch.setenv(name, value)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_validate_rejects_bad_config(
    tmp_path: Path, fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unset key variable (named by api_key_env) fails at validate().
    monkeypatch.delenv("OPENAI_API_KEY")
    config = load_config(write(tmp_path / "unset.yaml", SAMPLE))
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        validate(config)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    # A name that is not in the alias table is an unknown alias.
    config = load_config(write(tmp_path / "sample.yaml", SAMPLE))
    with pytest.raises(ConfigError, match="unknown alias nope"):
        resolve_alias(config, "nope")

    # An alias that names a provider which is not configured fails at validate().
    unknown = SAMPLE.replace("provider: openai", "provider: nowhere", 1)
    with pytest.raises(ConfigError, match="nowhere"):
        validate(load_config(write(tmp_path / "unknown.yaml", unknown)))

    # A model outside allowed_models fails at validate().
    outside = SAMPLE.replace('  - "<model id>"\n', "", 1)
    with pytest.raises(ConfigError, match="allowed_models"):
        validate(load_config(write(tmp_path / "outside.yaml", outside)))


def test_load_config_reads_yaml_path(
    tmp_path: Path, fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    given = write(tmp_path / "given.yaml", SAMPLE)
    # A different file under the name the library might search for must be ignored.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    write(elsewhere / "llm-adapter.yaml", "providers: {}\n")
    monkeypatch.chdir(elsewhere)

    config = load_config(given)

    assert set(config.aliases) == {"default", "deep", "planner"}
    assert config.providers["anthropic"].base_url == FAKE_ENV["ANTHROPIC_BASE_URL"]
    assert config.aliases["default"].primary is not None
    assert config.aliases["default"].primary.model == "fake-model"
    assert config.aliases["planner"].fallback is None


def test_load_config_does_not_search_when_path_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")


def test_sample_config_parses_with_the_proposed_windows(tmp_path: Path, fake_env: None) -> None:
    config = load_config(write(tmp_path / "sample.yaml", SAMPLE))

    validate(config)
    windows = {name: alias.context_window for name, alias in config.aliases.items()}
    assert windows == {"default": 1000000, "deep": 1000000, "planner": 1000000}


def test_validate_rejects_alias_without_context_window(tmp_path: Path, fake_env: None) -> None:
    no_window = SAMPLE.replace("    context_window: 1000000\n", "", 1)
    config = load_config(write(tmp_path / "no_window.yaml", no_window))

    with pytest.raises(ConfigError, match="default"):
        validate(config)


def test_unset_placeholder_variable_raises_at_load_and_names_only_the_variable(
    tmp_path: Path, fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL")
    path = write(tmp_path / "placeholder.yaml", SAMPLE)

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    message = str(caught.value)
    assert "OPENAI_BASE_URL" in message
    for value in FAKE_ENV.values():
        assert value not in message


def test_validate_error_names_the_variable_and_prints_no_value(
    tmp_path: Path, fake_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY")
    config = load_config(write(tmp_path / "gemini.yaml", SAMPLE))

    with pytest.raises(ConfigError) as caught:
        validate(config)

    message = str(caught.value)
    assert "GEMINI_API_KEY" in message
    for value in FAKE_ENV.values():
        assert value not in message


def test_yaml_error_does_not_echo_the_file_text(tmp_path: Path) -> None:
    broken = write(tmp_path / "broken.yaml", "providers: [fake-secret-value\n")

    with pytest.raises(ConfigError) as caught:
        load_config(broken)

    assert "fake-secret-value" not in str(caught.value)
