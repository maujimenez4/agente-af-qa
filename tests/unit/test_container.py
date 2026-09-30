"""Pruebas de core/container.py: composición, valores de RAG y logging seguro (T-07 · CA-00-04)."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import structlog

from core import container as container_module
from core.config import AppConfig, ConfigError, Settings, load_models_config
from core.container import (
    DEFAULT_MEMORY_DIR,
    DEFAULT_TOP_K,
    Container,
    build_container,
)
from core.graph.nodes import GraphNodes
from core.graph.state import initial_state
from core.logging import MASK, get_logger
from tests.fakes.auth import FakeAuthProvider
from tests.fakes.container import fake_container
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.memory_generator import FakeMemoryGenerator
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore

# Valor sintético con forma de clave; no es una credencial real.
FAKE_GROQ_KEY = "dummy-groq-key-0000-solo-pruebas"  # gitleaks:allow (valor ficticio)

DEPENDENCY_NAMES = [
    "issue_tracker",
    "test_management",
    "llm",
    "embeddings",
    "vector_store",
    "memory_generator",
    "auth",
]


def _all_fakes() -> dict[str, Any]:
    return {
        "issue_tracker": FakeIssueTracker(),
        "test_management": FakeTestManagement(),
        "llm": FakeLLMProvider(),
        "embeddings": FakeEmbeddingProvider(),
        "vector_store": FakeVectorStore(),
        "memory_generator": FakeMemoryGenerator(),
        "auth": FakeAuthProvider(),
    }


@pytest.fixture
def app_config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    return AppConfig(Settings(_env_file=None), load_models_config())


@pytest.fixture
def restore_logging() -> Iterator[None]:
    levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore", "openai")}
    yield
    structlog.reset_defaults()
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


# --- dependencias obligatorias ------------------------------------------------------------------


def test_build_container_without_dependencies_lists_all_missing() -> None:
    """CA-00-04 (error): sin adaptadores → ConfigError con todos los nombres que faltan."""
    with pytest.raises(ConfigError) as exc_info:
        build_container()

    message = str(exc_info.value)
    for name in DEPENDENCY_NAMES:
        assert name in message


@pytest.mark.parametrize("missing", DEPENDENCY_NAMES)
def test_build_container_missing_one_dependency_names_it(missing: str) -> None:
    """CA-00-04 (negativo): si falta una dependencia, el error la nombra solo a ella."""
    dependencies = _all_fakes()
    del dependencies[missing]

    with pytest.raises(ConfigError) as exc_info:
        build_container(**dependencies)

    message = str(exc_info.value)
    assert missing in message
    assert all(name not in message.split(":")[-1] for name in dependencies)


def test_build_container_with_all_fakes_composes_container(tmp_path: Path) -> None:
    """CA-00-04: con todas las dependencias se obtiene un Container con esas instancias."""
    dependencies = _all_fakes()

    built = build_container(memory_dir=tmp_path, **dependencies)

    assert isinstance(built, Container)
    for name, value in dependencies.items():
        assert getattr(built, name) is value
    assert built.memory_dir == tmp_path
    assert built.config is None


def test_build_container_default_memory_dir() -> None:
    """SPEC-00 §6: sin memory_dir, las memorias van a data/memory."""
    built = build_container(**_all_fakes())

    assert built.memory_dir == DEFAULT_MEMORY_DIR
    assert DEFAULT_MEMORY_DIR.parts[-2:] == ("data", "memory")


def test_fake_container_accepts_overrides(tmp_path: Path) -> None:
    """CA-00-03/04: fake_container permite sustituir un fake concreto."""
    custom = FakeTestManagement(fail_case_ids={"CP-01"})

    built = fake_container(tmp_path, test_management=custom)

    assert built.test_management is custom
    assert len(built.vector_store.chunks) == 2  # type: ignore[attr-defined]


# --- top_k y memory_boost -----------------------------------------------------------------------


def test_rag_defaults_without_config() -> None:
    """RF-51: sin configuración, top_k por defecto y sin prioridad de memorias."""
    built = build_container(**_all_fakes())

    assert built.top_k == DEFAULT_TOP_K
    assert built.memory_boost == 1.0


def test_rag_values_come_from_app_config(app_config: AppConfig, restore_logging: None) -> None:
    """RF-51: con AppConfig, top_k y memory_boost salen de config/models.yaml."""
    built = build_container(app_config, **_all_fakes())

    assert built.config is app_config
    assert built.top_k == app_config.models.rag.top_k
    assert built.memory_boost == app_config.models.rag.memory_boost
    assert built.memory_boost != 1.0


def test_retrieve_context_uses_configured_top_k(
    app_config: AppConfig, restore_logging: None, tmp_path: Path
) -> None:
    """RF-51: el nodo retrieve_context respeta el top_k de la configuración."""
    rag = app_config.models.rag.model_copy(update={"top_k": 1})
    config = AppConfig(app_config.settings, app_config.models.model_copy(update={"rag": rag}))
    base = fake_container(tmp_path)
    built = build_container(
        config, memory_dir=tmp_path, **{n: getattr(base, n) for n in DEPENDENCY_NAMES}
    )
    nodes = GraphNodes(built)
    state = initial_state("af-demo", "functional", {"kind": "story", "key": "DEMO-3"})
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    assert len(nodes.retrieve_context(state)["rag_context"]) == 1


# --- logging ------------------------------------------------------------------------------------


def test_build_container_with_config_bootstraps_logging(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RNF-02: con configuración, build_container inicializa el logging."""
    calls: list[AppConfig] = []
    monkeypatch.setattr(container_module, "bootstrap_logging", calls.append)

    build_container(app_config, **_all_fakes())

    assert calls == [app_config]


def test_build_container_without_config_does_not_bootstrap_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RNF-02: sin configuración no se toca el logging global."""
    calls: list[object] = []
    monkeypatch.setattr(container_module, "bootstrap_logging", calls.append)

    build_container(**_all_fakes())

    assert calls == []


def test_config_secret_never_appears_in_logs(
    clean_env: pytest.MonkeyPatch,
    restore_logging: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RNF-02 · RNF-23: un secreto de la configuración se enmascara en los logs."""
    clean_env.setenv("GROQ_API_KEY", FAKE_GROQ_KEY)
    config = AppConfig(Settings(_env_file=None), load_models_config())
    assert config.settings.groq_api_key is not None

    build_container(config, **_all_fakes())
    get_logger("test").info(
        f"llamada con {FAKE_GROQ_KEY}", detail={"texto": f"clave {FAKE_GROQ_KEY}"}
    )

    output = capsys.readouterr().out
    assert FAKE_GROQ_KEY not in output
    assert MASK in output
    assert logging.getLogger("httpx").level == logging.WARNING
