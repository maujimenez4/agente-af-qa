"""QA encadenada en el grafo: HU aprobada → entrega → conversación de QA (T-54 · RF-14, RF-22).

Cubren el flujo completo con fakes (live y simulación), que el hilo de QA no relee Jira ni llama
a `structure_story`, que el RAG se consulta con el texto de la HU, la trazabilidad en la
auditoría de `create`, el rechazo de aprobar/publicar casos de una HU sin publicar, que el grafo
no se fía del estado (entrega ajena, de otro hilo, no recogida, manipulada o sin almacén),
`validate_origin` con `handoff_id` y la serialización de `source_story` en el checkpointer.
Solo fakes de `tests/fakes/`; datos 100 % ficticios.
"""

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.base import TaskType, User
from adapters.errors import NotFoundError
from core.container import Container
from core.conversations import new_conversation_config
from core.graph import build_graph, initial_state, memory_checkpointer
from core.graph.builder import checkpoint_serializer
from core.graph.nodes import UNPUBLISHED_STORY, GraphNodes, PublishError, validate_origin
from core.handoff import (
    Handoff,
    HandoffError,
    InMemoryHandoffStore,
    QaStart,
    hand_off,
    list_handoffs,
    take_handoff,
)
from core.qa.writer import UNPUBLISHED_STORY_KEY
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider

ANA = User(username="ana-ficticia", role="functional")
QUIM = User(username="quim-ficticio", role="qa")
ROC = User(username="roc-ficticio", role="qa")
STORY_ORIGIN = {"kind": "story", "key": "DEMO-3"}


# --- utilidades -------------------------------------------------------------------------------


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[-1].value


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    payload = _pending(graph, config)
    return Command(resume={"decision": "approve", "fingerprint": payload["fingerprint"]})


def _thread(config: dict[str, Any]) -> str:
    return str(config["configurable"]["thread_id"])


class _Chain:
    """Contenedor, grafo y almacén de entregas compartidos por el hilo funcional y el de QA."""

    def __init__(self, tmp_path: Path, publish_mode: str, **overrides: Any) -> None:
        self.store = InMemoryHandoffStore()
        self.container: Container = fake_container(tmp_path, publish_mode=publish_mode, **overrides)
        self.graph = build_graph(self.container, handoffs=self.store)

    def approved_story(self) -> Handoff:
        """HU DEMO-3 aprobada (y publicada o simulada) y pasada a QA."""
        config = new_conversation_config(ANA.username)
        self.graph.invoke(initial_state(ANA.username, "functional", STORY_ORIGIN), config)  # type: ignore[arg-type]
        self.graph.invoke(_approve(self.graph, config), config)
        return hand_off(self.container, self.graph, self.store, ANA, _thread(config))

    def llm(self) -> FakeLLMProvider:
        assert isinstance(self.container.llm, FakeLLMProvider)
        return self.container.llm


def _qa_artifact(chain: _Chain, start: QaStart) -> Artifact:
    artifact = chain.graph.get_state(start.config).values["artifact"]
    assert isinstance(artifact, Artifact)
    return artifact


# --- 1 · flujo completo en live ---------------------------------------------------------------


def test_chained_flow_live_publishes_cases_and_traces_source(tmp_path: Path) -> None:
    """T-54 · criterio 1: HU publicada → entrega → QA la ve, la recoge, genera, aprueba, publica."""
    chain = _Chain(tmp_path, "live")
    handoff = chain.approved_story()
    assert handoff.story_key == "DEMO-3"

    assert [h.id for h in list_handoffs(chain.store, QUIM)] == [handoff.id]
    start = take_handoff(chain.store, QUIM, handoff.id)
    result = chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    payload = result["__interrupt__"][0].value
    suite = payload["artifact"]["content"]
    assert payload["artifact"]["type"] == ArtifactType.TEST_SUITE.value
    assert suite["story_jira_key"] == "DEMO-3"
    assert payload["plan"] == [
        {"op": "publish_suite", "project": "DEMO", "story": "DEMO-3", "cases": "2"}
    ]
    assert payload["error"] is None

    final = chain.graph.invoke(_approve(chain.graph, start.config), start.config)

    qa_thread = _thread(start.config)
    row = chain.container.conversations.get(qa_thread)
    assert row is not None
    assert (row.username, row.mode, row.status) == (QUIM.username, "qa", "published")
    assert row.origin_key == "DEMO-3"
    assert final["published_keys"]
    assert all(key.startswith("DEMO-") for key in final["published_keys"])
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    artifact = final["artifact"]
    (create,) = [e for e in chain.container.audit.entries(artifact.id) if e.action == "create"]  # type: ignore[attr-defined]
    assert create.user == QUIM.username
    assert create.detail["handoff_id"] == handoff.id
    assert create.detail["source_artifact_id"] == str(handoff.artifact_id)
    assert create.detail["source_version"] == handoff.version
    assert create.detail["source_story_key"] == "DEMO-3"
    actions = [e.action for e in chain.container.audit.entries(artifact.id)]  # type: ignore[attr-defined]
    assert actions == ["create", "approve", "publish"]


# --- 2 · sin Jira ni structure en el hilo de QA -----------------------------------------------


def test_chained_qa_does_not_read_jira_nor_structure(tmp_path: Path) -> None:
    """T-54 · criterio 2: en el hilo de QA no se llama a get_issue y solo a GENERATE_TESTS."""
    chain = _Chain(tmp_path, "live")
    handoff = chain.approved_story()
    start = take_handoff(chain.store, QUIM, handoff.id)
    tracker = chain.container.issue_tracker
    seen: list[str] = []
    original = tracker.get_issue

    def spy(key: str) -> Any:
        seen.append(key)
        return original(key)

    tracker.get_issue = spy  # type: ignore[method-assign]
    before = len(chain.llm().calls)

    chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]
    chain.graph.invoke(_approve(chain.graph, start.config), start.config)

    assert seen == []
    qa_calls = chain.llm().calls[before:]
    assert [c["task"] for c in qa_calls] == [TaskType.GENERATE_TESTS]
    assert [c["schema"] for c in qa_calls] == [TestSuite]
    # Ninguna versión de partida guardada: no hubo structure_story.
    artifact = _qa_artifact(chain, start)
    assert (chain.container.state_store.load(str(artifact.id)) or {}).get("baseline") is None


def test_chained_qa_jira_context_is_empty_and_source_story_from_server(tmp_path: Path) -> None:
    """T-54 · criterio 2/8: jira_context vacío; source_story es la HU de la entrega."""
    chain = _Chain(tmp_path, "live")
    handoff = chain.approved_story()
    start = take_handoff(chain.store, QUIM, handoff.id)

    chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    values = chain.graph.get_state(start.config).values
    assert values["jira_context"] == []
    assert values["source_story"] == handoff.story


# --- 8 · RAG con el texto de la HU ------------------------------------------------------------


def test_chained_qa_queries_rag_with_story_text(tmp_path: Path) -> None:
    """T-54 · criterio 8: sin incidencia de Jira, el RAG se consulta con título y descripción."""
    chain = _Chain(tmp_path, "live")
    handoff = chain.approved_story()
    start = take_handoff(chain.store, QUIM, handoff.id)
    embeddings = chain.container.embeddings
    queries: list[str] = []
    original = embeddings.embed

    def spy(texts: list[str]) -> list[list[float]]:
        queries.extend(texts)
        return original(texts)

    embeddings.embed = spy  # type: ignore[method-assign]

    chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    expected = f"{handoff.story.title}. {handoff.story.description}"
    assert expected in queries
    values = chain.graph.get_state(start.config).values
    assert values["rag_context"]
    assert values["jira_context"] == []
    # El texto de consulta no se guarda en el origen del estado.
    assert "text" not in values["origin"]


# --- 3 · simulación: HU sin publicar ----------------------------------------------------------


def _simulated_review(tmp_path: Path) -> tuple[_Chain, Handoff, QaStart, dict[str, Any]]:
    chain = _Chain(tmp_path, "simulation")
    handoff = chain.approved_story()
    start = take_handoff(chain.store, QUIM, handoff.id)
    result = chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]
    return chain, handoff, start, result["__interrupt__"][0].value


def test_simulated_chain_suite_has_unpublished_key_and_empty_plan(tmp_path: Path) -> None:
    """T-54 · criterio 3: entrega sin clave → suite «SIN-CLAVE» y plan vacío."""
    _chain, handoff, start, payload = _simulated_review(tmp_path)

    assert handoff.story_key is None
    assert "key" not in start.state["origin"]
    assert payload["artifact"]["content"]["story_jira_key"] == UNPUBLISHED_STORY_KEY
    assert payload["artifact"]["origin_key"] is None
    assert payload["plan"] == []


def test_simulated_chain_conversation_title_has_project_and_no_key(tmp_path: Path) -> None:
    """T-54 · T-52: la conversación de QA sin clave se titula con el flujo y el proyecto."""
    chain, _handoff, start, _payload = _simulated_review(tmp_path)

    summary = chain.container.conversations.get(_thread(start.config))

    assert summary is not None
    assert (summary.mode, summary.origin_key, summary.username) == ("qa", None, QUIM.username)
    assert summary.title == "Preparar pruebas de · DEMO"
    assert summary.status == "in_review"


def test_simulated_chain_strips_starting_jira_key_from_story(tmp_path: Path) -> None:
    """T-54 · criterio 3 (límite): la HU entregada con jira_key de partida no lo transmite."""
    store = InMemoryHandoffStore()
    container = fake_container(tmp_path, publish_mode="simulation")
    graph = build_graph(container, handoffs=store)
    handoff = store.create(
        Handoff(
            id=secrets.token_hex(16),
            artifact_id=uuid4(),
            version=2,
            project_key="DEMO",
            story_key=None,
            title="Renovar un préstamo",
            story=dataset.renewal_story(jira_key="DEMO-3"),
            from_user=ANA.username,
            from_thread_id=str(uuid4()),
            created_at=datetime.now(UTC),
        )
    )
    start = take_handoff(store, QUIM, handoff.id)

    result = graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    content = result["__interrupt__"][0].value["artifact"]["content"]
    assert content["story_jira_key"] == UNPUBLISHED_STORY_KEY


def test_simulated_chain_approve_is_rejected_without_recording(tmp_path: Path) -> None:
    """T-54 · criterio 3: aprobar → error UNPUBLISHED_STORY, sin aprobación ni auditoría."""
    chain, _handoff, start, _payload = _simulated_review(tmp_path)
    artifact = _qa_artifact(chain, start)

    chain.graph.invoke(_approve(chain.graph, start.config), start.config)

    payload = _pending(chain.graph, start.config)
    assert payload["error"] == UNPUBLISHED_STORY
    assert chain.container.approvals._approvals.get((str(artifact.id), artifact.version)) is None
    actions = [e.action for e in chain.container.audit.entries(artifact.id)]  # type: ignore[attr-defined]
    assert actions == ["create"]
    assert _qa_artifact(chain, start).status is ArtifactStatus.IN_REVIEW
    row = chain.container.conversations.get(_thread(start.config))
    assert row is not None and row.status == "in_review"
    assert chain.container.test_management.publish_calls == 0  # type: ignore[attr-defined]


@pytest.mark.parametrize("publish_mode", ["simulation", "live"])
def test_publish_node_with_manipulated_state_and_no_key_raises(
    tmp_path: Path, publish_mode: str
) -> None:
    """T-54 · criterio 3: estado manipulado (approve, APPROVED, sin clave) → PublishError."""
    chain, _handoff, start, _payload = _simulated_review(tmp_path)
    state = dict(chain.graph.get_state(start.config).values)
    state["artifact"] = _qa_artifact(chain, start).model_copy(
        update={"status": ArtifactStatus.APPROVED}
    )
    state["decision"] = "approve"
    container = chain.container
    if publish_mode == "live":
        container = fake_container(
            tmp_path,
            publish_mode="live",
            state_store=chain.container.state_store,
            test_management=chain.container.test_management,
        )

    with pytest.raises(PublishError) as exc_info:
        GraphNodes(container, chain.store).publish(state, start.config)  # type: ignore[arg-type]

    assert str(exc_info.value) == UNPUBLISHED_STORY
    assert container.test_management.publish_calls == 0  # type: ignore[attr-defined]


# --- 7 · el grafo no se fía del estado --------------------------------------------------------


def _assert_nothing_generated(chain: _Chain, before: int, thread_id: str) -> None:
    assert len(chain.llm().calls) == before
    assert chain.container.conversations.get(thread_id) is None
    created = [
        e
        for e in chain.container.audit.recorded  # type: ignore[attr-defined]
        if e.action == "create" and e.user != ANA.username
    ]
    assert created == []


def test_graph_rejects_handoff_taken_by_another_user(tmp_path: Path) -> None:
    """T-54 · criterio 7: entrega recogida por otra persona → HandoffError, nada generado."""
    chain = _Chain(tmp_path, "live")
    handoff = chain.approved_story()
    take_handoff(chain.store, QUIM, handoff.id)
    config = new_conversation_config(ROC.username)
    state = initial_state(
        ROC.username, "qa", {"kind": "story", "key": "DEMO-3"}, handoff_id=handoff.id
    )
    before = len(chain.llm().calls)

    with pytest.raises(HandoffError):
        chain.graph.invoke(state, config)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, before, _thread(config))


def test_graph_rejects_handoff_from_another_thread(tmp_path: Path) -> None:
    """T-54 · criterio 7: la misma persona en otro hilo → HandoffError."""
    chain = _Chain(tmp_path, "live")
    start = take_handoff(chain.store, QUIM, chain.approved_story().id)
    other = new_conversation_config(QUIM.username)
    before = len(chain.llm().calls)

    with pytest.raises(HandoffError):
        chain.graph.invoke(start.state, other)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, before, _thread(other))


def test_graph_rejects_handoff_not_taken(tmp_path: Path) -> None:
    """T-54 · criterio 7: entrega pendiente (no recogida) → HandoffError."""
    chain = _Chain(tmp_path, "live")
    handoff = chain.approved_story()
    config = new_conversation_config(QUIM.username)
    state = initial_state(
        QUIM.username, "qa", {"kind": "story", "key": "DEMO-3"}, handoff_id=handoff.id
    )
    before = len(chain.llm().calls)

    with pytest.raises(HandoffError):
        chain.graph.invoke(state, config)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, before, _thread(config))
    assert chain.store.get(handoff.id).status == "pending"  # type: ignore[union-attr]


@pytest.mark.parametrize("handoff_id", [secrets.token_hex(16), "no-es-un-id"])
def test_graph_rejects_unknown_or_malformed_handoff(tmp_path: Path, handoff_id: str) -> None:
    """T-54 · criterio 7: entrega inexistente o con formato no válido → HandoffError."""
    chain = _Chain(tmp_path, "live")
    config = new_conversation_config(QUIM.username)
    state = initial_state(
        QUIM.username, "qa", {"kind": "story", "key": "DEMO-3"}, handoff_id=handoff_id
    )

    with pytest.raises(HandoffError):
        chain.graph.invoke(state, config)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, 0, _thread(config))


def test_graph_rejects_manipulated_story_key(tmp_path: Path) -> None:
    """T-54 · criterio 7: clave del origen distinta de la de la entrega → NotFoundError."""
    chain = _Chain(tmp_path, "live")
    start = take_handoff(chain.store, QUIM, chain.approved_story().id)
    start.state["origin"]["key"] = "DEMO-4"
    before = len(chain.llm().calls)

    with pytest.raises(NotFoundError):
        chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, before, _thread(start.config))


def test_graph_rejects_key_added_to_unpublished_handoff(tmp_path: Path) -> None:
    """T-54 · criterio 7: añadir una clave a una entrega sin publicar → NotFoundError."""
    chain = _Chain(tmp_path, "simulation")
    start = take_handoff(chain.store, QUIM, chain.approved_story().id)
    start.state["origin"]["key"] = "DEMO-3"
    before = len(chain.llm().calls)

    with pytest.raises(NotFoundError):
        chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, before, _thread(start.config))


def test_graph_rejects_manipulated_project(tmp_path: Path) -> None:
    """T-54 · criterio 7: proyecto del origen distinto del de la entrega → NotFoundError."""
    chain = _Chain(tmp_path, "simulation")
    start = take_handoff(chain.store, QUIM, chain.approved_story().id)
    start.state["origin"]["project"] = "OTRO"
    before = len(chain.llm().calls)

    with pytest.raises(NotFoundError):
        chain.graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, before, _thread(start.config))


def test_graph_without_handoff_store_fails_closed(tmp_path: Path) -> None:
    """T-54 · criterio 7: build_graph sin `handoffs` → la QA encadenada falla (HandoffError)."""
    chain = _Chain(tmp_path, "live")
    start = take_handoff(chain.store, QUIM, chain.approved_story().id)
    graph = build_graph(chain.container)
    before = len(chain.llm().calls)

    with pytest.raises(HandoffError):
        graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    _assert_nothing_generated(chain, before, _thread(start.config))


@pytest.mark.parametrize(
    "config",
    [None, {}, {"configurable": {}}, {"configurable": {"thread_id": "hilo con espacios"}}],
    ids=["none", "empty", "no_thread", "bad_thread"],
)
def test_load_origin_without_valid_thread_id_raises(tmp_path: Path, config: Any) -> None:
    """T-54 · criterio 7: sin thread_id (o no válido) → NotFoundError y sin fila."""
    chain = _Chain(tmp_path, "live")
    start = take_handoff(chain.store, QUIM, chain.approved_story().id)
    rows = dict(chain.container.conversations.rows)  # type: ignore[attr-defined]

    with pytest.raises(NotFoundError):
        GraphNodes(chain.container, chain.store).load_origin(start.state, config)

    assert chain.container.conversations.rows == rows  # type: ignore[attr-defined]


def test_load_origin_rejects_other_actor_in_config(tmp_path: Path) -> None:
    """T-54 · criterio 7: `configurable.user` distinto del dueño del estado → NotFoundError."""
    chain = _Chain(tmp_path, "live")
    start = take_handoff(chain.store, QUIM, chain.approved_story().id)
    config = {"configurable": {**start.config["configurable"], "user": ROC.username}}  # type: ignore[dict-item]

    with pytest.raises(NotFoundError):
        GraphNodes(chain.container, chain.store).load_origin(start.state, config)  # type: ignore[arg-type]


def test_load_origin_ignores_source_story_injected_in_state(tmp_path: Path) -> None:
    """T-54 · criterio 7 (seguridad): la source_story del estado se sustituye por la real."""
    chain = _Chain(tmp_path, "live")
    handoff = chain.approved_story()
    start = take_handoff(chain.store, QUIM, handoff.id)
    injected = dataset.renewal_story().model_copy(update={"title": "HU inyectada ficticia"})
    state = {**start.state, "source_story": injected}

    update = GraphNodes(chain.container, chain.store).load_origin(state, start.config)  # type: ignore[arg-type]

    assert update["source_story"] == handoff.story
    assert update["jira_context"] == []


def test_injected_source_story_without_handoff_is_ignored(tmp_path: Path) -> None:
    """T-54 · seguridad: en una QA normal, una `source_story` metida en el estado no se usa."""
    chain = _Chain(tmp_path, "live")
    config = new_conversation_config(QUIM.username)
    injected = dataset.renewal_story().model_copy(update={"title": "HU inyectada ficticia"})
    state = {
        **initial_state(QUIM.username, "qa", {"kind": "story", "key": "DEMO-3"}),
        "source_story": injected,
    }

    chain.graph.invoke(state, config)  # type: ignore[arg-type]

    tasks = [call["task"] for call in chain.llm().calls]
    # Camino normal: estructura la HU de Jira (versión de partida) antes de generar la suite.
    assert TaskType.EVOLVE_STORY in tasks and TaskType.GENERATE_TESTS in tasks
    for call in chain.llm().calls:
        assert all("HU inyectada ficticia" not in m.content for m in call["messages"])


def test_generate_rejects_origin_key_altered_after_load(tmp_path: Path) -> None:
    """T-54 · seguridad: al iterar, una clave puesta a mano en el origen no cambia el destino."""
    chain, _handoff, start, _payload = _simulated_review(tmp_path)
    state = chain.graph.get_state(start.config).values
    altered = {**state, "origin": {**state["origin"], "key": "DEMO-2"}}
    before = len(chain.llm().calls)

    with pytest.raises(NotFoundError):
        GraphNodes(chain.container, chain.store).generate(altered, start.config)  # type: ignore[arg-type]

    assert len(chain.llm().calls) == before


def test_empty_handoff_id_fails_closed(tmp_path: Path) -> None:
    """T-54 · seguridad: un `handoff_id` vacío no se toma por «sin entrega»: falla cerrado."""
    chain = _Chain(tmp_path, "live")
    config = new_conversation_config(QUIM.username)
    state = initial_state(QUIM.username, "qa", {"kind": "story", "project": "DEMO"}, handoff_id="")

    with pytest.raises(HandoffError):
        chain.graph.invoke(state, config)  # type: ignore[arg-type]

    assert chain.llm().calls == []


# --- validate_origin con handoff_id -----------------------------------------------------------


def _state(mode: str, origin: dict[str, Any]) -> Any:
    origin = dict(origin)
    handoff_id = origin.pop("handoff_id", None)
    return {
        **initial_state("persona-ficticia", mode, {"kind": "story", "key": "DEMO-3"}),
        "origin": origin,
        "handoff_id": handoff_id,
    }  # type: ignore[arg-type]


def test_validate_origin_rejects_handoff_in_functional_mode() -> None:
    """T-54 · criterio 7: handoff_id en modo functional → ValueError."""
    origin = {"kind": "story", "key": "DEMO-3", "project": "DEMO", "handoff_id": "a" * 32}

    with pytest.raises(ValueError, match="QA"):
        validate_origin(_state("functional", origin))


@pytest.mark.parametrize("kind", ["epic", "need"])
def test_validate_origin_rejects_handoff_with_non_story_kind(kind: str) -> None:
    """T-54 · criterio 7: handoff_id con kind distinto de story → ValueError."""
    origin = {"kind": kind, "key": "DEMO-1", "project": "DEMO", "text": "x", "handoff_id": "a" * 32}

    with pytest.raises(ValueError):
        validate_origin(_state("qa", origin))


def test_validate_origin_story_without_key_requires_handoff() -> None:
    """T-54 · criterio 7: story sin clave solo es válida con handoff_id."""
    with pytest.raises(ValueError, match="clave de Jira"):
        validate_origin(_state("qa", {"kind": "story", "project": "DEMO"}))

    validate_origin(_state("qa", {"kind": "story", "project": "DEMO", "handoff_id": "a" * 32}))


def test_validate_origin_handoff_still_checks_project_and_key() -> None:
    """T-54 · criterio 7 (límite): con handoff_id siguen las reglas de proyecto y clave."""
    with pytest.raises(ValueError, match="proyecto"):
        validate_origin(_state("qa", {"kind": "story", "handoff_id": "a" * 32}))
    with pytest.raises(ValueError, match="no pertenece"):
        validate_origin(
            _state("qa", {"kind": "story", "key": "OTRO-1", "project": "DEMO", "handoff_id": "a"})
        )


def test_initial_state_sets_handoff_id_only_when_given() -> None:
    """T-54 · criterio 6/7: initial_state añade handoff_id solo si se pasa."""
    plain = initial_state(QUIM.username, "qa", {"kind": "story", "key": "DEMO-3"})
    chained = initial_state(
        QUIM.username, "qa", {"kind": "story", "project": "DEMO"}, handoff_id="b" * 32
    )

    assert plain["handoff_id"] is None
    assert chained["handoff_id"] == "b" * 32
    # Nunca en `origin`: ese diccionario también llega de la API.
    assert "handoff_id" not in plain["origin"] and "handoff_id" not in chained["origin"]


# --- 11 · checkpointer ------------------------------------------------------------------------


def test_source_story_survives_checkpointer_and_resume(tmp_path: Path) -> None:
    """T-54 · criterio 11: source_story se serializa con memory_checkpointer y se reanuda."""
    store = InMemoryHandoffStore()
    container = fake_container(tmp_path, publish_mode="live")
    checkpointer = memory_checkpointer()
    graph = build_graph(container, checkpointer, handoffs=store)
    config = new_conversation_config(ANA.username)
    graph.invoke(initial_state(ANA.username, "functional", STORY_ORIGIN), config)  # type: ignore[arg-type]
    graph.invoke(_approve(graph, config), config)
    handoff = hand_off(container, graph, store, ANA, _thread(config))
    start = take_handoff(store, QUIM, handoff.id)
    graph.invoke(start.state, start.config)  # type: ignore[arg-type]

    # Grafo nuevo sobre el mismo checkpointer: el estado se lee deserializado.
    resumed = build_graph(container, checkpointer, handoffs=store)
    values = resumed.get_state(start.config).values
    assert isinstance(values["source_story"], UserStory)
    assert values["source_story"] == handoff.story

    final = resumed.invoke(_approve(resumed, start.config), start.config)
    assert final["artifact"].status is ArtifactStatus.PUBLISHED


def test_checkpoint_serializer_roundtrips_user_story() -> None:
    """T-54 · criterio 11: el serializador de tipos explícitos admite UserStory."""
    serde = checkpoint_serializer()
    story = dataset.renewal_story()

    restored = serde.loads_typed(serde.dumps_typed({"source_story": story}))

    assert restored["source_story"] == story
    assert isinstance(restored["source_story"], UserStory)


def test_qa_without_handoff_keeps_reading_jira(tmp_path: Path) -> None:
    """T-54 (regresión): QA normal (sin entrega) sigue leyendo Jira y no tiene source_story."""
    container = fake_container(tmp_path)
    graph = build_graph(container, handoffs=InMemoryHandoffStore())
    config = {"configurable": {"thread_id": str(UUID(int=7))}}

    graph.invoke(initial_state(QUIM.username, "qa", STORY_ORIGIN), config)  # type: ignore[arg-type]

    values = graph.get_state(config).values
    assert values["jira_context"]
    assert values.get("source_story") is None
    assert values["artifact"].content.story_jira_key == "DEMO-3"
