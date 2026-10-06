"""Fixtures compartidas de las pruebas."""

import gc
from collections.abc import Iterator

import pytest

from core.config import Settings

ENV_VARS = [
    "JIRA_BASE_URL",
    "JIRA_CLOUD_ID",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_PROJECT_KEY",
    "JIRA_TEST_SUBTASK_TYPE",
    "JIRA_PUBLISH_MODE",
    "GROQ_API_KEY",
    "LANGFUSE_PUBLIC_KEY",  # T-40: sin claves en el entorno, las pruebas nunca trazan de verdad
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "LANGFUSE_BASE_URL",  # alias de LANGFUSE_HOST (nombre del apartado .env de Langfuse)
    "LANGFUSE_CAPTURE_CONTENT",
    "OPENROUTER_API_KEY",
    "OLLAMA_BASE_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",  # PA-278
    "POSTGRES_PORT",
    "DATABASE_URL",
    "APP_ENV",
    "LOG_LEVEL",
    "MODELS_CONFIG_PATH",
]


@pytest.fixture(scope="session", autouse=True)
def _no_automatic_garbage_collection() -> Iterator[None]:
    """Sin recolección automática durante las pruebas (PA-425).

    Si una prueba deja a medias un `stream()` de LangGraph, el recolector puede finalizarlo
    en cualquier momento, también mientras arranca un hilo de otra prueba: el finalizador cierra
    un `ThreadPoolExecutor` y en Python 3.12 el arranque del hilo se bloquea para siempre. Sin
    recolección automática, los finalizadores solo corren en `_collect_garbage_per_module`.
    """
    gc.disable()
    yield
    gc.enable()


@pytest.fixture(scope="module", autouse=True)
def _collect_garbage_per_module() -> Iterator[None]:
    """Recoge la basura al acabar cada archivo de pruebas, entre pruebas y sin hilos arrancando."""
    yield
    gc.collect()


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Entorno sin ninguna variable del proyecto (simula que no hay claves configuradas)."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def no_keys_settings(clean_env: pytest.MonkeyPatch) -> Settings:
    """Settings sin `.env` ni variables de entorno."""
    return Settings(_env_file=None)
