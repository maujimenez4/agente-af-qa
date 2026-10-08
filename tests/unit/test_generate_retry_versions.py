"""PA-454 · Reintentar una iteración tras un fallo de la auditoría no choca con la versión N+1.

Al iterar, `generate` audita antes de guardar la versión: si la auditoría falla, no queda la
versión guardada y el reintento (que genera otro contenido) la guarda sin `VersionConflictError`.
El registro de versiones de la prueba rechaza, como el real, la misma versión con otro contenido.
Datos ficticios (proyecto DEMO).
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langgraph.types import Command

from core.audit import AuditEntry, InMemoryAuditTrail
from core.graph import Origin, build_graph, initial_state
from core.impact.versions import VersionConflictError
from schemas.artifact import Artifact
from schemas.user_story import UserStory
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider

NEED: Origin = {"kind": "need", "text": "Renovar préstamos de la biblioteca", "project": "DEMO"}
FEEDBACK = "Añade un criterio sobre el aviso de vencimiento (ficticio)."


class StrictVersions:
    """Como `StoryVersionStore.save`: una versión no cambia de contenido."""

    def __init__(self) -> None:
        self.saved: dict[tuple[UUID, int], str] = {}

    def save(self, artifact: Artifact) -> None:
        key = (artifact.id, artifact.version)
        content = artifact.content.model_dump_json()
        if key in self.saved and self.saved[key] != content:
            raise VersionConflictError("La versión ya existe con otro contenido.", service="db")
        self.saved[key] = content

    def update_status(self, artifact_id: UUID, status: str, jira_key: str | None = None) -> None:
        pass


class FlakyAudit(InMemoryAuditTrail):
    """Falla la primera vez que se audita una iteración."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_iterate = True

    def record(self, entry: AuditEntry) -> None:
        if entry.action == "iterate" and self.fail_next_iterate:
            self.fail_next_iterate = False
            raise RuntimeError("auditoría caída (ficticio)")
        super().record(entry)


def _varying_llm() -> FakeLLMProvider:
    """Cada HU generada lleva otro título: el reintento genera otro contenido."""
    llm = FakeLLMProvider()
    original = llm.builders[UserStory]
    calls = {"n": 0}

    def build(messages: list[Any]) -> UserStory:
        calls["n"] += 1
        story = original(messages)
        return story.model_copy(update={"title": f"{story.title} · intento {calls['n']}"})

    llm.builders[UserStory] = build
    return llm


def test_retry_after_failed_iteration_audit_saves_new_version(tmp_path: Path) -> None:
    versions, audit = StrictVersions(), FlakyAudit()
    container = fake_container(tmp_path, llm=_varying_llm(), versions=versions, audit=audit)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-pa454"}}
    graph.invoke(initial_state("af-demo", "functional", NEED), config)

    with pytest.raises(RuntimeError):
        graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    artifact_id = graph.get_state(config).values["artifact"].id
    assert (artifact_id, 2) not in versions.saved  # nada guardado si la auditoría falló

    graph.invoke(None, config)  # /retry: genera otro contenido para la versión 2

    artifact = graph.get_state(config).values["artifact"]
    assert artifact.version == 2
    assert versions.saved[(artifact_id, 2)] == artifact.content.model_dump_json()
    iterations = [e for e in audit.recorded if e.action == "iterate"]
    assert len(iterations) == 1 and iterations[0].detail["version"] == 2


def test_first_version_is_saved_before_its_audit(tmp_path: Path) -> None:
    """La primera versión se guarda antes de auditar (la fila del artefacto debe existir)."""
    order: list[str] = []

    class Versions(StrictVersions):
        def save(self, artifact: Artifact) -> None:
            order.append(f"save v{artifact.version}")
            super().save(artifact)

    class Audit(InMemoryAuditTrail):
        def record(self, entry: AuditEntry) -> None:
            order.append(entry.action)
            super().record(entry)

    container = fake_container(tmp_path, versions=Versions(), audit=Audit())
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-pa454-orden"}}
    graph.invoke(initial_state("af-demo", "functional", NEED), config)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)

    assert order == ["save v1", "create", "iterate", "save v2"]
