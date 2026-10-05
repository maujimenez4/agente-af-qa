"""Fixtures compartidas de las pruebas."""

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
