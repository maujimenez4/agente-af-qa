"""Pruebas del nodo `publish` en modo simulación y de `publish_mode` (T-25 · RF-33, RF-34, RF-35).

En simulación, `publish` no escribe en Jira: audita el plan de operaciones, deja el artefacto
APPROVED y la aprobación vigente. Las unitarias usan los fakes (ningún LLM real). Las de
integración recorren el grafo con fakes para Jira/LLM y persistencia real (versiones, auditoría
y estado) sobre una BD temporal propia; se saltan si PostgreSQL no está disponible.
"""

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
from core.approvals import ApprovalLedger
from core.artifact_state import SqlArtifactStateStore
from core.audit import InMemoryAuditTrail, SqlAuditTrail
from core.config import ROOT_DIR, AppConfig, Settings, load_models_config
from core.container import Container, build_container
from core.graph import Origin, build_graph, initial_state, memory_checkpointer
from core.graph.nodes import LINK_TYPE_IMPACT, GraphNodes, _target
from core.impact.analysis import ImpactAnalyzer
from core.impact.versions import StoryVersionStore
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.auth import FakeAuthProvider
from tests.fakes.container import fake_container
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.memory_generator import FakeMemoryGenerator
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore
from tests.pg_temp import temporary_database, truncate_t25_tables

AF_USER = "af-demo"
QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
EPIC_ORIGIN: Origin = {"kind": "epic", "key": "DEMO-1"}
NEED_ORIGIN: Origin = {
    "kind": "need",
    "project": "DEMO",
    "text": "Avisar por correo tres días antes del vencimiento del préstamo (ficticio).",
}
FEEDBACK = "Añade un criterio ficticio sobre el aviso de vencimiento."
STRUCTURE_MARK = "Pasas a la plantilla"  # prompts/structure_story.md


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


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _testmgmt(container: Container) -> FakeTestManagement:
    assert isinstance(container.test_management, FakeTestManagement)
    return container.test_management


def _audit(container: Container) -> InMemoryAuditTrail:
    assert isinstance(container.audit, InMemoryAuditTrail)
    return container.audit


def _memory_chunks(container: Container) -> list[str]:
    assert isinstance(container.vector_store, FakeVectorStore)
    return [
        chunk_id
        for chunk_id, chunk in container.vector_store.chunks.items()
        if chunk.metadata.get("category") == "memoria"
    ]


def _links(artifact: Artifact, source: str, exclude: str | None = None) -> list[dict[str, str]]:
    """Vínculos esperados: uno por HU afectada (sin repetir), sin la épica padre."""
    affected = artifact.impact.affected if artifact.impact else []
    keys = list(dict.fromkeys(item.jira_key for item in affected))
    return [
        {"op": "link", "from": source, "to": key, "type": LINK_TYPE_IMPACT}
        for key in keys
        if key != exclude
    ]


def _evolving_llm() -> FakeLLMProvider:
    """LLM fake cuya evolución cambia el título respecto a la versión de partida (hay diff)."""

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


def _simulate(
    tmp_path: Path,
    mode: str = "functional",
    origin: Origin = STORY_ORIGIN,
    user: str = AF_USER,
    **overrides: Any,
) -> tuple[Container, CompiledStateGraph, dict[str, Any], dict[str, Any]]:
    container = fake_container(tmp_path, publish_mode="simulation", **overrides)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, mode, origin, user)
    final = graph.invoke(_approve(graph, config), config)
    return container, graph, config, final


def _all_fakes() -> dict[str, Any]:
    return {
        "issue_tracker": FakeIssueTracker(),
        "test_management": FakeTestManagement(),
        "llm": FakeLLMProvider(),
        "embeddings": FakeEmbeddingProvider(),
        "vector_store": FakeVectorStore(),
        "memory_generator": FakeMemoryGenerator(),
        "auth": FakeAuthProvider(),
    }


# --- Simulación en el grafo -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "origin", "user"),
    [
        ("functional", STORY_ORIGIN, AF_USER),
        ("functional", EPIC_ORIGIN, AF_USER),
        ("functional", NEED_ORIGIN, AF_USER),
        ("qa", STORY_ORIGIN, QA_USER),
    ],
    ids=["evolucion", "epica", "necesidad", "qa"],
)
def test_simulated_publish_writes_nothing_and_keeps_approval(
    tmp_path: Path, mode: str, origin: Origin, user: str
) -> None:
    """RF-34 · T-25: en simulación, ni tracker ni publish_suite; APPROVED y aprobación vigente."""
    container, graph, config, final = _simulate(tmp_path, mode, origin, user)

    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0
    artifact: Artifact = final["artifact"]
    assert artifact.status is ArtifactStatus.APPROVED
    assert final["published_keys"] == []
    assert final["errors"] == []
    assert graph.get_state(config).next == ()
    target = _target(graph.get_state(config).values, config)
    assert container.approvals.find(artifact, target) is not None
    assert container.approvals.was_published(artifact) is False
    # memorize no escribe memoria: ni fichero, ni índice, ni llamada al generador.
    assert list(tmp_path.glob("*.md")) == []
    assert _memory_chunks(container) == []
    assert container.memory_generator.generated == []  # type: ignore[attr-defined]


def test_simulated_publish_audits_create_approve_publish_in_order(tmp_path: Path) -> None:
    """RF-35 · T-25: la auditoría registra create → approve → publish con simulated True."""
    container, _, _, final = _simulate(tmp_path)

    entries = _audit(container).entries(final["artifact"].id)
    assert [e.action for e in entries] == ["create", "approve", "publish"]
    publish = entries[-1]
    assert publish.detail["simulated"] is True
    assert publish.detail["status"] == "approved"
    assert publish.detail["version"] == 1
    assert publish.jira_keys == []
    assert publish.user == AF_USER


def test_simulated_plan_for_evolution_updates_story_and_links_affected(tmp_path: Path) -> None:
    """RF-34 · RF-06: evolución → update_story de la HU origen + vínculos a las afectadas."""
    container, _, _, final = _simulate(tmp_path, origin=STORY_ORIGIN, llm=_evolving_llm())
    artifact: Artifact = final["artifact"]
    assert artifact.impact is not None and artifact.impact.diffs

    plan = _audit(container).entries(artifact.id)[-1].detail["plan"]

    assert plan[0] == {"op": "update_story", "project": "DEMO", "key": "DEMO-3"}
    assert plan[1] == {"op": "comment", "key": "DEMO-3"}  # PA-319
    assert plan[2:] == _links(artifact, "DEMO-3")
    assert plan[2:], "el fake propone al menos una HU afectada (DEMO-2)"
    assert all(step["to"] != "DEMO-3" for step in plan[2:])


def test_simulated_plan_for_epic_creates_story_and_skips_epic_link(tmp_path: Path) -> None:
    """RF-34 · RF-06: desde épica → create_story con la épica; vínculos sin la épica."""
    container, _, _, final = _simulate(tmp_path, origin=EPIC_ORIGIN)
    artifact: Artifact = final["artifact"]

    plan = _audit(container).entries(artifact.id)[-1].detail["plan"]

    assert plan[0] == {"op": "create_story", "project": "DEMO", "epic": "DEMO-1"}
    assert plan[1:] == _links(artifact, "(HU nueva)", exclude="DEMO-1")
    assert plan[1:], "el fake propone al menos una HU afectada (DEMO-2)"
    assert all(step["to"] != "DEMO-1" for step in plan[1:])


def test_simulated_plan_for_need_creates_story_without_epic(tmp_path: Path) -> None:
    """RF-34: desde una necesidad → create_story sin épica."""
    container, _, _, final = _simulate(tmp_path, origin=NEED_ORIGIN)
    artifact: Artifact = final["artifact"]

    plan = _audit(container).entries(artifact.id)[-1].detail["plan"]

    assert plan[0] == {"op": "create_story", "project": "DEMO", "epic": ""}
    assert plan[1:] == _links(artifact, "(HU nueva)")


def test_simulated_plan_for_qa_publishes_suite_with_case_count(tmp_path: Path) -> None:
    """RF-34: QA → publish_suite de la HU con el número de casos."""
    container, _, _, final = _simulate(tmp_path, mode="qa", origin=STORY_ORIGIN, user=QA_USER)
    artifact: Artifact = final["artifact"]

    plan = _audit(container).entries(artifact.id)[-1].detail["plan"]

    assert plan == [
        {
            "op": "publish_suite",
            "project": "DEMO",
            "story": "DEMO-3",
            "cases": str(len(artifact.content.cases)),
        }
    ]
    assert plan[0]["cases"] == "2"


def test_simulated_publish_node_returns_empty_update(tmp_path: Path) -> None:
    """T-25: el nodo publish en simulación devuelve {} (no cambia el estado del grafo)."""
    container = fake_container(tmp_path, publish_mode="simulation")
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    updates = [u for u in graph.stream(_approve(graph, config), config, stream_mode="updates")]

    publish_updates = [u["publish"] for u in updates if "publish" in u]
    assert publish_updates in ([None], [{}])
    assert _tracker(container).writes == []


def test_simulated_approval_can_be_published_live_later(tmp_path: Path) -> None:
    """RF-33 · T-25: la aprobación no se consume en simulación; luego se publica en live."""
    container, graph, config, _final = _simulate(tmp_path)
    live = fake_container(
        tmp_path,
        publish_mode="live",
        state_store=container.state_store,
        issue_tracker=container.issue_tracker,
    )
    state = graph.get_state(config).values

    result = GraphNodes(live).publish(state, config)  # type: ignore[arg-type]

    assert result["artifact"].status is ArtifactStatus.PUBLISHED
    assert _tracker(live).writes[0] == ("update_story", {"key": "DEMO-3"})
    assert live.approvals.was_published(result["artifact"])


def test_live_publish_audits_not_simulated_with_keys_and_failed(tmp_path: Path) -> None:
    """RF-35 · T-25: en live, publish audita simulated False, jira_keys y failed."""
    container = fake_container(tmp_path, publish_mode="live")
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)
    final = graph.invoke(_approve(graph, config), config)

    publish = _audit(container).entries(final["artifact"].id)[-1]
    assert publish.action == "publish"
    assert publish.detail["simulated"] is False
    assert publish.jira_keys == final["published_keys"]
    assert publish.detail["failed"] == 0
    assert publish.detail["status"] == "published"
    assert publish.detail["plan"][0] == {"op": "create_story", "project": "DEMO", "epic": "DEMO-1"}
    assert _tracker(container).writes[0][0] == "create_story"


def test_live_publish_audits_failed_cases_when_qa_partially_fails(tmp_path: Path) -> None:
    """RF-35 · RNF-13: en live, un caso fallido queda como failed=1 y estado approved."""
    container = fake_container(
        tmp_path, publish_mode="live", test_management=FakeTestManagement(fail_case_ids={"CP-02"})
    )
    graph = build_graph(container)
    config = _config()
    _start(graph, config, mode="qa", user=QA_USER)
    final = graph.invoke(_approve(graph, config), config)

    publish = _audit(container).entries(final["artifact"].id)[-1]
    assert publish.detail["simulated"] is False
    assert publish.detail["failed"] == 1
    assert publish.detail["status"] == "approved"
    assert len(publish.jira_keys) == 1
    assert publish.detail["failed_ids"] == ["CP-02"]


def test_live_story_publish_audits_empty_failed_ids(tmp_path: Path) -> None:
    """RF-35 · T-25: una HU publicada sin fallos audita failed_ids vacío."""
    container = fake_container(tmp_path, publish_mode="live")
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)
    final = graph.invoke(_approve(graph, config), config)

    publish = _audit(container).entries(final["artifact"].id)[-1]
    assert publish.detail["failed_ids"] == []


def test_live_publish_keeps_story_published_when_a_link_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RNF-13 · RF-35: un vínculo que falla no deshace la HU publicada; se informa y se audita."""
    container = fake_container(tmp_path, publish_mode="live")
    tracker = _tracker(container)

    def failing_link(*_args: Any, **_kwargs: Any) -> None:
        raise ExternalServiceError("Jira no responde (ficticio).")

    monkeypatch.setattr(tracker, "link", failing_link)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=EPIC_ORIGIN)
    final = graph.invoke(_approve(graph, config), config)

    artifact: Artifact = final["artifact"]
    assert artifact.status is ArtifactStatus.PUBLISHED
    assert final["errors"], "el fake propone al menos una HU afectada (DEMO-2)"
    assert all(e.startswith("No se pudo vincular ") for e in final["errors"])
    publish = _audit(container).entries(artifact.id)[-1]
    assert publish.detail["failed"] == len(final["errors"])
    assert publish.detail["status"] == "published"


def _analyze_with_epic(monkeypatch: pytest.MonkeyPatch, epic: str) -> None:
    """Simula un análisis que (indebidamente) marca la épica como afectada."""
    original = ImpactAnalyzer.analyze

    def analyze(self: ImpactAnalyzer, *args: Any, **kwargs: Any) -> ImpactAnalysis:
        impact = original(self, *args, **kwargs)
        extra = ImpactItem(jira_key=epic, reason="Épica ficticia", kind="story")
        return impact.model_copy(update={"affected": [*impact.affected, extra]})

    monkeypatch.setattr(ImpactAnalyzer, "analyze", analyze)


@pytest.mark.parametrize("publish_mode", ["simulation", "live"])
def test_evolution_never_links_to_its_epic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publish_mode: str
) -> None:
    """PA-38 · RF-06: al evolucionar una HU, su épica nunca entra en el plan ni en los vínculos."""
    container = fake_container(tmp_path, publish_mode=publish_mode, llm=_evolving_llm())
    epic = _tracker(container).get_issue("DEMO-3").parent_key
    assert epic == "DEMO-1"
    _analyze_with_epic(monkeypatch, epic)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, origin=STORY_ORIGIN)
    final = graph.invoke(_approve(graph, config), config)

    artifact: Artifact = final["artifact"]
    assert artifact.impact is not None
    assert epic in {item.jira_key for item in artifact.impact.affected}
    plan = _audit(container).entries(artifact.id)[-1].detail["plan"]
    assert plan[0] == {"op": "update_story", "project": "DEMO", "key": "DEMO-3"}
    assert all(step.get("to") != epic for step in plan[1:])
    links = [data for op, data in _tracker(container).writes if op == "link"]
    assert all(data["to"] != epic for data in links)


# --- publish_mode en build_container y configuración -----------------------------------------


def test_build_container_defaults_to_simulation_without_config() -> None:
    """RF-34 · T-25: sin configuración ni parámetro, el modo es simulación."""
    assert build_container(**_all_fakes()).publish_mode == "simulation"


def test_build_container_explicit_mode_overrides_default() -> None:
    """T-25: el parámetro publish_mode tiene prioridad."""
    assert build_container(**_all_fakes(), publish_mode="live").publish_mode == "live"


def test_build_container_uses_simulation_from_config_by_default(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """RF-34: con AppConfig y sin JIRA_PUBLISH_MODE → simulation."""
    clean_env.delenv("JIRA_PUBLISH_MODE", raising=False)
    config = AppConfig(Settings(_env_file=None), load_models_config())

    assert build_container(config, **_all_fakes()).publish_mode == "simulation"


def test_build_container_uses_live_from_env(clean_env: pytest.MonkeyPatch) -> None:
    """RF-34: JIRA_PUBLISH_MODE=live → el contenedor publica de verdad."""
    clean_env.setenv("JIRA_PUBLISH_MODE", "live")
    config = AppConfig(Settings(_env_file=None), load_models_config())

    assert config.settings.jira_publish_mode == "live"
    assert build_container(config, **_all_fakes()).publish_mode == "live"


@pytest.mark.parametrize("value", ["LIVE-ficticio", "real", "true"])
def test_invalid_publish_mode_in_env_fails_validation(
    clean_env: pytest.MonkeyPatch, value: str
) -> None:
    """RF-34 (negativo): un valor no admitido en JIRA_PUBLISH_MODE → error de validación."""
    clean_env.setenv("JIRA_PUBLISH_MODE", value)
    with pytest.raises(pydantic.ValidationError, match="jira_publish_mode"):
        Settings(_env_file=None)


def test_env_example_documents_simulation_mode() -> None:
    """RF-34: .env.example declara JIRA_PUBLISH_MODE=simulation."""
    lines = (ROOT_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "JIRA_PUBLISH_MODE=simulation" in [line.strip() for line in lines]


def test_build_container_ledger_uses_the_injected_state_store() -> None:
    """PA-06: el ledger del contenedor persiste en el mismo state_store inyectado."""
    from core.artifact_state import InMemoryArtifactStateStore

    store = InMemoryArtifactStateStore()
    built = build_container(**_all_fakes(), state_store=store)

    assert built.state_store is store
    assert built.approvals.store is store


# --- Integración: flujo completo con persistencia real ---------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    with temporary_database("publish_sim_test") as (_url, engine):
        yield engine


@pytest.fixture
def engine(pg_engine: Engine) -> Engine:
    truncate_t25_tables(pg_engine)
    return pg_engine


def _sql_container(tmp_path: Path, engine: Engine, mode: str, **overrides: Any) -> Container:
    return fake_container(
        tmp_path,
        publish_mode=mode,
        versions=StoryVersionStore(engine),
        audit=SqlAuditTrail(engine),
        state_store=SqlArtifactStateStore(engine),
        **overrides,
    )


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(sa.text(sql), params))


@pytest.mark.integration
def test_full_simulated_flow_persists_coherent_rows(tmp_path: Path, engine: Engine) -> None:
    """RF-33 · RF-34 · RF-35: filas coherentes en las 4 tablas y ninguna escritura en Jira."""
    container = _sql_container(tmp_path, engine, "simulation")
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    final = graph.invoke(_approve(graph, config), config)
    artifact: Artifact = final["artifact"]

    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0
    (row,) = _rows(engine, "SELECT id, status, version, created_by, jira_key FROM artifacts")
    assert (row.id, row.status, row.version) == (artifact.id, "approved", 2)
    assert row.created_by == AF_USER and row.jira_key == "DEMO-3"
    versions = _rows(
        engine,
        "SELECT version FROM artifact_versions WHERE artifact_id = :id ORDER BY version",
        id=artifact.id,
    )
    assert [v.version for v in versions] == [1, 2]
    audit = SqlAuditTrail(engine).entries(artifact.id)
    assert [e.action for e in audit] == ["create", "iterate", "approve", "publish"]
    assert audit[-1].detail["simulated"] is True
    assert audit[-1].detail["plan"][0] == {"op": "update_story", "project": "DEMO", "key": "DEMO-3"}
    state = SqlArtifactStateStore(engine).load(str(artifact.id))
    assert state is not None
    assert set(state) == {"baseline", "ledger"}
    (approval,) = state["ledger"]["approvals"]
    assert approval["version"] == 2 and approval["consumed"] is False
    assert state["ledger"]["target"]["thread_id"] == config["configurable"]["thread_id"]


@pytest.mark.integration
def test_ledger_rebuilt_from_database_allows_live_publish(tmp_path: Path, engine: Engine) -> None:
    """RF-33 · PA-06: tras «reiniciar», el ledger leído de la BD permite publicar en live."""
    checkpointer = memory_checkpointer()
    config = _config()
    simulated = _sql_container(tmp_path, engine, "simulation")
    graph = build_graph(simulated, checkpointer)
    _start(graph, config)
    graph.invoke(_approve(graph, config), config)
    state = graph.get_state(config).values
    artifact_id = state["artifact"].id

    # «Reinicio»: contenedor y almacenes nuevos sobre la misma BD; nada compartido en memoria.
    restarted = _sql_container(tmp_path, engine, "live")
    assert restarted.approvals is not simulated.approvals
    assert restarted.approvals.find(state["artifact"], _target(state, config)) is not None
    result = GraphNodes(restarted).publish(state, config)  # type: ignore[arg-type]

    assert result["artifact"].status is ArtifactStatus.PUBLISHED
    assert result["published_keys"] == ["DEMO-3"]
    assert _tracker(restarted).writes[0] == ("update_story", {"key": "DEMO-3"})
    assert _tracker(simulated).writes == []
    audit = SqlAuditTrail(engine).entries(artifact_id)
    assert [e.action for e in audit] == ["create", "approve", "publish", "publish"]
    assert [e.detail["simulated"] for e in audit[2:]] == [True, False]
    assert audit[-1].jira_keys == ["DEMO-3"]
    saved = SqlArtifactStateStore(engine).load(str(artifact_id))
    assert saved is not None and "baseline" not in saved
    fresh = ApprovalLedger(store=SqlArtifactStateStore(engine))
    assert fresh.was_published(result["artifact"])
    assert fresh.find(state["artifact"], _target(state, config)) is None


@pytest.mark.integration
def test_live_publish_marks_artifact_row_as_published(tmp_path: Path, engine: Engine) -> None:
    """RF-33 · T-19: tras publicar en live, la fila de `artifacts` queda published."""
    container = _sql_container(tmp_path, engine, "live")
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    final = graph.invoke(_approve(graph, config), config)
    assert final["artifact"].status is ArtifactStatus.PUBLISHED

    (row,) = _rows(engine, "SELECT status FROM artifacts")
    assert row.status == "published"
