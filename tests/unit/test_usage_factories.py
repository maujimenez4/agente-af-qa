"""Composición del registro de uso (T-32 · RF-43): `core/factories.build_usage_recorder`.

Sin base de datos real: la URL es SQLite en memoria y el resto de factorías se sustituyen.
"""

from typing import Any

import pytest
import sqlalchemy as sa

from adapters.llm.usage import SqlUsageRecorder
from core import factories
from core.config import ROOT_DIR, AppConfig, Settings, load_models_config

MODELS_FIXTURE = ROOT_DIR / "tests" / "fixtures" / "models.yaml"


def _config(**settings: Any) -> AppConfig:
    values: dict[str, Any] = {"jira_publish_mode": "simulation", **settings}
    return AppConfig(
        Settings(_env_file=None, **values),  # type: ignore[call-arg]
        load_models_config(MODELS_FIXTURE),
    )


def test_build_usage_recorder_uses_settings_sqlalchemy_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA-8 · RF-43: el recorder se crea con `config.settings.sqlalchemy_url()`."""
    config = _config(database_url="sqlite://")
    urls: list[sa.URL] = []

    def spy_from_url(cls: type[SqlUsageRecorder], url: sa.URL) -> SqlUsageRecorder:
        urls.append(url)
        return cls(sa.create_engine("sqlite://"))

    monkeypatch.setattr(SqlUsageRecorder, "from_url", classmethod(spy_from_url))

    recorder = factories.build_usage_recorder(config)

    assert isinstance(recorder, SqlUsageRecorder)
    assert urls == [config.settings.sqlalchemy_url()]


def test_build_usage_recorder_points_to_configured_database() -> None:
    """CA-8: con DATABASE_URL ficticio de SQLite el motor apunta a esa base de datos."""
    recorder = factories.build_usage_recorder(_config(database_url="sqlite://"))

    assert isinstance(recorder, SqlUsageRecorder)
    assert recorder._engine.url.drivername == "sqlite"


def test_build_app_container_passes_sql_usage_recorder_to_llm_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA-8 · RF-43: el contenedor de la app entrega un SqlUsageRecorder al proveedor LLM."""
    calls: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}

    def fake(name: str) -> Any:
        def build(*args: Any, **kwargs: Any) -> object:
            calls[name] = (args, kwargs)
            return object()

        return build

    for name in (
        "build_issue_tracker",
        "build_llm_provider",
        "build_embeddings",
        "build_vector_store",
        "build_auth",
        "build_audit",
        "build_versions",
        "build_state_store",
        "build_last_projects",
        "build_conversations",
        "build_test_management",
    ):
        monkeypatch.setattr(factories, name, fake(name))
    monkeypatch.setattr("core.container.bootstrap_logging", lambda _config: None)
    config = _config(database_url="sqlite://")
    router = object()

    factories.build_app_container(config, router=router)  # type: ignore[arg-type]

    args, kwargs = calls["build_llm_provider"]
    recorder = args[1] if len(args) > 1 else kwargs.get("recorder")
    assert args[0] is config
    assert isinstance(recorder, SqlUsageRecorder)
    assert recorder._engine.url.drivername == "sqlite"
    assert kwargs["router"] is router
