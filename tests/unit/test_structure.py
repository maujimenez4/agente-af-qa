"""Comprueba que existe la estructura de paquetes de la SPEC-00 (T-01)."""

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PACKAGES = [
    "schemas",
    "adapters",
    "adapters.jira",
    "adapters.testmgmt",
    "adapters.llm",
    "adapters.auth",
    "adapters.embeddings",
    "adapters.vectorstore",
    "core",
    "core.graph",
    "core.context",
    "core.impact",
    "core.rag",
    "core.functional",
    "core.qa",
    "core.memory",
    "app",
    "eval",
    "tests.fakes",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_is_importable_and_documented(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} debe tener un docstring"


@pytest.mark.parametrize(
    "path", ["data/memory/.gitkeep", "data/seed/jira", "data/seed/corpus", "prompts"]
)
def test_data_directories_exist(path: str) -> None:
    assert (ROOT / path).exists()
