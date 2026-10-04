"""Vista de Administración de Streamlit (T-29 mínima; RF-01, RF-40, RF-41).

Solo las funciones puras de `app/views/administracion.py` (sin Streamlit en ejecución) y
`run_checks` con el catálogo y la base de datos sustituidos por fakes. Datos 100 % ficticios.
"""

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from adapters.base import TaskType, User
from app.session import SessionState
from app.views.administracion import (
    TEST_INTERVAL_S,
    allowed,
    check_rows,
    model_rows,
    run_checks,
    wait_seconds,
)
from core import factories
from core.config import AppConfig, Settings, load_models_config
from core.health import ServiceCheck
from tests.fakes.issue_tracker import FakeIssueTracker

MODELS_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "models.yaml"
DEMO_USER = "usuario_demo"
DEMO_PASS = "clave_demo"
OLLAMA_URL = f"http://{DEMO_USER}:{DEMO_PASS}@ollama.example.invalid:11434/v1"


@pytest.fixture
def config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    settings = Settings(
        _env_file=None,
        ollama_base_url=OLLAMA_URL,
        jira_base_url="https://sitio-ficticio.example.invalid",
    )
    return AppConfig(settings, load_models_config(MODELS_FIXTURE))


# --- wait_seconds -------------------------------------------------------------------------------


def test_wait_seconds_returns_none_when_never_tested() -> None:
    """CA T-29: sin prueba previa se puede probar ya."""
    assert wait_seconds(None, 100.0) is None


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [(0.0, 10), (0.5, 10), (3.2, 7), (9.0, 1), (9.99, 1)],
)
def test_wait_seconds_rounds_up_when_within_interval(elapsed: float, expected: int) -> None:
    """CA T-29: dentro de los 10 s devuelve los segundos que faltan, redondeados hacia arriba."""
    assert wait_seconds(100.0, 100.0 + elapsed) == expected


@pytest.mark.parametrize("elapsed", [TEST_INTERVAL_S, TEST_INTERVAL_S + 0.1, 3600.0])
def test_wait_seconds_returns_none_when_interval_elapsed(elapsed: float) -> None:
    """CA T-29 (límite): a partir de 10 s se puede volver a probar."""
    assert wait_seconds(100.0, 100.0 + elapsed) is None


def test_wait_seconds_uses_custom_interval_when_given() -> None:
    """CA T-29: el intervalo es configurable en la función."""
    assert wait_seconds(0.0, 1.0, interval_s=3.0) == 2
    assert wait_seconds(0.0, 3.0, interval_s=3.0) is None


# --- check_rows ---------------------------------------------------------------------------------


def test_check_rows_marks_status_and_duration_when_checks_given() -> None:
    """CA T-29: una fila por servicio con ✅/❌, el detalle y «N ms»."""
    rows = check_rows(
        [
            ServiceCheck("Jira", True, "Conexión correcta con sitio.example.invalid.", 412),
            ServiceCheck("Modelos · local", False, "Faltan modelos: qwen3.", 0),
        ]
    )
    assert rows == [
        {
            "Servicio": "Jira",
            "Estado": "✅",
            "Detalle": "Conexión correcta con sitio.example.invalid.",
            "Tiempo": "412 ms",
        },
        {
            "Servicio": "Modelos · local",
            "Estado": "❌",
            "Detalle": "Faltan modelos: qwen3.",
            "Tiempo": "0 ms",
        },
    ]


def test_check_rows_returns_empty_when_no_checks() -> None:
    """CA T-29 (límite): sin resultados no hay filas."""
    assert check_rows([]) == []


# --- model_rows ---------------------------------------------------------------------------------


def test_model_rows_lists_chains_and_embeddings_when_config_loaded(config: AppConfig) -> None:
    """CA T-29 (RF-40): una fila por modelo de cada cadena (con su orden) y otra de embeddings."""
    rows = model_rows(config)
    expected = sum(len(chain) for chain in config.models.tasks.values()) + 1
    assert len(rows) == expected
    story = [r for r in rows if r["Tarea"] == TaskType.GENERATE_STORY.value]
    assert story == [
        {
            "Tarea": "generate_story",
            "Orden": "1",
            "Proveedor": "groq",
            "Modelo": "openai/gpt-oss-120b",
            "Host": "api.groq.com",
        },
        {
            "Tarea": "generate_story",
            "Orden": "2",
            "Proveedor": "openrouter",
            "Modelo": "POR_DEFINIR:free",
            "Host": "openrouter.ai",
        },
    ]
    assert rows[-1] == {
        "Tarea": "embeddings",
        "Orden": "1",
        "Proveedor": "local",
        "Modelo": "bge-m3",
        "Host": "ollama.example.invalid:11434",
    }


def test_model_rows_show_host_only_when_url_has_credentials(config: AppConfig) -> None:
    """CA T-29 (seguridad): el host nunca lleva esquema, ruta, usuario ni contraseña."""
    for row in model_rows(config):
        for leaked in (DEMO_USER, DEMO_PASS, "://", "/v1", "@"):
            assert leaked not in row["Host"]


def test_model_rows_does_not_show_keys_when_provider_has_one(
    config: AppConfig, clean_env: pytest.MonkeyPatch
) -> None:
    """CA T-29 (seguridad): la clave de un proveedor no aparece en ninguna fila."""
    clean_env.setenv("GROQ_API_KEY", "clave-ficticia-vista-0000")
    keyed = AppConfig(Settings(_env_file=None), config.models)
    joined = repr(model_rows(keyed))
    assert "clave-ficticia-vista-0000" not in joined


# --- allowed ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "expected"), [("admin", True), ("functional", False), ("qa", False)]
)
def test_allowed_only_for_admin_when_role_given(role: str, expected: bool) -> None:
    """CA T-29 (solo admin): solo el rol admin ve la Administración."""
    session = SessionState(user=User(username=f"{role}-demo", role=role))  # type: ignore[arg-type]
    assert allowed(session) is expected


def test_allowed_false_when_no_user() -> None:
    """CA T-29 (negativa): sin sesión iniciada no se permite."""
    assert allowed(SessionState()) is False


# --- run_checks ---------------------------------------------------------------------------------


class FakeHttpCatalog:
    instances: ClassVar[list["FakeHttpCatalog"]] = []

    def __init__(self, base_urls: dict[str, str], api_keys: dict[str, Any]) -> None:
        self.base_urls = base_urls
        self.api_keys = api_keys
        self.calls: list[str] = []
        self.closed = False
        FakeHttpCatalog.instances.append(self)

    def list_models(self, provider: str) -> set[str]:
        self.calls.append(provider)
        return {"bge-m3:latest"}

    def close(self) -> None:
        self.closed = True


def test_run_checks_composes_fakes_and_closes_catalog_when_called(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA T-29: run_checks prueba cada servicio, solo lista modelos y cierra el catálogo."""
    FakeHttpCatalog.instances = []
    monkeypatch.setattr(factories, "HttpModelCatalog", FakeHttpCatalog)
    monkeypatch.setattr(factories, "database_check", lambda _url: lambda: "BD ficticia correcta.")
    tracker = FakeIssueTracker()
    checks = {c.service: c for c in run_checks(config, tracker)}
    (catalog,) = FakeHttpCatalog.instances
    assert catalog.closed
    assert set(catalog.base_urls) == {"groq", "openrouter", "local"}
    assert catalog.api_keys["groq"] is None
    assert checks["Jira"].ok
    assert checks["PostgreSQL"].detail == "BD ficticia correcta."
    assert checks["Modelos · groq"].detail == "Sin configurar."
    assert checks["Embeddings"].ok
    assert set(catalog.calls) == {"local"}
    assert tracker.writes == []


def test_run_checks_passes_key_when_provider_configured(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch, clean_env: pytest.MonkeyPatch
) -> None:
    """CA T-29: con clave en la configuración, el catálogo la recibe como SecretStr."""
    clean_env.setenv("GROQ_API_KEY", "clave-ficticia-vista-0001")
    keyed = AppConfig(Settings(_env_file=None), config.models)
    FakeHttpCatalog.instances = []
    monkeypatch.setattr(factories, "HttpModelCatalog", FakeHttpCatalog)
    monkeypatch.setattr(factories, "database_check", lambda _url: lambda: "BD ficticia correcta.")
    run_checks(keyed, None)
    (catalog,) = FakeHttpCatalog.instances
    assert isinstance(catalog.api_keys["groq"], SecretStr)
    assert catalog.closed
