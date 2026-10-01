"""Memoria real (`LLMMemoryGenerator`) en el grafo: publicar → memorizar → reindexar (T-33).

RF-36 (las 8 secciones en `data/memory/<clave>.md`), RF-38 (reindexado sin duplicados) y D-07.
Todo con los fakes de `tests/fakes/` y el dataset sintético; publicación en modo live de fakes.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.base import Message
from core.container import Container
from core.graph import Origin, build_graph, initial_state
from core.memory.generator import LLMMemoryGenerator, MemorySynthesisError
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus
from schemas.memory import Memory
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.vector_store import FakeVectorStore

AF_USER = "af-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
FEEDBACK = "Precisa el aviso de vencimiento (texto ficticio)."
SECTIONS = (
    "Objetivo",
    "Alcance",
    "Reglas de negocio",
    "Decisiones",
    "Dependencias",
    "Cambios",
    "Criterios de aceptación",
    "Referencias",
)


def _memory_builder(counter: dict[str, int], *, valid: bool = True) -> Any:
    """Respuesta del LLM para `Memory`; cambia el objetivo en cada llamada."""

    def build(_messages: list[Message]) -> Memory:
        counter["n"] += 1
        return Memory(
            artifact_type="test_suite",  # el generador lo corrige
            jira_key="OTRO-1",  # el generador lo corrige
            version=99,
            objective=f"Objetivo de la memoria {counter['n']} (ficticio).",
            scope="Renovación desde la ficha del préstamo.",
            business_rules=["RN-01: Máximo 2 renovaciones.", "RN-02: Sin reservas pendientes."],
            decisions=[],
            dependencies=["DEMO-2"],
            changes=[],
            acceptance_criteria=(
                ["CA-01: Renovación permitida.", "CA-02: Renovación rechazada."]
                if valid
                else ["CA-01: Renovación permitida.", "CA-77: Inventado."]
            ),
            references=["DEMO-3"],
        )

    return build


@pytest.fixture
def counter() -> dict[str, int]:
    return {"n": 0}


def _container(tmp_path: Path, counter: dict[str, int], *, valid: bool = True) -> Container:
    llm = FakeLLMProvider()
    llm.builders[Memory] = _memory_builder(counter, valid=valid)
    return fake_container(tmp_path, llm=llm, memory_generator=LLMMemoryGenerator(llm))


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"hilo-{uuid4()}"}}


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return Command(
        resume={"decision": "approve", "fingerprint": task.interrupts[0].value["fingerprint"]}
    )


def _publish(container: Container, *, iterations: int = 0) -> dict[str, Any]:
    graph = build_graph(container)
    config = _config()
    graph.invoke(initial_state(AF_USER, "functional", STORY_ORIGIN), config)  # type: ignore[arg-type]
    for _ in range(iterations):
        graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    return graph.invoke(_approve(graph, config), config)


def _store(container: Container) -> FakeVectorStore:
    assert isinstance(container.vector_store, FakeVectorStore)
    return container.vector_store


def _memory_chunks(container: Container) -> dict[str, Any]:
    return {
        chunk_id: chunk
        for chunk_id, chunk in _store(container).chunks.items()
        if chunk.metadata.get("category") == "memoria"
    }


def _sections(markdown: str) -> list[str]:
    return [line[3:] for line in markdown.splitlines() if line.startswith("## ")]


def test_publish_writes_memory_file_with_eight_sections(
    tmp_path: Path, counter: dict[str, int]
) -> None:
    """RF-36 · CA-00-04: al publicar se escribe data/memory/<clave>.md con las 8 secciones."""
    container = _container(tmp_path, counter)

    final = _publish(container)

    artifact: Artifact = final["artifact"]
    assert artifact.status is ArtifactStatus.PUBLISHED
    assert counter["n"] == 1
    memory_file = tmp_path / "DEMO-3.md"
    text = memory_file.read_text(encoding="utf-8")
    assert text.startswith("---\njira_key: DEMO-3\nartifact_type: user_story\nversion: 1\n---\n")
    assert _sections(text) == list(SECTIONS)
    assert "Objetivo de la memoria 1 (ficticio)." in text
    assert "- RN-01: Máximo 2 renovaciones." in text
    assert "- CA-02: Renovación rechazada." in text
    assert "OTRO-1" not in text
    assert list(tmp_path.glob("*.md")) == [memory_file]


def test_publish_indexes_memory_document_with_category(
    tmp_path: Path, counter: dict[str, int]
) -> None:
    """RF-38 · RF-51: la memoria se indexa como documento memoria-<clave>, categoría 'memoria'."""
    container = _container(tmp_path, counter)

    _publish(container)

    chunks = _memory_chunks(container)
    assert list(chunks) == ["memoria-DEMO-3-0"]
    chunk = chunks["memoria-DEMO-3-0"]
    assert chunk.document_id == "memoria-DEMO-3"
    assert chunk.metadata == {"category": "memoria", "related_key": "DEMO-3"}
    assert chunk.content == (tmp_path / "DEMO-3.md").read_text(encoding="utf-8")


def test_republishing_new_version_replaces_memory_without_duplicates(
    tmp_path: Path, counter: dict[str, int]
) -> None:
    """RF-38: una segunda versión publicada sustituye la memoria: un único documento, nuevo."""
    container = _container(tmp_path, counter)
    _publish(container)
    first = (tmp_path / "DEMO-3.md").read_text(encoding="utf-8")

    final = _publish(container, iterations=1)

    assert final["artifact"].version == 2
    assert counter["n"] == 2
    text = (tmp_path / "DEMO-3.md").read_text(encoding="utf-8")
    assert text != first
    assert "version: 2" in text and "(v2)" in text
    assert "Objetivo de la memoria 2 (ficticio)." in text
    chunks = _memory_chunks(container)
    assert list(chunks) == ["memoria-DEMO-3-0"]
    assert {c.document_id for c in chunks.values()} == {"memoria-DEMO-3"}
    assert chunks["memoria-DEMO-3-0"].content == text
    assert "Objetivo de la memoria 1" not in chunks["memoria-DEMO-3-0"].content
    # Los documentos del corpus siguen indexados.
    assert {"doc-reglamento-0", "doc-glosario-0"} <= set(_store(container).chunks)
    assert list(tmp_path.glob("*.md")) == [tmp_path / "DEMO-3.md"]


def test_memory_uses_synthesize_memory_calls_only_after_publish(
    tmp_path: Path, counter: dict[str, int]
) -> None:
    """Principio 1 · D-07: la memoria solo se sintetiza tras publicar (nada si no se aprueba)."""
    container = _container(tmp_path, counter)
    graph = build_graph(container)
    config = _config()
    graph.invoke(initial_state(AF_USER, "functional", STORY_ORIGIN), config)  # type: ignore[arg-type]

    graph.invoke(Command(resume={"decision": "discard"}), config)

    assert counter["n"] == 0
    assert _memory_chunks(container) == {}
    assert list(tmp_path.glob("*.md")) == []


def test_invalid_memory_after_publish_raises_and_writes_no_memory(
    tmp_path: Path, counter: dict[str, int]
) -> None:
    """T-33 (error): si la memoria no es válida tras el reintento no se escribe ni se indexa.

    La HU ya está publicada en Jira (publish va antes que memorize); el error sube al llamante.
    """
    container = _container(tmp_path, counter, valid=False)

    with pytest.raises(MemorySynthesisError):
        _publish(container)

    assert counter["n"] == 2  # primera respuesta + reintento
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    assert container.issue_tracker.writes == [("update_story", {"key": "DEMO-3"})]
    assert _memory_chunks(container) == {}
    assert list(tmp_path.glob("*.md")) == []
