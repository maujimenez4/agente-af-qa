"""Proyecto de Jira de la conversación: `core/projects.py` y su composición (T-50).

Cubre RF-02 (elegir proyecto y recordar el último usado), RF-14 (claves escritas a mano) y la
migración `0003_user_last_project`. Las unitarias usan fakes de `tests/fakes/`; las de
integración, una BD temporal propia que se salta si PostgreSQL no está disponible. Proyectos y
personas 100 % ficticios (DEMO, OTRO, TERCERO).
"""

from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from adapters.base import ProjectSummary
from adapters.errors import ExternalServiceError, NotFoundError
from core.config import AppConfig, Settings, load_models_config
from core.container import build_container
from core.projects import (
    InMemoryLastProjectStore,
    ProjectChoice,
    ProjectService,
    SqlLastProjectStore,
    normalize_issue_key,
    normalize_project_key,
    project_of,
)
from tests.fakes.auth import FakeAuthProvider
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.memory_generator import FakeMemoryGenerator
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore
from tests.fixtures import MODELS_FIXTURE
from tests.pg_temp import alembic_config, temporary_database

AF_USER = "af-demo"
OTHER_USER = "qa-demo"


class MultiProjectTracker(FakeIssueTracker):
    """Fake de Jira cuya conexión ve los proyectos indicados (por defecto DEMO y OTRO)."""

    def __init__(self, keys: tuple[str, ...] = ("DEMO", "OTRO")) -> None:
        super().__init__()
        self.visible = [ProjectSummary(key=k, name=f"Proyecto {k} (ficticio)") for k in keys]
        self.list_calls = 0

    def list_projects(self) -> list[ProjectSummary]:
        self.list_calls += 1
        return list(self.visible)


class BrokenEngine:
    """Engine que falla al abrir la transacción, como una BD caída (sin red)."""

    def begin(self) -> Any:
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("conexión rechazada (ficticia)"))


def _service(
    keys: tuple[str, ...] = ("DEMO", "OTRO"),
    default: str | None = None,
    store: InMemoryLastProjectStore | None = None,
) -> tuple[ProjectService, InMemoryLastProjectStore]:
    store = store or InMemoryLastProjectStore()
    return ProjectService(MultiProjectTracker(keys), store, default), store


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


# --- normalize_project_key -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("DEMO", "DEMO"),
        ("  demo  ", "DEMO"),
        ("Otro", "OTRO"),
        ("ab", "AB"),
        ("proj_2", "PROJ_2"),
        ("\tdemo9\n", "DEMO9"),
    ],
)
def test_normalize_project_key_strips_and_uppercases_when_valid(raw: str, expected: str) -> None:
    """RF-14 · T-50: la clave de proyecto escrita a mano se recorta y pasa a mayúsculas."""
    assert normalize_project_key(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "D", "1DEMO", "DEMO-3", "DE MO", "DEMO!", "_DEMO", "ñandú"],
)
def test_normalize_project_key_rejects_invalid_format(raw: str) -> None:
    """RF-14 · T-50 (negativo): formatos no válidos → ValueError en español."""
    with pytest.raises(ValueError, match="no es una clave de proyecto válida"):
        normalize_project_key(raw)


def test_normalize_project_key_error_message_truncates_input_to_50_chars() -> None:
    """T-50 (límite): el mensaje muestra como mucho 50 caracteres de lo escrito."""
    raw = "  " + "x" * 50 + "OVERFLOW!" + "  "
    with pytest.raises(ValueError) as exc_info:
        normalize_project_key(raw)
    message = str(exc_info.value)
    assert f"«{'x' * 50}»" in message
    assert "OVERFLOW" not in message
    assert "formato esperado: PROYECTO" in message


# --- normalize_issue_key -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("DEMO-3", "DEMO-3"), (" demo-12 ", "DEMO-12"), ("otro_2-7", "OTRO_2-7")],
)
def test_normalize_issue_key_strips_and_uppercases_when_valid(raw: str, expected: str) -> None:
    """RF-14 · T-50: la clave de incidencia escrita a mano se recorta y pasa a mayúsculas."""
    assert normalize_issue_key(raw) == expected


@pytest.mark.parametrize("raw", ["", "DEMO", "DEMO-", "D-1", "DEMO-3a", "-3", "DEMO 3", "1A-2"])
def test_normalize_issue_key_rejects_invalid_format(raw: str) -> None:
    """RF-14 · T-50 (negativo): formatos no válidos → ValueError con el formato esperado."""
    with pytest.raises(ValueError, match="formato esperado: PROYECTO-123"):
        normalize_issue_key(raw)


def test_normalize_issue_key_error_message_truncates_input_to_50_chars() -> None:
    """T-50 (límite): el mensaje de clave de incidencia también se trunca a 50 caracteres."""
    raw = "y" * 50 + "SOBRANTE"
    with pytest.raises(ValueError) as exc_info:
        normalize_issue_key(raw)
    assert f"«{'y' * 50}»" in str(exc_info.value)
    assert "SOBRANTE" not in str(exc_info.value)


# --- project_of ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "project"), [("DEMO-3", "DEMO"), ("OTRO-1", "OTRO"), ("PROJ_2-45", "PROJ_2")]
)
def test_project_of_returns_prefix_of_valid_key(key: str, project: str) -> None:
    """T-50: el proyecto de una incidencia es el prefijo de su clave."""
    assert project_of(key) == project


@pytest.mark.parametrize("key", ["demo-3", "DEMO", "DEMO-", " DEMO-3", ""])
def test_project_of_rejects_invalid_key_without_normalizing(key: str) -> None:
    """T-50 (negativo): `project_of` no normaliza; una clave no válida → ValueError."""
    with pytest.raises(ValueError, match="Clave de Jira no válida"):
        project_of(key)


def test_project_of_error_message_truncates_key() -> None:
    """T-50 (límite): la clave no válida se muestra truncada a 50 caracteres."""
    with pytest.raises(ValueError) as exc_info:
        project_of("z" * 50 + "EXTRA")
    assert "EXTRA" not in str(exc_info.value)


# --- InMemoryLastProjectStore --------------------------------------------------------------


def test_in_memory_last_project_returns_none_when_unknown_user() -> None:
    """RF-02 · T-50: sin proyecto recordado → None."""
    assert InMemoryLastProjectStore().get(AF_USER) is None


def test_in_memory_last_project_set_overwrites_and_is_per_user() -> None:
    """RF-02 · T-50: se recuerda el último por persona, sin mezclar personas."""
    store = InMemoryLastProjectStore()
    store.set(AF_USER, "DEMO")
    store.set(OTHER_USER, "OTRO")
    store.set(AF_USER, "TERCERO")

    assert store.get(AF_USER) == "TERCERO"
    assert store.get(OTHER_USER) == "OTRO"


# --- ProjectService.available --------------------------------------------------------------


def test_available_lists_all_visible_projects_and_preselects_last_used() -> None:
    """RF-02 · T-50: todos los proyectos visibles; preselecciona el último usado (sobre .env)."""
    service, store = _service(default="DEMO")
    store.set(AF_USER, "OTRO")

    choice = service.available(AF_USER)

    assert isinstance(choice, ProjectChoice)
    assert [p.key for p in choice.projects] == ["DEMO", "OTRO"]
    assert choice.preselected == "OTRO"


def test_available_falls_back_to_default_when_last_no_longer_visible() -> None:
    """RF-02 · T-50: el último usado ya no es visible → preselecciona el de `.env`."""
    service, store = _service(default="DEMO")
    store.set(AF_USER, "ANTIGUO")

    assert service.available(AF_USER).preselected == "DEMO"


def test_available_preselects_none_when_default_not_visible() -> None:
    """RF-02 · T-50 (límite): ni el último ni el de `.env` son visibles → sin preselección."""
    service, store = _service(default="AJENO")
    store.set(AF_USER, "ANTIGUO")

    assert service.available(AF_USER).preselected is None


def test_available_preselects_none_without_last_or_default() -> None:
    """RF-02 · T-50 (límite): sin último usado ni proyecto por defecto → None."""
    service, _ = _service(default=None)

    choice = service.available(AF_USER)

    assert choice.preselected is None
    assert [p.key for p in choice.projects] == ["DEMO", "OTRO"]


def test_available_uses_default_when_user_has_no_last_project() -> None:
    """RF-02 · T-50: primera vez de la persona → el de `.env` si es visible."""
    service, store = _service(default="OTRO")
    store.set(OTHER_USER, "DEMO")  # el de otra persona no cuenta

    assert service.available(AF_USER).preselected == "OTRO"


def test_available_with_no_visible_projects_returns_empty_choice() -> None:
    """RF-02 · T-50 (límite): la conexión no ve proyectos → lista vacía y sin preselección."""
    service, store = _service(keys=(), default="DEMO")
    store.set(AF_USER, "DEMO")

    assert service.available(AF_USER) == ProjectChoice(projects=[], preselected=None)


# --- ProjectService.choose -----------------------------------------------------------------


def test_choose_normalizes_validates_and_remembers_project() -> None:
    """RF-02 · RF-14 · T-50: proyecto visible escrito a mano → normalizado y recordado."""
    service, store = _service()

    assert service.choose(AF_USER, "  otro ") == "OTRO"
    assert store.get(AF_USER) == "OTRO"
    assert service.available(AF_USER).preselected == "OTRO"


def test_choose_not_visible_raises_not_found_and_does_not_remember() -> None:
    """RF-02 · T-50 (negativo): proyecto no visible → NotFoundError y no se recuerda."""
    service, store = _service()
    store.set(AF_USER, "DEMO")

    with pytest.raises(NotFoundError, match="El proyecto AJENO no existe") as exc_info:
        service.choose(AF_USER, "ajeno")

    assert exc_info.value.service == "jira"
    assert store.get(AF_USER) == "DEMO"


def test_choose_invalid_format_raises_value_error_without_calling_jira() -> None:
    """RF-14 · T-50 (negativo): formato no válido → ValueError, sin consultar Jira ni recordar."""
    tracker = MultiProjectTracker()
    store = InMemoryLastProjectStore()
    service = ProjectService(tracker, store)

    with pytest.raises(ValueError, match="no es una clave de proyecto válida"):
        service.choose(AF_USER, "DEMO-3")

    assert tracker.list_calls == 0
    assert store.get(AF_USER) is None


# --- Container ----------------------------------------------------------------------------


def test_container_last_projects_defaults_to_in_memory() -> None:
    """T-50: sin almacén inyectado, el último proyecto vive en memoria."""
    container = build_container(**_all_fakes())

    assert isinstance(container.last_projects, InMemoryLastProjectStore)


def test_container_last_projects_is_injectable_via_build_container() -> None:
    """T-50: `build_container(last_projects=...)` usa el almacén inyectado."""
    store = InMemoryLastProjectStore()
    container = build_container(**_all_fakes(), last_projects=store)

    assert container.last_projects is store
    container.projects.choose(AF_USER, "demo")
    assert store.get(AF_USER) == "DEMO"


def test_container_projects_uses_jira_project_key_from_config_as_default(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RF-02 · T-50: `projects` preselecciona `JIRA_PROJECT_KEY` si es visible."""
    clean_env.setenv("JIRA_PROJECT_KEY", "DEMO")
    config = AppConfig(Settings(_env_file=None), load_models_config(MODELS_FIXTURE))
    container = build_container(config=config, memory_dir=tmp_path, **_all_fakes())

    assert container.projects.available(AF_USER).preselected == "DEMO"


def test_container_projects_without_config_has_no_default() -> None:
    """RF-02 · T-50 (límite): sin configuración no hay proyecto por defecto."""
    container = build_container(**_all_fakes())

    assert container.projects.available(AF_USER).preselected is None


def test_container_projects_prefers_last_used_over_config_default(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RF-02 · T-50: el último usado prevalece sobre `JIRA_PROJECT_KEY`."""
    clean_env.setenv("JIRA_PROJECT_KEY", "DEMO")
    config = AppConfig(Settings(_env_file=None), load_models_config(MODELS_FIXTURE))
    fakes = {**_all_fakes(), "issue_tracker": MultiProjectTracker()}
    store = InMemoryLastProjectStore()
    store.set(AF_USER, "OTRO")
    container = build_container(config=config, memory_dir=tmp_path, last_projects=store, **fakes)

    assert container.projects.available(AF_USER).preselected == "OTRO"


# --- SqlLastProjectStore (unitarias, sin red) ----------------------------------------------


def test_sql_last_project_wraps_database_errors_when_unreachable() -> None:
    """T-50 (error): BD caída → ExternalServiceError en español al leer y al guardar."""
    store = SqlLastProjectStore(BrokenEngine())  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError, match="leer el último proyecto") as read_error:
        store.get(AF_USER)
    with pytest.raises(ExternalServiceError, match="guardar el último proyecto") as write_error:
        store.set(AF_USER, "DEMO")

    assert read_error.value.service == write_error.value.service == "postgres"
    assert read_error.value.__cause__ is None  # no se encadena el error del driver


class _RecordingConnection:
    def __init__(self, statements: list[Any]) -> None:
        self._statements = statements

    def execute(self, statement: Any) -> Any:
        self._statements.append(statement)
        return self

    def scalar_one_or_none(self) -> None:
        return None


class RecordingEngine:
    """Engine sin red que guarda las sentencias para compilarlas con el dialecto PostgreSQL."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    def begin(self) -> Any:
        return nullcontext(_RecordingConnection(self.statements))


def _sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_sql_last_project_set_is_an_upsert_by_username() -> None:
    """RF-02 · T-50: `set` es un INSERT … ON CONFLICT (username) DO UPDATE del proyecto."""
    engine = RecordingEngine()
    SqlLastProjectStore(engine).set(AF_USER, "DEMO")  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = " ".join(_sql(statement).split())
    assert sql.startswith("INSERT INTO user_last_project")
    assert "ON CONFLICT (username) DO UPDATE SET project_key = excluded.project_key" in sql
    assert "updated_at = now()" in sql


def test_sql_last_project_get_filters_by_username() -> None:
    """RF-02 · T-50: `get` lee solo el proyecto de esa persona."""
    engine = RecordingEngine()
    assert SqlLastProjectStore(engine).get(AF_USER) is None  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = " ".join(_sql(statement).split())
    assert "SELECT user_last_project.project_key FROM user_last_project" in sql
    assert "WHERE user_last_project.username =" in sql


# --- Integración: migración 0003 y SqlLastProjectStore -------------------------------------


def _tables(engine: Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


@pytest.mark.integration
def test_migration_0003_creates_and_drops_user_last_project() -> None:
    """T-50: 0003 crea `user_last_project` sobre 0002 y su downgrade la borra."""
    with temporary_database("user_last_project_migration_test", revision="0002_artifact_state") as (
        url,
        engine,
    ):
        config = alembic_config(url)
        assert "user_last_project" not in _tables(engine)

        command.upgrade(config, "0003_user_last_project")
        assert "user_last_project" in _tables(engine)
        columns = {c["name"]: c for c in sa.inspect(engine).get_columns("user_last_project")}
        assert set(columns) == {"username", "project_key", "updated_at"}
        assert columns["project_key"]["nullable"] is False
        assert sa.inspect(engine).get_pk_constraint("user_last_project")["constrained_columns"] == [
            "username"
        ]

        command.downgrade(config, "0002_artifact_state")
        assert "user_last_project" not in _tables(engine)
        assert "artifact_state" in _tables(engine)


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    with temporary_database("user_last_project_test") as (_url, engine):
        yield engine


@pytest.fixture
def engine(pg_engine: Engine) -> Engine:
    with pg_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE user_last_project"))
    return pg_engine


@pytest.mark.integration
def test_sql_last_project_returns_none_when_unknown_user(engine: Engine) -> None:
    """RF-02 · T-50: sin fila → None."""
    assert SqlLastProjectStore(engine).get(AF_USER) is None


@pytest.mark.integration
def test_sql_last_project_set_then_get(engine: Engine) -> None:
    """RF-02 · T-50: lo guardado se recupera por persona."""
    store = SqlLastProjectStore(engine)
    store.set(AF_USER, "DEMO")
    store.set(OTHER_USER, "OTRO")

    assert store.get(AF_USER) == "DEMO"
    assert store.get(OTHER_USER) == "OTRO"


@pytest.mark.integration
def test_sql_last_project_upsert_keeps_one_row_and_updates_timestamp(engine: Engine) -> None:
    """RF-02 · T-50: guardar de nuevo sustituye el proyecto (una fila) y renueva updated_at."""
    store = SqlLastProjectStore(engine)
    store.set(AF_USER, "DEMO")
    with engine.connect() as conn:
        first = conn.execute(sa.text("SELECT updated_at FROM user_last_project")).scalar_one()

    store.set(AF_USER, "OTRO")

    assert store.get(AF_USER) == "OTRO"
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT project_key, updated_at FROM user_last_project")).all()
    assert len(rows) == 1
    assert rows[0].project_key == "OTRO"
    assert rows[0].updated_at >= first


@pytest.mark.integration
def test_project_service_remembers_choice_across_restart_with_sql_store(engine: Engine) -> None:
    """RF-02 · T-50: el último proyecto sobrevive a un servicio nuevo sobre la misma BD."""
    ProjectService(MultiProjectTracker(), SqlLastProjectStore(engine)).choose(AF_USER, "otro")

    restarted = ProjectService(MultiProjectTracker(), SqlLastProjectStore(engine), "DEMO")
    assert restarted.available(AF_USER).preselected == "OTRO"
