"""Prueba de conexiones (T-29 mínima; RF-01, RF-40, RF-41): `core/health.py`.

Solo fakes: catálogo en memoria, `FakeIssueTracker` de `tests/fakes/` y la comprobación de la
base de datos inyectada como callable. Configuración y credenciales 100 % ficticias; no se
conecta a ningún servicio real.
"""

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
from pydantic import SecretStr
from sqlalchemy.engine import make_url

import core.health as health
from adapters.base import TaskType
from adapters.errors import AuthenticationError, ExternalServiceError
from core.config import AppConfig, ModelsConfig, Settings
from core.health import (
    MAX_DETAIL_CHARS,
    NOT_CONFIGURED,
    ConnectionTester,
    MissingMigrationsError,
    ServiceCheck,
    alembic_head,
    database_check,
    jira_host,
    normalize_model,
)
from tests.fakes.issue_tracker import FakeIssueTracker

LOCAL_URL = "http://ollama.example.invalid:11434/v1"
CLOUD_URL = "https://nube.example.invalid/v1"
CLOUD_KEY_ENV = "NUBE_FICTICIA_API_KEY"
FAKE_KEY = "clave-ficticia-health-0000"
DEMO_USER = "usuario_demo"
DEMO_PASS = "clave_demo"
DB_URL = f"postgresql+psycopg://{DEMO_USER}:{DEMO_PASS}@127.0.0.1:1/agente_demo"


# --- Configuración ficticia ---------------------------------------------------------------------


def _models(
    local_models: tuple[str, ...] = ("qwen3",), embeddings_model: str = "bge-m3"
) -> ModelsConfig:
    chain = [{"provider": "local", "model": m} for m in local_models]
    chain.append({"provider": "nube", "model": "modelo-nube-ficticio"})
    return ModelsConfig.model_validate(
        {
            "providers": {
                "local": {"type": "openai_compatible", "base_url": LOCAL_URL},
                "nube": {
                    "type": "openai_compatible",
                    "base_url": CLOUD_URL,
                    "api_key_env": CLOUD_KEY_ENV,
                },
            },
            "tasks": {task.value: chain for task in TaskType},
            "embeddings": {"provider": "local", "model": embeddings_model, "dimensions": 1024},
            "limits": {
                "max_retries_on_429": 1,
                "context_token_budget": 1000,
                "daily_token_warning": 1000,
            },
            "rag": {"chunk_tokens": 100, "overlap_tokens": 10, "top_k": 3, "memory_boost": 1.0},
        }
    )


def _config(models: ModelsConfig | None = None, **settings: Any) -> AppConfig:
    values: dict[str, Any] = {"jira_base_url": "https://sitio-ficticio.example.invalid"}
    return AppConfig(Settings(_env_file=None, **(values | settings)), models or _models())


@pytest.fixture
def env(clean_env: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Entorno limpio y con la clave ficticia del proveedor «nube»."""
    clean_env.setenv(CLOUD_KEY_ENV, FAKE_KEY)
    yield clean_env


@dataclass
class FakeCatalog:
    """Catálogo en memoria: `models[proveedor]`, o la excepción de `errors[proveedor]`."""

    models: dict[str, set[str]] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    slow: dict[str, threading.Event] = field(default_factory=dict)

    def list_models(self, provider: str) -> set[str]:
        self.calls.append(provider)
        if provider in self.slow:
            self.slow[provider].wait(1.0)  # ~1 s como mucho: se libera al acabar la prueba
        if provider in self.errors:
            raise self.errors[provider]
        return set(self.models.get(provider, set()))


def _healthy_catalog() -> FakeCatalog:
    return FakeCatalog(
        models={
            "local": {"qwen3:latest", "bge-m3:latest"},
            "nube": {"modelo-nube-ficticio"},
        }
    )


def _db_ok() -> str:
    return "Conexión correcta con db-ficticia:5432; migraciones al día (0001_ficticia)."


def _by_service(checks: list[ServiceCheck]) -> dict[str, ServiceCheck]:
    return {c.service: c for c in checks}


# --- Todo correcto ------------------------------------------------------------------------------


def test_run_reports_every_service_ok_when_all_respond(env: pytest.MonkeyPatch) -> None:
    """CA T-29 (RF-01, RF-40, RF-41): un resultado correcto por Jira, BD, proveedor y embeddings."""
    tester = ConnectionTester(
        _config(), _healthy_catalog(), issue_tracker=FakeIssueTracker(), database_check=_db_ok
    )
    checks = tester.run()
    assert [c.service for c in checks] == [
        "Jira",
        "PostgreSQL",
        "Modelos · local",
        "Modelos · nube",
        "Embeddings",
    ]
    assert all(c.ok for c in checks), checks
    by = _by_service(checks)
    assert by["Jira"].detail == "Conexión correcta con sitio-ficticio.example.invalid."
    assert by["PostgreSQL"].detail == _db_ok()
    assert by["Modelos · local"].detail == "1 modelo disponible."
    assert by["Embeddings"].detail == "1 modelo disponible."
    assert all(c.duration_ms >= 0 for c in checks)


def test_run_counts_models_once_when_repeated_in_several_chains(env: pytest.MonkeyPatch) -> None:
    """CA T-29: un modelo repetido en varias tareas cuenta una vez; plural «modelos disponibles»."""
    catalog = _healthy_catalog()
    catalog.models["local"].add("modelo-local-b:latest")
    config = _config(_models(local_models=("qwen3", "modelo-local-b")))
    checks = _by_service(ConnectionTester(config, catalog, database_check=_db_ok).run())
    assert checks["Modelos · local"].detail == "2 modelos disponibles."


def test_run_only_calls_model_catalog_when_checking_models(env: pytest.MonkeyPatch) -> None:
    """CA T-29 (sin gastar tokens): solo se lista el catálogo; no hay LLM en el tester."""
    catalog = _healthy_catalog()
    tracker = FakeIssueTracker()
    ConnectionTester(_config(), catalog, issue_tracker=tracker, database_check=_db_ok).run()
    assert sorted(catalog.calls) == ["local", "local", "nube"]  # tareas + embeddings
    assert tracker.writes == []  # solo lectura en Jira
    params = ConnectionTester.__init__.__code__.co_varnames
    assert "llm" not in params


# --- Fallos y tiempo límite ---------------------------------------------------------------------


def test_run_keeps_other_results_when_one_fails_and_other_times_out(
    env: pytest.MonkeyPatch,
) -> None:
    """CA T-29: un servicio caído y otro lento no impiden los resultados de los demás."""
    release = threading.Event()
    catalog = _healthy_catalog()
    catalog.slow["nube"] = release
    tracker = FakeIssueTracker(connected=False)
    tester = ConnectionTester(
        _config(), catalog, issue_tracker=tracker, database_check=_db_ok, timeout_s=0.2
    )
    try:
        started = time.perf_counter()
        checks = _by_service(tester.run())
        elapsed = time.perf_counter() - started
    finally:
        release.set()
    assert elapsed < 0.9  # no espera al lento
    assert not checks["Jira"].ok
    assert checks["Jira"].detail == "No se pudo conectar con Jira (fake)."
    assert not checks["Modelos · nube"].ok
    assert checks["Modelos · nube"].detail == "No respondió en 0.2 s."
    assert checks["Modelos · nube"].duration_ms == 200
    assert checks["PostgreSQL"].ok
    assert checks["Modelos · local"].ok
    assert checks["Embeddings"].ok


def test_run_reports_missing_models_when_not_downloaded(env: pytest.MonkeyPatch) -> None:
    """CA T-29 (RF-41): un modelo configurado que no está en el proveedor → «Faltan modelos»."""
    catalog = _healthy_catalog()
    catalog.models["local"] = {"bge-m3:latest"}
    checks = _by_service(ConnectionTester(_config(), catalog, database_check=_db_ok).run())
    assert not checks["Modelos · local"].ok
    assert checks["Modelos · local"].detail == "Faltan modelos: qwen3."
    assert checks["Embeddings"].ok


def test_run_lists_five_missing_models_and_counts_rest_when_many_missing(
    env: pytest.MonkeyPatch,
) -> None:
    """CA T-29 (límite): se muestran 5 modelos que faltan y «y N más»."""
    names = tuple(f"modelo-{i}" for i in range(8))
    catalog = _healthy_catalog()
    config = _config(_models(local_models=names))
    checks = _by_service(ConnectionTester(config, catalog, database_check=_db_ok).run())
    detail = checks["Modelos · local"].detail
    assert detail == "Faltan modelos: modelo-0, modelo-1, modelo-2, modelo-3, modelo-4 y 3 más."


@pytest.mark.parametrize(
    ("configured", "available"),
    [("qwen3", "qwen3:latest"), ("qwen3:latest", "qwen3"), ("qwen3", "qwen3")],
)
def test_run_treats_latest_tag_as_equal_when_comparing_models(
    env: pytest.MonkeyPatch, configured: str, available: str
) -> None:
    """CA T-29: `qwen3` ≡ `qwen3:latest` en ambos sentidos."""
    catalog = FakeCatalog(models={"local": {available, "bge-m3"}, "nube": {"modelo-nube-ficticio"}})
    config = _config(_models(local_models=(configured,)))
    checks = _by_service(ConnectionTester(config, catalog, database_check=_db_ok).run())
    assert checks["Modelos · local"].ok, checks["Modelos · local"].detail
    assert checks["Embeddings"].ok


def test_run_reports_missing_when_tag_differs(env: pytest.MonkeyPatch) -> None:
    """CA T-29 (negativa): `qwen3:8b` no equivale a `qwen3:latest`."""
    catalog = FakeCatalog(
        models={"local": {"qwen3:8b", "bge-m3"}, "nube": {"modelo-nube-ficticio"}}
    )
    checks = _by_service(ConnectionTester(_config(), catalog, database_check=_db_ok).run())
    assert checks["Modelos · local"].detail == "Faltan modelos: qwen3."


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("qwen3", "qwen3:latest"),
        ("qwen3:latest", "qwen3:latest"),
        ("  qwen3  ", "qwen3:latest"),
        ("qwen3:8b", "qwen3:8b"),
        ("openai/gpt-oss-20b", "openai/gpt-oss-20b:latest"),
    ],
)
def test_normalize_model_adds_latest_when_tag_missing(name: str, expected: str) -> None:
    """CA T-29: normalize_model añade `:latest` solo si falta la etiqueta."""
    assert normalize_model(name) == expected


def test_run_skips_provider_without_key_when_checking_models(clean_env: pytest.MonkeyPatch) -> None:
    """CA T-29: proveedor sin clave → «Sin configurar.» y el catálogo NO se llama para él."""
    catalog = _healthy_catalog()
    checks = _by_service(ConnectionTester(_config(), catalog, database_check=_db_ok).run())
    assert not checks["Modelos · nube"].ok
    assert checks["Modelos · nube"].detail == f"{NOT_CONFIGURED}."
    assert "nube" not in catalog.calls
    assert checks["Modelos · local"].ok


def test_run_reports_not_configured_when_jira_and_database_missing(
    env: pytest.MonkeyPatch,
) -> None:
    """CA T-29 (RF-01): sin tracker de Jira ni comprobación de BD → «Sin configurar.»."""
    checks = _by_service(ConnectionTester(_config(), _healthy_catalog()).run())
    assert checks["Jira"] == ServiceCheck(
        "Jira", False, "Sin configurar.", checks["Jira"].duration_ms
    )
    assert not checks["PostgreSQL"].ok
    assert checks["PostgreSQL"].detail == "Sin configurar."


# --- Detalle sin secretos -----------------------------------------------------------------------


def test_run_hides_text_when_unexpected_exception(env: pytest.MonkeyPatch) -> None:
    """CA T-29 (seguridad): una excepción genérica → «Error inesperado…», sin su texto."""
    leaked = f"postgresql://{DEMO_USER}:{DEMO_PASS}@db/x {FAKE_KEY}"

    def broken_db() -> str:
        raise RuntimeError(leaked)

    catalog = _healthy_catalog()
    catalog.errors["nube"] = ValueError(leaked)
    checks = _by_service(ConnectionTester(_config(), catalog, database_check=broken_db).run())
    for service in ("PostgreSQL", "Modelos · nube"):
        assert checks[service].detail == "Error inesperado al comprobar el servicio."
    joined = " ".join(c.detail for c in checks.values())
    for fragment in (FAKE_KEY, DEMO_USER, DEMO_PASS):
        assert fragment not in joined


def test_run_shows_message_when_agent_error(env: pytest.MonkeyPatch) -> None:
    """CA T-29: un AgentError (ya saneado) muestra su mensaje."""
    catalog = _healthy_catalog()
    catalog.errors["nube"] = AuthenticationError(
        "nube.example.invalid ha rechazado la clave del proveedor (HTTP 401).", service="nube"
    )
    checks = _by_service(ConnectionTester(_config(), catalog, database_check=_db_ok).run())
    assert not checks["Modelos · nube"].ok
    assert checks["Modelos · nube"].detail == (
        "nube.example.invalid ha rechazado la clave del proveedor (HTTP 401)."
    )


def test_run_truncates_detail_when_message_is_long(env: pytest.MonkeyPatch) -> None:
    """CA T-29 (límite): el detalle se recorta a MAX_DETAIL_CHARS."""

    def long_db() -> str:
        raise ExternalServiceError("x" * (MAX_DETAIL_CHARS * 3), service="postgresql")

    checks = _by_service(
        ConnectionTester(_config(), _healthy_catalog(), database_check=long_db).run()
    )
    assert len(checks["PostgreSQL"].detail) == MAX_DETAIL_CHARS


# --- jira_host ----------------------------------------------------------------------------------


def test_jira_host_returns_atlassian_api_when_cloud_id_present(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """CA T-29 (RF-01): con cloud id (token con ámbito) el host es api.atlassian.com."""
    config = _config(jira_cloud_id=SecretStr("cloud-id-ficticio-0000"))
    assert jira_host(config) == "api.atlassian.com"


def test_jira_host_returns_host_without_credentials_when_base_url(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """CA T-29: sin cloud id, solo el host de JIRA_BASE_URL (sin usuario ni ruta)."""
    config = _config(jira_base_url=f"https://{DEMO_USER}:{DEMO_PASS}@sitio.example.invalid/jira")
    assert jira_host(config) == "sitio.example.invalid"


def test_jira_host_returns_placeholder_when_nothing_configured(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """CA T-29 (límite): sin URL ni cloud id → «?»."""
    assert jira_host(_config(jira_base_url=None)) == "?"


# --- database_check -----------------------------------------------------------------------------


class _FailingEngine:
    def connect(self) -> Any:
        raise sqlalchemy.exc.OperationalError(
            "SELECT 1", {}, Exception(f"conexión rechazada {DEMO_USER}:{DEMO_PASS}")
        )

    def dispose(self) -> None:
        self.disposed = True


def test_database_check_hides_credentials_when_connection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA T-29 (seguridad): fallo de conexión → error con host:puerto y sin usuario."""
    engine = _FailingEngine()
    seen: dict[str, Any] = {}

    def fake_create_engine(url: Any, **kwargs: Any) -> _FailingEngine:
        seen.update(kwargs)
        return engine

    monkeypatch.setattr(sqlalchemy, "create_engine", fake_create_engine)
    check = database_check(make_url(DB_URL), timeout_s=1)
    with pytest.raises(ExternalServiceError) as info:
        check()
    message = str(info.value)
    assert "127.0.0.1:1" in message
    assert DEMO_USER not in message
    assert DEMO_PASS not in message
    assert info.value.__cause__ is None
    assert seen["connect_args"] == {
        "connect_timeout": 1,
        "options": "-c statement_timeout=1000",
    }
    assert getattr(engine, "disposed", False)


def test_database_check_uses_default_port_when_url_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA T-29 (límite): sin puerto en la URL se muestra 5432."""
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_a, **_k: _FailingEngine())
    url = make_url(f"postgresql+psycopg://{DEMO_USER}:{DEMO_PASS}@db-ficticia/agente_demo")
    with pytest.raises(ExternalServiceError, match="db-ficticia:5432"):
        database_check(url)()


@pytest.fixture
def sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`create_engine` apunta a un SQLite de archivo (sin `connect_args`, que SQLite no acepta)."""
    path = tmp_path / "health.sqlite"
    real_create_engine = sqlalchemy.create_engine

    def sqlite_engine(_url: Any, **_kwargs: Any) -> sqlalchemy.Engine:
        return real_create_engine(f"sqlite:///{path.as_posix()}")

    monkeypatch.setattr(sqlalchemy, "create_engine", sqlite_engine)
    monkeypatch.setattr(health, "alembic_head", lambda: "0002_ficticia")
    return path


def _set_revision(path: Path, revision: str) -> None:
    from sqlalchemy.engine import create_engine as real_create_engine  # sin el monkeypatch

    engine = real_create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("CREATE TABLE alembic_version (version_num TEXT)"))
            conn.execute(
                sqlalchemy.text("INSERT INTO alembic_version VALUES (:v)"), {"v": revision}
            )
    finally:
        engine.dispose()


def test_database_check_raises_missing_migrations_when_no_alembic_table(sqlite_db: Path) -> None:
    """CA T-29: conecta pero sin tabla de Alembic → «no hay migraciones aplicadas»."""
    with pytest.raises(MissingMigrationsError, match="no hay migraciones aplicadas") as info:
        database_check(make_url(DB_URL))()
    assert "127.0.0.1:1" in str(info.value)
    assert DEMO_PASS not in str(info.value)


def test_database_check_raises_missing_migrations_when_revision_differs(sqlite_db: Path) -> None:
    """CA T-29: revisión aplicada distinta de head → aviso con ambas revisiones."""
    _set_revision(sqlite_db, "0001_ficticia")
    with pytest.raises(MissingMigrationsError) as info:
        database_check(make_url(DB_URL))()
    assert "0001_ficticia" in str(info.value)
    assert "0002_ficticia" in str(info.value)


def test_database_check_returns_detail_when_migrations_up_to_date(sqlite_db: Path) -> None:
    """CA T-29: revisión al día → detalle con host:puerto y la revisión, sin credenciales."""
    _set_revision(sqlite_db, "0002_ficticia")
    detail = database_check(make_url(DB_URL))()
    assert detail == "Conexión correcta con 127.0.0.1:1; migraciones al día (0002_ficticia)."


def test_tester_shows_missing_migrations_message_when_database_outdated(
    sqlite_db: Path, env: pytest.MonkeyPatch
) -> None:
    """CA T-29: el aviso de migraciones llega tal cual al resultado de PostgreSQL."""
    tester = ConnectionTester(
        _config(), _healthy_catalog(), database_check=database_check(make_url(DB_URL))
    )
    check = _by_service(tester.run())["PostgreSQL"]
    assert not check.ok
    assert "no hay migraciones aplicadas" in check.detail


def test_alembic_head_returns_revision_when_migrations_exist() -> None:
    """CA T-29: alembic_head lee la última revisión de migrations/ sin conectar a la BD."""
    head = alembic_head()
    assert head and head != "None"
