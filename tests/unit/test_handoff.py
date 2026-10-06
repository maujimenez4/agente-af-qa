"""Entregas de HU aprobadas a QA: `core/handoff.py` (T-54 · RF-14, RF-22, D-01).

Cubren `hand_off` (validaciones contra la fila de la conversación, el checkpointer y el registro
de aprobaciones; idempotencia por versión y publicación), `list_handoffs`, `take_handoff`,
`load_taken_handoff`, `InMemoryHandoffStore` y `SqlHandoffStore` (unitarias sin red con engines
de mentira; las de PostgreSQL llevan `@pytest.mark.integration` y se saltan sin BD) y que los
logs no registran el contenido de la HU. Solo fakes de `tests/fakes/`; datos 100 % ficticios.
"""

import re
import secrets
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy.dialects import postgresql
from structlog.testing import capture_logs

from adapters.base import User
from adapters.errors import AuthenticationError, ExternalServiceError, NotFoundError
from core.approvals import ApprovalLedger
from core.artifact_state import InMemoryArtifactStateStore
from core.container import Container
from core.conversations import THREAD_ID, new_conversation_config
from core.graph import build_graph, initial_state
from core.graph.nodes import GraphNodes, _target
from core.handoff import (
    DEFAULT_LIMIT,
    NOT_AVAILABLE,
    Handoff,
    HandoffError,
    InMemoryHandoffStore,
    SqlHandoffStore,
    hand_off,
    list_handoffs,
    load_taken_handoff,
    release_failed_take,
    take_handoff,
)
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider
from tests.pg_temp import temporary_database

ANA = User(username="ana-ficticia", role="functional")
BEA = User(username="bea-ficticia", role="functional")
QUIM = User(username="quim-ficticio", role="qa")
ROC = User(username="roc-ficticio", role="qa")
ADMIN = User(username="admin-ficticio", role="admin")
STORY_ORIGIN = {"kind": "story", "key": "DEMO-3"}
FAKE_PASSWORD = "clave-ficticia-no-real"


# --- utilidades -------------------------------------------------------------------------------


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[-1].value


def _answer(graph: CompiledStateGraph, config: dict[str, Any], decision: str) -> Command:
    payload = _pending(graph, config)
    return Command(resume={"decision": decision, "fingerprint": payload["fingerprint"]})


def _functional(
    tmp_path: Path,
    publish_mode: str = "live",
    *,
    decision: str | None = "approve",
    user: User = ANA,
    mode: str = "functional",
    **overrides: Any,
) -> tuple[Container, CompiledStateGraph, InMemoryHandoffStore, dict[str, Any], str]:
    """Conversación funcional (o la indicada) de DEMO-3 hasta la decisión pedida."""
    store = InMemoryHandoffStore()
    container = fake_container(tmp_path, publish_mode=publish_mode, **overrides)
    graph = build_graph(container, handoffs=store)
    config = new_conversation_config(user.username)
    graph.invoke(initial_state(user.username, mode, STORY_ORIGIN), config)  # type: ignore[arg-type]
    if decision is not None:
        graph.invoke(_answer(graph, config, decision), config)
    return container, graph, store, config, str(config["configurable"]["thread_id"])  # type: ignore[index]


def _handoff(**update: Any) -> Handoff:
    data: dict[str, Any] = {
        "id": secrets.token_hex(16),
        "artifact_id": uuid4(),
        "version": 1,
        "project_key": "DEMO",
        "story_key": "DEMO-3",
        "title": "Renovar un préstamo",
        "story": dataset.renewal_story(),
        "from_user": ANA.username,
        "from_thread_id": str(uuid4()),
        "created_at": datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    }
    return Handoff(**(data | update))


class _StateReader:
    """Lector de estado de mentira: devuelve los valores dados (para estados manipulados)."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get_state(self, _config: Any) -> Any:
        return type("Snapshot", (), {"values": self._values})()


# --- hand_off: camino feliz -------------------------------------------------------------------


def test_hand_off_published_story_carries_jira_key_and_story(tmp_path: Path) -> None:
    """T-54 · criterio 1/4: HU publicada en live → entrega pendiente con clave y la HU."""
    container, graph, store, _config, tid = _functional(tmp_path, "live")
    artifact: Artifact = graph.get_state(_config).values["artifact"]

    handoff = hand_off(container, graph, store, ANA, tid)

    assert container.conversations.get(tid).status == "published"  # type: ignore[union-attr]
    assert handoff.status == "pending"
    assert handoff.story_key == "DEMO-3"
    assert handoff.published is True
    assert handoff.artifact_id == artifact.id
    assert handoff.version == artifact.version
    assert handoff.project_key == "DEMO"
    assert handoff.story == artifact.content
    assert handoff.from_user == ANA.username
    assert handoff.from_thread_id == tid
    assert handoff.taken_by is None and handoff.qa_thread_id is None
    assert store.get(handoff.id) == handoff


def test_hand_off_simulated_story_has_no_key_even_if_story_had_one(tmp_path: Path) -> None:
    """T-54 · criterio 3: en simulación la entrega va sin clave aunque la HU tuviera jira_key."""
    container, graph, store, _config, tid = _functional(tmp_path, "simulation")

    handoff = hand_off(container, graph, store, ANA, tid)

    assert container.conversations.get(tid).status == "simulated"  # type: ignore[union-attr]
    assert handoff.story_key is None
    assert handoff.published is False
    # La HU evolucionada conserva la clave de partida, pero esa versión no está en Jira.
    assert handoff.story.jira_key == "DEMO-3"


def test_hand_off_from_approved_conversation_without_publish(tmp_path: Path) -> None:
    """T-54 · criterio 4 (límite): «approved» (aprobada, aún sin publicar) también se entrega."""
    container, graph, store, _config, tid = _functional(tmp_path, "simulation")
    container.conversations.update(tid, status="approved", username=ANA.username)

    handoff = hand_off(container, graph, store, ANA, tid)

    assert handoff.story_key is None


def test_hand_off_title_is_normalized_and_truncated(tmp_path: Path) -> None:
    """T-54 (límite): el título se compacta (espacios) y se acota a 120 caracteres."""
    long_title = "Renovar   un\npréstamo " + "x" * 300
    llm = FakeLLMProvider()
    story = dataset.renewal_story(jira_key=None).model_copy(update={"title": long_title})
    default = llm.builders[type(story)]

    def builder(messages: list[Any]) -> Any:
        built = default(messages)
        return built.model_copy(update={"title": long_title})

    llm.builders[type(story)] = builder
    container, graph, store, _config, tid = _functional(tmp_path, "live", llm=llm)

    handoff = hand_off(container, graph, store, ANA, tid)

    assert len(handoff.title) == 120
    assert handoff.title.startswith("Renovar un préstamo x")


# --- hand_off: idempotencia por (versión, publicación) ----------------------------------------


def test_hand_off_twice_same_version_returns_same_handoff(tmp_path: Path) -> None:
    """T-54 · criterio 4: misma versión y misma publicación → misma entrega (idempotente)."""
    container, graph, store, _config, tid = _functional(tmp_path, "live")

    first = hand_off(container, graph, store, ANA, tid)
    second = hand_off(container, graph, store, ANA, tid)

    assert second.id == first.id
    assert len(store.rows) == 1


def test_hand_off_twice_in_simulation_returns_same_handoff(tmp_path: Path) -> None:
    """T-54 · criterio 4: también sin clave: dos «Pasar a QA» → una sola entrega."""
    container, graph, store, _config, tid = _functional(tmp_path, "simulation")

    first = hand_off(container, graph, store, ANA, tid)
    second = hand_off(container, graph, store, ANA, tid)

    assert second.id == first.id
    assert len(store.rows) == 1


def _publish_live_later(
    tmp_path: Path, container: Container, graph: CompiledStateGraph, config: dict[str, Any]
) -> Container:
    """La misma versión aprobada en simulación se publica después en live (T-25) con una
    aprobación nueva: la de la simulación quedó gastada (PA-41)."""
    live = fake_container(
        tmp_path,
        publish_mode="live",
        state_store=container.state_store,
        issue_tracker=container.issue_tracker,
        conversations=container.conversations,
        audit=container.audit,
    )
    state = graph.get_state(config).values
    target = _target(state, config, live.require_actor)  # type: ignore[arg-type]
    live.approvals.offer(state["artifact"], target)  # vuelve a revisión con el modo real
    live.approvals.record(state["artifact"], target)  # y una persona la aprueba de nuevo
    result = GraphNodes(live).publish(state, config)  # type: ignore[arg-type]
    graph.update_state(config, result, as_node="publish")
    return live


def test_hand_off_after_live_publish_upgrades_pending_unpublished_handoff(
    tmp_path: Path,
) -> None:
    """T-54 · idempotencia: simulación → entrega sin clave → live → misma entrega con clave."""
    container, graph, store, config, tid = _functional(tmp_path, "simulation")
    unpublished = hand_off(container, graph, store, ANA, tid)
    assert unpublished.story_key is None

    live = _publish_live_later(tmp_path, container, graph, config)
    assert live.conversations.get(tid).status == "published"  # type: ignore[union-attr]
    published = hand_off(live, graph, store, ANA, tid)

    assert published.id == unpublished.id
    assert published.story_key == "DEMO-3"
    assert published.status == "pending"
    assert published.story == graph.get_state(config).values["artifact"].content
    assert len(store.rows) == 1
    assert [h.story_key for h in list_handoffs(store, QUIM)] == ["DEMO-3"]


def test_hand_off_after_live_publish_creates_new_handoff_if_unpublished_was_taken(
    tmp_path: Path,
) -> None:
    """T-54 · idempotencia: si la entrega sin clave ya se recogió, se crea otra con clave."""
    container, graph, store, config, tid = _functional(tmp_path, "simulation")
    unpublished = hand_off(container, graph, store, ANA, tid)
    take_handoff(store, QUIM, unpublished.id)

    live = _publish_live_later(tmp_path, container, graph, config)
    published = hand_off(live, graph, store, ANA, tid)

    assert published.id != unpublished.id
    assert published.story_key == "DEMO-3"
    assert published.status == "pending"
    assert store.get(unpublished.id).story_key is None  # type: ignore[union-attr]
    assert store.get(unpublished.id).status == "taken"  # type: ignore[union-attr]
    assert len(store.rows) == 2
    # Repetir con la HU publicada devuelve la nueva entrega.
    assert hand_off(live, graph, store, ANA, tid).id == published.id


# --- hand_off: errores ------------------------------------------------------------------------


def test_hand_off_rejects_conversation_of_another_user(tmp_path: Path) -> None:
    """T-54 · criterio 4 (seguridad): nadie pasa a QA la conversación de otra persona."""
    container, graph, store, _config, tid = _functional(tmp_path, "live")

    with pytest.raises(NotFoundError):
        hand_off(container, graph, store, BEA, tid)

    assert store.rows == {}


@pytest.mark.parametrize("thread_id", ["", "hilo inválido", "x" * 65, str(uuid4())])
def test_hand_off_rejects_invalid_or_unknown_thread(tmp_path: Path, thread_id: str) -> None:
    """T-54 · criterio 4 (error): hilo con formato no válido o inexistente → NotFoundError."""
    container, graph, store, _config, _tid = _functional(tmp_path, "live")

    with pytest.raises(NotFoundError):
        hand_off(container, graph, store, ANA, thread_id)

    assert store.rows == {}


def test_hand_off_rejects_qa_conversation(tmp_path: Path) -> None:
    """T-54 · criterio 4: una conversación de QA (aunque sea propia) no se pasa a QA."""
    container, graph, store, _config, tid = _functional(tmp_path, "live", mode="qa")
    assert container.conversations.get(tid).mode == "qa"  # type: ignore[union-attr]

    with pytest.raises(HandoffError, match="aprobada o publicada"):
        hand_off(container, graph, store, ANA, tid)

    assert store.rows == {}


def test_hand_off_rejects_in_review_conversation(tmp_path: Path) -> None:
    """T-54 · criterio 4: «in_review» (sin aprobar) → HandoffError."""
    container, graph, store, _config, tid = _functional(tmp_path, "live", decision=None)
    assert container.conversations.get(tid).status == "in_review"  # type: ignore[union-attr]

    with pytest.raises(HandoffError):
        hand_off(container, graph, store, ANA, tid)

    assert store.rows == {}


def test_hand_off_rejects_discarded_conversation(tmp_path: Path) -> None:
    """T-54 · criterio 4: «discarded» → HandoffError."""
    container, graph, store, _config, tid = _functional(tmp_path, "live", decision="discard")
    assert container.conversations.get(tid).status == "discarded"  # type: ignore[union-attr]

    with pytest.raises(HandoffError):
        hand_off(container, graph, store, ANA, tid)

    assert store.rows == {}


def test_hand_off_rejects_started_conversation(tmp_path: Path) -> None:
    """T-54 · criterio 4: «started» (falló la generación) → HandoffError."""
    llm = FakeLLMProvider(error=RuntimeError("fallo ficticio del modelo"))
    store = InMemoryHandoffStore()
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container, handoffs=store)
    config = new_conversation_config(ANA.username)
    tid = str(config["configurable"]["thread_id"])  # type: ignore[index]
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state(ANA.username, "functional", STORY_ORIGIN), config)  # type: ignore[arg-type]
    assert container.conversations.get(tid).status == "started"  # type: ignore[union-attr]

    with pytest.raises(HandoffError):
        hand_off(container, graph, store, ANA, tid)

    assert store.rows == {}


@pytest.mark.parametrize("user", [QUIM, ADMIN], ids=["qa", "admin"])
def test_hand_off_requires_functional_role(tmp_path: Path, user: User) -> None:
    """T-54 · criterio 4 (permiso): solo el rol functional pasa HU a QA."""
    container, graph, store, _config, tid = _functional(tmp_path, "live")

    with pytest.raises(AuthenticationError):
        hand_off(container, graph, store, user, tid)

    assert store.rows == {}


@pytest.mark.parametrize("field", ["version", "artifact_id"])
def test_hand_off_rejects_when_checkpoint_does_not_match_row(tmp_path: Path, field: str) -> None:
    """T-54 · criterio 4: si el artefacto del checkpointer no coincide con la fila → error."""
    container, graph, store, _config, tid = _functional(tmp_path, "live")
    row = container.conversations.get(tid)
    assert row is not None
    changed = {"version": (row.version or 0) + 1, "artifact_id": str(uuid4())}[field]
    container.conversations.rows[tid] = row.model_copy(update={field: changed})  # type: ignore[attr-defined]

    with pytest.raises(HandoffError, match="no coincide"):
        hand_off(container, graph, store, ANA, tid)

    assert store.rows == {}


@pytest.mark.parametrize("publish_mode", ["live", "simulation"])
def test_hand_off_rejects_when_ledger_does_not_confirm(tmp_path: Path, publish_mode: str) -> None:
    """T-54 · criterio 4: con un registro de aprobaciones vacío no consta la aprobación."""
    container, graph, store, _config, tid = _functional(tmp_path, publish_mode)
    empty = replace(container, approvals=ApprovalLedger(store=InMemoryArtifactStateStore()))

    with pytest.raises(HandoffError, match="No consta la aprobación"):
        hand_off(empty, graph, store, ANA, tid)

    assert store.rows == {}


def test_hand_off_rejects_manipulated_story_content(tmp_path: Path) -> None:
    """T-54 · criterio 4 (seguridad): HU del checkpointer alterada → la huella no coincide."""
    container, graph, store, config, tid = _functional(tmp_path, "simulation")
    values = dict(graph.get_state(config).values)
    artifact: Artifact = values["artifact"]
    values["artifact"] = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"title": "Título inyectado"})}
    )

    with pytest.raises(HandoffError):
        hand_off(container, _StateReader(values), store, ANA, tid)

    assert store.rows == {}


def test_hand_off_rejects_published_status_without_ledger_publication(tmp_path: Path) -> None:
    """T-54 · criterio 4: artefacto marcado PUBLISHED a mano, sin publicación en el registro."""
    container, graph, store, config, tid = _functional(tmp_path, "simulation")
    values = dict(graph.get_state(config).values)
    artifact: Artifact = values["artifact"]
    values["artifact"] = artifact.model_copy(update={"status": ArtifactStatus.PUBLISHED})

    with pytest.raises(HandoffError, match="No consta la aprobación"):
        hand_off(container, _StateReader(values), store, ANA, tid)


def test_hand_off_rejects_missing_artifact(tmp_path: Path) -> None:
    """T-54 · criterio 4: sin artefacto en el checkpointer → HandoffError."""
    container, _graph, store, _config, tid = _functional(tmp_path, "live")

    with pytest.raises(HandoffError):
        hand_off(container, _StateReader({"artifact": None}), store, ANA, tid)


# --- list_handoffs ----------------------------------------------------------------------------


@pytest.mark.parametrize("user", [ANA, ADMIN], ids=["functional", "admin"])
def test_list_handoffs_requires_qa_role(user: User) -> None:
    """T-54 · criterio 5 (permiso): solo el rol qa ve la lista de HU entregadas."""
    store = InMemoryHandoffStore()
    store.create(_handoff())

    with pytest.raises(AuthenticationError):
        list_handoffs(store, user)


def test_list_handoffs_returns_only_pending_newest_first() -> None:
    """T-54 · criterio 5: solo pendientes, ordenadas de la más reciente a la más antigua."""
    store = InMemoryHandoffStore()
    base = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    old = store.create(_handoff(created_at=base))
    new = store.create(_handoff(created_at=base + timedelta(hours=2)))
    taken = store.create(_handoff(created_at=base + timedelta(hours=1)))
    store.take(taken.id, ROC.username, str(uuid4()), base)

    listed = list_handoffs(store, QUIM)

    assert [h.id for h in listed] == [new.id, old.id]


def test_list_handoffs_filters_by_projects() -> None:
    """T-54 · criterio 5: filtro por proyectos visibles; colección vacía → nada."""
    store = InMemoryHandoffStore()
    demo = store.create(_handoff(project_key="DEMO"))
    store.create(_handoff(project_key="OTRO", story_key="OTRO-1"))

    assert [h.id for h in list_handoffs(store, QUIM, projects={"DEMO"})] == [demo.id]
    assert list_handoffs(store, QUIM, projects=[]) == []
    assert len(list_handoffs(store, QUIM)) == 2


@pytest.mark.parametrize(("limit", "expected"), [(500, DEFAULT_LIMIT), (0, 1), (-3, 1), (7, 7)])
def test_list_handoffs_bounds_limit_to_50(limit: int, expected: int) -> None:
    """T-54 · criterio 5 (límite): el límite se acota a [1, 50]."""
    store = InMemoryHandoffStore()
    base = datetime(2026, 10, 1, tzinfo=UTC)
    for minute in range(60):
        store.create(_handoff(created_at=base + timedelta(minutes=minute)))

    assert len(list_handoffs(store, QUIM, limit=limit)) == expected
    assert len(list_handoffs(store, QUIM)) == DEFAULT_LIMIT


# --- take_handoff -----------------------------------------------------------------------------


@pytest.mark.parametrize("user", [ANA, ADMIN], ids=["functional", "admin"])
def test_take_handoff_requires_qa_role(user: User) -> None:
    """T-54 · criterio 6 (permiso): solo el rol qa recoge una entrega."""
    store = InMemoryHandoffStore()
    handoff = store.create(_handoff())

    with pytest.raises(AuthenticationError):
        take_handoff(store, user, handoff.id)

    assert store.get(handoff.id).status == "pending"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "handoff_id",
    ["", "abc", "A" * 32, "g" * 32, "a" * 31, "a" * 33, "../" + "a" * 29, "a" * 32 + "\n"],
)
def test_take_handoff_rejects_invalid_id_format(handoff_id: str) -> None:
    """T-54 · criterio 6 (error): id con formato no válido → HandoffError, sin tocar el almacén."""
    store = InMemoryHandoffStore()

    with pytest.raises(HandoffError) as exc_info:
        take_handoff(store, QUIM, handoff_id)

    assert str(exc_info.value) == NOT_AVAILABLE


def test_take_handoff_rejects_unknown_id() -> None:
    """T-54 · criterio 6 (error): id con formato válido pero inexistente → HandoffError."""
    with pytest.raises(HandoffError):
        take_handoff(InMemoryHandoffStore(), QUIM, secrets.token_hex(16))


def test_take_handoff_only_once() -> None:
    """T-54 · criterio 6: una sola vez; la segunda (misma u otra persona) → HandoffError."""
    store = InMemoryHandoffStore()
    handoff = store.create(_handoff())
    start = take_handoff(store, QUIM, handoff.id)

    with pytest.raises(HandoffError):
        take_handoff(store, QUIM, handoff.id)
    with pytest.raises(HandoffError):
        take_handoff(store, ROC, handoff.id)

    stored = store.get(handoff.id)
    assert stored is not None
    assert stored.taken_by == QUIM.username
    assert stored.qa_thread_id == start.config["configurable"]["thread_id"]  # type: ignore[index]


def test_take_handoff_generates_thread_id_on_server() -> None:
    """T-54 · criterio 6: el hilo de QA lo genera el servidor y queda en la entrega."""
    store = InMemoryHandoffStore()
    first = take_handoff(store, QUIM, store.create(_handoff()).id)
    second = take_handoff(store, QUIM, store.create(_handoff()).id)

    configurable = first.config["configurable"]
    assert isinstance(configurable, dict)
    thread_id = configurable["thread_id"]
    assert THREAD_ID.fullmatch(thread_id)
    assert UUID(thread_id)
    assert configurable["user"] == QUIM.username
    assert first.handoff.qa_thread_id == thread_id
    assert first.handoff.status == "taken"
    assert first.handoff.taken_at is not None
    assert second.config["configurable"]["thread_id"] != thread_id  # type: ignore[index]


def test_take_handoff_initial_state_with_story_key() -> None:
    """T-54 · criterio 6: estado inicial QA, kind story, proyecto, clave y handoff_id."""
    store = InMemoryHandoffStore()
    handoff = store.create(_handoff(story_key="DEMO-3"))

    state = take_handoff(store, QUIM, handoff.id).state

    assert state["user"] == QUIM.username
    assert state["mode"] == "qa"
    assert state["origin"] == {"kind": "story", "project": "DEMO", "key": "DEMO-3"}
    assert state["handoff_id"] == handoff.id
    assert state["artifact"] is None
    assert state.get("source_story") is None  # la HU la carga el grafo, no el estado


def test_take_handoff_initial_state_without_story_key() -> None:
    """T-54 · criterio 6 (límite): sin clave publicada, el origen no lleva `key`."""
    store = InMemoryHandoffStore()
    handoff = store.create(_handoff(story_key=None, project_key="OTRO"))

    state = take_handoff(store, QUIM, handoff.id).state

    assert "key" not in state["origin"]
    assert state["origin"] == {"kind": "story", "project": "OTRO"}
    assert state["handoff_id"] == handoff.id


# --- load_taken_handoff -----------------------------------------------------------------------


def test_load_taken_handoff_returns_handoff_for_owner_and_thread() -> None:
    """T-54 · criterio 7: la entrega recogida por esa persona para ese hilo."""
    store = InMemoryHandoffStore()
    handoff = store.create(_handoff())
    start = take_handoff(store, QUIM, handoff.id)
    thread_id = str(start.config["configurable"]["thread_id"])  # type: ignore[index]

    assert load_taken_handoff(store, handoff.id, QUIM.username, thread_id).id == handoff.id


@pytest.mark.parametrize(
    "case", ["other_user", "other_thread", "pending", "unknown", "bad", "none"]
)
def test_load_taken_handoff_fails_closed(case: str) -> None:
    """T-54 · criterio 7: ajena, otro hilo, no recogida, inexistente, formato o sin almacén."""
    store = InMemoryHandoffStore()
    taken = store.create(_handoff())
    start = take_handoff(store, QUIM, taken.id)
    thread_id = str(start.config["configurable"]["thread_id"])  # type: ignore[index]
    pending = store.create(_handoff())
    args = {
        "other_user": (store, taken.id, ROC.username, thread_id),
        "other_thread": (store, taken.id, QUIM.username, str(uuid4())),
        "pending": (store, pending.id, QUIM.username, thread_id),
        "unknown": (store, secrets.token_hex(16), QUIM.username, thread_id),
        "bad": (store, "x", QUIM.username, thread_id),
        "none": (None, taken.id, QUIM.username, thread_id),
    }[case]

    with pytest.raises(HandoffError):
        load_taken_handoff(*args)  # type: ignore[arg-type]


# --- InMemoryHandoffStore ---------------------------------------------------------------------


def test_in_memory_create_same_version_same_publication_returns_existing() -> None:
    """T-54 · criterio 10: (artifact_id, version, publicada) repetido → la entrega existente."""
    store = InMemoryHandoffStore()
    first = store.create(_handoff())
    again = store.create(_handoff(artifact_id=first.artifact_id))

    assert again.id == first.id
    assert len(store.rows) == 1


def test_in_memory_create_other_version_is_new_handoff() -> None:
    """T-54 · criterio 10 (límite): otra versión del mismo artefacto → otra entrega."""
    store = InMemoryHandoffStore()
    first = store.create(_handoff())
    second = store.create(_handoff(artifact_id=first.artifact_id, version=2))

    assert second.id != first.id
    assert len(store.rows) == 2


def test_in_memory_create_published_upgrades_pending_unpublished() -> None:
    """T-54 · criterio 10: publicada + entrega sin clave pendiente → misma entrega con clave."""
    store = InMemoryHandoffStore()
    unpublished = store.create(_handoff(story_key=None, story=dataset.renewal_story(None)))
    published_story = dataset.renewal_story("DEMO-3")

    upgraded = store.create(
        _handoff(artifact_id=unpublished.artifact_id, story_key="DEMO-3", story=published_story)
    )

    assert upgraded.id == unpublished.id
    assert upgraded.story_key == "DEMO-3"
    assert upgraded.story == published_story
    assert upgraded.status == "pending"
    assert store.get(unpublished.id) == upgraded
    assert len(store.rows) == 1


def test_in_memory_create_published_after_taken_unpublished_creates_new() -> None:
    """T-54 · criterio 10: si la entrega sin clave ya se recogió → otra entrega con clave."""
    store = InMemoryHandoffStore()
    unpublished = store.create(_handoff(story_key=None))
    store.take(unpublished.id, QUIM.username, str(uuid4()), datetime.now(UTC))

    published = store.create(_handoff(artifact_id=unpublished.artifact_id))

    assert published.id != unpublished.id
    assert published.story_key == "DEMO-3"
    assert store.get(unpublished.id).story_key is None  # type: ignore[union-attr]
    assert len(store.rows) == 2


def test_in_memory_create_unpublished_after_published_returns_new_unpublished() -> None:
    """T-54 · criterio 10 (límite): una entrega sin clave no degrada la ya publicada."""
    store = InMemoryHandoffStore()
    published = store.create(_handoff())

    unpublished = store.create(_handoff(artifact_id=published.artifact_id, story_key=None))

    assert store.get(published.id).story_key == "DEMO-3"  # type: ignore[union-attr]
    assert unpublished.id != published.id
    assert unpublished.story_key is None


def test_in_memory_take_is_single_use() -> None:
    """T-54 · criterio 10: take marca la entrega una sola vez; inexistente → None."""
    store = InMemoryHandoffStore()
    handoff = store.create(_handoff())
    at = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)

    taken = store.take(handoff.id, QUIM.username, "hilo-qa-1", at)

    assert taken is not None
    assert (taken.status, taken.taken_by, taken.taken_at, taken.qa_thread_id) == (
        "taken",
        QUIM.username,
        at,
        "hilo-qa-1",
    )
    assert store.take(handoff.id, ROC.username, "hilo-qa-2", at) is None
    assert store.get(handoff.id) == taken
    assert store.take(secrets.token_hex(16), QUIM.username, "hilo-qa-3", at) is None
    assert store.list_pending() == []


# --- SqlHandoffStore sin red ------------------------------------------------------------------


class BrokenEngine:
    """Engine que falla al abrir la transacción, como una BD caída (sin red)."""

    def begin(self) -> Any:
        raise sa.exc.OperationalError(
            "SELECT * FROM qa_handoffs", {}, Exception(f"conexión rechazada {FAKE_PASSWORD}")
        )


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda s: s.create(_handoff()), "No se pudo guardar la entrega a QA."),
        (lambda s: s.get(secrets.token_hex(16)), "No se pudo leer la entrega a QA."),
        (lambda s: s.list_pending(), "No se pudo listar las entregas a QA."),
        (
            lambda s: s.take(secrets.token_hex(16), QUIM.username, "hilo", datetime.now(UTC)),
            "No se pudo recoger la entrega a QA.",
        ),
    ],
    ids=["create", "get", "list_pending", "take"],
)
def test_sql_store_wraps_database_errors_without_details(call: Any, message: str) -> None:
    """T-54 · criterio 10 (error): BD caída → ExternalServiceError en español, sin detalles."""
    store = SqlHandoffStore(BrokenEngine())  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError) as exc_info:
        call(store)

    assert str(exc_info.value) == message
    assert exc_info.value.service == "postgres"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert FAKE_PASSWORD not in str(exc_info.value)
    assert "qa_handoffs" not in str(exc_info.value)


class _Result:
    returns_rows = False


class _RecordingConnection:
    def __init__(self, statements: list[Any]) -> None:
        self._statements = statements

    def execute(self, statement: Any) -> _Result:
        self._statements.append(statement)
        return _Result()


class RecordingEngine:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def begin(self) -> Any:
        return nullcontext(_RecordingConnection(self.statements))


def _sql(statement: Any) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def test_sql_store_take_is_a_single_conditional_update_returning() -> None:
    """T-54 · criterio 10: take es un UPDATE condicionado a 'pending' con RETURNING (atómico)."""
    engine = RecordingEngine()

    assert SqlHandoffStore(engine).take("a" * 32, QUIM.username, "h", datetime.now(UTC)) is None  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = _sql(statement)
    assert sql.startswith("UPDATE qa_handoffs SET")
    assert re.search(
        r"WHERE qa_handoffs\.id = %\(id_1\)s\S* AND qa_handoffs\.status = %\(status_1\)s", sql
    )
    assert "RETURNING" in sql
    assert statement.compile().params["status_1"] == "pending"


def test_sql_store_list_pending_filters_orders_and_limits() -> None:
    """T-54 · criterio 5/10: list_pending filtra pendientes y proyectos, desc y con LIMIT."""
    engine = RecordingEngine()

    SqlHandoffStore(engine).list_pending({"DEMO"}, 7)  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = _sql(statement)
    assert "qa_handoffs.status = %(status_1)s" in sql
    assert "qa_handoffs.project_key IN" in sql
    assert "ORDER BY qa_handoffs.created_at DESC" in sql
    assert "LIMIT %(param_1)s" in sql
    assert statement.compile().params["param_1"] == 7


def test_sql_store_create_inserts_on_conflict_do_nothing() -> None:
    """T-54 · criterio 10: create usa ON CONFLICT DO NOTHING sobre la restricción única."""
    engine = RecordingEngine()

    with pytest.raises(IndexError):  # el engine de mentira no devuelve filas
        SqlHandoffStore(engine).create(_handoff(story_key=None))  # type: ignore[arg-type]

    sqls = [_sql(s) for s in engine.statements]
    assert sqls[0].startswith("INSERT INTO qa_handoffs")
    assert "ON CONFLICT ON CONSTRAINT uq_qa_handoffs_artifact_version DO NOTHING" in sqls[0]
    assert sqls[-1].startswith("SELECT")


# --- Logs -------------------------------------------------------------------------------------


def test_hand_off_and_take_do_not_log_story_content(tmp_path: Path) -> None:
    """T-54 · criterio 12: los logs de hand_off y take_handoff no llevan el texto de la HU."""
    container, graph, store, _config, tid = _functional(tmp_path, "live")
    story = graph.get_state(_config).values["artifact"].content

    with capture_logs() as logs:
        handoff = hand_off(container, graph, store, ANA, tid)
        take_handoff(store, QUIM, handoff.id)

    actions = [entry.get("action") for entry in logs]
    assert "handoff" in actions and "take_handoff" in actions
    texts = [story.title, story.description, story.action, story.benefit]
    texts += [c.text for c in story.acceptance_criteria if hasattr(c, "text")]
    dumped = " ".join(str(value) for entry in logs for value in entry.values())
    for text in texts:
        assert text not in dumped
    for entry in logs:
        assert "story" not in entry and "title" not in entry


# --- SqlHandoffStore contra PostgreSQL --------------------------------------------------------


@pytest.fixture
def sql_store() -> Any:
    with temporary_database("handoffs_test") as (_url, engine):
        yield SqlHandoffStore(engine), engine


@pytest.mark.integration
def test_sql_store_create_is_idempotent_and_roundtrips(sql_store: Any) -> None:
    """T-54 · criterio 10 (PostgreSQL): create idempotente y la HU vuelve igual."""
    store, _engine = sql_store
    first = store.create(_handoff())

    again = store.create(_handoff(artifact_id=first.artifact_id))

    assert again.id == first.id
    assert again.story == first.story
    assert again.artifact_id == first.artifact_id
    assert store.get(first.id) == again


@pytest.mark.integration
def test_sql_store_published_upgrades_pending_unpublished(sql_store: Any) -> None:
    """T-54 · criterio 10 (PostgreSQL): la entrega sin clave pendiente recibe la clave."""
    store, _engine = sql_store
    unpublished = store.create(_handoff(story_key=None, story=dataset.renewal_story(None)))

    upgraded = store.create(_handoff(artifact_id=unpublished.artifact_id))

    assert upgraded.id == unpublished.id
    assert upgraded.story_key == "DEMO-3"
    assert upgraded.story.jira_key == "DEMO-3"
    assert [h.id for h in store.list_pending()] == [unpublished.id]


@pytest.mark.integration
def test_sql_store_published_after_taken_unpublished_creates_new(sql_store: Any) -> None:
    """T-54 · criterio 10 (PostgreSQL): sin clave recogida → otra entrega publicada."""
    store, _engine = sql_store
    unpublished = store.create(_handoff(story_key=None))
    assert store.take(unpublished.id, QUIM.username, "hilo-qa", datetime.now(UTC))

    published = store.create(_handoff(artifact_id=unpublished.artifact_id))

    assert published.id != unpublished.id
    assert published.story_key == "DEMO-3"
    assert store.get(unpublished.id).story_key is None
    assert store.create(_handoff(artifact_id=unpublished.artifact_id)).id == published.id


@pytest.mark.integration
def test_sql_store_take_only_once_and_list_pending(sql_store: Any) -> None:
    """T-54 · criterio 10 (PostgreSQL): take una sola vez; list_pending solo pendientes."""
    store, _engine = sql_store
    base = datetime(2026, 10, 1, tzinfo=UTC)
    old = store.create(_handoff(created_at=base))
    new = store.create(_handoff(created_at=base + timedelta(hours=1)))
    other = store.create(_handoff(created_at=base, project_key="OTRO", story_key="OTRO-1"))

    taken = store.take(old.id, QUIM.username, "hilo-qa-1", base)

    assert taken is not None and taken.taken_by == QUIM.username
    assert store.take(old.id, ROC.username, "hilo-qa-2", base) is None
    assert [h.id for h in store.list_pending()] == [new.id, other.id]
    assert [h.id for h in store.list_pending({"DEMO"})] == [new.id]
    assert len(store.list_pending(limit=1)) == 1


@pytest.mark.integration
def test_sql_store_database_error_is_wrapped(sql_store: Any) -> None:
    """T-54 · criterio 10 (PostgreSQL, error): tabla ausente → ExternalServiceError sin SQL."""
    store, engine = sql_store
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE qa_handoffs"))

    with pytest.raises(ExternalServiceError) as exc_info:
        store.get(secrets.token_hex(16))

    assert "qa_handoffs" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


# --- PA-113: devolver la entrega si la conversación de QA falla --------------------------------


def _taken(store: InMemoryHandoffStore, thread: str = "hilo-qa-1") -> Handoff:
    handoff = store.create(_handoff())
    taken = store.take(handoff.id, QUIM.username, thread, datetime(2026, 10, 2, tzinfo=UTC))
    assert taken is not None
    return taken


def test_in_memory_release_returns_taken_handoff_to_pending() -> None:
    """PA-113 · criterio 7: release con quien la recogió y su hilo → pendiente y sin datos."""
    store = InMemoryHandoffStore()
    taken = _taken(store)

    assert store.release(taken.id, QUIM.username, "hilo-qa-1") is True

    row = store.get(taken.id)
    assert row is not None
    assert (row.status, row.taken_by, row.taken_at, row.qa_thread_id) == (
        "pending",
        None,
        None,
        None,
    )
    assert row.story == taken.story and row.created_at == taken.created_at
    assert [h.id for h in store.list_pending()] == [taken.id]
    assert store.take(taken.id, ROC.username, "hilo-qa-2", datetime.now(UTC)) is not None


@pytest.mark.parametrize(
    ("username", "thread"),
    [("roc-ficticio", "hilo-qa-1"), ("quim-ficticio", "hilo-qa-otro"), ("roc-ficticio", "x")],
    ids=["other-person", "other-thread", "both"],
)
def test_in_memory_release_requires_matching_person_and_thread(username: str, thread: str) -> None:
    """PA-113 · criterio 7 (negativa): nadie libera la entrega de otra persona u otro hilo."""
    store = InMemoryHandoffStore()
    taken = _taken(store)

    assert store.release(taken.id, username, thread) is False

    assert store.get(taken.id) == taken


def test_in_memory_release_of_pending_or_unknown_is_false() -> None:
    """PA-113 · criterio 7 (límite): una entrega pendiente o inexistente no se libera."""
    store = InMemoryHandoffStore()
    pending = store.create(_handoff())

    assert store.release(pending.id, QUIM.username, "hilo-qa-1") is False
    assert store.release(secrets.token_hex(16), QUIM.username, "hilo-qa-1") is False
    assert store.get(pending.id) == pending


def test_in_memory_release_is_single_use() -> None:
    """PA-113 · criterio 7: liberada una vez, el mismo hilo no puede liberarla otra vez."""
    store = InMemoryHandoffStore()
    taken = _taken(store)
    assert store.release(taken.id, QUIM.username, "hilo-qa-1") is True

    assert store.release(taken.id, QUIM.username, "hilo-qa-1") is False


def test_released_handoff_is_not_available_to_failed_thread() -> None:
    """PA-113 · criterio 7: tras liberarla, el hilo fallido ya no la carga."""
    store = InMemoryHandoffStore()
    taken = _taken(store)
    assert load_taken_handoff(store, taken.id, QUIM.username, "hilo-qa-1") == taken

    release_failed_take(store, taken.id, QUIM.username, "hilo-qa-1")

    with pytest.raises(HandoffError, match=NOT_AVAILABLE):
        load_taken_handoff(store, taken.id, QUIM.username, "hilo-qa-1")


def test_release_failed_take_logs_without_story_content() -> None:
    """PA-113 · criterio 7: se registra la acción y el id, nunca el texto de la HU."""
    store = InMemoryHandoffStore()
    taken = _taken(store)

    with capture_logs() as logs:
        assert release_failed_take(store, taken.id, QUIM.username, "hilo-qa-1") is True
        assert release_failed_take(store, taken.id, QUIM.username, "hilo-qa-1") is False

    (entry,) = [e for e in logs if e.get("action") == "release_handoff"]
    assert entry["handoff_id"] == taken.id
    assert entry["user"] == QUIM.username
    assert taken.story.title not in str(logs)


def test_sql_store_release_is_a_single_conditional_update() -> None:
    """PA-113 · criterio 7: release es un UPDATE condicionado a taken, persona e hilo."""
    engine = RecordingEngine()

    assert SqlHandoffStore(engine).release("a" * 32, QUIM.username, "hilo-qa-1") is False  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = _sql(statement)
    assert sql.startswith("UPDATE qa_handoffs SET")
    for column in ("id", "status", "taken_by", "qa_thread_id"):
        assert f"qa_handoffs.{column} = " in sql
    assert "RETURNING" in sql
    params = statement.compile().params
    assert params["status_1"] == "taken"
    assert params["taken_by_1"] == QUIM.username
    assert params["qa_thread_id_1"] == "hilo-qa-1"
    assert params["status"] == "pending"


def test_sql_store_release_wraps_database_errors_without_details() -> None:
    """PA-113 · criterio 7 (error): BD caída → ExternalServiceError en español."""
    store = SqlHandoffStore(BrokenEngine())  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError) as exc_info:
        store.release(secrets.token_hex(16), QUIM.username, "hilo")

    assert str(exc_info.value) == "No se pudo devolver la entrega a QA."
    assert FAKE_PASSWORD not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.integration
def test_sql_store_release_against_postgres(sql_store: Any) -> None:
    """PA-113 · criterio 7 (PostgreSQL): solo con persona e hilo; vuelve a la lista."""
    store, _engine = sql_store
    handoff = store.create(_handoff())
    at = datetime(2026, 10, 2, tzinfo=UTC)
    assert store.take(handoff.id, QUIM.username, "hilo-qa-1", at) is not None

    assert store.release(handoff.id, ROC.username, "hilo-qa-1") is False
    assert store.release(handoff.id, QUIM.username, "hilo-qa-otro") is False
    assert store.get(handoff.id).status == "taken"

    assert store.release(handoff.id, QUIM.username, "hilo-qa-1") is True

    row = store.get(handoff.id)
    assert (row.status, row.taken_by, row.taken_at, row.qa_thread_id) == (
        "pending",
        None,
        None,
        None,
    )
    assert [h.id for h in store.list_pending()] == [handoff.id]
    assert store.release(handoff.id, QUIM.username, "hilo-qa-1") is False
    assert store.take(handoff.id, ROC.username, "hilo-qa-2", at) is not None
