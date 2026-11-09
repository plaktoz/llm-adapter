import importlib

import pytest

MODULES = [
    "llm_adapter",
    "llm_adapter.core",
    "llm_adapter.types",
    "llm_adapter.adapters",
    "llm_adapter.adapters.anthropic",
    "llm_adapter.adapters.openai",
    "llm_adapter.adapters.gemini",
    "llm_adapter.adapters.openai_compat",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(name) is not None
