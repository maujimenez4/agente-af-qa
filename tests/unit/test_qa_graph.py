"""Modo QA del grafo con `core/qa/writer.TestWriter` (PA-61 · RF-22 a RF-25, RF-20, RF-21, D-07).

Cubren el nodo `generate` en modo QA: la HU de Jira se estructura una sola vez por artefacto
(`structure_story`) y la suite se genera con `generate_tests`; la trazabilidad del artefacto
(`story_jira_key`, `prompt_version`, `model_used`), las citas con extracto real, la iteración con
feedback, el borrado de la versión de partida, los errores de cobertura y de citas, las fuentes
excluidas (T-51) y la publicación en live con el fake. Solo fakes de `tests/fakes/`; datos 100 %
ficticios.
"""

import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

import core.graph.nodes as nodes
from adapters.base import Message, TaskType
from adapters.errors import ExternalServiceError
from core.artifact_state import InMemoryArtifactStateStore
from core.audit import InMemoryAuditTrail
from core.container import Container
from core.functional.citations import CitationError
from core.functional.context import StoryContext
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import _pending_baseline_key
from core.qa.validation import CoverageError
from core.qa.writer import MissingCases
from core.rag.prompts import load_prompt
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider, renewal_test_suite
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore

QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
FEEDBACK = "Anade un caso de limite con la segunda renovacion (texto ficticio)."
SECOND_FEEDBACK = "Prioriza los casos negativos (texto ficticio)."
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_SOURCE_TAG = re.compile(r'<fuente ref="([^"]+)" tipo="(jira|rag|memory)"')


# --- utilidades --------------------------------------------------------------------------


class RecordingTestManagement(FakeTestManagement):
    """Fake de TestManagement que además guarda cada suite recibida por `publish_suite`."""

    __test__ = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.published: list[TestSuite] = []

    def publish_suite(self, suite: TestSuite) -> Any:
        self.published.append(suite.model_copy(deep=True))
        return super().publish_suite(suite)


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"hilo-{uuid4()}"}}


def _start(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    excluded: list[str] | None = None,
) -> dict[str, Any]:
    state = initial_state(QA_USER, "qa", STORY_ORIGIN, excluded)
    return graph.invoke(state, config)


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    (pending,) = result["__interrupt__"]
    return pending.value


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[-1].value


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> Command:
    return Command(
        resume={"decision": "approve", "fingerprint": _pending(graph, config)["fingerprint"]}
    )


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _audit(container: Container) -> InMemoryAuditTrail:
    assert isinstance(container.audit, InMemoryAuditTrail)
    return container.audit


def _testmgmt(container: Container) -> FakeTestManagement:
    assert isinstance(container.test_management, FakeTestManagement)
    return container.test_management


def _system(call: dict[str, Any]) -> str:
    return next(m.content for m in call["messages"] if m.role == "system")


def _user(call: dict[str, Any]) -> str:
    """Primer mensaje de usuario: el contexto renderizado (no el feedback del reintento)."""
    return next(m.content for m in call["messages"] if m.role == "user")


def _calls_for(container: Container, prompt: str) -> list[dict[str, Any]]:
    text = load_prompt(prompt).text
    return [c for c in _llm(container).calls if _system(c) == text]


def _header_version(name: str) -> str:
    """Versión leída directamente de la cabecera del archivo, sin el cargador de producción."""
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    header = raw.split("---", 2)[1]
    match = re.search(r"^version:\s*(\S+)\s*$", header, re.MULTILINE)
    assert match is not None
    return match.group(1)


def _baseline(container: Container, artifact_id: str) -> Any:
    return (container.state_store.load(artifact_id) or {}).get("baseline")


def _uncovering_suite(_messages: list[Message]) -> TestSuite:
    """Suite del dataset con CP-02 sobre CA-01: CA-02 queda sin ningún caso."""
    suite = renewal_test_suite()
    positive, negative = suite.cases
    moved = negative.model_copy(update={"criterion_ids": ["CA-01"], "rule_ids": ["RN-01"]})
    cited = [SourceRef(kind="jira", ref="DEMO-3")]
    return suite.model_copy(update={"cases": [positive, moved], "sources": cited})


def _suite_citing_unknown_source(_messages: list[Message]) -> TestSuite:
    """Suite con buena cobertura que cita una fuente que no está en el contexto."""
    return renewal_test_suite().model_copy(
        update={"sources": [SourceRef(kind="rag", ref="doc-inexistente-ficticio")]}
    )


def _assert_nothing_offered_or_audited(container: Container) -> None:
    approvals = container.approvals
    assert approvals._offers == {}
    assert approvals._targets == {}
    assert approvals._approvals == {}
    assert _audit(container).recorded == []
    assert _testmgmt(container).publish_calls == 0


# --- 1 · structure_story y después generate_tests ---------------------------------------------


def test_generate_qa_structures_story_then_generates_tests_from_story_origin(
    tmp_path: Path,
) -> None:
    """PA-61 · RF-22: primero `structure_story` (UserStory) y después `generate_tests`."""
    container = fake_container(tmp_path)
    graph = build_graph(container)

    _start(graph, _config())

    calls = _llm(container).calls
    assert [(c["schema"], c["task"]) for c in calls] == [
        (UserStory, TaskType.EVOLVE_STORY),
        (TestSuite, TaskType.GENERATE_TESTS),
    ]
    assert _system(calls[0]) == load_prompt("structure_story").text
    assert "Pasas a la plantilla" in _system(calls[0])
    assert _system(calls[1]) == load_prompt("generate_tests").text
    assert "la suite de pruebas" in _system(calls[1])
    # Ningún análisis de impacto en modo QA.
    assert all(c["task"] is not TaskType.ANALYZE_IMPACT for c in calls)


def test_generate_qa_structure_receives_only_origin_issue_without_rag(tmp_path: Path) -> None:
    """PA-61 · PA-30: la versión de partida solo ve la incidencia de origen (sin RAG ni otras)."""
    container = fake_container(tmp_path)
    _start(build_graph(container), _config())

    (structure,) = _calls_for(container, "structure_story")
    refs = [m.group(1) for m in _SOURCE_TAG.finditer(_user(structure))]
    assert refs == ["DEMO-3"]


def test_generate_tests_receives_structured_story_and_context(tmp_path: Path) -> None:
    """PA-61 · RF-21: `generate_tests` recibe la HU estructurada y el contexto completo."""
    container = fake_container(tmp_path)
    _start(build_graph(container), _config())

    (tests_call,) = _calls_for(container, "generate_tests")
    user = _user(tests_call)
    assert '<origen tipo="story" clave="DEMO-3"/>' in user
    assert "<hu_actual>" in user
    refs = [m.group(1) for m in _SOURCE_TAG.finditer(user)]
    assert refs[0] == "DEMO-3"
    assert len(refs) > 1  # además de la HU de origen llegan otras fuentes de Jira o del RAG


def test_generate_qa_artifact_is_test_suite_with_traceability(tmp_path: Path) -> None:
    """PA-61 · Principio 4: TEST_SUITE con `story_jira_key`, `prompt_version` y `model_used`."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()

    payload = _payload(_start(graph, config))

    artifact: Artifact = graph.get_state(config).values["artifact"]
    assert artifact.type is ArtifactType.TEST_SUITE
    assert artifact.status is ArtifactStatus.IN_REVIEW
    assert artifact.version == 1
    assert artifact.origin_key == "DEMO-3"
    assert isinstance(artifact.content, TestSuite)
    assert artifact.content.story_jira_key == "DEMO-3"
    expected_version = _header_version("generate_tests")
    assert artifact.prompt_version == expected_version
    assert artifact.model_used == "fake/fake-model"
    assert payload["artifact"]["type"] == ArtifactType.TEST_SUITE.value
    assert payload["artifact"]["prompt_version"] == expected_version
    assert payload["plan"] == [
        {"op": "publish_suite", "project": "DEMO", "story": "DEMO-3", "cases": "2"}
    ]
    (create,) = _audit(container).entries(artifact.id)
    assert create.action == "create"
    assert create.detail["prompt_version"] == expected_version
    assert create.model == "fake/fake-model"


def test_generate_qa_model_used_reflects_provider_and_model(tmp_path: Path) -> None:
    """PA-61: `model_used` es `proveedor/modelo` de la llamada de `generate_tests`."""
    llm = FakeLLMProvider(provider="ollama", model="modelo-abierto-ficticio")
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = _config()

    _start(graph, config)

    assert graph.get_state(config).values["artifact"].model_used == (
        "ollama/modelo-abierto-ficticio"
    )


def test_generate_qa_saves_baseline_once_per_artifact(tmp_path: Path) -> None:
    """PA-61 · PA-37: la HU estructurada se guarda en `state_store["baseline"]`."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()

    _start(graph, config)

    artifact_id = str(graph.get_state(config).values["artifact"].id)
    saved = _baseline(container, artifact_id)
    assert saved is not None
    assert UserStory.model_validate(saved).title == dataset.renewal_story().title


# --- 2 · citas con extracto real ------------------------------------------------------------


def test_generate_qa_suite_cites_context_source_with_real_excerpt(tmp_path: Path) -> None:
    """PA-61 · RF-21: la suite cita la primera fuente del contexto con su extracto real."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()

    _start(graph, config)

    state = graph.get_state(config).values
    suite: TestSuite = state["artifact"].content
    (tests_call,) = _calls_for(container, "generate_tests")
    first = _SOURCE_TAG.search(_user(tests_call))
    assert first is not None
    assert [(s.kind, s.ref) for s in suite.sources] == [(first.group(2), first.group(1))]
    ctx = StoryContext(origin_kind="story", jira=state["jira_context"], rag=state["rag_context"])
    expected = {(s.kind, s.ref): s.excerpt for s in ctx.sources()}
    (cited,) = suite.sources
    assert cited.excerpt == expected[(cited.kind, cited.ref)]
    # El extracto procede de Jira, no de lo que diga el modelo.
    assert cited.excerpt.startswith(dataset.STORIES["DEMO-3"].summary)


def test_generate_qa_rag_citation_gets_document_excerpt(tmp_path: Path) -> None:
    """PA-61 · RF-21: una cita del RAG recibe el extracto real del fragmento recuperado."""
    llm = FakeLLMProvider()
    llm.builders[TestSuite] = lambda _m: renewal_test_suite().model_copy(
        update={"sources": [SourceRef(kind="rag", ref="doc-reglamento", excerpt="inventado")]}
    )
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = _config()

    _start(graph, config)

    (tests_call,) = _calls_for(container, "generate_tests")
    assert '<fuente ref="doc-reglamento" tipo="rag"' in _user(tests_call)
    suite: TestSuite = graph.get_state(config).values["artifact"].content
    (cited,) = suite.sources
    assert (cited.kind, cited.ref) == ("rag", "doc-reglamento")
    assert cited.excerpt == dataset.DOCUMENTS["doc-reglamento"]["content"][:120]
    assert cited.excerpt != "inventado"


def test_generate_qa_without_sources_in_context_keeps_suite_uncited(tmp_path: Path) -> None:
    """PA-61 (límite): sin fuentes en el contexto, la suite del fake no cita nada."""
    container = fake_container(tmp_path)
    nodes_llm = _llm(container)
    suite = nodes_llm.builders[TestSuite]([Message(role="user", content="sin fuentes")])
    assert isinstance(suite, TestSuite)
    assert suite.sources == []


# --- 3 · iterar ---------------------------------------------------------------------------


def test_iterate_qa_regenerates_suite_without_restructuring_story(tmp_path: Path) -> None:
    """PA-61 · RF-20: al iterar, una sola `structure_story`; la suite se regenera (v2, mismo id)."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))

    second = _payload(
        graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    )

    assert len(_calls_for(container, "structure_story")) == 1
    tests_calls = _calls_for(container, "generate_tests")
    assert len(tests_calls) == 2
    assert FEEDBACK not in _user(tests_calls[0])
    assert "<feedback>" in _user(tests_calls[1])
    assert FEEDBACK in _user(tests_calls[1])
    assert second["artifact"]["id"] == first["artifact"]["id"]
    assert second["artifact"]["version"] == 2
    assert second["artifact"]["type"] == ArtifactType.TEST_SUITE.value
    assert second["artifact"]["status"] == ArtifactStatus.IN_REVIEW.value
    assert second["artifact"]["prompt_version"] == _header_version("generate_tests")
    assert second["fingerprint"] != first["fingerprint"]
    actions = [e.action for e in _audit(container).entries(UUID(first["artifact"]["id"]))]
    assert actions == ["create", "iterate"]


def test_iterate_qa_twice_accumulates_feedback_and_keeps_single_structure(
    tmp_path: Path,
) -> None:
    """PA-61 · RF-20 (límite): dos iteraciones acumulan el feedback; la HU se estructura una vez."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)

    third = _payload(
        graph.invoke(Command(resume={"decision": "iterate", "feedback": SECOND_FEEDBACK}), config)
    )

    assert third["artifact"]["version"] == 3
    assert len(_calls_for(container, "structure_story")) == 1
    last = _user(_calls_for(container, "generate_tests")[-1])
    assert FEEDBACK in last and SECOND_FEEDBACK in last


def test_iterate_qa_uses_saved_baseline_as_story(tmp_path: Path) -> None:
    """PA-61 · PA-37: la suite regenerada parte de la HU guardada como versión de partida."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    artifact_id = str(graph.get_state(config).values["artifact"].id)
    saved = _baseline(container, artifact_id)

    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)

    assert _baseline(container, artifact_id) == saved
    hu_titles = [_user(c) for c in _calls_for(container, "generate_tests")]
    assert all(UserStory.model_validate(saved).title in text for text in hu_titles)


# --- 4 · versión de partida al descartar y al publicar ---------------------------------------


def test_discard_qa_forgets_baseline(tmp_path: Path) -> None:
    """PA-61 · PA-37: descartar la suite borra la versión de partida guardada."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    artifact_id = str(graph.get_state(config).values["artifact"].id)
    assert _baseline(container, artifact_id) is not None

    final = graph.invoke(Command(resume={"decision": "discard"}), config)

    assert final["artifact"].status is ArtifactStatus.DISCARDED
    assert _baseline(container, artifact_id) is None
    assert _testmgmt(container).publish_calls == 0


def test_publish_qa_forgets_baseline(tmp_path: Path) -> None:
    """PA-61 · PA-37: publicar la suite borra la versión de partida guardada."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    artifact_id = str(graph.get_state(config).values["artifact"].id)
    assert _baseline(container, artifact_id) is not None

    final = graph.invoke(_approve(graph, config), config)

    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert _baseline(container, artifact_id) is None


def test_publish_qa_partial_failure_keeps_baseline(tmp_path: Path) -> None:
    """PA-61 · RNF-13 (límite): si falla un caso, sigue APPROVED y se conserva la partida."""
    container = fake_container(
        tmp_path, test_management=FakeTestManagement(fail_case_ids={"CP-02"})
    )
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    artifact_id = str(graph.get_state(config).values["artifact"].id)

    final = graph.invoke(_approve(graph, config), config)

    assert final["artifact"].status is ArtifactStatus.APPROVED
    assert final["errors"] == ["No se pudo publicar CP-02."]
    assert _baseline(container, artifact_id) is not None


# --- 5 · CoverageError ------------------------------------------------------------------------


def _uncovering_suite_without_negative(_messages: list[Message]) -> TestSuite:
    """Suite con solo el caso positivo sobre CA-01: falta CA-02 y falta un caso negativo.

    PA-426: el caso negativo que falta es un error que bloquea (reintento completo); el CA sin
    caso, por sí solo, ya no lo es.
    """
    positive = renewal_test_suite().cases[0]
    cited = [SourceRef(kind="jira", ref="DEMO-3")]
    return renewal_test_suite().model_copy(update={"cases": [positive], "sources": cited})


def test_generate_qa_raises_coverage_error_after_retry_without_offer_or_audit(
    tmp_path: Path,
) -> None:
    """PA-61 · RF-24 · PA-426: si tras el reintento de siempre sigue faltando un caso negativo (y
    un CA), `CoverageError` sale de `generate`, sin reintento dirigido ni nada ofrecido."""
    llm = FakeLLMProvider()
    llm.builders[TestSuite] = _uncovering_suite_without_negative
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = _config()

    with pytest.raises(CoverageError, match="no cubre la HU"):
        _start(graph, config)

    tests_calls = _calls_for(container, "generate_tests")
    assert len(tests_calls) == 2  # el reintento conserva el prompt de sistema de generate_tests
    tasks = [(c["schema"], c["task"]) for c in llm.calls]
    assert tasks == [
        (UserStory, TaskType.EVOLVE_STORY),
        (TestSuite, TaskType.GENERATE_TESTS),
        (TestSuite, TaskType.GENERATE_TESTS),  # reintento con tests_retry (sin dirigido)
    ]
    retry_messages = llm.calls[-1]["messages"]
    assert retry_messages[-1].role == "user"
    assert "CA-02" in retry_messages[-1].content
    assert "negativo" in retry_messages[-1].content
    _assert_nothing_offered_or_audited(container)
    state = graph.get_state(config)
    assert state.values.get("artifact") is None
    assert state.next == ("generate",)


def test_generate_qa_only_missing_criterion_reaches_review_without_full_retry(
    tmp_path: Path,
) -> None:
    """PA-426: si lo único que falla es un CA sin caso, no hay reintento completo ni
    `CoverageError`: un reintento dirigido y, si no lo cubre, la suite llega a revisión."""
    llm = FakeLLMProvider()
    llm.builders[TestSuite] = _uncovering_suite

    def provider_down(_messages: list[Message]) -> TestSuite:
        raise ExternalServiceError("Proveedor ficticio no disponible.", service="llm")

    llm.builders[MissingCases] = provider_down
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = _config()

    payload = _payload(_start(graph, config))

    assert [c["schema"] for c in llm.calls] == [UserStory, TestSuite, MissingCases]
    assert len(_calls_for(container, "generate_tests")) == 1
    assert payload["artifact"]["type"] == ArtifactType.TEST_SUITE.value
    assert [e.action for e in _audit(container).recorded] == ["create"]


def test_generate_qa_recovers_when_retry_covers_story(tmp_path: Path) -> None:
    """PA-61 · RF-24 (límite): si el reintento sí cubre la HU, se ofrece la suite corregida
    (PA-426: el primer intento falla también por no tener caso negativo)."""
    llm = FakeLLMProvider()
    # el segundo, el del fake
    responses = iter([_uncovering_suite_without_negative, llm.builders[TestSuite]])
    llm.builders[TestSuite] = lambda m: next(responses)(m)
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = _config()

    payload = _payload(_start(graph, config))

    assert payload["artifact"]["type"] == ArtifactType.TEST_SUITE.value
    assert {c["internal_id"] for c in payload["artifact"]["content"]["cases"]} == {
        "CP-01",
        "CP-02",
    }
    # Cubierta tras el reintento de siempre: no hace falta el dirigido.
    assert [c["schema"] for c in llm.calls] == [UserStory, TestSuite, TestSuite]
    actions = [e.action for e in _audit(container).recorded]
    assert actions == ["create"]


# --- 6 · CitationError ------------------------------------------------------------------------


def test_generate_qa_raises_citation_error_after_retry_without_offer_or_audit(
    tmp_path: Path,
) -> None:
    """PA-61 · RF-21 · RNF-14: citar dos veces una fuente inexistente → `CitationError`."""
    llm = FakeLLMProvider()
    llm.builders[TestSuite] = _suite_citing_unknown_source
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = _config()

    with pytest.raises(CitationError, match="cita fuentes"):
        _start(graph, config)

    assert [c["task"] for c in llm.calls].count(TaskType.GENERATE_TESTS) == 2
    _assert_nothing_offered_or_audited(container)
    assert graph.get_state(config).values.get("artifact") is None


def test_generate_qa_citation_error_message_does_not_repeat_invented_ref(
    tmp_path: Path,
) -> None:
    """PA-61 · RNF-14 (error): el mensaje para la UI no repite la referencia inventada."""
    llm = FakeLLMProvider()
    llm.builders[TestSuite] = _suite_citing_unknown_source
    container = fake_container(tmp_path, llm=llm)

    with pytest.raises(CitationError) as excinfo:
        _start(build_graph(container), _config())

    assert "doc-inexistente-ficticio" not in str(excinfo.value)


# --- 7 · fuentes excluidas (T-51) ------------------------------------------------------------


def test_generate_qa_without_exclusions_includes_related_sources(tmp_path: Path) -> None:
    """T-51 (control): sin exclusiones, DEMO-2 y doc-glosario sí llegan a `generate_tests`."""
    container = fake_container(tmp_path)
    _start(build_graph(container), _config())

    (tests_call,) = _calls_for(container, "generate_tests")
    refs = {m.group(1) for m in _SOURCE_TAG.finditer(_user(tests_call))}
    assert {"DEMO-2", "doc-glosario"} <= refs


def test_generate_qa_excluded_sources_do_not_reach_generate_tests(tmp_path: Path) -> None:
    """PA-61 · T-51 · RF-21: las fuentes excluidas no llegan al prompt de `generate_tests`."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()

    _start(graph, config, excluded=["DEMO-2", "doc-glosario"])

    for call in _llm(container).calls:
        user = "\n".join(m.content for m in call["messages"] if m.role == "user")
        assert 'ref="DEMO-2"' not in user
        assert 'ref="doc-glosario"' not in user
    (tests_call,) = _calls_for(container, "generate_tests")
    refs = {m.group(1) for m in _SOURCE_TAG.finditer(_user(tests_call))}
    assert "DEMO-3" in refs  # el origen nunca se excluye
    artifact: Artifact = graph.get_state(config).values["artifact"]
    assert all(s.ref not in {"DEMO-2", "doc-glosario"} for s in artifact.content.sources)
    (create,) = _audit(container).entries(artifact.id)
    assert create.detail["excluded_sources"] == ["DEMO-2", "doc-glosario"]


def test_iterate_qa_keeps_excluded_sources_out_of_generate_tests(tmp_path: Path) -> None:
    """PA-61 · T-51: al iterar, las fuentes excluidas siguen fuera del prompt."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    _start(graph, config, excluded=["doc-glosario"])

    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)

    last = _user(_calls_for(container, "generate_tests")[-1])
    assert 'ref="doc-glosario"' not in last


# --- 8 · flujo completo en live con el fake ---------------------------------------------------


def test_qa_live_flow_publishes_generated_suite_without_memory(tmp_path: Path) -> None:
    """PA-61 · D-09 · D-07: generate → approve con huella → `publish_suite` de la suite generada."""
    testmgmt = RecordingTestManagement()
    container = fake_container(tmp_path, test_management=testmgmt)
    assert container.publish_mode == "live"
    graph = build_graph(container)
    config = _config()
    payload = _payload(_start(graph, config))
    generated = TestSuite.model_validate(payload["artifact"]["content"])

    final = graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": payload["fingerprint"]}), config
    )

    assert "__interrupt__" not in final
    assert graph.get_state(config).next == ()
    (published,) = testmgmt.published
    assert published == generated
    assert published.story_jira_key == "DEMO-3"
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert final["artifact"].content == generated
    created = [case.key for case in testmgmt.list_cases("DEMO-3")]
    assert final["published_keys"] == created and len(created) == 2
    assert final["errors"] == []
    attachments = testmgmt.attachments["DEMO-3"]
    assert attachments["estrategia-DEMO-3.md"] == generated.strategy_md
    assert attachments["matriz-DEMO-3.md"] == generated.coverage_md()
    # D-07: sin memoria para las suites.
    assert list(tmp_path.glob("*.md")) == []
    assert container.memory_generator.generated == []  # type: ignore[attr-defined]
    store = container.vector_store
    assert isinstance(store, FakeVectorStore)
    assert all(c.metadata.get("category") != "memoria" for c in store.chunks.values())
    assert container.issue_tracker.writes == []  # type: ignore[attr-defined]
    entries = _audit(container).entries(final["artifact"].id)
    assert [e.action for e in entries] == ["create", "approve", "publish"]
    assert entries[-1].detail["simulated"] is False
    assert entries[-1].jira_keys == created
    assert container.approvals.was_published(final["artifact"]) is True


def test_qa_live_flow_rejects_approval_with_wrong_fingerprint(tmp_path: Path) -> None:
    """PA-61 · Principio 1 (negativo): una huella que no es la mostrada no publica la suite."""
    testmgmt = RecordingTestManagement()
    container = fake_container(tmp_path, test_management=testmgmt)
    graph = build_graph(container)
    config = _config()
    first = _payload(_start(graph, config))

    again = _payload(
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": "huella-ficticia"}), config
        )
    )

    assert again["error"]
    assert again["fingerprint"] == first["fingerprint"]
    assert testmgmt.published == []
    assert testmgmt.publish_calls == 0
    actions = [e.action for e in _audit(container).entries(UUID(first["artifact"]["id"]))]
    assert actions == ["create"]


def test_qa_live_flow_after_iteration_publishes_latest_suite(tmp_path: Path) -> None:
    """PA-61 · RF-20: tras iterar, se publica la versión 2 aprobada, no la primera."""
    testmgmt = RecordingTestManagement()
    container = fake_container(tmp_path, test_management=testmgmt)
    graph = build_graph(container)
    config = _config()
    _start(graph, config)
    second = _payload(
        graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    )

    final = graph.invoke(_approve(graph, config), config)

    assert final["artifact"].version == 2
    (published,) = testmgmt.published
    assert published == TestSuite.model_validate(second["artifact"]["content"])
    assert len(_calls_for(container, "structure_story")) == 1


def _shared_ids(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """PA-432: anota los ids de la estructura compartida que calcula `_baseline`."""
    ids: list[str | None] = []
    original = nodes._shared_baseline_id

    def spy(issue_key: str | None, origin_only: StoryContext) -> str | None:
        ids.append(original(issue_key, origin_only))
        return ids[-1]

    monkeypatch.setattr(nodes, "_shared_baseline_id", spy)
    return ids


def test_failed_first_generation_leaves_no_orphan_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-1 de PA-61: si la primera versión falla, no queda versión de partida guardada.

    PA-432: la estructura compartida de la HU no es de la conversación; puede quedar además.
    """
    shared = _shared_ids(monkeypatch)
    llm = FakeLLMProvider()
    uncovered = renewal_test_suite().model_copy(
        update={"cases": renewal_test_suite().cases[:1]}  # CA-02 sin casos
    )
    llm.builders[TestSuite] = lambda _messages: uncovered
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-huerfano"}}
    state = initial_state("qa-demo", "qa", {"kind": "story", "key": "DEMO-3"})

    with pytest.raises((CoverageError, CitationError)):
        graph.invoke(state, config)
    with pytest.raises((CoverageError, CitationError)):
        graph.invoke(None, config)  # reintento en el mismo hilo

    store = container.state_store
    assert isinstance(store, InMemoryArtifactStateStore)
    # Ningún intento deja su versión de partida; solo queda la de la conversación (PA-339),
    # una sola, para que el siguiente reintento no vuelva a estructurar, y la compartida de la
    # HU (PA-432), la misma en los dos intentos.
    keys = {key for key, s in store.states.items() if "baseline" in s}
    assert len(set(shared)) == 1 and None not in shared
    assert keys == {_pending_baseline_key(config), *shared}


def test_initial_feedback_reaches_first_generate_tests(tmp_path: Path) -> None:
    """Tipos de caso de QA 1: `initial_state(..., feedback)` llega a la primera suite."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-feedback-qa"}}
    hint = "Incluye casos: positivos, negativos y de excepción (ficticio)."
    graph.invoke(initial_state(QA_USER, "qa", STORY_ORIGIN, feedback=[f"  {hint} ", " "]), config)

    (call,) = _calls_for(container, "generate_tests")
    assert hint in _user(call)
    assert graph.get_state(config).values["feedback"] == [hint]


def test_initial_feedback_reaches_first_evolution(tmp_path: Path) -> None:
    """Restricciones de Mixta 2 al evolucionar: llegan a la primera llamada `evolve_story`."""
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-feedback-hu"}}
    hint = "Mismas reglas que en la web (ficticio)."
    graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN, feedback=[hint]), config)

    evolve = _calls_for(container, "evolve_story")
    assert evolve and hint in _user(evolve[0])


def test_failed_first_evolution_leaves_no_orphan_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La limpieza de la versión de partida vale también para evolucionar una HU; solo queda la
    de la conversación (PA-339) y la estructura compartida de la HU (PA-432)."""
    shared = _shared_ids(monkeypatch)
    llm = FakeLLMProvider()
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-huerfano-hu"}}
    calls = {"n": 0}
    original = llm.builders[UserStory]

    def structure_then_fail(messages: list[Message]) -> UserStory:
        calls["n"] += 1
        if calls["n"] > 1:  # la estructuración funciona; la evolución falla
            raise RuntimeError("fallo ficticio del proveedor")
        return original(messages)

    llm.builders[UserStory] = structure_then_fail
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)

    store = container.state_store
    assert isinstance(store, InMemoryArtifactStateStore)
    keys = {key for key, s in store.states.items() if "baseline" in s}
    assert len(shared) == 1 and shared[0] is not None
    assert keys == {_pending_baseline_key(config), shared[0]}
