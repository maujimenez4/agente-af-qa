"""Pruebas del grafo LangGraph de extremo a extremo con fakes (T-07 · CA-00-04).

Cubren la pausa en `human_review`, la reanudación (iterate/approve/discard), la regla de que
solo `publish` escribe en Jira y solo con artefactos APPROVED, la memoria (D-07, RF-38) y el
checkpointer en memoria. Todos los datos proceden del dataset sintético de `tests/fakes/`.
"""

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.event_hooks import register_serde_event_listener
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.errors import InvalidUpdateError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.errors import NotFoundError, PublishError
from core.approvals import ApprovalError
from core.container import Container
from core.graph import AgentState, Origin, build_graph, initial_state, memory_checkpointer
from core.graph.nodes import GraphNodes, _target
from schemas import test_case as tc
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import renewal_test_suite
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore

AF_USER = "af-demo"
QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
EPIC_ORIGIN: Origin = {"kind": "epic", "key": "DEMO-1"}
NEED_ORIGIN: Origin = {
    "kind": "need",
    "project": "DEMO",
    "text": "Avisar a la persona socia por correo tres días antes del vencimiento del préstamo.",
}
FEEDBACK = "Añade un criterio para el aviso de vencimiento (texto ficticio)."


# --- utilidades --------------------------------------------------------------------------


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path)


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"hilo-{uuid4()}"}}


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _testmgmt(container: Container) -> FakeTestManagement:
    assert isinstance(container.test_management, FakeTestManagement)
    return container.test_management


def _store(container: Container) -> FakeVectorStore:
    assert isinstance(container.vector_store, FakeVectorStore)
    return container.vector_store


def _memory_chunks(container: Container) -> list[str]:
    return sorted(
        chunk_id
        for chunk_id, chunk in _store(container).chunks.items()
        if chunk.metadata.get("category") == "memoria"
    )


def _start(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    mode: str = "functional",
    origin: Origin = STORY_ORIGIN,
    user: str = AF_USER,
) -> dict[str, Any]:
    return graph.invoke(initial_state(user, mode, origin), config)  # type: ignore[arg-type]


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    (pending,) = result["__interrupt__"]
    return pending.value


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    """Aprobación tal como la envía la UI: con la huella de la versión mostrada."""
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return Command(
        resume={"decision": "approve", "fingerprint": task.interrupts[0].value["fingerprint"]}
    )


def _run_to_publish(
    container: Container,
    mode: str = "functional",
    origin: Origin = STORY_ORIGIN,
    user: str = AF_USER,
) -> dict[str, Any]:
    graph = build_graph(container)
    config = _config()
    _start(graph, config, mode, origin, user)
    return graph.invoke(_approve(graph, config), config)


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[-1].value


def _rejected(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    command: Command,
    previous: dict[str, Any],
) -> dict[str, Any]:
    """T-51: una respuesta rechazada vuelve a pausar con la misma versión y huella y `error`."""
    payload = _payload(graph.invoke(command, config))
    assert payload["version"] == previous["version"]
    assert payload["fingerprint"] == previous["fingerprint"]
    assert isinstance(payload["error"], str) and payload["error"]
    assert _pending(graph, config)["error"] == payload["error"]
    return payload


def _assert_nothing_approved_or_written(
    container: Container, graph: CompiledStateGraph, config: dict[str, Any]
) -> None:
    """Principio 1: sin escrituras, sin memoria, sin approve auditado y sin aprobación vigente."""
    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0
    assert _memory_chunks(container) == []
    state = graph.get_state(config).values
    artifact = state["artifact"]
    assert artifact.status is not ArtifactStatus.APPROVED
    actions = [e.action for e in container.audit.entries(artifact.id)]
    assert "approve" not in actions and "publish" not in actions
    assert container.approvals.find(artifact, _target(state, config)) is None
    assert container.approvals.was_published(artifact) is False


def _assert_no_effects(container: Container, artifact: Artifact, *targets: Any) -> None:
    """Como la anterior, sin leer el estado del hilo (tras un ataque puede quedar inservible)."""
    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0
    assert _memory_chunks(container) == []
    actions = [e.action for e in container.audit.entries(artifact.id)]
    assert actions == ["create"]
    for target in targets:
        assert container.approvals.find(artifact, target) is None
    assert container.approvals.was_published(artifact) is False


def _resume_after_attack_does_not_publish(
    graph: CompiledStateGraph, config: dict[str, Any], fingerprint: str
) -> None:
    """Tras un ataque rechazado, el hilo falla cerrado: pausa con error o excepción."""
    try:
        result = graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": fingerprint}), config
        )
    except (InvalidUpdateError, ApprovalError):
        return  # el hilo falla cerrado: tampoco se publica nada
    assert "__interrupt__" in result


def _artifact(status: ArtifactStatus, content: UserStory | tc.TestSuite | None = None) -> Artifact:
    content = content or dataset.renewal_story()
    kind = ArtifactType.TEST_SUITE if isinstance(content, tc.TestSuite) else ArtifactType.USER_STORY
    return Artifact(
        id=uuid4(),
        type=kind,
        status=status,
        version=1,
        origin_key="DEMO-3",
        content=content,
        created_by=AF_USER,
    )


def _state(
    artifact: Artifact | None,
    decision: str | None = "approve",
    mode: str = "functional",
    origin: Origin = STORY_ORIGIN,
) -> AgentState:
    state = initial_state(AF_USER, mode, origin)  # type: ignore[arg-type]
    state["artifact"] = artifact
    state["decision"] = decision  # type: ignore[typeddict-item]
    return state


# --- 1 · iterar → aprobar → publicar → memorizar (HU existente) -------------------------------


def test_first_invocation_pauses_in_human_review_with_artifact_in_review(
    container: Container,
) -> None:
    """CA-00-04: la primera invocación se detiene en human_review con la propuesta v1."""
    graph = build_graph(container)
    config = _config()

    payload = _payload(_start(graph, config))

    assert payload["artifact"]["status"] == ArtifactStatus.IN_REVIEW.value
    assert payload["artifact"]["version"] == 1
    assert payload["artifact"]["type"] == ArtifactType.USER_STORY.value
    assert payload["artifact"]["content"]["jira_key"] == "DEMO-3"
    assert payload["impact"] is not None
    # T-51: la edición manual es una decisión más de la revisión (RF-32).
    assert payload["decisions"] == ["iterate", "edit", "approve", "discard"]
    assert graph.get_state(config).next == ("human_review",)


def test_resume_iterate_with_feedback_pauses_again_with_new_version(
    container: Container,
) -> None:
    """CA-00-04 · RF-20: iterar regenera con el feedback, misma identidad y versión + 1."""
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))

    second = _payload(
        graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    )

    assert second["artifact"]["id"] == first["artifact"]["id"]
    assert second["artifact"]["version"] == 2
    assert second["artifact"]["status"] == ArtifactStatus.IN_REVIEW.value
    state = graph.get_state(config).values
    assert state["feedback"] == [FEEDBACK]
    assert state["decision"] is None
    # El feedback llega al LLM en la regeneración.
    messages = container.llm.calls[-1]["messages"]  # type: ignore[attr-defined]
    assert any(FEEDBACK in m.content for m in messages if m.role == "user")
    assert _tracker(container).writes == []


def test_resume_iterate_with_blank_feedback_does_not_store_it(container: Container) -> None:
    """CA-00-04 (límite): un feedback en blanco no se añade al historial."""
    graph = build_graph(container)
    config = _config()
    _start(graph, config)

    graph.invoke(Command(resume={"decision": "iterate", "feedback": "   "}), config)

    assert graph.get_state(config).values["feedback"] == []


def test_full_story_flow_iterate_approve_publish_memorize(
    container: Container, tmp_path: Path
) -> None:
    """CA-00-04: iterar → aprobar → publicar (update + vínculo) → memorizar."""
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)

    final = graph.invoke(_approve(graph, config), config)

    assert "__interrupt__" not in final
    assert graph.get_state(config).next == ()
    artifact: Artifact = final["artifact"]
    assert artifact.status is ArtifactStatus.PUBLISHED
    assert artifact.version == 2
    assert final["published_keys"] == ["DEMO-3"]
    assert final["errors"] == []
    assert final["feedback"] == [FEEDBACK]

    tracker = _tracker(container)
    # Hasta T-21 el impacto solo trae el diff determinista: no hay HU afectadas que vincular.
    assert tracker.writes == [("update_story", {"key": "DEMO-3"})]
    comments = tracker.issues["DEMO-3"].comments
    assert any("Cambios propuestos por el agente y aprobados" in c for c in comments)
    # El diff ya no lo inventa el LLM: sale de diff_stories frente a la versión de Jira.
    assert not any("| title | Renovar | Renovar un préstamo |" in c for c in comments)

    memory_file = tmp_path / "DEMO-3.md"
    assert memory_file.exists()
    text = memory_file.read_text(encoding="utf-8")
    assert text.startswith("---\njira_key: DEMO-3\nartifact_type: user_story\nversion: 2\n---\n")

    assert _memory_chunks(container) == ["memoria-DEMO-3-0"]
    chunk = _store(container).chunks["memoria-DEMO-3-0"]
    assert chunk.document_id == "memoria-DEMO-3"
    assert chunk.metadata == {"category": "memoria", "related_key": "DEMO-3"}
    assert chunk.content == text


def test_republishing_same_story_reindexes_without_duplicates(
    container: Container, tmp_path: Path
) -> None:
    """RF-38 · CA-00-04: publicar dos veces la misma HU sustituye su memoria, no la duplica."""
    _run_to_publish(container)
    _run_to_publish(container)  # otro hilo, mismo contenedor

    assert _memory_chunks(container) == ["memoria-DEMO-3-0"]
    assert list(tmp_path.glob("*.md")) == [tmp_path / "DEMO-3.md"]
    # Los documentos del corpus siguen indexados.
    assert {"doc-reglamento-0", "doc-glosario-0"} <= set(_store(container).chunks)


def test_writes_happen_only_in_publish_node(container: Container) -> None:
    """Principio 1 · CA-00-04: ninguna escritura antes de publish ni después de él."""
    graph = build_graph(container)
    config = _config()
    tracker = _tracker(container)

    _start(graph, config)
    assert tracker.writes == []
    assert _testmgmt(container).publish_calls == 0

    writes_after: dict[str, int] = {}
    for update in graph.stream(_approve(graph, config), config, stream_mode="updates"):
        (node,) = update
        writes_after[node] = len(tracker.writes)

    assert list(writes_after) == ["human_review", "publish", "memorize"]
    assert writes_after["human_review"] == 0
    assert writes_after["publish"] == 1
    assert writes_after["memorize"] == 1


# --- 2 · épica y necesidad nueva --------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "expected_epic"), [(EPIC_ORIGIN, "DEMO-1"), (NEED_ORIGIN, None)]
)
def test_approve_new_story_creates_it_in_jira(
    container: Container, tmp_path: Path, origin: Origin, expected_epic: str | None
) -> None:
    """CA-00-04: desde épica o necesidad, aprobar crea la HU (con o sin épica padre)."""
    graph = build_graph(container)
    config = _config()
    payload = _payload(_start(graph, config, origin=origin))
    # T-21: una HU nueva también lleva impacto (sin diff) sobre las HU relacionadas.
    assert payload["impact"]["diffs"] == []
    assert payload["artifact"]["content"]["jira_key"] is None

    final = graph.invoke(_approve(graph, config), config)

    tracker = _tracker(container)
    (action, data), *links = tracker.writes
    assert action == "create_story"
    assert data["epic_key"] == expected_epic
    # RF-06: la HU creada se vincula a las HU afectadas (el fake propone DEMO-2).
    assert [w[0] for w in links] == ["link"] * len(links)
    assert all(w[1]["from"] == data["key"] and w[1]["to"] != expected_epic for w in links)
    new_key = data["key"]
    assert final["published_keys"] == [new_key]
    assert final["artifact"].content.jira_key == new_key
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert tracker.issues[new_key].parent_key == expected_epic
    assert (tmp_path / f"{new_key}.md").exists()
    assert _memory_chunks(container) == [f"memoria-{new_key}-0"]


# --- 3 · descartar --------------------------------------------------------------------------


def test_resume_discard_ends_without_writes_or_memory(container: Container, tmp_path: Path) -> None:
    """CA-00-04: descartar termina el grafo sin escribir en Jira ni generar memoria."""
    graph = build_graph(container)
    config = _config()
    _start(graph, config)

    final = graph.invoke(Command(resume={"decision": "discard"}), config)

    assert "__interrupt__" not in final
    assert graph.get_state(config).next == ()
    assert final["artifact"].status is ArtifactStatus.DISCARDED
    assert final["decision"] == "discard"
    assert final["published_keys"] == []
    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0
    assert list(tmp_path.glob("*.md")) == []
    assert _memory_chunks(container) == []


# --- 4 · publicar sin aprobación ------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact",
    [_artifact(ArtifactStatus.IN_REVIEW), _artifact(ArtifactStatus.DRAFT), None],
    ids=["in_review", "draft", "sin_artefacto"],
)
def test_publish_rejects_non_approved_artifact(
    container: Container, artifact: Artifact | None
) -> None:
    """Principio 1: publish exige un artefacto APPROVED; si no, PublishError sin escrituras."""
    with pytest.raises(PublishError, match="aprobados"):
        GraphNodes(container).publish(_state(artifact))

    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0


@pytest.mark.parametrize("decision", [None, "iterate", "discard"])
def test_publish_rejects_approved_artifact_without_explicit_decision(
    container: Container, decision: str | None
) -> None:
    """Principio 1: APPROVED sin decisión 'approve' del usuario → PublishError."""
    with pytest.raises(PublishError, match="confirmación explícita"):
        GraphNodes(container).publish(_state(_artifact(ArtifactStatus.APPROVED), decision))

    assert _tracker(container).writes == []


def test_publish_rejects_approved_test_suite_without_decision(container: Container) -> None:
    """Principio 1 (QA): una suite APPROVED sin 'approve' no llega a publish_suite."""
    state = _state(_artifact(ArtifactStatus.APPROVED, renewal_test_suite()), None, mode="qa")

    with pytest.raises(PublishError):
        GraphNodes(container).publish(state)

    assert _testmgmt(container).publish_calls == 0


def test_forced_approve_decision_on_paused_graph_fails_to_publish(
    container: Container,
) -> None:
    """Principio 1 · CA-00-04: forzar decision='approve' sin aprobar el artefacto no publica."""
    graph = build_graph(container)
    config = _config()
    _start(graph, config)

    graph.update_state(config, {"decision": "approve"}, as_node="human_review")
    assert graph.get_state(config).values["artifact"].status is ArtifactStatus.IN_REVIEW

    with pytest.raises(PublishError):
        graph.invoke(None, config)

    assert _tracker(container).writes == []
    assert _memory_chunks(container) == []


# --- 5 · modo QA ------------------------------------------------------------------------------


def test_qa_flow_publishes_suite_with_attachments_and_no_memory(
    container: Container, tmp_path: Path
) -> None:
    """CA-00-04 · D-09 · D-07: aprobar publica la suite y sus adjuntos; no genera memoria."""
    graph = build_graph(container)
    config = _config()
    payload = _payload(_start(graph, config, mode="qa", user=QA_USER))
    assert payload["artifact"]["type"] == ArtifactType.TEST_SUITE.value
    assert payload["artifact"]["content"]["story_jira_key"] == "DEMO-3"

    final = graph.invoke(_approve(graph, config), config)

    testmgmt = _testmgmt(container)
    assert testmgmt.publish_calls == 1
    created = [case.key for case in testmgmt.list_cases("DEMO-3")]
    assert len(created) == 2
    assert final["published_keys"] == created
    assert final["errors"] == []
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert isinstance(final["artifact"].content, tc.TestSuite)
    assert set(testmgmt.attachments["DEMO-3"]) == {"estrategia-DEMO-3.md", "matriz-DEMO-3.md"}
    assert _tracker(container).writes == []
    # D-07: la suite no genera memoria aunque todo vaya bien.
    assert list(tmp_path.glob("*.md")) == []
    assert _memory_chunks(container) == []
    assert container.memory_generator.generated == []  # type: ignore[attr-defined]


def test_qa_partial_failure_reports_errors_and_keeps_approved(tmp_path: Path) -> None:
    """RNF-13 · CA-00-04: si falla un caso, se informa y el artefacto no pasa a PUBLISHED."""
    container = fake_container(
        tmp_path, test_management=FakeTestManagement(fail_case_ids={"CP-02"})
    )

    final = _run_to_publish(container, mode="qa", user=QA_USER)

    assert final["errors"] == ["No se pudo publicar CP-02."]
    assert len(final["published_keys"]) == 1
    assert final["artifact"].status is ArtifactStatus.APPROVED
    assert list(tmp_path.glob("*.md")) == []
    assert _memory_chunks(container) == []


# --- 6 · validaciones de load_origin y de la decisión -----------------------------------------


@pytest.mark.parametrize(
    ("mode", "origin", "message"),
    [
        ("functional", {"kind": "story"}, "necesita una clave"),
        ("functional", {"kind": "epic", "key": ""}, "necesita una clave"),
        ("functional", {"kind": "need", "project": "DEMO"}, "texto descriptivo"),
        (
            "functional",
            {"kind": "need", "text": "   ", "project": "DEMO"},
            "texto descriptivo",
        ),
        ("functional", {"kind": "bug", "key": "DEMO-3"}, "no válido"),
        ("qa", {"kind": "epic", "key": "DEMO-1"}, "modo QA"),
        ("qa", NEED_ORIGIN, "modo QA"),
    ],
    ids=[
        "story_sin_clave",
        "epic_clave_vacia",
        "need_sin_texto",
        "need_texto_en_blanco",
        "kind_no_valido",
        "qa_desde_epica",
        "qa_desde_necesidad",
    ],
)
def test_load_origin_rejects_invalid_origin(
    container: Container, mode: str, origin: dict[str, str], message: str
) -> None:
    """CA-00-04 (negativo): orígenes no válidos → ValueError sin escrituras ni lecturas."""
    graph = build_graph(container)

    with pytest.raises(ValueError, match=message):
        _start(graph, _config(), mode, origin)  # type: ignore[arg-type]

    assert _tracker(container).writes == []
    assert container.llm.calls == []  # type: ignore[attr-defined]


def test_load_origin_unknown_key_raises_not_found(container: Container) -> None:
    """CA-00-04 (error): una clave inexistente → NotFoundError."""
    with pytest.raises(NotFoundError):
        _start(build_graph(container), _config(), origin={"kind": "story", "key": "DEMO-999"})


@pytest.mark.parametrize(
    "answer",
    [{"decision": "publicar"}, {"feedback": "sin decisión"}, {"decision": None}, "approve"],
    ids=["decision_desconocida", "sin_decision", "decision_nula", "no_es_dict"],
)
def test_resume_with_invalid_decision_pauses_again_with_error(
    container: Container, answer: object
) -> None:
    """CA-00-04 · T-51 (negativo): decisión no válida → misma pausa con `error`, sin efectos."""
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))

    rejected = _rejected(graph, config, Command(resume=answer), first)

    assert "Decisión no válida" in rejected["error"]
    _assert_nothing_approved_or_written(container, graph, config)
    assert graph.get_state(config).values["artifact"].status is ArtifactStatus.IN_REVIEW


def test_human_review_without_artifact_raises(container: Container) -> None:
    """CA-00-04 (error): human_review sin artefacto → ValueError."""
    with pytest.raises(ValueError, match="ningún artefacto"):
        GraphNodes(container).human_review(_state(None, None))


# --- 7 · retrieve_context ---------------------------------------------------------------------


def test_retrieve_context_includes_parent_siblings_and_links_once(
    container: Container,
) -> None:
    """RF (contexto, pasos 2–3): épica padre, hermanas y vínculos, sin duplicados."""
    nodes = GraphNodes(container)
    state = initial_state(AF_USER, "functional", STORY_ORIGIN)
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    update = nodes.retrieve_context(state)

    keys = [issue.key for issue in update["jira_context"]]
    assert keys[0] == "DEMO-3"
    assert sorted(keys) == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]
    assert len(keys) == len(set(keys))


def test_retrieve_context_returns_rag_sources_from_dataset(container: Container) -> None:
    """RF (contexto RAG): rag_context no vacío con fuentes del corpus sintético."""
    nodes = GraphNodes(container)
    state = initial_state(AF_USER, "functional", STORY_ORIGIN)
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    rag = nodes.retrieve_context(state)["rag_context"]

    assert rag
    assert {r.source.ref for r in rag} <= set(dataset.DOCUMENTS)
    assert all(r.source.kind == "rag" for r in rag)
    assert len(rag) <= container.top_k


def test_retrieve_context_for_need_uses_text_and_no_jira(container: Container) -> None:
    """RF (contexto): una necesidad nueva no carga Jira pero sí consulta el RAG con su texto."""
    nodes = GraphNodes(container)
    state = initial_state(AF_USER, "functional", NEED_ORIGIN)
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    update = nodes.retrieve_context(state)

    assert update["jira_context"] == []
    assert update["rag_context"]


def test_published_memory_is_retrieved_with_priority(container: Container) -> None:
    """RF-51: tras publicar, la memoria de la HU aparece en el contexto como fuente 'memory'."""
    _run_to_publish(container)
    nodes = GraphNodes(container)
    state = initial_state(QA_USER, "qa", STORY_ORIGIN)
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    rag = nodes.retrieve_context(state)["rag_context"]

    assert any(r.source.kind == "memory" and r.source.ref == "memoria-DEMO-3" for r in rag)


# --- 8 · checkpointer en memoria ----------------------------------------------------------------


@pytest.fixture
def serde_events() -> Any:
    events: list[dict[str, Any]] = []
    unregister = register_serde_event_listener(events.append)
    yield events
    unregister()


def _serde_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if "Blocked deserialization" in r.getMessage() or "unregistered" in r.getMessage()
    ]


@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_memory_checkpointer_deserializes_state_without_warnings(
    container: Container,
    caplog: pytest.LogCaptureFixture,
    serde_events: list[dict[str, Any]],
    mode: str,
) -> None:
    """CA-00-04: el checkpointer restaura todos los tipos del estado sin bloqueos ni avisos."""
    caplog.set_level(logging.WARNING)
    graph = build_graph(container, memory_checkpointer())
    config = _config()
    _start(graph, config, mode)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    final = graph.invoke(_approve(graph, config), config)

    assert isinstance(final["artifact"], Artifact)
    assert serde_events == []
    assert _serde_warnings(caplog) == []


def test_strict_serializer_without_allowlist_is_detected(
    container: Container, serde_events: list[dict[str, Any]]
) -> None:
    """Control de la prueba anterior: sin lista de tipos, el bloqueo sí se detecta."""
    strict = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=None))
    graph = build_graph(container, strict)
    config = _config()
    _start(graph, config)

    graph.get_state(config)

    assert any(e["kind"] == "msgpack_blocked" for e in serde_events)


def test_retrieve_context_for_epic_includes_its_stories(tmp_path: Path) -> None:
    """Con origen épica, el contexto incluye sus HU hijas (futuras hermanas de la HU nueva)."""
    container = fake_container(tmp_path)
    nodes = GraphNodes(container)
    state = initial_state("af-demo", "functional", {"kind": "epic", "key": "DEMO-1"})
    state.update(nodes.load_origin(state))
    keys = [issue.key for issue in nodes.retrieve_context(state)["jira_context"]]
    assert keys[0] == "DEMO-1"
    assert sorted(keys) == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]


# --- Aprobación humana: intentos de saltarla (revisión de seguridad de T-07) ---------------


def test_forged_approved_artifact_via_update_state_cannot_publish(tmp_path: Path) -> None:
    """Falsificar artefacto APPROVED y decisión con update_state no basta: no hay aprobación."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    result = _start(graph, config)
    artifact = Artifact.model_validate(_payload(result)["artifact"])
    forged = artifact.model_copy(update={"status": ArtifactStatus.APPROVED})
    graph.update_state(config, {"artifact": forged, "decision": "approve"}, as_node="human_review")
    with pytest.raises(PublishError, match="aprobación humana"):
        graph.invoke(None, config)
    assert _tracker(container).writes == []
    assert not (tmp_path / "DEMO-3.md").exists()


def test_content_swapped_at_resume_is_rejected(tmp_path: Path) -> None:
    """Sustituir el contenido al reanudar invalida la huella: no se aprueba lo que no se vio.

    T-51: la respuesta se rechaza con una nueva pausa (`error`) y, aunque se apruebe después
    con la huella que muestra esa pausa, la versión alterada nunca se ofreció: tampoco se aprueba.
    """
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    result = _start(graph, config)
    payload = _payload(result)
    artifact = Artifact.model_validate(payload["artifact"])
    original_target = _target(graph.get_state(config).values, config)
    swapped = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"title": "CONTENIDO NO REVISADO"})}
    )

    rejected = _payload(
        graph.invoke(
            Command(
                update={"artifact": swapped},
                resume={"decision": "approve", "fingerprint": payload["fingerprint"]},
            ),
            config,
        )
    )
    assert "versión revisada" in rejected["error"]
    _assert_nothing_approved_or_written(container, graph, config)

    # Segundo intento: aprobar con la huella de la pausa que muestra el contenido alterado.
    # El registro de aprobaciones no la ofreció: falla cerrado, sin reintento (T-51).
    with pytest.raises(ApprovalError, match="versión revisada"):
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": rejected["fingerprint"]}),
            config,
        )
    _assert_no_effects(container, artifact, original_target)
    assert container.approvals.find(swapped, original_target) is None
    assert container.approvals.is_offered(artifact, original_target)  # la oferta sigue intacta
    _resume_after_attack_does_not_publish(graph, config, payload["fingerprint"])
    _assert_no_effects(container, artifact, original_target)


@pytest.mark.parametrize(
    "answer", [{"decision": "approve"}, {"decision": "approve", "fingerprint": "0" * 64}]
)
def test_approve_without_matching_fingerprint_is_rejected(tmp_path: Path, answer: dict) -> None:
    """Principio 1 · T-51: sin la huella revisada → misma pausa con `error`, sin aprobación."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))

    rejected = _rejected(graph, config, Command(resume=answer), first)

    assert "versión revisada" in rejected["error"]
    _assert_nothing_approved_or_written(container, graph, config)


def test_interrupt_payload_exposes_version_and_fingerprint(tmp_path: Path) -> None:
    graph = build_graph(fake_container(tmp_path))
    payload = _payload(_start(graph, _config()))
    assert payload["version"] == 1
    assert len(payload["fingerprint"]) == 64


def test_publish_node_requires_ledger_entry(tmp_path: Path) -> None:
    """Un artefacto APPROVED que nadie aprobó no se publica; tras registrarlo, sí."""
    container = fake_container(tmp_path)
    nodes = GraphNodes(container)
    artifact = _artifact(ArtifactStatus.APPROVED)
    with pytest.raises(PublishError, match="aprobación humana"):
        nodes.publish(_state(artifact), _config())
    state, config = _state(artifact), _config()
    container.approvals.offer(artifact, _target(state, config))
    container.approvals.record(artifact, _target(state, config))
    assert nodes.publish(state, config)["artifact"].status is ArtifactStatus.PUBLISHED


# --- Claves de Jira y rutas de memoria -------------------------------------------------------


@pytest.mark.parametrize("key", ["../escape", "C:/Windows/x", "DEMO-3/../../x", "demo-3", "DEMO-"])
def test_load_origin_rejects_malformed_jira_keys(tmp_path: Path, key: str) -> None:
    container = fake_container(tmp_path)
    state = initial_state(AF_USER, "functional", {"kind": "story", "key": key})
    with pytest.raises(ValueError, match="Clave de Jira no válida"):
        GraphNodes(container).load_origin(state)


def test_memorize_rejects_path_traversal_from_generator(tmp_path: Path) -> None:
    """Aunque el generador devuelva una clave maliciosa, no se escribe fuera de memory_dir."""
    memory_dir = tmp_path / "memory"
    container = fake_container(memory_dir)
    nodes = GraphNodes(container)
    story = dataset.renewal_story(jira_key="../escape")
    artifact = _artifact(ArtifactStatus.PUBLISHED, story)
    state = _state(artifact)
    target = _target(state, _config())
    container.approvals.offer(artifact, target)
    container.approvals.consume(container.approvals.record(artifact, target), artifact)
    with pytest.raises(ValueError, match="Clave de Jira no válida"):
        nodes.memorize(state)
    assert not (tmp_path / "escape.md").exists()


def test_approval_cannot_be_reused_in_another_thread_target_or_user(tmp_path: Path) -> None:
    """PoC D: la aprobación de DEMO-3 no sirve para publicar en DEMO-4 ni con otro usuario."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(_approve(graph, config), config)
    approved = graph.get_state(config).values["artifact"]
    writes_before = list(_tracker(container).writes)

    nodes = GraphNodes(container)
    other_target = _state(approved)
    other_target["origin"] = {"kind": "story", "key": "DEMO-4"}
    with pytest.raises(PublishError):
        nodes.publish(other_target)
    other_user = _state(approved)
    other_user["user"] = "otro-usuario-ficticio"
    with pytest.raises(PublishError):
        nodes.publish(other_user)
    assert _tracker(container).writes == writes_before


def test_approval_is_consumed_after_publishing(tmp_path: Path) -> None:
    """PoC C: reinyectar la versión aprobada tras publicar no provoca una segunda escritura."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)
    graph.invoke(_approve(graph, config), config)
    creates = [w for w in _tracker(container).writes if w[0] == "create_story"]
    assert len(creates) == 1
    history = list(graph.get_state_history(config))
    approved = next(
        s.values["artifact"]
        for s in history
        if s.values.get("artifact") is not None
        and s.values["artifact"].status is ArtifactStatus.APPROVED
    )
    graph.update_state(
        config, {"artifact": approved, "decision": "approve"}, as_node="human_review"
    )
    with pytest.raises(PublishError):
        graph.invoke(None, config)
    assert len([w for w in _tracker(container).writes if w[0] == "create_story"]) == 1


def test_content_swapped_with_recomputed_fingerprint_is_rejected(tmp_path: Path) -> None:
    """PoC A: recalcular la huella del contenido cambiado no basta; no es la versión ofrecida."""
    from core.approvals import content_fingerprint

    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    artifact = Artifact.model_validate(_payload(_start(graph, config))["artifact"])
    original_target = _target(graph.get_state(config).values, config)
    evil = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"title": "NO REVISADO"})}
    )

    rejected = _payload(
        graph.invoke(
            Command(
                update={"artifact": evil},
                resume={"decision": "approve", "fingerprint": content_fingerprint(evil)},
            ),
            config,
        )
    )
    assert "versión revisada" in rejected["error"]
    _assert_nothing_approved_or_written(container, graph, config)

    # Ni siquiera con la huella de revisión recalculada que muestra la nueva pausa.
    # El registro de aprobaciones no la ofreció: falla cerrado, sin reintento (T-51).
    with pytest.raises(ApprovalError, match="versión revisada"):
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": rejected["fingerprint"]}),
            config,
        )
    _assert_no_effects(container, artifact, original_target)
    assert container.approvals.find(evil, original_target) is None
    _resume_after_attack_does_not_publish(graph, config, rejected["fingerprint"])
    _assert_no_effects(container, artifact, original_target)


def test_memorize_requires_recorded_publication(tmp_path: Path) -> None:
    """PoC F: un artefacto marcado PUBLISHED sin publicación registrada no genera memoria."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    artifact = Artifact.model_validate(_payload(_start(graph, config))["artifact"])
    fake_published = artifact.model_copy(update={"status": ArtifactStatus.PUBLISHED})
    graph.update_state(config, {"artifact": fake_published}, as_node="publish")
    with pytest.raises(PublishError, match="publicación"):
        graph.invoke(None, config)
    assert not (tmp_path / "DEMO-3.md").exists()
    assert _memory_chunks(container) == []


@pytest.mark.parametrize(
    ("start_origin", "swapped_origin"),
    [
        (EPIC_ORIGIN, {"kind": "story", "key": "DEMO-1"}),  # PoC N: sobrescribir la épica
        (STORY_ORIGIN, {"kind": "epic", "key": "DEMO-3"}),  # PoC J: crear una HU no aprobada
    ],
)
def test_origin_kind_swapped_at_resume_cannot_change_operation(
    tmp_path: Path, start_origin: Origin, swapped_origin: Origin
) -> None:
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=start_origin)
    approve = _approve(graph, config)
    with pytest.raises((ValueError, PublishError)):
        graph.invoke(Command(update={"origin": swapped_origin}, resume=approve.resume), config)
    assert _tracker(container).writes == []


def test_origin_kind_swapped_after_approval_cannot_change_operation(tmp_path: Path) -> None:
    """Aunque se cambie el origen entre la aprobación y la publicación, no se escribe."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)
    graph.invoke(_approve(graph, config), config)
    creates = len(_tracker(container).writes)
    state = graph.get_state(config).values
    nodes = GraphNodes(container)
    tampered = {**state, "origin": {"kind": "story", "key": "DEMO-1"}, "decision": "approve"}
    with pytest.raises(PublishError):
        nodes.publish(tampered, config)
    assert len(_tracker(container).writes) == creates


def test_user_swapped_at_resume_is_rejected(tmp_path: Path) -> None:
    """PoC L: la aprobación no puede quedar a nombre de otro usuario (T-51: pausa con error)."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    original_target = _target(graph.get_state(config).values, config)
    approve = _approve(graph, config)

    rejected = _payload(
        graph.invoke(
            Command(update={"user": "otro-usuario-ficticio"}, resume=approve.resume), config
        )
    )
    assert "versión revisada" in rejected["error"]
    assert rejected["version"] == first["version"]
    _assert_nothing_approved_or_written(container, graph, config)

    # Con la huella de la pausa (calculada para el otro usuario) tampoco: no se le ofreció.
    # El registro de aprobaciones no la ofreció: falla cerrado, sin reintento (T-51).
    with pytest.raises(ApprovalError, match="versión revisada"):
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": rejected["fingerprint"]}),
            config,
        )
    artifact = Artifact.model_validate(first["artifact"])
    other_target = replace(original_target, user="otro-usuario-ficticio")
    _assert_no_effects(container, artifact, original_target, other_target)
    _resume_after_attack_does_not_publish(graph, config, first["fingerprint"])
    _assert_no_effects(container, artifact, original_target, other_target)


def test_approval_from_another_thread_is_not_reused(tmp_path: Path) -> None:
    """PoC K: la aprobación está ligada al hilo en que se revisó."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(_approve(graph, config), config)
    writes = len(_tracker(container).writes)
    approved = next(
        s.values["artifact"]
        for s in graph.get_state_history(config)
        if s.values.get("artifact") is not None
        and s.values["artifact"].status is ArtifactStatus.APPROVED
    )
    other_config = _config()
    with pytest.raises(PublishError):
        GraphNodes(container).publish(_state(approved), other_config)
    assert len(_tracker(container).writes) == writes


@pytest.mark.parametrize(
    ("start_origin", "swapped"),
    [
        (EPIC_ORIGIN, {"origin": {"kind": "story", "key": "DEMO-1"}}),  # PoC N2
        (STORY_ORIGIN, {"origin": {"kind": "epic", "key": "DEMO-3"}}),  # PoC J3
        (STORY_ORIGIN, {"mode": "qa"}),  # PoC P3
        (STORY_ORIGIN, {"user": "otro-usuario-ficticio"}),  # PoC P4
    ],
)
def test_operation_cannot_change_through_an_iteration(
    tmp_path: Path, start_origin: Origin, swapped: dict[str, Any]
) -> None:
    """Cambiar origen, modo o usuario junto con una iteración no altera la operación fijada."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=start_origin)
    with pytest.raises((ValueError, PublishError)):
        graph.invoke(Command(update=swapped, resume={"decision": "iterate"}), config)
    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0


def test_interrupt_payload_describes_the_operation(tmp_path: Path) -> None:
    graph = build_graph(fake_container(tmp_path))
    payload = _payload(_start(graph, _config(), origin=EPIC_ORIGIN))
    assert payload["target"] == {
        "operation": "crear HU",
        "project": "DEMO",
        "jira_key": None,
        "epic_key": "DEMO-1",
    }


def test_published_version_cannot_be_approved_again(tmp_path: Path) -> None:
    """PoC R1: rebobinar a generate y volver a aprobar la misma versión no vuelve a crear la HU."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)
    graph.invoke(_approve(graph, config), config)
    in_review = next(s for s in graph.get_state_history(config) if s.next == ("human_review",))
    graph.update_state(in_review.config, in_review.values, as_node="generate")
    with pytest.raises((ValueError, PublishError)):
        graph.invoke(_approve(graph, config), config)
    creates = [w for w in _tracker(container).writes if w[0] == "create_story"]
    assert len(creates) == 1


@pytest.mark.parametrize("key", ["DEMO-3\n", "DEMO-3\n../x"])
def test_load_origin_rejects_keys_with_trailing_newline(tmp_path: Path, key: str) -> None:
    """PA-18: `fullmatch` impide que un salto de línea final pase la validación."""
    state = initial_state(AF_USER, "functional", {"kind": "story", "key": key})
    with pytest.raises(ValueError, match="Clave de Jira no válida"):
        GraphNodes(fake_container(tmp_path)).load_origin(state)


def test_evolution_diff_is_deterministic_against_jira_baseline(tmp_path: Path) -> None:
    """PA-30 / T-19: el diff compara la versión de Jira estructurada con la evolución."""
    from core.impact.diff import diff_stories
    from tests.fakes.llm import FakeLLMProvider

    calls: list[str] = []

    def story_builder(messages: list[Any]) -> UserStory:
        system = messages[0].content
        story = dataset.renewal_story(jira_key=None)
        cited = story.model_copy(update={"sources": [SourceRef(kind="jira", ref="DEMO-3")]})
        if "Pasas a la plantilla" in system:  # structure_story: versión de partida
            calls.append("structure")
            return cited
        calls.append("evolve")
        return cited.model_copy(update={"title": "Renovar un préstamo desde la app"})

    llm = FakeLLMProvider()
    llm.builders[UserStory] = story_builder
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = _config()
    artifact = Artifact.model_validate(_payload(_start(graph, config))["artifact"])
    baseline = dataset.renewal_story(jira_key="DEMO-3").model_copy(
        update={"sources": [SourceRef(kind="jira", ref="DEMO-3")]}
    )
    expected = diff_stories(baseline, artifact.content)
    assert artifact.impact is not None
    assert [d.field for d in artifact.impact.diffs] == [d.field for d in expected] == ["title"]
    assert artifact.prompt_version is not None
    assert calls == ["structure", "evolve"]
    # Al iterar, la versión de partida no se vuelve a estructurar.
    graph.invoke(Command(resume={"decision": "iterate", "feedback": "Ajusta el título"}), config)
    assert calls == ["structure", "evolve", "evolve"]
