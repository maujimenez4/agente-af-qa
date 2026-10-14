"""PA-485 (RF-39, D-07 revisada) · Memoria .md de los artefactos de QA.

Al publicar de verdad una suite se genera su memoria de QA (`qa/<CLAVE>.md`, documento
`memoria-qa-<CLAVE>`), aparte de la de la HU; en simulación o a medias, no. Las tareas de QA la
recuperan con prioridad y la redacción de HU antepone las memorias funcionales. Datos ficticios.
"""

from pathlib import Path
from typing import Any

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.base import Chunk, TaskType
from core.container import Container
from core.context.service import build_context_service
from core.graph import Origin, build_graph, initial_state
from core.memory.generator import (
    QA_MEMORY_PROMPT,
    STORY_MEMORY_PROMPT,
    LLMMemoryGenerator,
    MemorySynthesisError,
    prompt_name,
)
from core.rag.prompts import load_prompt
from schemas.common import ArtifactStatus, ArtifactType
from schemas.memory import Memory
from tests.fakes.container import fake_container
from tests.fakes.llm import renewal_test_suite
from tests.fakes.memory_generator import FakeMemoryGenerator
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore
from tests.unit.test_memory_generator import _artifact, _llm, _suite_memory

QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}


def _store(container: Container) -> FakeVectorStore:
    store = container.vector_store
    assert isinstance(store, FakeVectorStore)
    return store


def _memory_docs(container: Container) -> dict[str, list[Chunk]]:
    docs: dict[str, list[Chunk]] = {}
    for chunk in _store(container).chunks.values():
        if chunk.metadata.get("category") == "memoria":
            docs.setdefault(chunk.document_id, []).append(chunk)
    return docs


def _publish_suite(graph: CompiledStateGraph, thread: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread}}
    graph.invoke(initial_state(QA_USER, "qa", STORY_ORIGIN), config)
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    fingerprint = task.interrupts[-1].value["fingerprint"]
    return graph.invoke(Command(resume={"decision": "approve", "fingerprint": fingerprint}), config)


# --- Cuándo -------------------------------------------------------------------------------------


def test_real_publication_of_suite_generates_and_indexes_qa_memory(tmp_path: Path) -> None:
    container = fake_container(tmp_path, publish_mode="live")
    final = _publish_suite(build_graph(container), "hilo-qa-memoria")

    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    path = tmp_path / "qa" / "DEMO-3.md"
    assert path.is_file() and "artifact_type: test_suite" in path.read_text(encoding="utf-8")
    assert not (tmp_path / "DEMO-3.md").exists()  # la de la HU no se escribe
    (chunk,) = _memory_docs(container)["memoria-qa-DEMO-3"]
    assert chunk.metadata == {
        "category": "memoria",
        "related_key": "DEMO-3",
        "artifact_type": "test_suite",
    }
    assert chunk.content == path.read_text(encoding="utf-8")


def test_simulated_publication_of_suite_has_no_memory(tmp_path: Path) -> None:
    container = fake_container(tmp_path, publish_mode="simulation")
    final = _publish_suite(build_graph(container), "hilo-qa-simulada")

    assert final["artifact"].status is ArtifactStatus.APPROVED
    assert not (tmp_path / "qa").exists()
    assert _memory_docs(container) == {}
    assert container.memory_generator.generated == []  # type: ignore[attr-defined]


def test_partially_published_suite_has_no_memory(tmp_path: Path) -> None:
    """Jira no confirmó todas las subtareas: la suite no está publicada y no hay memoria."""
    container = fake_container(
        tmp_path, publish_mode="live", test_management=FakeTestManagement(fail_case_ids={"CP-02"})
    )
    final = _publish_suite(build_graph(container), "hilo-qa-parcial")

    assert final["artifact"].status is ArtifactStatus.APPROVED
    assert _memory_docs(container) == {}


class FailingMemory(FakeMemoryGenerator):
    def generate(self, artifact: Any) -> Memory:
        raise MemorySynthesisError("No se pudo generar una memoria válida de DEMO-3 (ficticio).")


def test_memory_failure_does_not_undo_the_publication(tmp_path: Path) -> None:
    testmgmt = FakeTestManagement()
    container = fake_container(
        tmp_path, publish_mode="live", test_management=testmgmt, memory_generator=FailingMemory()
    )
    graph = build_graph(container)

    with pytest.raises(MemorySynthesisError):
        _publish_suite(graph, "hilo-qa-memoria-falla")

    assert len(testmgmt.list_cases("DEMO-3")) == 2  # las subtareas siguen en Jira
    artifact = graph.get_state({"configurable": {"thread_id": "hilo-qa-memoria-falla"}}).values[
        "artifact"
    ]
    assert artifact.status is ArtifactStatus.PUBLISHED
    assert container.approvals.was_published(artifact)
    assert _memory_docs(container) == {}


# --- Reindexado (RF-38) -------------------------------------------------------------------------


def test_republishing_replaces_qa_memory_and_keeps_functional_one(tmp_path: Path) -> None:
    container = fake_container(tmp_path, publish_mode="live")
    functional = Chunk(
        id="memoria-DEMO-3-0",
        document_id="memoria-DEMO-3",
        ordinal=0,
        content="Memoria funcional ficticia de DEMO-3.",
        embedding=container.embeddings.embed(["Memoria funcional ficticia de DEMO-3."])[0],
        metadata={"category": "memoria", "related_key": "DEMO-3"},
    )
    _store(container).upsert([functional])
    graph = build_graph(container)

    _publish_suite(graph, "hilo-qa-uno")
    second = _publish_suite(graph, "hilo-qa-dos")  # otra suite (CP-03…), PA-450

    docs = _memory_docs(container)
    assert set(docs) == {"memoria-DEMO-3", "memoria-qa-DEMO-3"}
    assert docs["memoria-DEMO-3"] == [functional]
    (qa,) = docs["memoria-qa-DEMO-3"]
    generated = container.memory_generator.generated  # type: ignore[attr-defined]
    assert len(generated) == 2  # una por publicación; el índice guarda solo la última
    assert qa.content == generated[-1].to_markdown()
    assert second["artifact"].content.cases[0].internal_id == "CP-03"
    assert [p.name for p in (tmp_path / "qa").glob("*.md")] == ["DEMO-3.md"]


# --- Recuperación -------------------------------------------------------------------------------

QUERY = "renovar préstamo biblioteca casos de prueba"


def _seed_memories(container: Container) -> None:
    def chunk(document_id: str, text: str, **meta: str) -> Chunk:
        (vector,) = container.embeddings.embed([text])
        return Chunk(
            id=f"{document_id}-0",
            document_id=document_id,
            ordinal=0,
            content=text,
            embedding=vector,
            metadata={"category": "memoria", "related_key": "DEMO-3", **meta},
        )

    _store(container).upsert(
        [
            # La de QA se parece más a la consulta: por puntuación iría primero.
            chunk("memoria-qa-DEMO-3", QUERY + " CP-01", artifact_type="test_suite"),
            chunk("memoria-DEMO-3", "renovar préstamo"),
        ]
    )


def _memory_order(container: Container, task: TaskType | None) -> list[str]:
    service = build_context_service(container, "DEMO", task)
    results = service._rag_context(QUERY, set())
    return [r.chunk.document_id for r in results if r.chunk.metadata.get("category") == "memoria"]


def test_qa_tasks_put_qa_memories_first(tmp_path: Path) -> None:
    container = fake_container(tmp_path)
    _seed_memories(container)
    assert _memory_order(container, TaskType.GENERATE_TESTS)[:2] == [
        "memoria-qa-DEMO-3",
        "memoria-DEMO-3",
    ]


@pytest.mark.parametrize(
    "task", [TaskType.GENERATE_STORY, TaskType.EVOLVE_STORY, TaskType.REVIEW_STORY]
)
def test_story_tasks_do_not_put_qa_memories_before_functional_ones(
    tmp_path: Path, task: TaskType
) -> None:
    container = fake_container(tmp_path)
    _seed_memories(container)
    assert _memory_order(container, task)[:2] == ["memoria-DEMO-3", "memoria-qa-DEMO-3"]


def test_without_task_memories_keep_todays_order(tmp_path: Path) -> None:
    """Sin tarea (p. ej. el panel de fuentes), el orden de siempre: memorias por puntuación."""
    container = fake_container(tmp_path)
    _seed_memories(container)
    assert _memory_order(container, None)[:2] == ["memoria-qa-DEMO-3", "memoria-DEMO-3"]


# --- Contenido y validación ---------------------------------------------------------------------


def test_suite_uses_its_own_prompt_and_story_keeps_the_old_one() -> None:
    assert prompt_name(_artifact(renewal_test_suite())) == QA_MEMORY_PROMPT
    assert prompt_name(_artifact()) == STORY_MEMORY_PROMPT
    prompt = load_prompt(QA_MEMORY_PROMPT)
    assert prompt.version == "1" and "story_jira_key" in prompt.text

    llm = _llm(_suite_memory())
    LLMMemoryGenerator(llm).generate(_artifact(renewal_test_suite()))
    assert "suite de pruebas" in llm.calls[0]["messages"][0].content


def test_invented_case_is_rejected() -> None:
    bad = _suite_memory(
        acceptance_criteria=[
            "CA-01: Renovación permitida → CP-01, CP-09.",
            "CA-02: Renovación rechazada → CP-02.",
        ]
    )
    with pytest.raises(MemorySynthesisError, match="criterios, reglas y casos"):
        LLMMemoryGenerator(_llm(bad)).generate(_artifact(renewal_test_suite()))


def test_missing_case_is_rejected() -> None:
    bad = _suite_memory(
        acceptance_criteria=["CA-01: → CP-01.", "CA-02: sin su caso."],
        business_rules=["RN-01: → CP-01.", "RN-02: sin su caso."],
    )
    with pytest.raises(MemorySynthesisError):
        LLMMemoryGenerator(_llm(bad)).generate(_artifact(renewal_test_suite()))


def test_personal_data_is_rejected() -> None:
    bad = _suite_memory(decisions=["Datos de prueba: el DNI 12345678Z para CP-01."])
    with pytest.raises(MemorySynthesisError):
        LLMMemoryGenerator(_llm(bad)).generate(_artifact(renewal_test_suite()))


def test_valid_suite_memory_after_one_retry() -> None:
    bad = _suite_memory(acceptance_criteria=["CA-01: → CP-01, CP-09.", "CA-02: → CP-02."])
    llm = _llm(bad, _suite_memory())
    memory = LLMMemoryGenerator(llm).generate(_artifact(renewal_test_suite()))
    assert memory.artifact_type is ArtifactType.TEST_SUITE
    assert len(llm.calls) == 2


# --- Regresión de la memoria de HU --------------------------------------------------------------


def test_story_memory_is_unchanged(tmp_path: Path) -> None:
    """La HU sigue en `<CLAVE>.md` y `memoria-<CLAVE>`, sin `artifact_type` en los metadatos."""
    container = fake_container(tmp_path, publish_mode="live")
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-hu-memoria"}}
    graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    fingerprint = task.interrupts[-1].value["fingerprint"]
    graph.invoke(Command(resume={"decision": "approve", "fingerprint": fingerprint}), config)

    assert (tmp_path / "DEMO-3.md").is_file()
    assert not (tmp_path / "qa").exists()
    (chunk,) = _memory_docs(container)["memoria-DEMO-3"]
    assert chunk.metadata == {"category": "memoria", "related_key": "DEMO-3"}
