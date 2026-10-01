"""Contenedor real de la aplicación (`core/factories.build_app_container`, para T-24)."""

from typing import Any

import pytest

from adapters.errors import AgentError, ExternalServiceError, PublishError
from core import factories
from core.config import ROOT_DIR, AppConfig, ConfigError, Settings, load_models_config
from core.container import Container
from tests.fakes.llm import renewal_test_suite

MODELS_FIXTURE = ROOT_DIR / "tests" / "fixtures" / "models.yaml"


def test_pending_test_management_refuses_to_publish_with_a_clear_message() -> None:
    with pytest.raises(PublishError, match="T-30"):
        factories.PendingTestManagement().publish_suite(renewal_test_suite())


def test_pending_test_management_does_not_pretend_there_are_no_cases() -> None:
    with pytest.raises(ExternalServiceError, match="T-30"):
        factories.PendingTestManagement().list_cases("DEMO-3")


def test_build_app_container_refuses_live_mode_until_t30_and_t33() -> None:
    """En `live`, una HU se publicaría sin memoria: se falla al componer."""
    settings = Settings(_env_file=None, jira_publish_mode="live")  # type: ignore[call-arg]
    config = AppConfig(settings, load_models_config(MODELS_FIXTURE))
    with pytest.raises(ConfigError, match="T-30"):
        factories.build_app_container(config)


def test_pending_memory_generator_fails_as_agent_error() -> None:
    with pytest.raises(ExternalServiceError, match="T-33") as raised:
        factories.PendingMemoryGenerator().generate(None)  # type: ignore[arg-type]
    assert isinstance(raised.value, AgentError)  # la UI lo muestra como cualquier error


def test_build_app_container_composes_real_adapters_and_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auditoría, versiones y estado van juntos; el router del selector llega al LLM (RF-42)."""
    built: dict[str, Any] = {}

    def fake(name: str) -> Any:
        def build(*args: Any, **kwargs: Any) -> object:
            built[name] = kwargs
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
    ):
        monkeypatch.setattr(factories, name, fake(name))
    monkeypatch.setattr("core.container.bootstrap_logging", lambda _config: None)
    router = object()
    config = _config()

    container = factories.build_app_container(config, router=router)  # type: ignore[arg-type]

    assert isinstance(container, Container)
    assert set(built) >= {"build_audit", "build_versions", "build_state_store"}
    assert built["build_llm_provider"] == {"router": router}
    assert isinstance(container.test_management, factories.PendingTestManagement)
    assert isinstance(container.memory_generator, factories.PendingMemoryGenerator)
    assert container.versions is not None
    assert container.approvals.store is container.state_store
    assert container.publish_mode == "simulation"  # por defecto no se escribe en Jira
    assert container.require_actor is True  # T-52: la app exige quién actúa


def _config() -> Any:
    settings = Settings(_env_file=None, jira_publish_mode="simulation")  # type: ignore[call-arg]
    return AppConfig(settings, load_models_config(MODELS_FIXTURE))
