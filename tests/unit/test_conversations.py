"""Conversaciones persistentes y lista por usuario (T-52 · RF-20, RF-47).

Cubren `core/conversations.py` (títulos, resúmenes, almacenes en memoria y SQL, propiedad del
hilo), la fila que mantienen los nodos del grafo a lo largo del flujo, la composición
(`Container.conversations`, `core/factories`), `postgres_checkpointer` y la migración `0004`.
Las unitarias usan los fakes de `tests/fakes/` y engines sin red; las de integración, una BD
temporal propia (`tests/pg_temp`) que se salta si PostgreSQL no está disponible. Personas,
proyectos e hilos 100 % ficticios.
"""

import copy
import logging
import warnings
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import psycopg
import pydantic
import pytest
import sqlalchemy as sa
from alembic import command
from langgraph.checkpoint.serde.event_hooks import register_serde_event_listener
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from adapters.errors import ExternalServiceError, NotFoundError
from core import factories
from core.config import AppConfig, Settings, load_models_config
from core.container import Container, build_container
from core.conversations import (
    ConversationStatus,
    ConversationSummary,
    InMemoryConversationStore,
    SqlConversationStore,
    conversation_title,
    new_conversation_config,
    new_summary,
    resume_config,
)
from core.graph import Origin, build_graph, initial_state
from core.graph import builder as graph_builder
from core.graph.nodes import GraphNodes
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus
from tests.fakes.auth import FakeAuthProvider
from tests.fakes.container import fake_container
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.memory_generator import FakeMemoryGenerator
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore
from tests.pg_temp import alembic_config, temporary_database

AF_USER = "af-demo"
QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
EPIC_ORIGIN: Origin = {"kind": "epic", "key": "DEMO-1"}
NEED_TEXT = "Avisar a la persona socia ficticia tres dias antes del vencimiento (texto ficticio)."
NEED_ORIGIN: Origin = {"kind": "need", "project": "DEMO", "text": NEED_TEXT}
FEEDBACK = "Anade un criterio ficticio sobre el aviso de vencimiento."
EDITED_TITLE = "Renovar un prestamo desde la ficha ficticia editada"
FAKE_PASSWORD = "clave-ficticia-1234"
BASE_TIME = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


# --- utilidades --------------------------------------------------------------------------


class RecordingConversationStore(InMemoryConversationStore):
    """Almacén en memoria que además guarda cada `update` recibido (incluso de hilos ajenos)."""

    def __init__(self) -> None:
        super().__init__()
        self.updates: list[tuple[str, str, int | None]] = []

    def update(
        self,
        thread_id: str,
        *,
        status: ConversationStatus,
        artifact_id: str | None = None,
        version: int | None = None,
        username: str | None = None,
    ) -> None:
        self.updates.append((thread_id, status, version))
        super().update(
            thread_id, status=status, artifact_id=artifact_id, version=version, username=username
        )

    def statuses(self, thread_id: str) -> list[str]:
        return [status for tid, status, _ in self.updates if tid == thread_id]


def _thread() -> str:
    return f"hilo-{uuid4()}"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _container(
    tmp_path: Path, store: InMemoryConversationStore | None = None, **overrides: object
) -> tuple[Container, RecordingConversationStore]:
    conversations = store or RecordingConversationStore()
    container = fake_container(tmp_path, conversations=conversations, **overrides)
    return container, conversations  # type: ignore[return-value]


def _start(
    graph: CompiledStateGraph,
    thread_id: str,
    mode: str = "functional",
    origin: Origin = STORY_ORIGIN,
    user: str = AF_USER,
) -> dict[str, Any]:
    state = initial_state(user, mode, origin)  # type: ignore[arg-type]
    return graph.invoke(state, _config(thread_id))


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    (pending,) = result["__interrupt__"]
    return pending.value


def _pending(graph: CompiledStateGraph, thread_id: str) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(_config(thread_id)).tasks if t.interrupts]
    return task.interrupts[-1].value


def _resume(graph: CompiledStateGraph, thread_id: str, answer: object) -> dict[str, Any]:
    return graph.invoke(Command(resume=answer), _config(thread_id))


def _approve(graph: CompiledStateGraph, thread_id: str) -> dict[str, Any]:
    fingerprint = _pending(graph, thread_id)["fingerprint"]
    return _resume(graph, thread_id, {"decision": "approve", "fingerprint": fingerprint})


def _summary(
    thread_id: str,
    user: str = AF_USER,
    updated_at: datetime = BASE_TIME,
    status: ConversationStatus = "started",
) -> ConversationSummary:
    return ConversationSummary(
        thread_id=thread_id,
        username=user,
        project_key="DEMO",
        mode="functional",
        origin_kind="story",
        origin_key="DEMO-3",
        title="Evolucionar DEMO-3",
        status=status,
        created_at=BASE_TIME,
        updated_at=updated_at,
    )


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


# --- conversation_title y new_summary ------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "kind", "key", "expected"),
    [
        ("functional", "story", "DEMO-3", "Evolucionar DEMO-3"),
        ("functional", "need", None, "Nueva necesidad · DEMO"),
        ("functional", "epic", "DEMO-1", "HU nueva en la épica DEMO-1"),
        ("qa", "story", "DEMO-3", "Preparar pruebas de DEMO-3"),
    ],
    ids=["evolucionar", "necesidad", "epica", "qa"],
)
def test_conversation_title_composes_flow_and_key_for_each_flow(
    mode: str, kind: str, key: str | None, expected: str
) -> None:
    """T-52 · RF-47: el título de los 4 flujos es «flujo + clave» (o «flujo · proyecto»)."""
    assert conversation_title(mode, kind, key, "DEMO") == expected


@pytest.mark.parametrize(
    ("mode", "kind", "key", "expected"),
    [
        ("qa", "epic", "DEMO-1", "Conversación DEMO-1"),
        ("qa", "need", None, "Conversación · DEMO"),
        ("otro", "story", "DEMO-3", "Conversación DEMO-3"),
    ],
)
def test_conversation_title_falls_back_to_generic_flow_when_unknown(
    mode: str, kind: str, key: str | None, expected: str
) -> None:
    """T-52 (límite): una combinación de flujo desconocida usa «Conversación»."""
    assert conversation_title(mode, kind, key, "DEMO") == expected


def test_new_summary_starts_with_title_and_no_artifact() -> None:
    """T-52 · RF-47: el resumen nuevo está en `started`, sin artefacto ni versión."""
    summary = new_summary(
        thread_id="hilo-1",
        username=AF_USER,
        project="DEMO",
        mode="qa",
        origin_kind="story",
        origin_key="DEMO-3",
    )

    assert summary.title == "Preparar pruebas de DEMO-3"
    assert summary.status == "started"
    assert summary.artifact_id is None and summary.version is None
    assert summary.project_key == "DEMO"
    assert summary.created_at == summary.updated_at
    assert summary.created_at.tzinfo is not None


@pytest.mark.parametrize(
    ("field", "value"), [("mode", "admin"), ("origin_kind", "bug")], ids=["modo", "origen"]
)
def test_new_summary_rejects_unknown_mode_or_origin_kind(field: str, value: str) -> None:
    """T-52 (negativo): modo u origen fuera del contrato → ValidationError."""
    values: dict[str, Any] = {
        "thread_id": "hilo-1",
        "username": AF_USER,
        "project": "DEMO",
        "mode": "functional",
        "origin_kind": "story",
        "origin_key": "DEMO-3",
    }
    values[field] = value
    with pytest.raises(pydantic.ValidationError):
        new_summary(**values)


def test_conversation_summary_rejects_unknown_status() -> None:
    """T-52 (negativo): un estado fuera de la lista (p. ej. `draft`) no es válido."""
    with pytest.raises(pydantic.ValidationError):
        _summary("hilo-1", status="draft")  # type: ignore[arg-type]


# --- InMemoryConversationStore -------------------------------------------------------------


def test_in_memory_start_keeps_existing_row() -> None:
    """T-52: `start` sobre un hilo existente conserva la fila (al reanudar no se reinicia)."""
    store = InMemoryConversationStore()
    store.start(_summary("hilo-1"))
    store.update("hilo-1", status="in_review", artifact_id=str(uuid4()), version=2)
    before = store.get("hilo-1")

    store.start(_summary("hilo-1", updated_at=BASE_TIME + timedelta(days=1)))

    assert store.get("hilo-1") == before
    assert before is not None and before.status == "in_review" and before.version == 2


def test_in_memory_update_ignores_unknown_thread() -> None:
    """T-52 (límite): actualizar un hilo desconocido no crea filas ni falla."""
    store = InMemoryConversationStore()

    store.update("hilo-inexistente", status="published", version=1)

    assert store.get("hilo-inexistente") is None
    assert store.list_for(AF_USER) == []


def test_in_memory_update_keeps_artifact_and_version_when_not_given() -> None:
    """T-52: un `update` sin artefacto ni versión solo cambia estado y `updated_at`."""
    store = InMemoryConversationStore()
    artifact_id = str(uuid4())
    store.start(_summary("hilo-1"))
    store.update("hilo-1", status="in_review", artifact_id=artifact_id, version=3)

    store.update("hilo-1", status="discarded")

    row = store.get("hilo-1")
    assert row is not None
    assert (row.status, row.artifact_id, row.version) == ("discarded", artifact_id, 3)
    assert row.updated_at > BASE_TIME


def test_in_memory_list_for_orders_by_updated_desc_and_applies_limit() -> None:
    """T-52 · RF-47: la lista va de la más reciente a la más antigua y respeta `limit`."""
    store = InMemoryConversationStore()
    for offset in (2, 0, 3, 1):
        store.start(_summary(f"hilo-{offset}", updated_at=BASE_TIME + timedelta(hours=offset)))

    assert [r.thread_id for r in store.list_for(AF_USER)] == [
        "hilo-3",
        "hilo-2",
        "hilo-1",
        "hilo-0",
    ]
    assert [r.thread_id for r in store.list_for(AF_USER, limit=2)] == ["hilo-3", "hilo-2"]
    assert store.list_for(AF_USER, limit=0) == []


def test_in_memory_list_for_default_limit_is_50() -> None:
    """T-52 (límite): sin `limit`, la lista devuelve como mucho 50 conversaciones."""
    store = InMemoryConversationStore()
    for i in range(55):
        store.start(_summary(f"hilo-{i}", updated_at=BASE_TIME + timedelta(minutes=i)))

    rows = store.list_for(AF_USER)

    assert len(rows) == 50
    assert rows[0].thread_id == "hilo-54"


def test_in_memory_list_for_only_returns_own_conversations() -> None:
    """T-52 · RF-47: dos personas no se ven entre sí."""
    store = InMemoryConversationStore()
    store.start(_summary("hilo-af", user=AF_USER))
    store.start(_summary("hilo-qa", user=QA_USER))

    assert [r.thread_id for r in store.list_for(AF_USER)] == ["hilo-af"]
    assert [r.thread_id for r in store.list_for(QA_USER)] == ["hilo-qa"]
    assert store.list_for("persona-sin-hilos") == []


# --- resume_config: propiedad del hilo -----------------------------------------------------


def test_resume_config_returns_thread_config_for_owner() -> None:
    """T-52 · RF-20: la dueña retoma su conversación con su `thread_id`."""
    store = InMemoryConversationStore()
    store.start(_summary("hilo-1"))

    assert resume_config(store, AF_USER, "hilo-1") == {
        "configurable": {"thread_id": "hilo-1", "user": AF_USER}
    }


def test_resume_config_rejects_other_user_and_unknown_thread_with_same_message() -> None:
    """T-52 (negativo): hilo ajeno o inexistente → NotFoundError con el mismo mensaje."""
    store = InMemoryConversationStore()
    store.start(_summary("hilo-1", user=AF_USER))

    with pytest.raises(NotFoundError) as foreign:
        resume_config(store, QA_USER, "hilo-1")
    with pytest.raises(NotFoundError) as unknown:
        resume_config(store, QA_USER, "hilo-inexistente")

    assert str(foreign.value) == str(unknown.value) == "No existe esa conversación o no es tuya."
    assert foreign.value.service == unknown.value.service == "conversaciones"
    assert "hilo-1" not in str(foreign.value)


# --- Container y factories -----------------------------------------------------------------


def test_container_conversations_defaults_to_in_memory() -> None:
    """T-52: sin almacén inyectado, la lista vive en memoria."""
    assert isinstance(build_container(**_all_fakes()).conversations, InMemoryConversationStore)


def test_container_conversations_is_injectable_via_build_container() -> None:
    """T-52: `build_container(conversations=...)` usa el almacén inyectado."""
    store = InMemoryConversationStore()

    assert build_container(**_all_fakes(), conversations=store).conversations is store


def _app_config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    clean_env.setenv("POSTGRES_PASSWORD", FAKE_PASSWORD)
    return AppConfig(Settings(_env_file=None), load_models_config())


def test_build_conversations_returns_sql_store_without_connecting(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """T-52: `build_conversations` compone el almacén SQL (el engine conecta de forma perezosa)."""
    assert isinstance(factories.build_conversations(_app_config(clean_env)), SqlConversationStore)


def test_build_checkpointer_passes_libpq_conninfo_with_password(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """T-52: el checkpointer recibe una URL `postgresql://` (sin `+psycopg`) con la contraseña."""
    received: list[str] = []
    sentinel = object()

    def fake_checkpointer(conninfo: str) -> object:
        received.append(conninfo)
        return sentinel

    clean_env.setattr(factories, "postgres_checkpointer", fake_checkpointer)

    assert factories.build_checkpointer(_app_config(clean_env)) is sentinel
    (conninfo,) = received
    assert conninfo.startswith("postgresql://")
    assert "+psycopg" not in conninfo
    assert FAKE_PASSWORD in conninfo


# --- postgres_checkpointer sin red ---------------------------------------------------------


class _FakePool:
    instances: ClassVar[list["_FakePool"]] = []

    def __init__(self, conninfo: str, **kwargs: Any) -> None:
        self.conninfo = conninfo
        self.kwargs = kwargs
        self.closed = False
        _FakePool.instances.append(self)

    def close(self) -> None:
        self.closed = True


class _FakeSaver:
    fail = False

    def __init__(self, conn: Any, *, serde: Any) -> None:
        self.conn = conn
        self.serde = serde
        self.setup_calls = 0

    def setup(self) -> None:
        self.setup_calls += 1
        if _FakeSaver.fail:
            raise psycopg.OperationalError(f"fallo ficticio con {FAKE_PASSWORD}")


@pytest.fixture
def fake_pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _FakePool.instances = []
    _FakeSaver.fail = False
    monkeypatch.setattr(graph_builder, "ConnectionPool", _FakePool)
    monkeypatch.setattr(graph_builder, "PostgresSaver", _FakeSaver)
    yield


def test_postgres_checkpointer_configures_pool_and_strict_serializer(fake_pg: None) -> None:
    """T-52 · RF-20: pool con autocommit, sin sentencias preparadas, `dict_row` y `setup()`."""
    conninfo = f"postgresql://persona:{FAKE_PASSWORD}@localhost:5432/bd_ficticia"

    saver: Any = graph_builder.postgres_checkpointer(conninfo, max_size=3)

    (pool,) = _FakePool.instances
    assert pool.conninfo == conninfo
    assert pool.kwargs["max_size"] == 3
    assert pool.kwargs["min_size"] == 1  # max_size < 4 no choca con el mínimo del pool
    assert pool.kwargs["timeout"] == 10.0  # con la BD caída, aviso en segundos
    assert pool.kwargs["open"] is True
    assert pool.kwargs["kwargs"] == {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": psycopg.rows.dict_row,
    }
    assert saver.conn is pool and saver.setup_calls == 1
    assert pool.closed is False
    # El mismo serializador de tipos explícitos que el checkpointer en memoria.
    expected = graph_builder.checkpoint_serializer()
    assert type(saver.serde) is type(expected)
    assert saver.serde._allowed_msgpack_modules == expected._allowed_msgpack_modules


def test_postgres_checkpointer_wraps_setup_error_and_closes_pool(fake_pg: None) -> None:
    """T-52 (error): fallo de `setup()` → pool cerrado y ExternalServiceError sin encadenar."""
    _FakeSaver.fail = True
    conninfo = f"postgresql://persona:{FAKE_PASSWORD}@localhost:5432/bd_ficticia"

    with pytest.raises(ExternalServiceError) as exc_info:
        graph_builder.postgres_checkpointer(conninfo)

    (pool,) = _FakePool.instances
    assert pool.closed is True
    assert exc_info.value.service == "postgres"
    assert exc_info.value.__cause__ is None and exc_info.value.__suppress_context__
    assert FAKE_PASSWORD not in str(exc_info.value)
    assert "localhost" not in str(exc_info.value)


def test_postgres_checkpointer_accepts_max_size_below_pool_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-52 (límite): `max_size=1` es válido; un fallo de `setup()` → ExternalServiceError."""
    monkeypatch.setattr(_FakeSaver, "fail", True)
    monkeypatch.setattr(graph_builder, "PostgresSaver", _FakeSaver)
    conninfo = f"postgresql://persona:{FAKE_PASSWORD}@127.0.0.1:1/bd_ficticia?connect_timeout=1"

    with pytest.raises(ExternalServiceError):
        graph_builder.postgres_checkpointer(conninfo, max_size=1)


# --- SqlConversationStore sin red ----------------------------------------------------------


class BrokenEngine:
    """Engine que falla al abrir la transacción, como una BD caída (sin red)."""

    def begin(self) -> Any:
        raise sa.exc.OperationalError(
            "SELECT 1", {}, Exception(f"conexión rechazada ficticia {FAKE_PASSWORD}")
        )


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda s: s.start(_summary("hilo-1")), "No se pudo guardar la conversación."),
        (
            lambda s: s.update("hilo-1", status="in_review", version=1),
            "No se pudo actualizar la conversación.",
        ),
        (lambda s: s.get("hilo-1"), "No se pudieron leer las conversaciones."),
        (lambda s: s.list_for(AF_USER), "No se pudieron leer las conversaciones."),
    ],
    ids=["start", "update", "get", "list_for"],
)
def test_sql_store_wraps_database_errors_without_chaining(call: Any, message: str) -> None:
    """T-52 (error): BD caída → ExternalServiceError en español, sin encadenar ni filtrar."""
    store = SqlConversationStore(BrokenEngine())  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError) as exc_info:
        call(store)

    assert str(exc_info.value) == message
    assert exc_info.value.service == "postgres"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert FAKE_PASSWORD not in str(exc_info.value)


class _RecordingConnection:
    def __init__(self, statements: list[Any]) -> None:
        self._statements = statements

    def execute(self, statement: Any) -> Any:
        self._statements.append(statement)
        return self

    def mappings(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return []


class RecordingEngine:
    """Engine sin red que guarda las sentencias para compilarlas con el dialecto PostgreSQL."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    def begin(self) -> Any:
        return nullcontext(_RecordingConnection(self.statements))


def _sql(statement: Any) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def test_sql_store_start_is_insert_on_conflict_do_nothing() -> None:
    """T-52: `start` es INSERT … ON CONFLICT (thread_id) DO NOTHING (conserva la fila)."""
    engine = RecordingEngine()
    SqlConversationStore(engine).start(_summary("hilo-1"))  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = _sql(statement)
    assert sql.startswith("INSERT INTO conversations")
    assert sql.endswith("ON CONFLICT (thread_id) DO NOTHING")


def test_sql_store_update_filters_by_thread_and_omits_missing_fields() -> None:
    """T-52: `update` filtra por hilo y no toca artefacto ni versión si no llegan."""
    engine = RecordingEngine()
    SqlConversationStore(engine).update("hilo-1", status="discarded")  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = _sql(statement)
    assert sql.startswith("UPDATE conversations SET status=")
    assert "updated_at=" in sql
    assert "artifact_id" not in sql and "version" not in sql
    assert "WHERE conversations.thread_id = %(thread_id_1)s" in sql


def test_sql_store_list_for_filters_user_orders_desc_and_limits() -> None:
    """T-52 · RF-47: `list_for` filtra por persona, ordena por `updated_at` DESC y limita."""
    engine = RecordingEngine()
    assert SqlConversationStore(engine).list_for(AF_USER, limit=7) == []  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = _sql(statement)
    assert "WHERE conversations.username = %(username_1)s" in sql
    assert "ORDER BY conversations.updated_at DESC" in sql
    assert "LIMIT %(param_1)s" in sql
    assert statement.compile().params["param_1"] == 7


def test_sql_store_get_returns_none_when_no_row() -> None:
    """T-52 (límite): `get` sin fila → None."""
    assert SqlConversationStore(RecordingEngine()).get("hilo-x") is None  # type: ignore[arg-type]


# --- load_origin ---------------------------------------------------------------------------


@pytest.mark.parametrize("config", [None, {}, {"configurable": {}}, _config("")])
def test_load_origin_without_thread_id_does_not_create_row(
    tmp_path: Path, config: dict[str, Any] | None
) -> None:
    """T-52 (límite): sin `thread_id` en la config, `load_origin` no crea fila y no falla."""
    container, store = _container(tmp_path)
    state = initial_state(AF_USER, "functional", STORY_ORIGIN)

    result = GraphNodes(container).load_origin(state, config)  # type: ignore[arg-type]

    assert [issue.key for issue in result["jira_context"]] == ["DEMO-3"]
    assert store.rows == {}


@pytest.mark.parametrize(
    ("mode", "origin", "user", "title", "project", "key"),
    [
        ("functional", STORY_ORIGIN, AF_USER, "Evolucionar DEMO-3", "DEMO", "DEMO-3"),
        ("functional", EPIC_ORIGIN, AF_USER, "HU nueva en la épica DEMO-1", "DEMO", "DEMO-1"),
        ("functional", NEED_ORIGIN, AF_USER, "Nueva necesidad · DEMO", "DEMO", None),
        ("qa", STORY_ORIGIN, QA_USER, "Preparar pruebas de DEMO-3", "DEMO", "DEMO-3"),
    ],
    ids=["evolucionar", "epica", "necesidad", "qa"],
)
def test_load_origin_creates_row_with_title_and_without_free_text(
    tmp_path: Path,
    mode: str,
    origin: Origin,
    user: str,
    title: str,
    project: str,
    key: str | None,
) -> None:
    """T-52 · RF-47: la fila tiene dueño, proyecto, flujo y título; nunca el texto libre."""
    container, store = _container(tmp_path)
    thread_id = _thread()

    GraphNodes(container).load_origin(
        initial_state(user, mode, origin),  # type: ignore[arg-type]
        _config(thread_id),  # type: ignore[arg-type]
    )

    row = store.get(thread_id)
    assert row is not None
    assert (row.username, row.project_key, row.mode, row.origin_kind, row.origin_key) == (
        user,
        project,
        mode,
        origin["kind"],
        key,
    )
    assert (row.title, row.status, row.artifact_id, row.version) == (title, "started", None, None)
    dumped = row.model_dump_json()
    assert NEED_TEXT not in dumped
    assert "vencimiento" not in dumped


# --- estados a lo largo del grafo ----------------------------------------------------------


def test_generate_moves_row_to_in_review_with_artifact_and_version(tmp_path: Path) -> None:
    """T-52 · RF-47: tras la primera generación la fila está `in_review` con artefacto y v1."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()

    payload = _payload(_start(graph, thread_id))

    row = store.get(thread_id)
    assert row is not None
    assert (row.status, row.version) == ("in_review", 1)
    assert row.artifact_id == payload["artifact"]["id"]
    assert store.statuses(thread_id) == ["in_review"]


def test_iterate_regenerates_and_keeps_in_review_with_new_version(tmp_path: Path) -> None:
    """T-52 · RF-20: `iterate` no cambia el estado; `generate` lo deja `in_review` con v2."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()
    first = _payload(_start(graph, thread_id))

    second = _payload(_resume(graph, thread_id, {"decision": "iterate", "feedback": FEEDBACK}))

    row = store.get(thread_id)
    assert row is not None
    assert (row.status, row.version) == ("in_review", 2)
    assert row.artifact_id == first["artifact"]["id"] == second["artifact"]["id"]
    # Solo `generate` actualiza: no hay una actualización propia de `iterate`.
    assert store.statuses(thread_id) == ["in_review", "in_review"]
    assert FEEDBACK not in row.model_dump_json()


def test_edit_moves_row_to_in_review_with_edited_version(tmp_path: Path) -> None:
    """T-52 · RF-32: `edit` deja la fila `in_review` con la versión editada (v2)."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()
    first = _payload(_start(graph, thread_id))
    edited = copy.deepcopy(first["artifact"]["content"]) | {"title": EDITED_TITLE}

    second = _payload(
        _resume(
            graph,
            thread_id,
            {"decision": "edit", "content": edited, "fingerprint": first["fingerprint"]},
        )
    )

    assert second["version"] == 2
    row = store.get(thread_id)
    assert row is not None
    assert (row.status, row.version) == ("in_review", 2)
    assert row.artifact_id == first["artifact"]["id"]
    assert EDITED_TITLE not in row.model_dump_json()


def test_discard_moves_row_to_discarded(tmp_path: Path) -> None:
    """T-52 · RF-47: descartar deja la fila `discarded` con la versión revisada."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()
    _start(graph, thread_id)

    _resume(graph, thread_id, {"decision": "discard"})

    row = store.get(thread_id)
    assert row is not None
    assert (row.status, row.version) == ("discarded", 1)
    assert store.statuses(thread_id) == ["in_review", "discarded"]


def test_approve_and_live_publish_moves_row_to_published(tmp_path: Path) -> None:
    """T-52 · RF-47: en live, aprobar pasa por `approved` y la publicación deja `published`."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()
    _start(graph, thread_id)

    final = _approve(graph, thread_id)

    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    row = store.get(thread_id)
    assert row is not None
    assert (row.status, row.version) == ("published", 1)
    assert row.artifact_id == str(final["artifact"].id)
    assert store.statuses(thread_id) == ["in_review", "approved", "published"]


def test_approve_and_simulated_publish_moves_row_to_simulated(tmp_path: Path) -> None:
    """T-52 · T-25: en simulación, aprobar → `approved` y la publicación simulada → `simulated`."""
    container, store = _container(tmp_path, publish_mode="simulation")
    graph = build_graph(container)
    thread_id = _thread()
    _start(graph, thread_id)

    _approve(graph, thread_id)

    row = store.get(thread_id)
    assert row is not None
    assert (row.status, row.version) == ("simulated", 1)
    assert store.statuses(thread_id) == ["in_review", "approved", "simulated"]
    assert container.issue_tracker.writes == []  # type: ignore[attr-defined]


def test_qa_live_publish_moves_row_to_published(tmp_path: Path) -> None:
    """T-52 · RF-47 (QA): publicar la suite completa deja la fila `published`."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()
    _start(graph, thread_id, mode="qa", user=QA_USER)

    _approve(graph, thread_id)

    row = store.get(thread_id)
    assert row is not None
    assert (row.title, row.status) == ("Preparar pruebas de DEMO-3", "published")


def test_qa_partial_publish_keeps_row_approved(tmp_path: Path) -> None:
    """T-52 · RNF-13 (QA): si falla un caso, la fila no pasa a `published` (queda `approved`)."""
    container, store = _container(
        tmp_path, test_management=FakeTestManagement(fail_case_ids={"CP-02"})
    )
    graph = build_graph(container)
    thread_id = _thread()
    _start(graph, thread_id, mode="qa", user=QA_USER)

    final = _approve(graph, thread_id)

    assert final["errors"] == ["No se pudo publicar CP-02."]
    row = store.get(thread_id)
    assert row is not None
    assert row.status == "approved"
    assert store.statuses(thread_id) == ["in_review", "approved"]


@pytest.mark.parametrize(
    "answer",
    [
        {"decision": "publicar"},
        "approve",
        {"decision": "approve", "fingerprint": "huella-ficticia"},
        {"decision": "edit", "content": {}, "fingerprint": "huella-ficticia"},
    ],
    ids=["decision_desconocida", "no_es_dict", "huella_ajena", "edicion_sin_huella_valida"],
)
def test_rejected_answers_do_not_touch_the_row(tmp_path: Path, answer: object) -> None:
    """T-52 · T-51 (negativo): una respuesta rechazada no cambia la fila (ni `updated_at`)."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()
    _start(graph, thread_id)
    before = store.get(thread_id)

    rejected = _payload(_resume(graph, thread_id, answer))

    assert rejected["error"]
    assert store.get(thread_id) == before
    assert store.statuses(thread_id) == ["in_review"]


def test_two_users_do_not_see_each_others_conversations_through_the_graph(
    tmp_path: Path,
) -> None:
    """T-52 · RF-47: cada persona solo lista y retoma sus conversaciones."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    af_thread, qa_thread = _thread(), _thread()
    _start(graph, af_thread, user=AF_USER)
    _start(graph, qa_thread, mode="qa", user=QA_USER)

    assert [r.thread_id for r in store.list_for(AF_USER)] == [af_thread]
    assert [r.thread_id for r in store.list_for(QA_USER)] == [qa_thread]
    with pytest.raises(NotFoundError):
        resume_config(store, QA_USER, af_thread)
    expected = {"configurable": {"thread_id": af_thread, "user": AF_USER}}
    assert resume_config(store, AF_USER, af_thread) == expected


def test_resume_config_resumes_the_paused_review_in_the_same_graph(tmp_path: Path) -> None:
    """T-52 · RF-20: con `resume_config` se retoma la pausa pendiente y se aprueba."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    thread_id = _thread()
    first = _payload(_start(graph, thread_id))

    config = resume_config(store, AF_USER, thread_id)
    final = graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": first["fingerprint"]}), config
    )

    assert isinstance(final["artifact"], Artifact)
    assert final["artifact"].status is ArtifactStatus.PUBLISHED


# --- Integración: migración 0004, SqlConversationStore y PostgresSaver ---------------------


def _tables(engine: Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


@pytest.mark.integration
def test_migration_0004_creates_and_drops_conversations() -> None:
    """T-52: 0004 crea `conversations` (CHECK e índice) sobre 0003 y su downgrade la borra."""
    with temporary_database("conversations_migration_test", revision="0003_user_last_project") as (
        url,
        engine,
    ):
        config = alembic_config(url)
        assert "conversations" not in _tables(engine)

        command.upgrade(config, "0004_conversations")
        inspector = sa.inspect(engine)
        columns = {c["name"]: c for c in inspector.get_columns("conversations")}
        assert set(columns) == {
            "thread_id",
            "username",
            "project_key",
            "mode",
            "origin_kind",
            "origin_key",
            "title",
            "status",
            "artifact_id",
            "version",
            "created_at",
            "updated_at",
        }
        for required in ("username", "project_key", "mode", "title", "status", "updated_at"):
            assert columns[required]["nullable"] is False
        assert columns["origin_key"]["nullable"] is True
        assert inspector.get_pk_constraint("conversations")["constrained_columns"] == ["thread_id"]
        checks = {c["name"] for c in inspector.get_check_constraints("conversations")}
        assert {"ck_conversations_mode", "ck_conversations_status"} <= checks
        indexes = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("conversations")}
        assert indexes["ix_conversations_username_updated"] == ["username", "updated_at"]

        command.downgrade(config, "0003_user_last_project")
        assert "conversations" not in _tables(engine)
        assert "user_last_project" in _tables(engine)


@pytest.fixture(scope="module")
def pg_db() -> Iterator[tuple[sa.URL, Engine]]:
    with temporary_database("conversations_test") as (url, engine):
        yield url, engine


@pytest.fixture
def engine(pg_db: tuple[sa.URL, Engine]) -> Engine:
    _url, pg_engine = pg_db
    with pg_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE conversations"))
    return pg_engine


@pytest.mark.integration
@pytest.mark.parametrize(
    ("column", "value"), [("mode", "admin"), ("status", "draft")], ids=["modo", "estado"]
)
def test_conversations_check_constraints_reject_unknown_values(
    engine: Engine, column: str, value: str
) -> None:
    """T-52 (negativo): los CHECK de `mode` y `status` rechazan valores fuera de la lista."""
    row = {
        "thread_id": "hilo-check",
        "username": AF_USER,
        "project_key": "DEMO",
        "mode": "functional",
        "origin_kind": "story",
        "title": "Evolucionar DEMO-3",
        "status": "started",
    }
    row[column] = value
    insert = sa.text(
        "INSERT INTO conversations (thread_id, username, project_key, mode, origin_kind, title,"
        " status) VALUES (:thread_id, :username, :project_key, :mode, :origin_kind, :title,"
        " :status)"
    )
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(insert, row)


@pytest.mark.integration
def test_sql_store_round_trip_update_and_unknown_thread(engine: Engine) -> None:
    """T-52 · RF-47: guardar, leer, actualizar con artefacto e ignorar un hilo desconocido."""
    store = SqlConversationStore(engine)
    summary = new_summary(
        thread_id="hilo-sql-1",
        username=AF_USER,
        project="DEMO",
        mode="functional",
        origin_kind="need",
        origin_key=None,
    )
    store.start(summary)

    saved = store.get("hilo-sql-1")
    assert saved is not None
    assert saved.title == "Nueva necesidad · DEMO" and saved.status == "started"
    assert saved.artifact_id is None and saved.origin_key is None

    artifact_id = str(uuid4())
    store.update("hilo-sql-1", status="in_review", artifact_id=artifact_id, version=2)
    store.update("hilo-sql-1", status="approved")
    store.update("hilo-inexistente", status="published", version=9)

    row = store.get("hilo-sql-1")
    assert row is not None
    assert (row.status, row.artifact_id, row.version) == ("approved", artifact_id, 2)
    assert row.updated_at >= saved.updated_at
    assert store.get("hilo-inexistente") is None


@pytest.mark.integration
def test_sql_store_start_keeps_existing_row(engine: Engine) -> None:
    """T-52: un segundo `start` del mismo hilo no duplica ni reinicia la fila."""
    store = SqlConversationStore(engine)
    store.start(_summary("hilo-sql-2"))
    store.update("hilo-sql-2", status="in_review", artifact_id=str(uuid4()), version=1)

    store.start(_summary("hilo-sql-2", user=QA_USER))

    row = store.get("hilo-sql-2")
    assert row is not None
    assert (row.username, row.status, row.version) == (AF_USER, "in_review", 1)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM conversations")).scalar_one() == 1


@pytest.mark.integration
def test_sql_store_list_for_filters_orders_and_limits(engine: Engine) -> None:
    """T-52 · RF-47: lista propia, de la más reciente a la más antigua, con `limit`."""
    store = SqlConversationStore(engine)
    for offset in (1, 3, 0, 2):
        store.start(_summary(f"hilo-{offset}", updated_at=BASE_TIME + timedelta(hours=offset)))
    store.start(_summary("hilo-ajeno", user=QA_USER, updated_at=BASE_TIME + timedelta(days=1)))

    assert [r.thread_id for r in store.list_for(AF_USER)] == [
        "hilo-3",
        "hilo-2",
        "hilo-1",
        "hilo-0",
    ]
    assert [r.thread_id for r in store.list_for(AF_USER, limit=2)] == ["hilo-3", "hilo-2"]
    assert [r.thread_id for r in store.list_for(QA_USER)] == ["hilo-ajeno"]
    with pytest.raises(NotFoundError):
        resume_config(store, QA_USER, "hilo-3")


@pytest.fixture
def serde_events() -> Iterator[list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    unregister = register_serde_event_listener(events.append)
    yield events
    unregister()


def _conninfo(url: sa.URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_postgres_checkpointer_survives_restart_and_publishes_after_approval(
    pg_db: tuple[sa.URL, Engine],
    engine: Engine,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    serde_events: list[dict[str, Any]],
    mode: str,
) -> None:
    """T-52 · RF-20: la pausa sobrevive a otro checkpointer; se aprueba y queda `published`.

    Con `warnings.simplefilter("error")`, ninguna deserialización emite avisos.
    """
    url, _ = pg_db
    user = AF_USER if mode == "functional" else QA_USER
    conversations = SqlConversationStore(engine)
    container = fake_container(tmp_path, conversations=conversations)
    thread_id = _thread()
    caplog.set_level(logging.WARNING)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        saver = graph_builder.postgres_checkpointer(_conninfo(url))
        try:
            first = _payload(_start(build_graph(container, saver), thread_id, mode, user=user))
        finally:
            saver.conn.close()  # «reinicio» del proceso
        paused = conversations.get(thread_id)
        assert paused is not None and (paused.status, paused.version) == ("in_review", 1)

        saver2 = graph_builder.postgres_checkpointer(_conninfo(url))  # setup() idempotente
        try:
            graph2 = build_graph(container, saver2)
            config = resume_config(conversations, user, thread_id)
            pending = [t for t in graph2.get_state(config).tasks if t.interrupts]
            assert len(pending) == 1
            restored = pending[0].interrupts[-1].value
            assert restored["fingerprint"] == first["fingerprint"]
            assert restored["version"] == first["version"] == 1

            final = graph2.invoke(
                Command(resume={"decision": "approve", "fingerprint": restored["fingerprint"]}),
                config,
            )
        finally:
            saver2.conn.close()

    assert isinstance(final["artifact"], Artifact)
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    (row,) = conversations.list_for(user)
    assert (row.thread_id, row.status, row.version) == (thread_id, "published", 1)
    assert serde_events == []
    assert [r for r in caplog.records if "deserializ" in r.getMessage().lower()] == []


@pytest.mark.integration
def test_postgres_checkpointer_invalid_conninfo_raises_without_leaking(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T-52 (error): puerto cerrado → ExternalServiceError sin la cadena ni la contraseña.

    Tarda el `timeout` del pool (10 s): ver la observación del informe.
    """
    caplog.set_level(logging.WARNING)
    conninfo = (
        f"postgresql://persona-ficticia:{FAKE_PASSWORD}@127.0.0.1:1/bd_ficticia?connect_timeout=1"
    )

    with pytest.raises(ExternalServiceError) as exc_info:
        graph_builder.postgres_checkpointer(conninfo)

    message = str(exc_info.value)
    assert message == "No se pudo preparar el almacén de conversaciones en PostgreSQL."
    assert exc_info.value.service == "postgres"
    assert exc_info.value.__cause__ is None and exc_info.value.__suppress_context__
    assert FAKE_PASSWORD not in message and conninfo not in message
    assert all(FAKE_PASSWORD not in r.getMessage() for r in caplog.records)


# --- controles de propiedad (revisión de seguridad de T-52) ---------------------------------


def test_new_conversation_config_generates_server_side_thread_id_with_actor() -> None:
    first = new_conversation_config(AF_USER)
    second = new_conversation_config(AF_USER)
    assert first["configurable"]["user"] == AF_USER  # type: ignore[index]
    assert first["configurable"]["thread_id"] != second["configurable"]["thread_id"]  # type: ignore[index]
    UUID(first["configurable"]["thread_id"])  # type: ignore[index]


@pytest.mark.parametrize("thread_id", ["", "../hilo", "hilo con espacios", "h" * 65])
def test_resume_config_rejects_malformed_thread_ids_with_same_message(thread_id: str) -> None:
    store = InMemoryConversationStore()
    with pytest.raises(NotFoundError, match="no es tuya"):
        resume_config(store, AF_USER, thread_id)


def test_load_origin_refuses_thread_of_another_user(tmp_path: Path) -> None:
    """Un `thread_id` ajeno no se reutiliza: misma respuesta que `resume_config`."""
    container, store = _container(tmp_path)
    graph = build_graph(container)
    _start(graph, "hilo-ajeno", user=AF_USER)

    with pytest.raises(NotFoundError, match="no es tuya"):
        graph.invoke(
            initial_state(QA_USER, "qa", STORY_ORIGIN),  # type: ignore[arg-type]
            _config("hilo-ajeno"),
        )
    assert store.get("hilo-ajeno").username == AF_USER  # type: ignore[union-attr]


def test_actor_other_than_owner_cannot_review_or_approve(tmp_path: Path) -> None:
    """Quien actúa (`configurable.user`) tiene que ser la dueña: no aprueba en nombre de otra."""
    container, _store = _container(tmp_path)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-actor", "user": AF_USER}}
    first = graph.invoke(initial_state(AF_USER, "functional", STORY_ORIGIN), config)
    fingerprint = first["__interrupt__"][0].value["fingerprint"]

    intruder = {"configurable": {"thread_id": "hilo-actor", "user": "otra-persona-ficticia"}}
    with pytest.raises(NotFoundError, match="no es tuya"):
        graph.invoke(Command(resume={"decision": "approve", "fingerprint": fingerprint}), intruder)
    artifact = Artifact.model_validate(first["__interrupt__"][0].value["artifact"])
    assert not container.approvals._approvals  # nada aprobado
    assert artifact.status is ArtifactStatus.IN_REVIEW


def test_update_with_username_only_touches_own_row() -> None:
    store = InMemoryConversationStore()
    store.start(_summary("hilo-1"))
    store.update("hilo-1", status="approved", username="otra-persona-ficticia")
    assert store.get("hilo-1").status == "started"  # type: ignore[union-attr]
    store.update("hilo-1", status="approved", username=AF_USER)
    assert store.get("hilo-1").status == "approved"  # type: ignore[union-attr]


def test_sql_update_with_username_filters_by_owner() -> None:
    engine = RecordingEngine()
    SqlConversationStore(engine).update(  # type: ignore[arg-type]
        "hilo-1", status="approved", username=AF_USER
    )
    (statement,) = engine.statements
    sql = _sql(statement)
    assert "conversations.thread_id = " in sql and "conversations.username = " in sql


class _FailingUpdates(InMemoryConversationStore):
    def update(self, *args: Any, **kwargs: Any) -> None:
        raise ExternalServiceError("No se pudo actualizar la conversación.", service="postgres")


def test_failing_conversation_index_does_not_break_the_flow(tmp_path: Path) -> None:
    """La lista es secundaria: si su BD falla, se aprueba y se publica igual (sin repetir)."""
    container = fake_container(tmp_path, conversations=_FailingUpdates())
    graph = build_graph(container)
    config = _config("hilo-indice-caido")
    first = graph.invoke(initial_state(AF_USER, "functional", STORY_ORIGIN), config)
    fingerprint = first["__interrupt__"][0].value["fingerprint"]

    final = graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": fingerprint}), config
    )
    assert final["artifact"].status is ArtifactStatus.PUBLISHED


def test_app_requires_actor_in_config(tmp_path: Path) -> None:
    """Con `require_actor` (la app), una config sin `user` falla cerrada antes de nada."""
    container = fake_container(tmp_path, require_actor=True)
    graph = build_graph(container)
    with pytest.raises(NotFoundError, match="no es tuya"):
        graph.invoke(initial_state(AF_USER, "functional", STORY_ORIGIN), _config(_thread()))
    assert container.conversations.list_for(AF_USER) == []

    ok = graph.invoke(
        initial_state(AF_USER, "functional", STORY_ORIGIN), new_conversation_config(AF_USER)
    )
    assert "__interrupt__" in ok


def test_load_origin_rejects_malformed_thread_id(tmp_path: Path) -> None:
    graph = build_graph(fake_container(tmp_path))
    with pytest.raises(NotFoundError, match="no es tuya"):
        graph.invoke(initial_state(AF_USER, "functional", STORY_ORIGIN), _config("h" * 65))
