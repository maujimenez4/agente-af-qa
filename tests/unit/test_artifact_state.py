"""Pruebas del estado persistente por artefacto (T-25 · PA-06, PA-37, RF-33).

Cubren `core/artifact_state.py`, la persistencia del `ApprovalLedger` (aprobaciones que
sobreviven a un reinicio) y la versión de partida de Jira guardada bajo "baseline". Las
unitarias usan fakes y `InMemoryArtifactStateStore`; ningún LLM real. Las de integración usan
BD temporales propias y se saltan si PostgreSQL no está disponible.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy.engine import Engine

from adapters.errors import ExternalServiceError
from core.approvals import ApprovalError, ApprovalLedger, PublishTarget
from core.artifact_state import InMemoryArtifactStateStore, SqlArtifactStateStore
from core.container import Container
from core.graph import Origin, build_graph, initial_state, memory_checkpointer
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.pg_temp import alembic_config, temporary_database, truncate_t25_tables

AF_USER = "af-demo"
THREAD = "hilo-ficticio-1"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
EPIC_ORIGIN: Origin = {"kind": "epic", "key": "DEMO-1"}
FEEDBACK = "Ajusta el título (texto ficticio)."
STRUCTURE_MARK = "Pasas a la plantilla"  # prompts/structure_story.md


# --- utilidades --------------------------------------------------------------------------


def _target(origin_key: str = "DEMO-3", thread_id: str = THREAD) -> PublishTarget:
    return PublishTarget(
        mode="functional",
        origin_kind="story",
        origin_key=origin_key,
        user=AF_USER,
        thread_id=thread_id,
    )


def _artifact(version: int = 1, title: str | None = None, artifact_id: Any = None) -> Artifact:
    story = dataset.renewal_story()
    if title:
        story = story.model_copy(update={"title": title})
    return Artifact(
        id=artifact_id or uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.IN_REVIEW,
        version=version,
        origin_key="DEMO-3",
        content=story,
        created_by=AF_USER,
    )


def _config(thread_id: str | None = None) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id or f"hilo-{uuid4()}"}}


def _start(
    graph: CompiledStateGraph, config: dict[str, Any], origin: Origin = STORY_ORIGIN
) -> dict[str, Any]:
    return graph.invoke(initial_state(AF_USER, "functional", origin), config)


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return Command(
        resume={"decision": "approve", "fingerprint": task.interrupts[0].value["fingerprint"]}
    )


def _structure_calls(llm: FakeLLMProvider) -> int:
    return sum(
        1
        for call in llm.calls
        if call["messages"] and STRUCTURE_MARK in call["messages"][0].content
    )


def _artifact_id(graph: CompiledStateGraph, config: dict[str, Any]) -> str:
    return str(graph.get_state(config).values["artifact"].id)


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


class BrokenEngine:
    """Engine que falla al abrir la transacción, como una BD caída (sin red)."""

    def begin(self) -> Any:
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("conexión rechazada (ficticia)"))


# --- InMemoryArtifactStateStore -------------------------------------------------------------


def test_in_memory_store_returns_none_when_artifact_unknown() -> None:
    """PA-06: un artefacto sin estado → None."""
    assert InMemoryArtifactStateStore().load(str(uuid4())) is None


def test_in_memory_store_saves_and_loads_state() -> None:
    """PA-06: lo guardado se recupera por artefacto."""
    store = InMemoryArtifactStateStore()
    first, second = str(uuid4()), str(uuid4())
    store.save(first, {"baseline": {"title": "HU ficticia"}})
    store.save(second, {"ledger": {"offer": None}})

    assert store.load(first) == {"baseline": {"title": "HU ficticia"}}
    assert store.load(second) == {"ledger": {"offer": None}}


def test_in_memory_store_returns_copy_when_caller_mutates_it() -> None:
    """PA-06 (límite): modificar lo leído no cambia el almacén sin `save`."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    store.save(artifact_id, {"baseline": {"title": "HU ficticia"}})

    loaded = store.load(artifact_id)
    assert loaded is not None
    loaded.pop("baseline")

    assert store.load(artifact_id) == {"baseline": {"title": "HU ficticia"}}


def test_sql_store_wraps_database_errors_when_unreachable() -> None:
    """PA-06 (error): BD caída → ExternalServiceError en español al leer y al guardar."""
    store = SqlArtifactStateStore(BrokenEngine())  # type: ignore[arg-type]
    with pytest.raises(ExternalServiceError, match="leer el estado"):
        store.load(str(uuid4()))
    with pytest.raises(ExternalServiceError, match="guardar el estado"):
        store.save(str(uuid4()), {"ledger": None})


# --- ApprovalLedger persistente (simula reinicio) --------------------------------------------


def test_approval_survives_restart_when_ledger_shares_store() -> None:
    """PA-06 · RF-33: offer→record en un ledger; `find` es válido en otro con el mismo store."""
    store = InMemoryArtifactStateStore()
    artifact, target = _artifact(), _target()
    before = ApprovalLedger(store=store)
    before.offer(artifact, target)
    recorded = before.record(artifact, target)

    after = ApprovalLedger(store=store)  # «reinicio»: instancia nueva, mismo almacén
    found = after.find(artifact, target)

    assert found is not None
    assert found == recorded
    assert found.consumed is False


def test_approval_not_found_after_restart_when_other_target_or_content() -> None:
    """PA-06 (negativo): tras recargar, otra operación u otro contenido no tienen aprobación."""
    store = InMemoryArtifactStateStore()
    artifact, target = _artifact(), _target()
    ledger = ApprovalLedger(store=store)
    ledger.offer(artifact, target)
    ledger.record(artifact, target)

    reloaded = ApprovalLedger(store=store)

    assert reloaded.find(artifact, _target(thread_id="hilo-ficticio-2")) is None
    tampered = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"title": "Otro título"})}
    )
    assert reloaded.find(tampered, target) is None


def test_pending_offer_survives_restart() -> None:
    """PA-06: la versión ofrecida sigue ofrecida tras recargar y puede aprobarse allí."""
    store = InMemoryArtifactStateStore()
    artifact, target = _artifact(), _target()
    ApprovalLedger(store=store).offer(artifact, target)

    reloaded = ApprovalLedger(store=store)

    assert reloaded.is_offered(artifact, target)
    reloaded.record(artifact, target)
    assert ApprovalLedger(store=store).find(artifact, target) is not None
    ledger_state = store.load(str(artifact.id))["ledger"]  # type: ignore[index]
    assert ledger_state["offer"] is None  # la oferta se consume al aprobar


def test_record_fails_after_restart_when_nothing_was_offered() -> None:
    """PA-06 (negativo): un ledger recargado no aprueba lo que nunca se ofreció."""
    store = InMemoryArtifactStateStore()
    with pytest.raises(ApprovalError):
        ApprovalLedger(store=store).record(_artifact(), _target())


def test_consume_persists_and_was_published_after_restart() -> None:
    """PA-06 · RF-33: consumir persiste; tras recargar, was_published y sin aprobación vigente."""
    store = InMemoryArtifactStateStore()
    artifact, target = _artifact(), _target()
    ledger = ApprovalLedger(store=store)
    ledger.offer(artifact, target)
    approval = ledger.record(artifact, target)
    published = artifact.model_copy(update={"status": ArtifactStatus.PUBLISHED})
    ledger.consume(approval, published)

    reloaded = ApprovalLedger(store=store)

    assert reloaded.was_published(published)
    assert reloaded.find(artifact, target) is None
    (saved,) = store.load(str(artifact.id))["ledger"]["approvals"]  # type: ignore[index]
    assert saved["consumed"] is True
    assert saved["published_fingerprint"]


def test_consumed_version_cannot_be_approved_again_after_restart() -> None:
    """PA-06 (negativo): tras recargar, una versión ya publicada no se vuelve a aprobar."""
    store = InMemoryArtifactStateStore()
    artifact, target = _artifact(), _target()
    ledger = ApprovalLedger(store=store)
    ledger.offer(artifact, target)
    ledger.consume(ledger.record(artifact, target), artifact)

    reloaded = ApprovalLedger(store=store)
    reloaded.offer(artifact, target)
    with pytest.raises(ApprovalError, match="ya se publicó"):
        reloaded.record(artifact, target)


def test_fixed_target_is_kept_after_restart() -> None:
    """PA-06: la operación fijada en la primera oferta no cambia tras recargar."""
    store = InMemoryArtifactStateStore()
    artifact_id = uuid4()
    ApprovalLedger(store=store).offer(_artifact(1, artifact_id=artifact_id), _target())

    reloaded = ApprovalLedger(store=store)
    v2 = _artifact(2, title="Renovar un préstamo (v2 ficticia)", artifact_id=artifact_id)
    with pytest.raises(ApprovalError, match="destino"):
        reloaded.offer(v2, _target(thread_id="hilo-ficticio-2"))

    again = ApprovalLedger(store=store)
    again.offer(v2, _target())  # misma operación: se admite
    assert again.is_offered(v2, _target())
    assert store.load(str(artifact_id))["ledger"]["target"]["thread_id"] == THREAD  # type: ignore[index]


def test_new_offer_drops_pending_approval_of_previous_version_after_restart() -> None:
    """PA-06 (límite): ofrecer v2 invalida la aprobación pendiente de v1, también al recargar."""
    store = InMemoryArtifactStateStore()
    artifact_id = uuid4()
    v1 = _artifact(1, artifact_id=artifact_id)
    ledger = ApprovalLedger(store=store)
    ledger.offer(v1, _target())
    ledger.record(v1, _target())
    ledger.offer(_artifact(2, title="Versión 2 ficticia", artifact_id=artifact_id), _target())

    assert ApprovalLedger(store=store).find(v1, _target()) is None
    assert store.load(str(artifact_id))["ledger"]["approvals"] == []  # type: ignore[index]


def test_ledger_key_is_saved_without_removing_other_keys() -> None:
    """PA-06 · PA-37: el ledger se guarda bajo "ledger" y conserva "baseline"."""
    store = InMemoryArtifactStateStore()
    artifact, target = _artifact(), _target()
    store.save(str(artifact.id), {"baseline": {"title": "Partida ficticia"}})

    ledger = ApprovalLedger(store=store)
    ledger.offer(artifact, target)
    ledger.record(artifact, target)

    state = store.load(str(artifact.id))
    assert state is not None
    assert set(state) == {"baseline", "ledger"}
    assert state["baseline"] == {"title": "Partida ficticia"}
    assert state["ledger"]["target"] == {
        "mode": "functional",
        "origin_kind": "story",
        "origin_key": "DEMO-3",
        "user": AF_USER,
        "thread_id": THREAD,
    }


def test_ledger_without_store_works_in_memory_only() -> None:
    """PA-06 (límite): sin store, el ledger funciona en memoria y no persiste nada."""
    artifact, target = _artifact(), _target()
    ledger = ApprovalLedger()
    ledger.offer(artifact, target)
    ledger.record(artifact, target)

    assert ledger.find(artifact, target) is not None
    assert ApprovalLedger().find(artifact, target) is None


# --- Versión de partida ("baseline") en el grafo ---------------------------------------------


def test_baseline_is_saved_after_generating_from_story(tmp_path: Path) -> None:
    """PA-37: con origen HU, el state_store guarda la versión de partida tras generar."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)

    state = container.state_store.load(_artifact_id(graph, config))
    assert state is not None
    assert state["baseline"]["title"] == dataset.renewal_story().title
    assert "ledger" in state
    assert _structure_calls(_llm(container)) == 1


def test_baseline_is_not_saved_when_origin_is_epic(tmp_path: Path) -> None:
    """PA-37 (negativo): una HU nueva no tiene versión de partida de Jira."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)

    state = container.state_store.load(_artifact_id(graph, config))
    assert state is not None and "baseline" not in state
    assert _structure_calls(_llm(container)) == 0


def test_baseline_is_not_restructured_when_graph_nodes_are_rebuilt(tmp_path: Path) -> None:
    """PA-37: al iterar con un GraphNodes nuevo (mismo contenedor), no se reestructura."""
    container = fake_container(tmp_path)
    checkpointer = memory_checkpointer()
    config = _config()
    _start(build_graph(container, checkpointer), config)
    assert _structure_calls(_llm(container)) == 1

    restarted = build_graph(container, checkpointer)  # GraphNodes nuevo
    result = restarted.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)

    assert result["__interrupt__"]
    assert restarted.get_state(config).values["artifact"].version == 2
    assert _structure_calls(_llm(container)) == 1


def test_baseline_and_approval_survive_new_container_with_same_store(tmp_path: Path) -> None:
    """PA-37 · PA-06: contenedor nuevo con el mismo store → sin reestructurar y publica."""
    store = InMemoryArtifactStateStore()
    llm = FakeLLMProvider()
    tracker = FakeIssueTracker()
    checkpointer = memory_checkpointer()
    config = _config()
    first = fake_container(tmp_path, llm=llm, state_store=store, issue_tracker=tracker)
    _start(build_graph(first, checkpointer), config)

    second = fake_container(tmp_path, llm=llm, state_store=store, issue_tracker=tracker)
    graph = build_graph(second, checkpointer)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    final = graph.invoke(_approve(graph, config), config)

    assert _structure_calls(llm) == 1
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert tracker.writes[0] == ("update_story", {"key": "DEMO-3"})


def test_baseline_is_removed_after_live_publish(tmp_path: Path) -> None:
    """PA-37: al publicar (live) se borra la versión de partida; el ledger se conserva."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    final = graph.invoke(_approve(graph, config), config)

    state = container.state_store.load(str(final["artifact"].id))
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert state is not None
    assert "baseline" not in state
    assert state["ledger"]["approvals"][0]["consumed"] is True


def test_baseline_is_removed_after_discard(tmp_path: Path) -> None:
    """PA-37: al descartar se borra la versión de partida."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    artifact_id = _artifact_id(graph, config)

    graph.invoke(Command(resume={"decision": "discard"}), config)

    state = container.state_store.load(artifact_id)
    assert state is not None and "baseline" not in state


def test_baseline_is_kept_after_simulated_publish(tmp_path: Path) -> None:
    """PA-37 · T-25: la simulación no publica, así que la versión de partida se conserva."""
    container = fake_container(tmp_path, publish_mode="simulation")
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(_approve(graph, config), config)

    state = container.state_store.load(_artifact_id(graph, config))
    assert state is not None and "baseline" in state


# --- Integración: migración 0002 y SqlArtifactStateStore -------------------------------------


def _tables(engine: Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


@pytest.mark.integration
def test_migration_0002_creates_and_drops_artifact_state() -> None:
    """T-25: 0002 crea `artifact_state` sobre 0001 y su downgrade la borra sin tocar el resto."""
    with temporary_database("artifact_state_migration_test", revision="0001_initial") as (
        url,
        engine,
    ):
        config = alembic_config(url)
        assert "artifact_state" not in _tables(engine)

        command.upgrade(config, "0002_artifact_state")
        assert "artifact_state" in _tables(engine)
        columns = {c["name"]: c for c in sa.inspect(engine).get_columns("artifact_state")}
        assert set(columns) == {"artifact_id", "state", "updated_at"}
        assert columns["state"]["nullable"] is False
        assert sa.inspect(engine).get_pk_constraint("artifact_state")["constrained_columns"] == [
            "artifact_id"
        ]
        with engine.begin() as conn:  # valores por defecto del servidor
            conn.execute(
                sa.text("INSERT INTO artifact_state (artifact_id) VALUES (:id)"), {"id": uuid4()}
            )
            row = conn.execute(sa.text("SELECT state, updated_at FROM artifact_state")).one()
        assert row.state == {} and row.updated_at is not None

        command.downgrade(config, "0001_initial")
        assert "artifact_state" not in _tables(engine)
        assert {"artifacts", "audit_log", "artifact_versions"} <= _tables(engine)


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    with temporary_database("artifact_state_test") as (_url, engine):
        yield engine


@pytest.fixture
def engine(pg_engine: Engine) -> Engine:
    truncate_t25_tables(pg_engine)
    return pg_engine


@pytest.mark.integration
def test_sql_store_returns_none_when_artifact_unknown(engine: Engine) -> None:
    """PA-06: sin fila → None."""
    assert SqlArtifactStateStore(engine).load(str(uuid4())) is None


@pytest.mark.integration
def test_sql_store_saves_and_loads_nested_state(engine: Engine) -> None:
    """PA-06: JSONB anidado con texto en español se guarda y recupera igual."""
    store = SqlArtifactStateStore(engine)
    artifact_id = str(uuid4())
    state = {"baseline": {"title": "Renovar un préstamo", "tags": ["ñandú", "acción"]}, "n": 1}

    store.save(artifact_id, state)

    assert store.load(artifact_id) == state


@pytest.mark.integration
def test_sql_store_upsert_replaces_state_and_updates_timestamp(engine: Engine) -> None:
    """PA-06: guardar de nuevo sustituye el estado (una sola fila) y renueva updated_at."""
    store = SqlArtifactStateStore(engine)
    artifact_id = str(uuid4())
    store.save(artifact_id, {"baseline": {"title": "v1"}})
    with engine.connect() as conn:
        first = conn.execute(sa.text("SELECT updated_at FROM artifact_state")).scalar_one()

    store.save(artifact_id, {"ledger": {"offer": None}})

    assert store.load(artifact_id) == {"ledger": {"offer": None}}
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT updated_at FROM artifact_state")).all()
    assert len(rows) == 1
    assert rows[0].updated_at >= first


@pytest.mark.integration
def test_sql_store_keeps_ledger_across_restart(engine: Engine) -> None:
    """PA-06 · RF-33: el ledger sobre PostgreSQL recupera aprobación y consumo tras reiniciar."""
    artifact, target = _artifact(), _target()
    ledger = ApprovalLedger(store=SqlArtifactStateStore(engine))
    ledger.offer(artifact, target)
    approval = ledger.record(artifact, target)

    reloaded = ApprovalLedger(store=SqlArtifactStateStore(engine))
    found = reloaded.find(artifact, target)
    assert found == approval  # incluida la fecha (isoformat ↔ JSONB)

    reloaded.consume(found, artifact)
    assert ApprovalLedger(store=SqlArtifactStateStore(engine)).was_published(artifact)
