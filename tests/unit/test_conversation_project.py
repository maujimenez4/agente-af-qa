"""Proyecto de Jira en la conversación: estado, validación, aprobación y publicación (T-50).

Cubre RF-02 (cada conversación trabaja en un proyecto), RF-04 (lo aprobado es lo publicado,
también el proyecto) y RF-14 (la necesidad busca en el proyecto de la conversación) sobre
`core/graph/state.py`, `core/graph/nodes.py` y `core/approvals.py`. Solo fakes de
`tests/fakes/`; proyectos y textos ficticios (DEMO, OTRO).
"""

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.errors import PublishError
from core.approvals import ApprovalError, ApprovalLedger, PublishTarget, review_fingerprint
from core.artifact_state import InMemoryArtifactStateStore
from core.audit import InMemoryAuditTrail
from core.container import Container
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import GraphNodes, _check_project, _target, validate_origin
from core.graph.state import AgentState
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker

AF_USER = "af-demo"
THREAD = "hilo-ficticio-t50"
NEED_TEXT = "Avisar por correo antes del vencimiento del préstamo (texto ficticio)."


# --- utilidades --------------------------------------------------------------------------


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"hilo-{uuid4()}"}}


def _need(project: str = "DEMO") -> Origin:
    return {"kind": "need", "text": NEED_TEXT, "project": project}


def _state(origin: dict[str, Any], mode: str = "functional") -> AgentState:
    """Estado construido a mano, sin pasar por `initial_state` (como si se hubiera alterado)."""
    return AgentState(
        user=AF_USER,
        mode=mode,  # type: ignore[typeddict-item]
        origin=origin,  # type: ignore[typeddict-item]
        jira_context=[],
        rag_context=[],
        artifact=None,
        feedback=[],
        decision=None,
        published_keys=[],
        errors=[],
    )


def _publish_target(
    origin_kind: str = "story",
    origin_key: str | None = "DEMO-3",
    project_key: str = "DEMO",
    mode: str = "functional",
) -> PublishTarget:
    return PublishTarget(
        mode=mode,
        origin_kind=origin_kind,
        origin_key=origin_key,
        project_key=project_key,
        user=AF_USER,
        thread_id=THREAD,
    )


def _artifact() -> Artifact:
    return Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.IN_REVIEW,
        version=1,
        origin_key="DEMO-3",
        content=dataset.renewal_story(),
        created_by=AF_USER,
    )


def _start(graph: CompiledStateGraph, config: dict[str, Any], origin: Origin) -> dict[str, Any]:
    return graph.invoke(initial_state(AF_USER, "functional", origin), config)


def _interrupt(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[0].value


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    fingerprint = _interrupt(graph, config)["fingerprint"]
    return Command(resume={"decision": "approve", "fingerprint": fingerprint})


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _audit(container: Container) -> InMemoryAuditTrail:
    assert isinstance(container.audit, InMemoryAuditTrail)
    return container.audit


# --- initial_state -------------------------------------------------------------------------


def test_initial_state_derives_project_from_origin_key() -> None:
    """RF-02 · T-50: con clave de origen, el proyecto es el prefijo de la clave."""
    origin: Origin = {"kind": "story", "key": "DEMO-3"}

    state = initial_state(AF_USER, "functional", origin)

    assert state["origin"] == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    assert "project" not in origin  # copia el origen, no lo modifica


def test_initial_state_key_of_other_project_overrides_given_project() -> None:
    """RF-02 · T-50: una clave de otro proyecto prevalece sobre el `project` dado."""
    origin: Origin = {"kind": "epic", "key": "OTRO-7", "project": "DEMO"}

    state = initial_state(AF_USER, "functional", origin)

    assert state["origin"]["project"] == "OTRO"
    assert origin["project"] == "DEMO"


def test_initial_state_need_keeps_given_project() -> None:
    """RF-02 · T-50: una necesidad conserva el proyecto elegido (no hay clave)."""
    state = initial_state(AF_USER, "functional", _need("OTRO"))

    assert state["origin"]["project"] == "OTRO"


def test_initial_state_need_without_project_leaves_it_missing() -> None:
    """T-50 (límite): sin clave ni proyecto, `initial_state` no inventa uno."""
    state = initial_state(AF_USER, "functional", {"kind": "need", "text": NEED_TEXT})

    assert "project" not in state["origin"]


def test_initial_state_invalid_key_does_not_derive_project() -> None:
    """T-50 (límite): una clave no válida (minúsculas) no fija proyecto; la rechaza validate."""
    state = initial_state(AF_USER, "functional", {"kind": "story", "key": "demo-3"})

    assert "project" not in state["origin"]


# --- validate_origin -----------------------------------------------------------------------


def test_validate_origin_need_without_project_is_rejected() -> None:
    """RF-02 · T-50 (negativo): una necesidad sin proyecto → ValueError para la UI."""
    with pytest.raises(ValueError, match="Elige el proyecto de Jira de la conversación"):
        validate_origin(_state({"kind": "need", "text": NEED_TEXT}))


def test_validate_origin_need_with_empty_project_is_rejected() -> None:
    """RF-02 · T-50 (límite): proyecto vacío equivale a no elegido."""
    with pytest.raises(ValueError, match="Elige el proyecto"):
        validate_origin(_state({"kind": "need", "text": NEED_TEXT, "project": ""}))


@pytest.mark.parametrize("project", ["demo", "D", "1DEMO", "DEMO-1", "DE MO", " DEMO"])
def test_validate_origin_rejects_invalid_project_format(project: str) -> None:
    """RF-14 · T-50 (negativo): proyecto con formato no válido → ValueError."""
    with pytest.raises(ValueError, match="Clave de proyecto no válida"):
        validate_origin(_state({"kind": "need", "text": NEED_TEXT, "project": project}))


@pytest.mark.parametrize("kind", ["story", "epic"])
def test_validate_origin_rejects_key_of_other_project(kind: str) -> None:
    """RF-02 · T-50 (negativo): clave de otro proyecto en un estado alterado → ValueError."""
    with pytest.raises(ValueError, match="La incidencia OTRO-3 no pertenece al proyecto DEMO"):
        validate_origin(_state({"kind": kind, "key": "OTRO-3", "project": "DEMO"}))


def test_validate_origin_rejects_lowercase_key() -> None:
    """RF-14 · T-50 (negativo): la clave en minúsculas no se normaliza en el grafo."""
    with pytest.raises(ValueError, match="Clave de Jira no válida"):
        validate_origin(_state({"kind": "story", "key": "demo-3", "project": "DEMO"}))


def test_validate_origin_accepts_key_of_the_project() -> None:
    """RF-02 · T-50: clave y proyecto coherentes → sin error."""
    validate_origin(_state({"kind": "epic", "key": "DEMO-1", "project": "DEMO"}))
    validate_origin(_state(dict(_need("OTRO"))))


def test_graph_need_without_project_fails_without_reading_or_writing(tmp_path: Path) -> None:
    """RF-02 · T-50 (negativo): el grafo no arranca una necesidad sin proyecto."""
    container = fake_container(tmp_path)
    graph = build_graph(container)

    with pytest.raises(ValueError, match="Elige el proyecto"):
        _start(graph, _config(), {"kind": "need", "text": NEED_TEXT})

    assert _tracker(container).writes == []
    assert container.llm.calls == []  # type: ignore[attr-defined]


def test_graph_lowercase_story_key_is_rejected(tmp_path: Path) -> None:
    """RF-14 · T-50 (negativo): `demo-3` se rechaza al cargar el origen."""
    container = fake_container(tmp_path)

    with pytest.raises(ValueError, match="Clave de Jira no válida"):
        _start(build_graph(container), _config(), {"kind": "story", "key": "demo-3"})

    assert _tracker(container).writes == []


# --- PublishTarget y ApprovalLedger --------------------------------------------------------


def test_target_takes_project_from_origin() -> None:
    """RF-04 · T-50: la operación que se aprueba lleva el proyecto de la conversación."""
    state = initial_state(AF_USER, "functional", _need("OTRO"))

    target = _target(state, {"configurable": {"thread_id": THREAD}})

    assert target.project_key == "OTRO"
    assert target.origin_key is None


def test_review_fingerprint_changes_when_project_changes() -> None:
    """RF-04 · T-50: el proyecto entra en la huella que aprueba la persona."""
    artifact = _artifact()
    demo = _publish_target(origin_kind="need", origin_key=None, project_key="DEMO")
    other = replace(demo, project_key="OTRO")

    assert review_fingerprint(artifact, demo) != review_fingerprint(artifact, other)
    assert review_fingerprint(artifact, demo) == review_fingerprint(artifact, replace(demo))


def test_offer_with_other_project_between_iterations_is_rejected() -> None:
    """RF-04 · T-50 (negativo): el proyecto no puede cambiar entre iteraciones."""
    artifact = _artifact()
    target = _publish_target()
    ledger = ApprovalLedger()
    ledger.offer(artifact, target)

    with pytest.raises(ApprovalError, match="no puede cambiar entre iteraciones"):
        ledger.offer(artifact, replace(target, project_key="OTRO"))


def test_approval_for_other_project_is_not_found() -> None:
    """RF-04 · T-50 (negativo): una aprobación de DEMO no vale para publicar en OTRO."""
    artifact = _artifact()
    target = _publish_target()
    ledger = ApprovalLedger()
    ledger.offer(artifact, target)
    ledger.record(artifact, target)

    assert ledger.find(artifact, target) is not None
    assert ledger.find(artifact, replace(target, project_key="OTRO")) is None


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (
            _publish_target(),
            {
                "operation": "actualizar HU",
                "project": "DEMO",
                "jira_key": "DEMO-3",
                "epic_key": None,
            },
        ),
        (
            _publish_target("epic", "OTRO-1", "OTRO"),
            {"operation": "crear HU", "project": "OTRO", "jira_key": None, "epic_key": "OTRO-1"},
        ),
        (
            _publish_target("need", None, "OTRO"),
            {"operation": "crear HU", "project": "OTRO", "jira_key": None, "epic_key": None},
        ),
        (
            _publish_target(mode="qa"),
            {
                "operation": "publicar casos de prueba",
                "project": "DEMO",
                "jira_key": "DEMO-3",
                "epic_key": None,
            },
        ),
    ],
    ids=["evolucion", "epica", "necesidad", "qa"],
)
def test_describe_includes_project(target: PublishTarget, expected: dict[str, Any]) -> None:
    """RF-04 · T-50: la UI muestra el proyecto de la operación antes de aprobar."""
    assert target.describe() == expected


def _ledger_with_stored_target(target_data: dict[str, Any]) -> tuple[ApprovalLedger, Artifact]:
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    store.save(
        str(artifact.id),
        {"ledger": {"target": target_data, "offer": None, "approvals": []}},
    )
    return ApprovalLedger(store=store), artifact


def _legacy_target() -> dict[str, Any]:
    """Destino persistido antes de T-50: sin `project_key`."""
    return {
        "mode": "functional",
        "origin_kind": "story",
        "origin_key": "DEMO-3",
        "user": AF_USER,
        "thread_id": THREAD,
    }


def test_persisted_ledger_without_project_key_fails_closed() -> None:
    """RF-04 · T-50 (error): un registro sin `project_key` → ApprovalError, sin sobrescribirlo."""
    ledger, artifact = _ledger_with_stored_target(_legacy_target())
    store = ledger.store
    assert store is not None
    before = store.load(str(artifact.id))

    with pytest.raises(ApprovalError, match="está dañado"):
        ledger.offer(artifact, _publish_target())
    with pytest.raises(ApprovalError, match="está dañado"):
        ledger.find(artifact, _publish_target())

    assert store.load(str(artifact.id)) == before


def test_persisted_approval_without_project_key_fails_closed() -> None:
    """RF-04 · T-50 (error): una aprobación guardada sin `project_key` también falla cerrado."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    current = _publish_target()
    ledger = ApprovalLedger(store=store)
    ledger.offer(artifact, current)
    ledger.record(artifact, current)
    state = store.load(str(artifact.id))
    assert state is not None
    del state["ledger"]["approvals"][0]["target"]["project_key"]
    store.save(str(artifact.id), state)

    with pytest.raises(ApprovalError, match="está dañado"):
        ApprovalLedger(store=store).find(artifact, current)


# --- _check_project ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        _publish_target("story", "DEMO-3", "DEMO"),
        _publish_target("epic", "OTRO-1", "OTRO"),
        _publish_target("need", None, "OTRO"),
    ],
    ids=["evolucion", "epica", "necesidad"],
)
def test_check_project_accepts_coherent_target(target: PublishTarget) -> None:
    """RF-04 · T-50: clave de origen del proyecto aprobado (o sin clave) → se puede publicar."""
    _check_project(target)


@pytest.mark.parametrize("origin_key", ["OTRO-3", "DEMOX-3"])
def test_check_project_rejects_origin_of_other_project(origin_key: str) -> None:
    """RF-04 · T-50 (negativo): la clave de origen de otro proyecto → PublishError."""
    with pytest.raises(PublishError, match="no pertenece al proyecto aprobado \\(DEMO\\)"):
        _check_project(_publish_target("story", origin_key, "DEMO"))


@pytest.mark.parametrize("project", ["", "demo", "D", "DEMO-3"])
def test_check_project_rejects_invalid_project(project: str) -> None:
    """RF-04 · T-50 (negativo): proyecto aprobado no válido → PublishError."""
    with pytest.raises(PublishError, match="proyecto de Jira válido"):
        _check_project(_publish_target("need", None, project))


def test_check_project_rejects_malformed_origin_key() -> None:
    """RF-04 · T-50 (negativo): clave de origen mal formada → PublishError (sin ValueError)."""
    with pytest.raises(PublishError, match="no pertenece al proyecto aprobado"):
        _check_project(_publish_target("story", "demo-3", "DEMO"))


# --- publish y plan -----------------------------------------------------------------------


def test_live_publish_creates_need_story_in_conversation_project(tmp_path: Path) -> None:
    """RF-02 · RF-04 · T-50: en live, la HU de una necesidad se crea en el proyecto elegido."""
    container = fake_container(tmp_path, publish_mode="live")
    graph = build_graph(container)
    config = _config()
    _start(graph, config, _need("OTRO"))

    assert _interrupt(graph, config)["target"]["project"] == "OTRO"
    final = graph.invoke(_approve(graph, config), config)

    writes = _tracker(container).writes
    assert writes[0][0] == "create_story"
    created = writes[0][1]
    assert created["project"] == "OTRO"
    assert created["key"].startswith("OTRO-")
    assert created["epic_key"] is None
    assert final["published_keys"][0] == created["key"]
    assert final["artifact"].status is ArtifactStatus.PUBLISHED


def test_simulated_plan_includes_conversation_project(tmp_path: Path) -> None:
    """RF-04 · T-50: el plan simulado indica el proyecto en la creación de la HU."""
    container = fake_container(tmp_path, publish_mode="simulation")
    graph = build_graph(container)
    config = _config()
    _start(graph, config, _need("OTRO"))
    final = graph.invoke(_approve(graph, config), config)

    plan = _audit(container).entries(final["artifact"].id)[-1].detail["plan"]

    assert plan[0] == {"op": "create_story", "project": "OTRO", "epic": ""}
    assert all("project" not in step for step in plan[1:] if step["op"] == "link")
    assert _tracker(container).writes == []


def test_publish_with_project_altered_in_state_is_rejected(tmp_path: Path) -> None:
    """RF-04 · T-50 (negativo): cambiar el proyecto en el estado tras aprobar no publica."""
    simulated = fake_container(tmp_path, publish_mode="simulation")
    graph = build_graph(simulated)
    config = _config()
    _start(graph, config, _need("DEMO"))
    graph.invoke(_approve(graph, config), config)  # la simulación gasta la aprobación (PA-41)
    live = fake_container(
        tmp_path,
        publish_mode="live",
        state_store=simulated.state_store,
        issue_tracker=simulated.issue_tracker,
    )
    state = dict(graph.get_state(config).values)
    target = _target(state, config, live.require_actor)  # type: ignore[arg-type]
    live.approvals.offer(state["artifact"], target)  # aprobación vigente con el modo real
    live.approvals.record(state["artifact"], target)
    state["origin"] = {**state["origin"], "project": "OTRO"}

    with pytest.raises(PublishError, match="No consta una aprobación"):
        GraphNodes(live).publish(state, config)  # type: ignore[arg-type]

    assert _tracker(live).writes == []


# --- retrieve_context ----------------------------------------------------------------------


class SearchSpyTracker(FakeIssueTracker):
    def __init__(self) -> None:
        super().__init__()
        self.jqls: list[str] = []

    def search(self, jql: str, limit: int = 50) -> Any:
        self.jqls.append(jql)
        return super().search(jql, limit)


def test_retrieve_context_for_need_searches_in_origin_project(tmp_path: Path) -> None:
    """RF-14 · T-50: la búsqueda de texto de una necesidad usa el proyecto del origen."""
    tracker = SearchSpyTracker()
    nodes = GraphNodes(fake_container(tmp_path, issue_tracker=tracker))
    state = initial_state(AF_USER, "functional", _need("OTRO"))
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    nodes.retrieve_context(state)

    assert tracker.jqls, "una necesidad con proyecto consulta Jira"
    assert all(jql.startswith('project = "OTRO"') for jql in tracker.jqls)
