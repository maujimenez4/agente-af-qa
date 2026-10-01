"""Pruebas de `core/audit.py` y de la auditoría del grafo (T-25 · RF-35).

Las unitarias usan los fakes de `tests/fakes/` y `InMemoryAuditTrail`; ninguna llama a un LLM
real. Las de integración usan una BD temporal propia (`<db>_audit_test`) y se saltan si
PostgreSQL no está disponible.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pydantic
import pytest
import sqlalchemy as sa
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy.engine import Engine

from adapters.errors import ExternalServiceError
from core.audit import AuditEntry, AuditTrail, InMemoryAuditTrail, SqlAuditTrail
from core.container import Container
from core.graph import Origin, build_graph, initial_state
from core.impact.versions import StoryVersionStore
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.pg_temp import temporary_database, truncate_t25_tables

AF_USER = "af-demo"
QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
EPIC_ORIGIN: Origin = {"kind": "epic", "key": "DEMO-1"}
FEEDBACK = "Añade un criterio ficticio sobre el aviso de vencimiento."
MODEL = "fake/fake-model"
ALLOWED_DETAIL_KEYS = {
    "version",
    "status",
    "prompt_version",
    "operation",
    "simulated",
    "plan",
    "failed",
    "failed_ids",
}


# --- utilidades --------------------------------------------------------------------------


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"hilo-{uuid4()}"}}


def _start(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    mode: str = "functional",
    origin: Origin = STORY_ORIGIN,
    user: str = AF_USER,
) -> dict[str, Any]:
    return graph.invoke(initial_state(user, mode, origin), config)  # type: ignore[arg-type]


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return Command(
        resume={"decision": "approve", "fingerprint": task.interrupts[0].value["fingerprint"]}
    )


def _audit(container: Container) -> InMemoryAuditTrail:
    assert isinstance(container.audit, InMemoryAuditTrail)
    return container.audit


def _artifact_id(graph: CompiledStateGraph, config: dict[str, Any]) -> Any:
    return graph.get_state(config).values["artifact"].id


def _artifact(version: int = 1) -> Artifact:
    return Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.IN_REVIEW,
        version=version,
        origin_key="DEMO-3",
        content=dataset.renewal_story(),
        created_by=AF_USER,
        model_used=MODEL,
    )


class BrokenEngine:
    """Engine que falla al abrir la transacción, como una BD caída (sin red)."""

    def begin(self) -> Any:
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("conexión rechazada (ficticia)"))


class SpyVersionSink:
    """VersionSink espía: guarda cada artefacto que recibe (en el orden recibido)."""

    def __init__(self) -> None:
        self.saved: list[Artifact] = []
        self.status_updates: list[tuple[object, str, str | None]] = []

    def save(self, artifact: Artifact) -> None:
        self.saved.append(artifact.model_copy(deep=True))

    def update_status(self, artifact_id: object, status: str, jira_key: str | None = None) -> None:
        self.status_updates.append((artifact_id, status, jira_key))


# --- InMemoryAuditTrail ---------------------------------------------------------------------


def test_in_memory_trail_implements_protocol_when_built() -> None:
    """RF-35: InMemoryAuditTrail cumple el protocolo AuditTrail."""
    trail: AuditTrail = InMemoryAuditTrail()
    assert hasattr(trail, "record") and hasattr(trail, "entries")


def test_in_memory_entries_are_filtered_by_artifact_and_ordered_when_several() -> None:
    """RF-35: `entries` devuelve solo las del artefacto pedido, en orden de registro."""
    trail = InMemoryAuditTrail()
    first, other = uuid4(), uuid4()
    trail.record(AuditEntry(artifact_id=first, action="create", user=AF_USER))
    trail.record(AuditEntry(artifact_id=other, action="create", user=QA_USER))
    trail.record(AuditEntry(artifact_id=first, action="approve", user=AF_USER))

    assert [e.action for e in trail.entries(first)] == ["create", "approve"]
    assert [e.user for e in trail.entries(other)] == [QA_USER]
    assert trail.entries(uuid4()) == []


def test_in_memory_record_stores_a_copy_when_entry_is_mutated_later() -> None:
    """RF-35 (límite): mutar la entrada tras registrarla no altera la auditoría."""
    trail = InMemoryAuditTrail()
    entry = AuditEntry(artifact_id=uuid4(), action="create", user=AF_USER, detail={"version": 1})
    trail.record(entry)

    entry.detail["version"] = 99

    assert trail.recorded[0].detail == {"version": 1}


@pytest.mark.parametrize("action", ["delete", "update", ""])
def test_audit_entry_rejects_unknown_action(action: str) -> None:
    """RF-35 (negativo): solo create/iterate/approve/publish/discard (CHECK de audit_log)."""
    with pytest.raises(pydantic.ValidationError):
        AuditEntry(artifact_id=uuid4(), action=action, user=AF_USER)  # type: ignore[arg-type]


def test_audit_entry_defaults_are_empty_when_omitted() -> None:
    """RF-35: sin claves ni detalle, listas y diccionarios vacíos (no compartidos)."""
    a = AuditEntry(artifact_id=None, action="create", user=AF_USER)
    b = AuditEntry(artifact_id=None, action="create", user=AF_USER)
    a.detail["x"] = "1"
    assert a.jira_keys == [] and a.model is None
    assert b.detail == {}


def test_sql_trail_wraps_database_errors_when_unreachable() -> None:
    """RF-35 (error): sin BD accesible → ExternalServiceError en español, sin el error original."""
    trail = SqlAuditTrail(BrokenEngine())  # type: ignore[arg-type]
    with pytest.raises(ExternalServiceError, match="auditoría") as exc_info:
        trail.record(AuditEntry(artifact_id=uuid4(), action="create", user=AF_USER))
    assert "conexión rechazada" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    with pytest.raises(ExternalServiceError):
        trail.entries(uuid4())


# --- Auditoría del grafo (modo live con fakes) ------------------------------------------------


def test_graph_audits_create_iterate_approve_publish_in_order_when_live(tmp_path: Path) -> None:
    """RF-35 · T-25: crear, iterar, aprobar y publicar quedan auditados en ese orden."""
    container = fake_container(tmp_path)  # los fakes publican en live
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    final = graph.invoke(_approve(graph, config), config)

    entries = _audit(container).entries(final["artifact"].id)
    assert [e.action for e in entries] == ["create", "iterate", "approve", "publish"]
    assert [e.detail["version"] for e in entries] == [1, 2, 2, 2]
    assert [e.detail["status"] for e in entries] == [
        "in_review",
        "in_review",
        "approved",
        "published",
    ]
    assert all(e.user == AF_USER and e.model == MODEL for e in entries)
    assert entries[0].detail["prompt_version"] is not None
    assert entries[2].detail["operation"] == {
        "operation": "actualizar HU",
        "jira_key": "DEMO-3",
        "epic_key": None,
    }
    publish = entries[-1]
    assert publish.detail["simulated"] is False
    assert publish.jira_keys == ["DEMO-3"]
    assert publish.detail["failed"] == 0


def test_graph_audits_discard_when_person_discards(tmp_path: Path) -> None:
    """RF-35 · T-25: descartar queda auditado como `discard` con estado discarded."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    artifact_id = _artifact_id(graph, config)

    graph.invoke(Command(resume={"decision": "discard"}), config)

    entries = _audit(container).entries(artifact_id)
    assert [e.action for e in entries] == ["create", "discard"]
    assert entries[-1].detail == {"version": 1, "status": "discarded"}
    assert entries[-1].user == AF_USER and entries[-1].model == MODEL
    assert entries[-1].jira_keys == []


def test_graph_audits_iteration_only_once_per_new_version(tmp_path: Path) -> None:
    """RF-35 (límite): iterar dos veces → create + dos iterate, sin entradas en human_review."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    for _ in range(2):
        graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)

    entries = _audit(container).entries(_artifact_id(graph, config))
    assert [(e.action, e.detail["version"]) for e in entries] == [
        ("create", 1),
        ("iterate", 2),
        ("iterate", 3),
    ]


def test_graph_audits_qa_flow_with_created_case_keys_when_live(tmp_path: Path) -> None:
    """RF-35 · T-25: en QA, publish audita las claves de los casos creados."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, mode="qa", origin=STORY_ORIGIN, user=QA_USER)
    final = graph.invoke(_approve(graph, config), config)

    entries = _audit(container).entries(final["artifact"].id)
    assert [e.action for e in entries] == ["create", "approve", "publish"]
    assert all(e.user == QA_USER for e in entries)
    assert entries[-1].jira_keys == final["published_keys"]
    assert len(entries[-1].jira_keys) == 2


def test_audit_entries_never_contain_prompts_or_artifact_content(tmp_path: Path) -> None:
    """RF-35 · CLAUDE.md: ni prompts ni contenido de la HU ni feedback en la auditoría."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    final = graph.invoke(_approve(graph, config), config)

    entries = _audit(container).entries(final["artifact"].id)
    assert len(entries) == 4
    serialized = json.dumps([e.model_dump(mode="json") for e in entries], ensure_ascii=False)
    story = final["artifact"].content
    for text in (story.title, story.description, story.action, story.benefit, FEEDBACK):
        assert text not in serialized
    assert "Eres analista funcional" not in serialized
    for call in container.llm.calls:  # type: ignore[attr-defined]
        for message in call["messages"]:
            assert message.content not in serialized
    assert all(set(e.detail) <= ALLOWED_DETAIL_KEYS for e in entries)


# --- Versiones (VersionSink espía) ----------------------------------------------------------


def test_generate_and_review_save_versions_and_publish_does_not(tmp_path: Path) -> None:
    """T-25 · T-19: generate y human_review guardan versión; publish no vuelve a guardarla."""
    spy = SpyVersionSink()
    container = fake_container(tmp_path, versions=spy)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    assert [(a.version, a.status) for a in spy.saved] == [(1, ArtifactStatus.IN_REVIEW)]

    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    final = graph.invoke(_approve(graph, config), config)

    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert [(a.version, a.status) for a in spy.saved] == [
        (1, ArtifactStatus.IN_REVIEW),
        (2, ArtifactStatus.IN_REVIEW),
        (2, ArtifactStatus.APPROVED),
    ]
    assert all(a.id == final["artifact"].id for a in spy.saved)
    # Al publicar solo se actualiza el estado (y la clave de Jira), sin reescribir versiones.
    assert spy.status_updates == [(final["artifact"].id, "published", "DEMO-3")]


def test_discard_saves_the_discarded_version(tmp_path: Path) -> None:
    """T-25: descartar guarda la versión con estado discarded (misma versión, mismo contenido)."""
    spy = SpyVersionSink()
    container = fake_container(tmp_path, versions=spy)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)

    graph.invoke(Command(resume={"decision": "discard"}), config)

    assert [(a.version, a.status) for a in spy.saved] == [
        (1, ArtifactStatus.IN_REVIEW),
        (1, ArtifactStatus.DISCARDED),
    ]
    assert spy.saved[0].content == spy.saved[1].content


def test_simulated_publish_does_not_save_a_version(tmp_path: Path) -> None:
    """T-25: la publicación simulada no guarda contenido nuevo."""
    spy = SpyVersionSink()
    container = fake_container(tmp_path, versions=spy, publish_mode="simulation")
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(_approve(graph, config), config)

    assert [a.status for a in spy.saved] == [ArtifactStatus.IN_REVIEW, ArtifactStatus.APPROVED]


# --- Integración: SqlAuditTrail -------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    with temporary_database("audit_test") as (_url, engine):
        yield engine


@pytest.fixture
def engine(pg_engine: Engine) -> Engine:
    truncate_t25_tables(pg_engine)
    return pg_engine


@pytest.mark.integration
def test_sql_trail_records_and_returns_entries_in_order(engine: Engine) -> None:
    """RF-35: record/entries en audit_log, en orden de inserción y con todos los campos."""
    artifact = _artifact()
    StoryVersionStore(engine).save(artifact)  # clave foránea a artifacts
    trail = SqlAuditTrail(engine)
    trail.record(
        AuditEntry(
            artifact_id=artifact.id,
            action="create",
            user=AF_USER,
            model=MODEL,
            detail={"version": 1, "status": "in_review"},
        )
    )
    trail.record(
        AuditEntry(
            artifact_id=artifact.id,
            action="publish",
            user=AF_USER,
            jira_keys=["DEMO-3", "DEMO-2"],
            model=MODEL,
            detail={"simulated": True, "plan": [{"op": "update_story", "key": "DEMO-3"}]},
        )
    )

    entries = trail.entries(artifact.id)

    assert [e.action for e in entries] == ["create", "publish"]
    assert entries[0].detail == {"version": 1, "status": "in_review"}
    assert entries[0].jira_keys == []
    assert entries[1].jira_keys == ["DEMO-3", "DEMO-2"]
    assert entries[1].detail["plan"] == [{"op": "update_story", "key": "DEMO-3"}]
    assert all(e.artifact_id == artifact.id and e.model == MODEL for e in entries)
    with engine.connect() as conn:
        at = conn.execute(sa.text("SELECT count(*) FROM audit_log WHERE at IS NOT NULL")).scalar()
    assert at == 2


@pytest.mark.integration
def test_sql_trail_filters_by_artifact(engine: Engine) -> None:
    """RF-35: entries de un artefacto no incluye las de otro."""
    first, second = _artifact(), _artifact()
    versions = StoryVersionStore(engine)
    versions.save(first)
    versions.save(second)
    trail = SqlAuditTrail(engine)
    trail.record(AuditEntry(artifact_id=first.id, action="create", user=AF_USER))
    trail.record(AuditEntry(artifact_id=second.id, action="create", user=QA_USER))

    assert [e.user for e in trail.entries(first.id)] == [AF_USER]
    assert trail.entries(uuid4()) == []


@pytest.mark.integration
def test_sql_trail_rejects_entry_for_unknown_artifact(engine: Engine) -> None:
    """RF-35 (negativo): sin fila en artifacts, la clave foránea falla → ExternalServiceError."""
    trail = SqlAuditTrail(engine)
    with pytest.raises(ExternalServiceError, match="auditoría"):
        trail.record(AuditEntry(artifact_id=uuid4(), action="create", user=AF_USER))
