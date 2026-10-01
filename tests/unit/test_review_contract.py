"""Contrato de revisión para la UI (T-51 · RF-21, RF-31, RF-32).

Cubre:
- fuentes excluidas en `initial_state` y en `ContextService.gather` (antes del presupuesto);
- auditoría de `excluded_sources` en `create`;
- `plan` de operaciones de Jira en el payload de `human_review` (igual al que audita `publish`);
- decisión `edit`: contenido editado → versión nueva con su huella, sin llamar al LLM.

Solo fakes de `tests/fakes/`; datos 100 % ficticios.
"""

import copy
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.base import Chunk, RetrievedChunk
from core.audit import InMemoryAuditTrail
from core.container import Container
from core.context.service import ContextService
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import DECISIONS, GraphNodes, _target
from core.impact.diff import diff_stories
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, SourceRef
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore

AF_USER = "af-demo"
QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
EPIC_ORIGIN: Origin = {"kind": "epic", "key": "DEMO-1"}
NEED_ORIGIN: Origin = {
    "kind": "need",
    "project": "DEMO",
    "text": "Avisar por correo tres días antes del vencimiento del préstamo (ficticio).",
}
STRUCTURE_MARK = "Pasas a la plantilla"  # prompts/structure_story.md
EDITED_TITLE = "Renovar un prestamo desde la ficha ficticia editada"
EDITED_DESCRIPTION = "Descripcion editada a mano por la persona revisora (texto ficticio)."


# --- utilidades --------------------------------------------------------------------------


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"hilo-{uuid4()}"}}


def _start(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    mode: str = "functional",
    origin: Origin = STORY_ORIGIN,
    user: str = AF_USER,
    excluded: list[str] | None = None,
) -> dict[str, Any]:
    state = initial_state(user, mode, origin, excluded)  # type: ignore[arg-type]
    return graph.invoke(state, config)


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    (pending,) = result["__interrupt__"]
    return pending.value


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[0].value


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    return Command(
        resume={"decision": "approve", "fingerprint": _pending(graph, config)["fingerprint"]}
    )


def _edit_command(content: object, fingerprint: str | None, feedback: str | None = None) -> Command:
    answer: dict[str, Any] = {"decision": "edit", "content": content}
    if fingerprint is not None:
        answer["fingerprint"] = fingerprint
    if feedback is not None:
        answer["feedback"] = feedback
    return Command(resume=answer)


def _edited_story(content: dict[str, Any], **changes: Any) -> dict[str, Any]:
    edited = copy.deepcopy(content)
    edited.update(changes or {"title": EDITED_TITLE, "description": EDITED_DESCRIPTION})
    return edited


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _testmgmt(container: Container) -> FakeTestManagement:
    assert isinstance(container.test_management, FakeTestManagement)
    return container.test_management


def _audit(container: Container) -> InMemoryAuditTrail:
    assert isinstance(container.audit, InMemoryAuditTrail)
    return container.audit


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _snapshot(
    container: Container, graph: CompiledStateGraph, config: dict[str, Any]
) -> tuple[Any, ...]:
    """Efectos observables: escrituras, publicaciones, auditoría, versión y aprobación."""
    state = graph.get_state(config).values
    artifact = state["artifact"]
    return (
        list(_tracker(container).writes),
        _testmgmt(container).publish_calls,
        [(e.action, e.detail.get("version")) for e in _audit(container).entries(artifact.id)],
        artifact.version,
        artifact.status,
        container.approvals.find(artifact, _target(state, config)),
    )


def _rejected(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    command: Command,
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Respuesta inválida (D-1): vuelve a pausar con la misma versión y huella, y con `error`."""
    payload = _payload(graph.invoke(command, config))
    assert payload["version"] == previous["version"]
    assert payload["fingerprint"] == previous["fingerprint"]
    assert payload["artifact"] == previous["artifact"]
    assert payload["plan"] == previous["plan"]
    assert isinstance(payload["error"], str) and payload["error"]
    # La pausa pendiente se ve en las tareas (tras un rechazo, LangGraph deja `next` vacío).
    assert _pending(graph, config)["error"] == payload["error"]
    return payload


def _evolving_llm() -> FakeLLMProvider:
    """La evolución cambia el título respecto a la versión de partida (hay diff)."""

    def story_builder(messages: list[Any]) -> UserStory:
        story = dataset.renewal_story(jira_key=None).model_copy(
            update={"sources": [SourceRef(kind="jira", ref="DEMO-3")]}
        )
        if STRUCTURE_MARK in messages[0].content:
            return story
        return story.model_copy(update={"title": "Renovar un préstamo desde la app (ficticio)"})

    llm = FakeLLMProvider()
    llm.builders[UserStory] = story_builder
    return llm


class SpyVersionSink:
    """VersionSink espía: guarda cada artefacto recibido."""

    def __init__(self) -> None:
        self.saved: list[Artifact] = []
        self.status_updates: list[tuple[object, str, str | None]] = []

    def save(self, artifact: Artifact) -> None:
        self.saved.append(artifact.model_copy(deep=True))

    def update_status(self, artifact_id: object, status: str, jira_key: str | None = None) -> None:
        self.status_updates.append((artifact_id, status, jira_key))


def _add_doc(
    store: FakeVectorStore,
    embeddings: FakeEmbeddingProvider,
    document_id: str,
    category: str,
    content: str,
    *,
    doc_id: str | None = None,
    related: str = "",
) -> None:
    metadata = {"category": category, "doc_id": doc_id or document_id}
    if related:
        metadata["related"] = related
    (vector,) = embeddings.embed([content])
    store.upsert(
        [
            Chunk(
                id=f"{document_id}#0",
                document_id=document_id,
                ordinal=0,
                content=content,
                embedding=vector,
                metadata=metadata,
            )
        ]
    )


def _service(
    tracker: FakeIssueTracker | None = None,
    embeddings: FakeEmbeddingProvider | None = None,
    store: FakeVectorStore | None = None,
    *,
    top_k: int = 6,
    token_budget: int = 6000,
    project_key: str | None = None,
) -> ContextService:
    return ContextService(
        tracker or FakeIssueTracker(),
        embeddings or FakeEmbeddingProvider(),
        store if store is not None else FakeVectorStore(),
        top_k=top_k,
        memory_boost=1.0,
        token_budget=token_budget,
        project_key=project_key,
    )


def _refs(chunks: list[RetrievedChunk]) -> list[str]:
    return [c.source.ref for c in chunks]


def _rag_corpus() -> tuple[FakeEmbeddingProvider, FakeVectorStore]:
    """Norma ↔ acta, un glosario con doc_id distinto del documento y una memoria (ficticios)."""
    embeddings, store = FakeEmbeddingProvider(), FakeVectorStore()
    _add_doc(
        store,
        embeddings,
        "DOC-A",
        "politicas",
        "Norma ficticia: las reservas quedan bloqueadas cuarenta y ocho horas en mostrador.",
        related="DOC-B",
    )
    _add_doc(
        store,
        embeddings,
        "DOC-B",
        "documentacion",
        "Acta ficticia de la comisión: acuerdo sobre plazos y calendario anual.",
        related="DOC-A",
    )
    _add_doc(
        store,
        embeddings,
        "fichero-glosario-ficticio.pdf",
        "glosario",
        "Glosario ficticio: reservas, bloqueadas, horas y mostrador definidos.",
        doc_id="DOC-G",
    )
    _add_doc(
        store,
        embeddings,
        "memoria-DEMO-9",
        "memoria",
        "Memoria ficticia: reservas bloqueadas en mostrador durante cuarenta y ocho horas.",
    )
    return embeddings, store


RAG_NEED = {"kind": "need", "text": "reservas bloqueadas cuarenta ocho horas mostrador"}


# --- 1 · initial_state: excluded_sources ---------------------------------------------------


def test_initial_state_normalizes_excluded_sources_strip_dedupe_sort() -> None:
    """T-51 · RF-21: sin espacios, sin vacíos, sin duplicados y ordenadas."""
    state = initial_state(
        AF_USER,
        "functional",
        STORY_ORIGIN,
        [" doc-glosario ", "", "DEMO-4", "doc-glosario", "   ", "DEMO-2"],
    )
    assert state["excluded_sources"] == ["DEMO-2", "DEMO-4", "doc-glosario"]


@pytest.mark.parametrize("excluded", [None, [], ["", "  "]], ids=["none", "vacia", "en_blanco"])
def test_initial_state_without_excluded_sources_is_empty_list(excluded: list[str] | None) -> None:
    """T-51 (límite): sin exclusiones (o solo vacías) la lista queda vacía."""
    state = initial_state(AF_USER, "functional", STORY_ORIGIN, excluded)
    assert state["excluded_sources"] == []


def test_initial_state_default_keeps_previous_signature() -> None:
    """T-51: la firma de tres argumentos sigue valiendo (compatibilidad)."""
    assert initial_state(AF_USER, "functional", NEED_ORIGIN)["excluded_sources"] == []


@pytest.mark.parametrize(
    ("origin", "excluded"),
    [
        (STORY_ORIGIN, ["DEMO-3"]),
        (STORY_ORIGIN, ["DEMO-2", "  DEMO-3  "]),
        (EPIC_ORIGIN, ["DEMO-1"]),
    ],
    ids=["hu", "hu_con_espacios", "epica"],
)
def test_initial_state_rejects_excluding_origin_issue(origin: Origin, excluded: list[str]) -> None:
    """T-51 · RF-21 (negativo): la incidencia de origen no se puede excluir."""
    key = origin["key"]  # type: ignore[typeddict-item]
    with pytest.raises(ValueError, match=f"La incidencia de origen {key} no se puede excluir"):
        initial_state(AF_USER, "functional", origin, excluded)


def test_initial_state_need_origin_accepts_any_exclusion() -> None:
    """T-51: una necesidad no tiene incidencia de origen; cualquier clave se puede excluir."""
    state = initial_state(AF_USER, "functional", NEED_ORIGIN, ["DEMO-3", "doc-reglamento"])
    assert state["excluded_sources"] == ["DEMO-3", "doc-reglamento"]


# --- 2 · ContextService.gather(excluded) ---------------------------------------------------


def test_gather_excludes_rag_source_by_ref() -> None:
    """T-51 · RF-21: un fragmento cuya `source.ref` está excluida no llega al contexto."""
    embeddings, store = _rag_corpus()
    service = _service(embeddings=embeddings, store=store)
    baseline = _refs(service.gather(RAG_NEED, None).rag)
    assert "DOC-A" in baseline

    refs = _refs(service.gather(RAG_NEED, None, excluded={"DOC-A"}).rag)

    assert "DOC-A" not in refs
    assert set(refs) == set(baseline) - {"DOC-A"}


def test_gather_excludes_rag_source_by_metadata_doc_id() -> None:
    """T-51 · RF-21: también se excluye por `metadata["doc_id"]` aunque la ref sea otra."""
    embeddings, store = _rag_corpus()
    service = _service(embeddings=embeddings, store=store)
    assert "fichero-glosario-ficticio.pdf" in _refs(service.gather(RAG_NEED, None).rag)

    refs = _refs(service.gather(RAG_NEED, None, excluded=["DOC-G"]).rag)

    assert "fichero-glosario-ficticio.pdf" not in refs


def test_gather_excludes_rag_source_by_document_id_without_doc_id_metadata() -> None:
    """T-51 · RF-21: sin `doc_id` en metadatos se usa `document_id`."""
    embeddings, store = FakeEmbeddingProvider(), FakeVectorStore()
    _add_doc(store, embeddings, "DOC-Z", "glosario", "Glosario ficticio de reservas bloqueadas.")
    store.chunks["DOC-Z#0"].metadata.pop("doc_id")
    service = _service(embeddings=embeddings, store=store)
    assert _refs(service.gather(RAG_NEED, None).rag) == ["DOC-Z"]

    assert service.gather(RAG_NEED, None, excluded=["DOC-Z"]).rag == []


def test_gather_excludes_memory_source() -> None:
    """T-51 · RF-21 · RF-51: una memoria excluida no entra aunque tenga prioridad."""
    embeddings, store = _rag_corpus()
    service = _service(embeddings=embeddings, store=store)
    assert service.gather(RAG_NEED, None).rag[0].source.ref == "memoria-DEMO-9"

    rag = service.gather(RAG_NEED, None, excluded=["memoria-DEMO-9"]).rag

    assert all(r.source.kind != "memory" for r in rag)
    assert rag


def test_gather_excluding_norm_does_not_bring_its_minutes() -> None:
    """T-51 · O-1: excluir la norma no trae su acta por el par norma↔acta; el hueco se rellena."""
    embeddings, store = _rag_corpus()
    store.delete_by_document("memoria-DEMO-9")
    service = _service(embeddings=embeddings, store=store, top_k=1)
    origin = {"kind": "need", "text": "norma reservas bloqueadas cuarenta ocho horas mostrador"}
    assert _refs(service.gather(origin, None).rag) == ["DOC-A", "DOC-B"]

    refs = _refs(service.gather(origin, None, ["DOC-A"]).rag)

    assert "DOC-A" not in refs
    assert "DOC-B" not in refs
    assert refs == ["fichero-glosario-ficticio.pdf"]


def test_gather_excluded_slot_in_top_k_is_filled_with_next_result() -> None:
    """T-51 · O-1: el hueco que deja una fuente excluida en `top_k` lo ocupa el siguiente."""
    embeddings, store = FakeEmbeddingProvider(), FakeVectorStore()
    _add_doc(store, embeddings, "GLO-1", "glosario", "reservas bloqueadas horas mostrador ficticio")
    _add_doc(store, embeddings, "GLO-2", "glosario", "reservas bloqueadas horas ficticio otro")
    _add_doc(store, embeddings, "GLO-3", "glosario", "reservas ficticio tercero distinto")
    origin = {"kind": "need", "text": "reservas bloqueadas horas mostrador"}
    ranking = _refs(_service(embeddings=embeddings, store=store, top_k=3).gather(origin, None).rag)
    assert len(ranking) == 3
    service = _service(embeddings=embeddings, store=store, top_k=2)
    assert _refs(service.gather(origin, None).rag) == ranking[:2]

    refs = _refs(service.gather(origin, None, [ranking[0]]).rag)

    assert refs == ranking[1:]


def test_gather_several_exclusions_still_return_top_k() -> None:
    """T-51 · O-1 (límite): con varias exclusiones se siguen devolviendo `top_k` fragmentos."""
    embeddings, store = FakeEmbeddingProvider(), FakeVectorStore()
    for n in range(1, 6):
        _add_doc(store, embeddings, f"GLO-{n}", "glosario", f"reservas ficticias numero {n}")
    origin = {"kind": "need", "text": "reservas ficticias"}
    service = _service(embeddings=embeddings, store=store, top_k=2)
    excluded = _refs(service.gather(origin, None).rag)

    refs = _refs(service.gather(origin, None, excluded).rag)

    assert len(refs) == 2
    assert not set(refs) & set(excluded)


def test_gather_excluding_more_than_available_returns_the_rest() -> None:
    """T-51 · O-1 (límite): si se excluye casi todo, solo queda lo no excluido."""
    embeddings, store = FakeEmbeddingProvider(), FakeVectorStore()
    for n in range(1, 4):
        _add_doc(store, embeddings, f"GLO-{n}", "glosario", f"reservas ficticias numero {n}")
    service = _service(embeddings=embeddings, store=store, top_k=3)
    origin = {"kind": "need", "text": "reservas ficticias"}

    refs = _refs(service.gather(origin, None, ["GLO-1", "GLO-2"]).rag)

    assert refs == ["GLO-3"]


def test_gather_excludes_minutes_added_by_norm_pair() -> None:
    """T-51 · RF-11: el acta que añade el par norma↔acta también se filtra si está excluida."""
    embeddings, store = _rag_corpus()
    service = _service(embeddings=embeddings, store=store, top_k=1)
    origin = {"kind": "need", "text": "norma reservas bloqueadas cuarenta ocho horas mostrador"}
    store.delete_by_document("memoria-DEMO-9")
    store.delete_by_document("fichero-glosario-ficticio.pdf")
    assert _refs(service.gather(origin, None).rag) == ["DOC-A", "DOC-B"]

    assert _refs(service.gather(origin, None, excluded=["DOC-B"]).rag) == ["DOC-A"]


@pytest.mark.parametrize(
    "excluded", ["DEMO-2", "DEMO-1", "DEMO-4"], ids=["vinculo", "epica", "hermana"]
)
def test_gather_excludes_jira_issue(excluded: str) -> None:
    """T-51 · RF-21: una incidencia de Jira excluida (vínculo, épica o hermana) no entra."""
    tracker = FakeIssueTracker()
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)

    keys = [i.key for i in _service(tracker).gather(STORY_ORIGIN, origin, [excluded]).jira]

    assert excluded not in keys
    assert keys[0] == "DEMO-3"
    assert set(keys) == {"DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"} - {excluded}


def test_gather_excludes_jira_matches_of_a_need() -> None:
    """T-51 · RF-21: las HU encontradas para una necesidad también se pueden excluir."""
    tracker = FakeIssueTracker()
    service = _service(tracker, project_key="DEMO")
    origin = {"kind": "need", "text": "renovaciones"}
    assert [i.key for i in service.gather(origin, None).jira] == ["DEMO-3"]

    assert service.gather(origin, None, excluded=["DEMO-3"]).jira == []


def test_gather_never_excludes_origin_issue_even_if_requested() -> None:
    """T-51 · RF-21 (negativo): la incidencia de origen nunca se quita en gather."""
    tracker = FakeIssueTracker()
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)

    keys = [
        i.key for i in _service(tracker).gather(STORY_ORIGIN, origin, {"DEMO-3", "DEMO-2"}).jira
    ]

    assert keys[0] == "DEMO-3"
    assert "DEMO-2" not in keys


def test_gather_never_excludes_epic_origin_even_if_requested() -> None:
    """T-51 (negativo): con origen épica, la épica sigue siendo la primera incidencia."""
    tracker = FakeIssueTracker()
    origin = tracker.issues["DEMO-1"].model_copy(deep=True)

    keys = [i.key for i in _service(tracker).gather(EPIC_ORIGIN, origin, ["DEMO-1"]).jira]

    assert keys == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]


def test_gather_with_empty_exclusion_changes_nothing() -> None:
    """T-51 (límite): sin exclusiones el resultado es el mismo que antes de T-51."""
    embeddings, store = _rag_corpus()
    tracker = FakeIssueTracker()
    origin = tracker.issues["DEMO-3"]
    service = _service(tracker, embeddings, store)

    assert service.gather(STORY_ORIGIN, origin, ()) == service.gather(STORY_ORIGIN, origin)


def test_gather_unknown_excluded_reference_is_ignored() -> None:
    """T-51 (límite): una referencia que no está en el contexto no altera el resultado."""
    embeddings, store = _rag_corpus()
    service = _service(embeddings=embeddings, store=store)

    assert service.gather(RAG_NEED, None, ["DOC-INEXISTENTE"]) == service.gather(RAG_NEED, None)


def test_gather_exclusion_frees_jira_budget_for_another_issue() -> None:
    """T-51 · PA-07: la incidencia excluida libera presupuesto y entra otra que quedaba fuera."""
    tracker = FakeIssueTracker()
    origin = tracker.issues["DEMO-3"]
    service = _service(tracker, token_budget=360)
    before = service.gather(STORY_ORIGIN, origin)
    assert [i.key for i in before.jira] == ["DEMO-3", "DEMO-1"]
    assert before.budget.dropped_issues == 2

    after = service.gather(STORY_ORIGIN, origin, ["DEMO-1"])

    assert [i.key for i in after.jira] == ["DEMO-3", "DEMO-2"]
    assert after.budget.dropped_issues == 1  # solo DEMO-4; DEMO-1 no cuenta como descartada


def test_gather_exclusion_frees_rag_budget_for_another_chunk() -> None:
    """T-51 · PA-07: excluir un fragmento antes del presupuesto deja sitio a otro."""
    embeddings, store = FakeEmbeddingProvider(), FakeVectorStore()
    filler = " ".join(["palabra"] * 40)
    _add_doc(store, embeddings, "DOC-1", "glosario", f"reservas bloqueadas mostrador {filler}")
    _add_doc(store, embeddings, "DOC-2", "glosario", f"reservas horas {filler} ficticio")
    origin = {"kind": "need", "text": "reservas bloqueadas mostrador"}
    # Cabe el texto de la necesidad y un solo fragmento.
    service = _service(embeddings=embeddings, store=store, token_budget=150)
    before = service.gather(origin, None)
    assert len(before.rag) == 1
    assert before.budget.dropped_chunks == 1
    first = before.rag[0].source.ref

    after = service.gather(origin, None, [first])

    assert len(after.rag) == 1
    assert after.rag[0].source.ref != first
    assert after.budget.dropped_chunks == 0


# --- 3 · retrieve_context y generate --------------------------------------------------------


def test_retrieve_context_passes_excluded_sources_from_state(tmp_path: Path) -> None:
    """T-51 · RF-21: el nodo usa `excluded_sources` del estado para Jira y RAG."""
    nodes = GraphNodes(fake_container(tmp_path))
    state = initial_state(AF_USER, "functional", STORY_ORIGIN, ["DEMO-2", "doc-glosario"])
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    update = nodes.retrieve_context(state)

    keys = [i.key for i in update["jira_context"]]
    assert keys[0] == "DEMO-3" and "DEMO-2" not in keys
    assert "doc-glosario" not in _refs(update["rag_context"])


def test_retrieve_context_never_excludes_origin_with_hand_built_state(tmp_path: Path) -> None:
    """T-51 (negativo): aunque el estado se construya a mano con el origen, no se excluye."""
    nodes = GraphNodes(fake_container(tmp_path))
    state = initial_state(AF_USER, "functional", STORY_ORIGIN)
    state["excluded_sources"] = ["DEMO-3", "DEMO-2"]
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    keys = [i.key for i in nodes.retrieve_context(state)["jira_context"]]

    assert keys[0] == "DEMO-3"
    assert "DEMO-2" not in keys


def test_retrieve_context_tolerates_state_without_excluded_key(tmp_path: Path) -> None:
    """T-51 (compatibilidad): un estado antiguo sin `excluded_sources` sigue funcionando."""
    nodes = GraphNodes(fake_container(tmp_path))
    state = initial_state(AF_USER, "functional", STORY_ORIGIN)
    del state["excluded_sources"]  # type: ignore[misc]
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    keys = sorted(i.key for i in nodes.retrieve_context(state)["jira_context"])

    assert keys == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]


def test_excluded_sources_do_not_reach_the_llm(tmp_path: Path) -> None:
    """T-51 · RF-21: lo excluido no se cita como fuente en los mensajes al LLM."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    _start(graph, _config(), excluded=["DEMO-2", "doc-glosario"])

    story_calls = [c for c in _llm(container).calls if c["schema"] is UserStory]
    assert story_calls
    for call in story_calls:
        text = "\n".join(m.content for m in call["messages"] if m.role == "user")
        assert '<fuente ref="DEMO-2"' not in text
        assert '<fuente ref="doc-glosario"' not in text


def test_create_audits_excluded_sources_only_references(tmp_path: Path) -> None:
    """T-51 · RF-35: `create` audita `excluded_sources` (lista ordenada de referencias)."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    artifact = _payload(_start(graph, config, excluded=["doc-glosario", "DEMO-4"]))["artifact"]

    (create,) = _audit(container).entries(UUID(artifact["id"]))
    assert create.action == "create"
    assert create.detail["excluded_sources"] == ["DEMO-4", "doc-glosario"]


def test_create_without_exclusions_has_no_excluded_sources_in_audit(tmp_path: Path) -> None:
    """T-51 (límite): sin exclusiones, `create` no lleva la clave `excluded_sources`."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    artifact = _payload(_start(graph, _config()))["artifact"]

    (create,) = _audit(container).entries(UUID(artifact["id"]))
    assert "excluded_sources" not in create.detail


def test_iterate_does_not_audit_excluded_sources(tmp_path: Path) -> None:
    """T-51: `iterate` no repite `excluded_sources` (solo `create`)."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    artifact = _payload(_start(graph, config, excluded=["DEMO-4"]))["artifact"]
    graph.invoke(Command(resume={"decision": "iterate", "feedback": "Ajuste ficticio"}), config)

    create, iterate = _audit(container).entries(UUID(artifact["id"]))
    assert create.detail["excluded_sources"] == ["DEMO-4"]
    assert iterate.action == "iterate"
    assert "excluded_sources" not in iterate.detail


def test_excluded_sources_persist_across_iterations(tmp_path: Path) -> None:
    """T-51 · RF-21: al iterar se vuelve a reunir contexto sin las fuentes excluidas."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, excluded=["DEMO-2"])
    graph.invoke(Command(resume={"decision": "iterate", "feedback": "Ajuste ficticio"}), config)

    state = graph.get_state(config).values
    assert state["excluded_sources"] == ["DEMO-2"]
    assert "DEMO-2" not in [i.key for i in state["jira_context"]]


# --- 4 · plan en el payload de human_review -------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "origin", "user", "evolving"),
    [
        ("functional", STORY_ORIGIN, AF_USER, True),
        ("functional", EPIC_ORIGIN, AF_USER, False),
        ("functional", NEED_ORIGIN, AF_USER, False),
        ("qa", STORY_ORIGIN, QA_USER, False),
    ],
    ids=["evolucion", "epica", "necesidad", "qa"],
)
def test_review_plan_matches_simulated_publish_plan(
    tmp_path: Path, mode: str, origin: Origin, user: str, evolving: bool
) -> None:
    """T-51 · RF-31: el `plan` mostrado en la revisión es el que audita `publish` (simulación)."""
    overrides: dict[str, Any] = {"llm": _evolving_llm()} if evolving else {}
    container = fake_container(tmp_path, publish_mode="simulation", **overrides)
    graph = build_graph(container)
    config = _config()
    payload = _payload(_start(graph, config, mode, origin, user))
    assert payload["plan"]

    final = graph.invoke(_approve(graph, config), config)

    publish = _audit(container).entries(final["artifact"].id)[-1]
    assert publish.action == "publish" and publish.detail["simulated"] is True
    assert payload["plan"] == publish.detail["plan"]


@pytest.mark.parametrize(
    ("mode", "origin", "user", "first_op"),
    [
        (
            "functional",
            STORY_ORIGIN,
            AF_USER,
            {"op": "update_story", "project": "DEMO", "key": "DEMO-3"},
        ),
        (
            "functional",
            EPIC_ORIGIN,
            AF_USER,
            {"op": "create_story", "project": "DEMO", "epic": "DEMO-1"},
        ),
        ("functional", NEED_ORIGIN, AF_USER, {"op": "create_story", "project": "DEMO", "epic": ""}),
        (
            "qa",
            STORY_ORIGIN,
            QA_USER,
            {"op": "publish_suite", "project": "DEMO", "story": "DEMO-3", "cases": "2"},
        ),
    ],
    ids=["evolucion", "epica", "necesidad", "qa"],
)
def test_review_plan_first_operation_by_origin(
    tmp_path: Path, mode: str, origin: Origin, user: str, first_op: dict[str, str]
) -> None:
    """T-51 · RF-31: la primera operación del plan depende del origen y del modo."""
    graph = build_graph(fake_container(tmp_path))
    payload = _payload(_start(graph, _config(), mode, origin, user))
    assert payload["plan"][0] == first_op


def test_review_plan_links_never_include_the_epic(tmp_path: Path) -> None:
    """T-51 · PA-38: los vínculos del plan mostrado nunca apuntan a la épica."""
    graph = build_graph(fake_container(tmp_path))
    plan = _payload(_start(graph, _config(), origin=EPIC_ORIGIN))["plan"]
    links = [step for step in plan if step["op"] == "link"]
    assert links, "el fake propone al menos una HU afectada (DEMO-2)"
    assert all(step["to"] != "DEMO-1" and step["from"] == "(HU nueva)" for step in links)


def test_review_plan_matches_live_writes(tmp_path: Path) -> None:
    """T-51 · RF-31: en live, lo escrito en Jira coincide con el plan mostrado."""
    container = fake_container(tmp_path, publish_mode="live")
    graph = build_graph(container)
    config = _config()
    plan = _payload(_start(graph, config, origin=EPIC_ORIGIN))["plan"]

    final = graph.invoke(_approve(graph, config), config)

    writes = _tracker(container).writes
    assert [op for op, _ in writes] == [step["op"] for step in plan]
    new_key = final["published_keys"][0]
    assert [d["to"] for op, d in writes if op == "link"] == [
        s["to"] for s in plan if s["op"] == "link"
    ]
    assert all(d["from"] == new_key for op, d in writes if op == "link")


def test_review_payload_exposes_plan_without_writing(tmp_path: Path) -> None:
    """Principio 1 · T-51: calcular el plan en la revisión no escribe en Jira."""
    container = fake_container(tmp_path, publish_mode="live")
    _start(build_graph(container), _config(), origin=EPIC_ORIGIN)
    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0


# --- 5 · decisión edit ----------------------------------------------------------------------


def test_decisions_include_edit() -> None:
    """T-51 · RF-32: `edit` es una decisión válida."""
    assert DECISIONS == ("iterate", "edit", "approve", "discard")


def test_edit_story_creates_new_version_without_calling_llm(tmp_path: Path) -> None:
    """T-51 · RF-32: editar → versión + 1, IN_REVIEW, mismo id/modelo/prompt, sin LLM."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    calls_before = len(_llm(container).calls)
    edited = _edited_story(first["artifact"]["content"])

    second = _payload(graph.invoke(_edit_command(edited, first["fingerprint"]), config))

    assert len(_llm(container).calls) == calls_before
    artifact = second["artifact"]
    assert artifact["id"] == first["artifact"]["id"]
    assert artifact["version"] == second["version"] == 2
    assert artifact["status"] == ArtifactStatus.IN_REVIEW.value
    assert artifact["content"]["title"] == EDITED_TITLE
    assert artifact["content"]["description"] == EDITED_DESCRIPTION
    assert artifact["model_used"] == first["artifact"]["model_used"]
    assert artifact["prompt_version"] == first["artifact"]["prompt_version"]
    assert second["fingerprint"] != first["fingerprint"]
    assert len(second["fingerprint"]) == 64
    assert second["plan"] == first["plan"]
    assert graph.get_state(config).next == ("human_review",)
    assert graph.get_state(config).values["decision"] == "edit"
    assert _tracker(container).writes == []


def test_edit_is_audited_as_iterate_with_edited_flag(tmp_path: Path) -> None:
    """T-51 · RF-35: la edición se audita como `iterate` con `edited=True`, sin contenido."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    graph.invoke(
        _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]), config
    )

    create, edit = _audit(container).entries(UUID(first["artifact"]["id"]))
    assert create.action == "create"
    assert edit.action == "iterate"
    assert edit.user == AF_USER
    assert edit.detail == {
        "version": 2,
        "status": ArtifactStatus.IN_REVIEW.value,
        "edited": True,
        "prompt_version": first["artifact"]["prompt_version"],
    }
    assert EDITED_TITLE not in str(edit.model_dump())


def test_edit_saves_the_new_version(tmp_path: Path) -> None:
    """T-51 · T-19: la versión editada se guarda en el VersionSink."""
    spy = SpyVersionSink()
    container = fake_container(tmp_path, versions=spy)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    graph.invoke(
        _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]), config
    )

    assert [(a.version, a.status) for a in spy.saved] == [
        (1, ArtifactStatus.IN_REVIEW),
        (2, ArtifactStatus.IN_REVIEW),
    ]
    assert isinstance(spy.saved[-1].content, UserStory)
    assert spy.saved[-1].content.title == EDITED_TITLE


def test_edit_with_feedback_appends_it_and_blank_is_ignored(tmp_path: Path) -> None:
    """T-51 · RF-20: el feedback opcional de la edición se añade; en blanco, no."""
    graph = build_graph(fake_container(tmp_path))
    config = _config()
    first = _payload(_start(graph, config))
    second = _payload(
        graph.invoke(
            _edit_command(
                _edited_story(first["artifact"]["content"]), first["fingerprint"], "Nota ficticia"
            ),
            config,
        )
    )
    assert graph.get_state(config).values["feedback"] == ["Nota ficticia"]

    third_content = _edited_story(second["artifact"]["content"], title="Otro titulo ficticio")
    graph.invoke(_edit_command(third_content, second["fingerprint"], "   "), config)
    assert graph.get_state(config).values["feedback"] == ["Nota ficticia"]


def test_edit_evolution_recomputes_diffs_against_baseline_and_keeps_affected(
    tmp_path: Path,
) -> None:
    """T-51 · RF-32 · T-19: en una evolución, el diff se recalcula frente a la baseline."""
    container = fake_container(tmp_path, llm=_evolving_llm())
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    impact_before = first["impact"]
    assert [d["field"] for d in impact_before["diffs"]] == ["title"]
    edited = _edited_story(first["artifact"]["content"], description=EDITED_DESCRIPTION)

    second = _payload(graph.invoke(_edit_command(edited, first["fingerprint"]), config))

    saved = container.state_store.load(first["artifact"]["id"])
    assert saved and saved.get("baseline")
    baseline = UserStory.model_validate(saved["baseline"])
    expected = diff_stories(baseline, UserStory.model_validate(edited))
    assert second["impact"]["diffs"] == [d.model_dump(mode="json") for d in expected]
    assert {d["field"] for d in second["impact"]["diffs"]} == {"title", "description"}
    assert second["impact"]["affected"] == impact_before["affected"]
    assert second["impact"]["regression_notes"] == impact_before["regression_notes"]


def test_edit_evolution_back_to_baseline_leaves_no_diffs(tmp_path: Path) -> None:
    """T-51 (límite): si la edición deja la HU igual que en Jira, el diff queda vacío."""
    container = fake_container(tmp_path, llm=_evolving_llm())
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    baseline = container.state_store.load(first["artifact"]["id"])["baseline"]  # type: ignore[index]

    content = _edited_story(first["artifact"]["content"], title=baseline["title"])
    second = _payload(graph.invoke(_edit_command(content, first["fingerprint"]), config))

    assert second["impact"]["diffs"] == []
    assert second["impact"]["affected"] == first["impact"]["affected"]


@pytest.mark.parametrize("origin", [EPIC_ORIGIN, NEED_ORIGIN], ids=["epica", "necesidad"])
def test_edit_new_story_keeps_impact_unchanged(tmp_path: Path, origin: Origin) -> None:
    """T-51: en una HU nueva, editar no cambia el impacto (no hay baseline de Jira)."""
    graph = build_graph(fake_container(tmp_path))
    config = _config()
    first = _payload(_start(graph, config, origin=origin))
    edited = _edited_story(first["artifact"]["content"])

    second = _payload(graph.invoke(_edit_command(edited, first["fingerprint"]), config))

    assert second["impact"] == first["impact"]
    assert second["artifact"]["content"]["jira_key"] is None
    assert second["plan"] == first["plan"]


def test_edit_then_approve_publishes_edited_story_live(tmp_path: Path) -> None:
    """T-51 · RF-32 · Principio 1: edit → approve (huella nueva) → publish de lo editado."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    graph.invoke(
        _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]), config
    )
    assert _pending(graph, config)["fingerprint"] != first["fingerprint"]

    final = graph.invoke(_approve(graph, config), config)

    artifact: Artifact = final["artifact"]
    assert artifact.status is ArtifactStatus.PUBLISHED
    assert artifact.version == 2
    assert isinstance(artifact.content, UserStory)
    assert artifact.content.title == EDITED_TITLE
    tracker = _tracker(container)
    assert tracker.writes[0] == ("update_story", {"key": "DEMO-3"})
    assert tracker.issues["DEMO-3"].description_text == EDITED_DESCRIPTION
    memory = (tmp_path / "DEMO-3.md").read_text(encoding="utf-8")
    assert "version: 2" in memory
    actions = [e.action for e in _audit(container).entries(artifact.id)]
    assert actions == ["create", "iterate", "approve", "publish"]


def test_edit_then_approve_creates_edited_story_from_epic(tmp_path: Path) -> None:
    """T-51 · RF-32: desde épica, la HU creada en Jira lleva el contenido editado."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config, origin=EPIC_ORIGIN))
    graph.invoke(
        _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]), config
    )

    final = graph.invoke(_approve(graph, config), config)

    new_key = final["published_keys"][0]
    issue = _tracker(container).issues[new_key]
    assert issue.summary.endswith(EDITED_TITLE)
    assert issue.description_text == EDITED_DESCRIPTION
    assert issue.parent_key == "DEMO-1"


def test_approve_with_old_fingerprint_after_edit_is_rejected(tmp_path: Path) -> None:
    """T-51 · Principio 1 (negativo): tras editar, la huella de la v1 ya no aprueba nada."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    second = _payload(
        graph.invoke(
            _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]),
            config,
        )
    )
    before = _snapshot(container, graph, config)

    rejected = _rejected(
        graph,
        config,
        Command(resume={"decision": "approve", "fingerprint": first["fingerprint"]}),
        second,
    )

    assert "versión revisada" in rejected["error"]
    assert _snapshot(container, graph, config) == before
    assert graph.get_state(config).values["artifact"].status is ArtifactStatus.IN_REVIEW


def test_edit_twice_produces_versions_two_and_three(tmp_path: Path) -> None:
    """T-51 · RF-32: dos ediciones seguidas → v2 y v3, cada una con su huella."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    calls = len(_llm(container).calls)
    second = _payload(
        graph.invoke(
            _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]),
            config,
        )
    )
    third_content = _edited_story(second["artifact"]["content"], title="Tercera version ficticia")

    third = _payload(graph.invoke(_edit_command(third_content, second["fingerprint"]), config))

    assert [first["version"], second["version"], third["version"]] == [1, 2, 3]
    assert len({first["fingerprint"], second["fingerprint"], third["fingerprint"]}) == 3
    assert third["artifact"]["content"]["title"] == "Tercera version ficticia"
    assert third["artifact"]["content"]["description"] == EDITED_DESCRIPTION
    assert len(_llm(container).calls) == calls
    final = graph.invoke(_approve(graph, config), config)
    assert final["artifact"].version == 3
    assert final["artifact"].content.title == "Tercera version ficticia"
    assert final["artifact"].status is ArtifactStatus.PUBLISHED


def test_edit_with_fingerprint_of_previous_edit_is_rejected(tmp_path: Path) -> None:
    """T-51 (negativo): la huella de la v2 no sirve para editar la v3."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    second = _payload(
        graph.invoke(
            _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]),
            config,
        )
    )
    third_content = _edited_story(second["artifact"]["content"], title="Tercera version ficticia")
    third = _payload(graph.invoke(_edit_command(third_content, second["fingerprint"]), config))
    before = _snapshot(container, graph, config)

    rejected = _rejected(
        graph,
        config,
        _edit_command(_edited_story(third_content, title="X ficticia"), second["fingerprint"]),
        third,
    )

    assert "no parte de la versión revisada" in rejected["error"]
    assert _snapshot(container, graph, config) == before
    assert graph.get_state(config).values["artifact"].version == 3


def test_edit_then_iterate_sends_edited_version_to_llm(tmp_path: Path) -> None:
    """T-51 · RF-20: tras editar, iterar evoluciona la versión editada (v3)."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    second = _payload(
        graph.invoke(
            _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]),
            config,
        )
    )

    third = _payload(
        graph.invoke(Command(resume={"decision": "iterate", "feedback": "Ajuste ficticio"}), config)
    )

    story_calls = [c for c in _llm(container).calls if c["schema"] is UserStory]
    last_user = "\n".join(m.content for m in story_calls[-1]["messages"] if m.role == "user")
    assert "<hu_actual>" in last_user
    assert EDITED_TITLE in last_user
    assert EDITED_DESCRIPTION in last_user
    assert third["version"] == 3
    assert third["artifact"]["id"] == second["artifact"]["id"]
    assert third["fingerprint"] != second["fingerprint"]
    assert third["error"] is None


def test_edit_test_suite_then_approve_publishes_edited_cases(tmp_path: Path) -> None:
    """T-51 · RF-32 (QA): editar la suite → v2 sin LLM; aprobar publica los casos editados."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config, mode="qa", user=QA_USER))
    calls = len(_llm(container).calls)
    content = copy.deepcopy(first["artifact"]["content"])
    content["cases"][0]["title"] = "Caso editado a mano (ficticio)"

    second = _payload(graph.invoke(_edit_command(content, first["fingerprint"]), config))

    assert len(_llm(container).calls) == calls
    assert second["version"] == 2
    assert second["artifact"]["type"] == first["artifact"]["type"]
    assert second["impact"] == first["impact"]
    assert second["plan"] == first["plan"]
    assert second["artifact"]["content"]["story_jira_key"] == "DEMO-3"

    final = graph.invoke(_approve(graph, config), config)

    assert final["artifact"].version == 2
    summaries = [c.summary for c in _testmgmt(container).list_cases("DEMO-3")]
    assert "[CP-01] Caso editado a mano (ficticio)" in summaries


# --- 6 · respuestas rechazadas: nueva pausa con `error`, sin efectos (D-1) -------------------


def test_first_review_pause_has_error_none(tmp_path: Path) -> None:
    """T-51 · D-1: la primera pausa lleva siempre la clave `error` a None."""
    payload = _payload(_start(build_graph(fake_container(tmp_path)), _config()))
    assert "error" in payload
    assert payload["error"] is None


@pytest.mark.parametrize(
    "fingerprint", [None, "0" * 64, ""], ids=["sin_huella", "huella_falsa", "huella_vacia"]
)
def test_edit_with_wrong_fingerprint_is_rejected(tmp_path: Path, fingerprint: str | None) -> None:
    """T-51 (negativo): sin la huella de la versión revisada, la edición se rechaza sin efectos."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    before = _snapshot(container, graph, config)

    rejected = _rejected(
        graph,
        config,
        _edit_command(_edited_story(first["artifact"]["content"]), fingerprint),
        first,
    )

    assert "La edición no parte de la versión revisada" in rejected["error"]
    assert _snapshot(container, graph, config) == before
    assert graph.get_state(config).values["artifact"].status is ArtifactStatus.IN_REVIEW


@pytest.mark.parametrize(
    "content", [None, "texto libre", ["lista"], 42], ids=["nulo", "texto", "lista", "numero"]
)
def test_edit_with_non_dict_content_is_rejected(tmp_path: Path, content: object) -> None:
    """T-51 (negativo): el contenido editado tiene que ser el artefacto completo (dict)."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "contenido completo" in rejected["error"]
    assert _snapshot(container, graph, config) == before


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda c: c.pop("title"), "title"),
        (lambda c: c.update(title=""), "title"),
        (lambda c: c.update(priority="inventada"), "priority"),
        (lambda c: c.update(acceptance_criteria=[]), "acceptance_criteria"),
    ],
    ids=["sin_titulo", "titulo_vacio", "prioridad", "sin_criterios"],
)
def test_edit_with_invalid_story_content_lists_fields_without_pydantic_dump(
    tmp_path: Path, mutate: Any, field: str
) -> None:
    """T-51 (negativo): contenido inválido → `error` con los campos, sin volcar pydantic."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    content = copy.deepcopy(first["artifact"]["content"])
    mutate(content)
    before = _snapshot(container, graph, config)

    message = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)["error"]

    assert message.startswith("El contenido editado no es válido; revisa: ")
    assert field in message
    for leak in (
        "pydantic",
        "validation error",
        "Field required",
        "input_value",
        "errors.pydantic",
    ):
        assert leak not in message
    assert _snapshot(container, graph, config) == before


def test_edit_with_model_level_error_reports_generic_field(tmp_path: Path) -> None:
    """T-51 (negativo): un error del validador del modelo (IDs repetidos) → «contenido»."""
    graph = build_graph(fake_container(tmp_path))
    config = _config()
    first = _payload(_start(graph, config))
    content = copy.deepcopy(first["artifact"]["content"])
    content["acceptance_criteria"][1]["id"] = content["acceptance_criteria"][0]["id"]

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "revisa: contenido" in rejected["error"]


def test_edit_with_invalid_suite_content_is_rejected(tmp_path: Path) -> None:
    """T-51 (negativo, QA): una suite inválida se rechaza con los campos a revisar."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config, mode="qa", user=QA_USER))
    content = copy.deepcopy(first["artifact"]["content"])
    content.pop("cases")
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert re.search(r"no es válido; revisa: .*cases", rejected["error"])
    assert _snapshot(container, graph, config) == before


@pytest.mark.parametrize(
    ("origin", "changes", "field"),
    [
        (STORY_ORIGIN, {"jira_key": "DEMO-4"}, "jira_key"),
        (STORY_ORIGIN, {"jira_key": None}, "jira_key"),
        (STORY_ORIGIN, {"internal_id": "HU-99"}, "internal_id"),
        (EPIC_ORIGIN, {"jira_key": "DEMO-4"}, "jira_key"),
    ],
    ids=["cambia_clave", "quita_clave", "cambia_id_interno", "epica_pone_clave"],
)
def test_edit_cannot_change_story_identity_fields(
    tmp_path: Path, origin: Origin, changes: dict[str, Any], field: str
) -> None:
    """T-51 · Trazabilidad (negativo): `jira_key` e `internal_id` no se cambian al editar."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config, origin=origin))
    content = _edited_story(first["artifact"]["content"], title=EDITED_TITLE, **changes)
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert f"El campo {field} no se puede cambiar al editar" in rejected["error"]
    assert _snapshot(container, graph, config) == before


def test_edit_cannot_change_suite_story_key(tmp_path: Path) -> None:
    """T-51 · Trazabilidad (negativo, QA): `story_jira_key` no se cambia al editar."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config, mode="qa", user=QA_USER))
    content = copy.deepcopy(first["artifact"]["content"])
    content["story_jira_key"] = "DEMO-4"
    content["cases"][0]["title"] = "Caso editado (ficticio)"
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "El campo story_jira_key no se puede cambiar" in rejected["error"]
    assert _snapshot(container, graph, config) == before
    assert _testmgmt(container).publish_calls == 0


@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_edit_with_identical_content_is_rejected(tmp_path: Path, mode: str) -> None:
    """T-51 (negativo): una edición que no cambia nada se rechaza sin efectos."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    user = QA_USER if mode == "qa" else AF_USER
    first = _payload(_start(graph, config, mode=mode, user=user))
    before = _snapshot(container, graph, config)

    rejected = _rejected(
        graph,
        config,
        _edit_command(copy.deepcopy(first["artifact"]["content"]), first["fingerprint"]),
        first,
    )

    assert "no cambia nada" in rejected["error"]
    assert _snapshot(container, graph, config) == before


def test_failed_edit_keeps_review_open_for_a_valid_edit(tmp_path: Path) -> None:
    """T-51 · D-1: tras una edición rechazada, la revisión sigue abierta y se puede editar."""
    graph = build_graph(fake_container(tmp_path))
    config = _config()
    first = _payload(_start(graph, config))
    _rejected(graph, config, _edit_command("no es un dict", first["fingerprint"]), first)

    second = _payload(
        graph.invoke(
            _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]),
            config,
        )
    )

    assert second["version"] == 2
    assert second["fingerprint"] != first["fingerprint"]
    assert second["artifact"]["content"]["title"] == EDITED_TITLE


def test_several_rejections_then_valid_edit_and_approve_publish(tmp_path: Path) -> None:
    """T-51 · D-1: varios rechazos seguidos no bloquean; edit y approve válidos funcionan."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    bad_answers = [
        _edit_command("no es un dict", first["fingerprint"]),
        Command(resume={"decision": "approve", "fingerprint": "0" * 64}),
        Command(resume={"decision": "publicar"}),
        _edit_command(copy.deepcopy(first["artifact"]["content"]), first["fingerprint"]),
    ]
    errors = [_rejected(graph, config, answer, first)["error"] for answer in bad_answers]
    assert [("contenido completo" in errors[0]), ("versión revisada" in errors[1])] == [True, True]
    assert "Decisión no válida" in errors[2] and "no cambia nada" in errors[3]
    assert _tracker(container).writes == []
    assert [e.action for e in _audit(container).entries(UUID(first["artifact"]["id"]))] == [
        "create"
    ]

    second = _payload(
        graph.invoke(
            _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]),
            config,
        )
    )
    assert second["version"] == 2
    assert second["error"] is None
    _rejected(
        graph,
        config,
        Command(resume={"decision": "approve", "fingerprint": first["fingerprint"]}),
        second,
    )

    final = graph.invoke(_approve(graph, config), config)

    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert final["artifact"].version == 2
    assert final["artifact"].content.title == EDITED_TITLE
    assert _tracker(container).writes[0] == ("update_story", {"key": "DEMO-3"})
    actions = [e.action for e in _audit(container).entries(final["artifact"].id)]
    assert actions == ["create", "iterate", "approve", "publish"]


def test_several_rejections_then_valid_approve_publishes_v1(tmp_path: Path) -> None:
    """T-51 · D-1: tras rechazos, un approve con la huella correcta publica la versión revisada."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    for answer in (
        Command(resume={"decision": "approve"}),
        Command(resume={"decision": "approve", "fingerprint": "f" * 64}),
    ):
        _rejected(graph, config, answer, first)

    final = graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": first["fingerprint"]}), config
    )

    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert final["artifact"].version == 1
    assert final["published_keys"] == ["DEMO-3"]


def test_error_is_cleared_in_the_pause_of_the_next_version(tmp_path: Path) -> None:
    """T-51 · D-1: tras un rechazo, la pausa de la versión siguiente vuelve a `error: None`."""
    graph = build_graph(fake_container(tmp_path))
    config = _config()
    first = _payload(_start(graph, config))
    rejected = _rejected(graph, config, Command(resume={"decision": "nada"}), first)
    assert rejected["error"]

    second = _payload(
        graph.invoke(
            _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]),
            config,
        )
    )
    assert second["error"] is None
    assert _pending(graph, config)["error"] is None

    third = _payload(
        graph.invoke(Command(resume={"decision": "iterate", "feedback": "Ajuste ficticio"}), config)
    )
    assert third["version"] == 3
    assert third["error"] is None


def test_rejected_approve_leaves_no_approval_in_ledger(tmp_path: Path) -> None:
    """T-51 · D-1 · Principio 1: un approve rechazado no deja aprobación ni publicación."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))

    _rejected(
        graph, config, Command(resume={"decision": "approve", "fingerprint": "0" * 64}), first
    )

    state = graph.get_state(config).values
    target = _target(state, config)
    assert container.approvals.find(state["artifact"], target) is None
    approved = state["artifact"].model_copy(update={"status": ArtifactStatus.APPROVED})
    assert container.approvals.find(approved, target) is None
    assert container.approvals.was_published(state["artifact"]) is False
    assert "approve" not in [e.action for e in _audit(container).entries(state["artifact"].id)]
    assert _tracker(container).writes == []


def test_edit_then_discard_ends_without_writes(tmp_path: Path) -> None:
    """T-51 · Principio 1: editar y luego descartar termina sin escribir en Jira."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    graph.invoke(
        _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]), config
    )

    final = graph.invoke(Command(resume={"decision": "discard"}), config)

    assert final["artifact"].status is ArtifactStatus.DISCARDED
    assert final["artifact"].version == 2
    assert _tracker(container).writes == []
    assert list(tmp_path.glob("*.md")) == []


def test_edit_offers_only_the_edited_version_in_the_ledger(tmp_path: Path) -> None:
    """T-51 · Principio 1: la versión editada queda ofrecida en el registro de aprobaciones."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    graph.invoke(
        _edit_command(_edited_story(first["artifact"]["content"]), first["fingerprint"]), config
    )

    state = graph.get_state(config).values
    target = _target(state, config)
    assert container.approvals.is_offered(state["artifact"], target)


# --- límites del contrato (revisión de seguridad de T-51) --------------------------------------


def test_rejections_beyond_the_limit_end_the_review(tmp_path: Path) -> None:
    """T-51: una pausa admite MAX_REVIEW_REJECTIONS rechazos; después falla sin aprobar nada."""
    from core.graph.nodes import MAX_REVIEW_REJECTIONS

    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    bad = Command(resume={"decision": "approve", "fingerprint": "0" * 64})
    for _ in range(MAX_REVIEW_REJECTIONS):
        assert _payload(graph.invoke(bad, config))["error"]

    with pytest.raises(ValueError, match="Demasiadas respuestas rechazadas"):
        graph.invoke(bad, config)
    artifact = Artifact.model_validate(first["artifact"])
    target = _target(graph.get_state(config).values, config)
    assert container.approvals.find(artifact, target) is None
    assert _tracker(container).writes == []


def test_ledger_rejection_fails_closed_without_retry(tmp_path: Path) -> None:
    """T-51: un rechazo del registro de aprobaciones no se reintenta: falla cerrado."""
    from core.approvals import ApprovalError

    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))
    artifact = Artifact.model_validate(first["artifact"])
    # La oferta desaparece del registro (p. ej., otro proceso la consumió).
    container.approvals._offers.pop(str(artifact.id))

    with pytest.raises(ApprovalError):
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": first["fingerprint"]}), config
        )
    assert _tracker(container).writes == []


def test_invalid_decision_message_is_truncated(tmp_path: Path) -> None:
    """T-51: el texto de una decisión no válida se recorta a 50 caracteres en el error."""
    graph = build_graph(fake_container(tmp_path))
    config = _config()
    _start(graph, config)
    paused = _payload(graph.invoke(Command(resume={"decision": "x" * 500}), config))
    assert "x" * 50 in paused["error"]
    assert "x" * 51 not in paused["error"]


@pytest.mark.parametrize(
    "refs",
    [
        pytest.param([f"DOC-{n:03d}" for n in range(51)], id="demasiadas"),
        pytest.param(["texto libre con espacios"], id="texto_libre"),
        pytest.param(["D" * 101], id="demasiado_larga"),
    ],
)
def test_initial_state_rejects_invalid_excluded_sources(refs: list[str]) -> None:
    """T-51: como máximo 50 referencias con formato de clave o id (nunca texto libre)."""
    with pytest.raises(ValueError):
        initial_state(AF_USER, "functional", STORY_ORIGIN, refs)


def test_initial_state_accepts_fifty_reference_like_sources() -> None:
    refs = [f"DOC-{n:02d}" for n in range(48)] + ["memoria-DEMO-2", "DEMO-2"]
    state = initial_state(AF_USER, "functional", STORY_ORIGIN, refs)
    assert len(state["excluded_sources"]) == 50
