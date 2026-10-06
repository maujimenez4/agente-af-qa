"""Pruebas del arranque guiado sin IA (T-53 · RF-14, RF-19) y de la vista previa de fuentes.

Cubren el reconocimiento de claves de Jira en el texto, las opciones de arranque según el tipo
de incidencia y el modo, las HU parecidas por búsqueda de texto (`ContextService`), la vista
previa de fuentes del panel «Antes de generar» y que las opciones arrancan el grafo hasta
`human_review`. Ninguna llama al LLM. Datos 100 % sintéticos del dataset de `tests/fakes/`.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from adapters.base import Chunk, IssueDetail, IssueSummary
from core.config import AppConfig, Settings, load_models_config
from core.container import Container
from core.context.service import ContextService, build_context_service
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import GraphNodes, validate_origin
from core.guided_start import (
    MAX_KEYS,
    GuidedStart,
    SourcePreview,
    StartOption,
    find_issue_keys,
)
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.vector_store import FakeVectorStore

AF_USER = "af-demo"
QA_USER = "qa-demo"
OTHER_PROJECT = "OTRO"
OTHER_STORY = "OTRO-7"
NEED_TEXT = "Avisar por correo del vencimiento del préstamo con tres días de antelación."

# --- utilidades --------------------------------------------------------------------------


def _issue(key: str, issue_type: str, summary: str, parent: str | None = None) -> IssueDetail:
    return IssueDetail(
        key=key,
        summary=summary,
        issue_type=issue_type,
        status="Por hacer",
        parent_key=parent,
        description_text=f"Descripción ficticia de {key}.",
    )


EXTRA_ISSUES = {
    OTHER_STORY: _issue(OTHER_STORY, "Story", "[HU-90] Consultar avisos ficticios"),
    "DEMO-20": _issue("DEMO-20", "Subtarea", "CP-01 Renovar (subtarea ficticia)", "DEMO-3"),
    "DEMO-21": _issue("DEMO-21", "Sub-task", "CP-02 Renovar (subtarea ficticia)", "DEMO-3"),
    "DEMO-22": _issue("DEMO-22", "Task", "Configurar el entorno ficticio"),
    "DEMO-23": _issue("DEMO-23", "Tarea", "Revisar textos ficticios"),
    "DEMO-24": _issue("DEMO-24", "Épica", "Avisos de préstamo (épica ficticia)"),
}


@dataclass
class SpyIssueTracker(FakeIssueTracker):
    """Registra las JQL y devuelve `candidates` para la JQL de palabras clave (con «OR»).

    El fake base no casa `text ~ "a OR b"` (exige todas las palabras), así que aquí se simula
    la respuesta de Jira para la búsqueda de HU parecidas.
    """

    candidates: list[IssueSummary] = field(default_factory=list)
    jqls: list[str] = field(default_factory=list)

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        self.jqls.append(jql)
        if " OR " in jql or "text ~" in jql:
            return self.candidates[:limit]
        return super().search(jql, limit)


def _tracker_with_extras() -> FakeIssueTracker:
    tracker = FakeIssueTracker()
    tracker.issues.update({k: v.model_copy(deep=True) for k, v in EXTRA_ISSUES.items()})
    return tracker


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path, issue_tracker=_tracker_with_extras())


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _summary(issue: IssueDetail) -> IssueSummary:
    return dataset.summary_of(issue)


def _candidates() -> list[IssueSummary]:
    """Épica, subtareas y tareas mezcladas con HU, como podría devolverlas Jira."""
    return [
        _summary(dataset.EPIC),
        _summary(EXTRA_ISSUES["DEMO-20"]),
        _summary(dataset.STORIES["DEMO-3"]),
        _summary(EXTRA_ISSUES["DEMO-21"]),
        _summary(EXTRA_ISSUES["DEMO-22"]),
        _summary(dataset.STORIES["DEMO-2"]),
        _summary(EXTRA_ISSUES["DEMO-23"]),
        _summary(EXTRA_ISSUES["DEMO-24"]),
        _summary(dataset.STORIES["DEMO-4"]),
    ]


def _spy_container(tmp_path: Path, candidates: list[IssueSummary] | None = None) -> Container:
    spy = SpyIssueTracker(candidates=_candidates() if candidates is None else candidates)
    spy.issues.update({k: v.model_copy(deep=True) for k, v in EXTRA_ISSUES.items()})
    return fake_container(tmp_path, issue_tracker=spy)


def _spy(container: Container) -> SpyIssueTracker:
    assert isinstance(container.issue_tracker, SpyIssueTracker)
    return container.issue_tracker


def _kinds(options: list[StartOption]) -> list[str]:
    return [o.kind for o in options]


def _assert_origin_valid(option: StartOption, mode: str) -> None:
    """El `origin` de la opción va tal cual a `initial_state` y pasa `validate_origin`."""
    validate_origin(initial_state(AF_USER, mode, option.origin))  # type: ignore[arg-type]


def _add_memory(container: Container, document_id: str, content: str) -> None:
    store = container.vector_store
    assert isinstance(store, FakeVectorStore)
    (vector,) = container.embeddings.embed([content])
    store.upsert(
        [
            Chunk(
                id=f"{document_id}-0",
                document_id=document_id,
                ordinal=0,
                section="Memoria ficticia de DEMO-3",
                content=content,
                embedding=vector,
                metadata={"category": "memoria", "title": "Memoria ficticia de DEMO-3"},
            )
        ]
    )


# --- 1 · find_issue_keys -----------------------------------------------------------------


def test_find_issue_keys_lowercase_normalized_to_uppercase() -> None:
    """RF-14 (T-53): «demo-3» en minúsculas se reconoce como DEMO-3."""
    assert find_issue_keys("quiero evolucionar demo-3 cuanto antes") == ["DEMO-3"]


def test_find_issue_keys_mixed_case_normalized() -> None:
    """RF-14 (T-53): mayúsculas y minúsculas mezcladas se normalizan."""
    assert find_issue_keys("Revisar Demo-12 y dEmO-4") == ["DEMO-12", "DEMO-4"]


def test_find_issue_keys_duplicates_removed_keeping_order() -> None:
    """RF-14 (T-53): sin repetir (aunque cambie el caso) y en el orden de aparición."""
    text = "DEMO-4, luego demo-2, otra vez DEMO-4 y Demo-2 y por fin DEMO-3"
    assert find_issue_keys(text) == ["DEMO-4", "DEMO-2", "DEMO-3"]


def test_find_issue_keys_default_limit_is_five() -> None:
    """RF-14 (T-53, límite): como máximo MAX_KEYS (5) claves por defecto."""
    text = " ".join(f"DEMO-{n}" for n in range(1, 9))
    assert MAX_KEYS == 5
    assert find_issue_keys(text) == [f"DEMO-{n}" for n in range(1, 6)]


def test_find_issue_keys_custom_limit_counts_unique_keys() -> None:
    """RF-14 (T-53, límite): el límite cuenta claves distintas, no apariciones."""
    assert find_issue_keys("DEMO-1 DEMO-1 DEMO-1 DEMO-2 DEMO-3", limit=2) == ["DEMO-1", "DEMO-2"]


def test_find_issue_keys_zero_limit_returns_nothing() -> None:
    """RF-14 (T-53, límite): con limit=0 no se devuelve ninguna clave."""
    assert find_issue_keys("DEMO-1 DEMO-2", limit=0) == []


@pytest.mark.parametrize(
    "text",
    ["(DEMO-3).", "DEMO-3,", "«DEMO-3»", "[DEMO-3]", "DEMO-3:", "¿DEMO-3?", "'demo-3'", "DEMO-3\n"],
)
def test_find_issue_keys_punctuation_around_key(text: str) -> None:
    """RF-14 (T-53): la puntuación alrededor de la clave no impide reconocerla."""
    assert find_issue_keys(text) == ["DEMO-3"]


@pytest.mark.parametrize(
    "text",
    [
        "XDEMO-3a",  # letra detrás: no es una clave (no toma XDEMO-3 ni DEMO-3)
        "DEMO-3-4",  # guion detrás: se descarta entera (ni DEMO-3 ni DEMO-4)
        "DEMO-3a",
        "1DEMO-3",  # dígito delante
        "-DEMO-3",  # guion delante
        "DEMO-3_b",  # guion bajo detrás
    ],
)
def test_find_issue_keys_does_not_cut_longer_words(text: str) -> None:
    """RF-14 (T-53, negativo): no toma una clave de dentro de una palabra más larga."""
    assert find_issue_keys(text) == []


def test_find_issue_keys_underscore_prefix_is_part_of_project_key() -> None:
    """RF-14 (T-53, límite): «ab_DEMO-3» no da DEMO-3; el `_` es válido en la clave de proyecto,
    así que la palabra entera se toma como la clave AB_DEMO-3 (comportamiento documentado:
    solo contará si existe en Jira)."""
    assert find_issue_keys("ab_DEMO-3") == ["AB_DEMO-3"]


def test_find_issue_keys_single_letter_project_ignored() -> None:
    """RF-14 (T-53, negativo): «A-1» no tiene forma de clave (proyecto de 2+ caracteres)."""
    assert find_issue_keys("paso A-1 y b-2") == []


def test_find_issue_keys_number_first_ignored() -> None:
    """RF-14 (T-53, negativo): «123-4» o «2024-10» no son claves."""
    assert find_issue_keys("el 2024-10 y 123-4") == []


def test_find_issue_keys_covid_like_word_is_candidate() -> None:
    """RF-14 (T-53): «COVID-19» tiene forma de clave; se descarta después si no existe."""
    assert find_issue_keys("informe COVID-19") == ["COVID-19"]


@pytest.mark.parametrize("text", ["", "   ", "sin claves en este texto ficticio"])
def test_find_issue_keys_empty_or_without_keys(text: str) -> None:
    """RF-14 (T-53, límite): texto vacío o sin claves → lista vacía."""
    assert find_issue_keys(text) == []


def test_find_issue_keys_none_text_tolerated() -> None:
    """RF-14 (T-53, error): un `None` llegado de la UI no rompe (`text or ""`)."""
    assert find_issue_keys(None) == []  # type: ignore[arg-type]


# --- 2 · claves existentes y claves que no existen ---------------------------------------


def test_propose_lowercase_existing_key_offers_evolve(container: Container) -> None:
    """RF-14, RF-19 (T-53): «demo-3» existe → opción «Evolucionar DEMO-3» con origen story."""
    proposal = GuidedStart(container).propose("quiero cambiar demo-3", "DEMO")

    assert [i.key for i in proposal.recognized] == ["DEMO-3"]
    assert proposal.similar == []
    (option,) = proposal.options
    assert option.kind == "evolve"
    assert option.label == "Evolucionar DEMO-3"
    assert option.origin == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    assert option.issue is not None and option.issue.key == "DEMO-3"
    assert proposal.project == "DEMO"
    assert proposal.project_changed is False
    _assert_origin_valid(option, "functional")


def test_propose_nonexistent_key_ignored_keeps_existing(container: Container) -> None:
    """RF-14 (T-53, negativo): «COVID-19» no existe en Jira → se ignora; DEMO-3 sí cuenta."""
    proposal = GuidedStart(container).propose("COVID-19 afecta a DEMO-3", "DEMO")

    assert [i.key for i in proposal.recognized] == ["DEMO-3"]
    assert _kinds(proposal.options) == ["evolve"]


def test_propose_only_nonexistent_keys_falls_back_to_similar(tmp_path: Path) -> None:
    """RF-14, RF-19 (T-53): si ninguna clave existe, se pasa a HU parecidas por texto."""
    container = _spy_container(tmp_path, [_summary(dataset.STORIES["DEMO-3"])])
    proposal = GuidedStart(container).propose("Renovar préstamos durante el COVID-19", "DEMO")

    assert proposal.recognized == []
    assert [i.key for i in proposal.similar] == ["DEMO-3"]
    assert _kinds(proposal.options) == ["evolve", "new_need"]
    assert any("text ~" in jql for jql in _spy(container).jqls)


def test_propose_several_existing_keys_one_option_each(container: Container) -> None:
    """RF-14 (T-53): varias claves existentes → una opción por clave, en orden."""
    proposal = GuidedStart(container).propose("DEMO-4 depende de demo-2", "DEMO")

    assert [i.key for i in proposal.recognized] == ["DEMO-4", "DEMO-2"]
    assert [o.label for o in proposal.options] == ["Evolucionar DEMO-4", "Evolucionar DEMO-2"]
    for option in proposal.options:
        _assert_origin_valid(option, "functional")


def test_propose_recognized_are_summaries(container: Container) -> None:
    """RF-14 (T-53): `recognized` son resúmenes (clave, título, tipo, estado)."""
    proposal = GuidedStart(container).propose("DEMO-3", "DEMO")
    assert proposal.recognized == [_summary(dataset.STORIES["DEMO-3"])]


# --- 3 · clave de otro proyecto ----------------------------------------------------------


def test_propose_key_from_other_project_changes_project(container: Container) -> None:
    """RF-14 (T-50, T-53): una clave de otro proyecto → `project_changed` y el proyecto de la
    clave; el origen de la opción pertenece a ese proyecto."""
    proposal = GuidedStart(container).propose("revisar otro-7", "DEMO")

    assert proposal.project == OTHER_PROJECT
    assert proposal.project_changed is True
    (option,) = proposal.options
    assert option.origin == {"kind": "story", "key": OTHER_STORY, "project": OTHER_PROJECT}
    _assert_origin_valid(option, "functional")


def test_propose_project_is_the_first_recognized_key(container: Container) -> None:
    """RF-14 (T-53): con claves de varios proyectos manda la primera con opción; solo se ofrecen
    las de ese proyecto y el resto se avisa en `ignored_projects`."""
    proposal = GuidedStart(container).propose("DEMO-3 y OTRO-7", "OTRO")

    assert proposal.project == "DEMO"
    assert proposal.project_changed is True
    assert [o.origin.get("project") for o in proposal.options] == ["DEMO"]
    assert proposal.ignored_projects == [OTHER_PROJECT]


def test_propose_first_key_nonexistent_does_not_set_project(container: Container) -> None:
    """RF-14 (T-53, negativo): una primera clave inexistente no decide el proyecto."""
    proposal = GuidedStart(container).propose("NOPE-1 y OTRO-7", "DEMO")

    assert proposal.project == OTHER_PROJECT
    assert proposal.project_changed is True


def test_propose_same_project_lowercase_input_not_changed(container: Container) -> None:
    """RF-14 (T-53): el proyecto dado se normaliza («demo» → DEMO) y no cuenta como cambio."""
    proposal = GuidedStart(container).propose("DEMO-3", " demo ")

    assert proposal.project == "DEMO"
    assert proposal.project_changed is False


@pytest.mark.parametrize("project", ["", "1DEMO", "DEMO-1", "../x", "D"])
def test_propose_invalid_project_raises(container: Container, project: str) -> None:
    """RF-14 (T-53, error): un proyecto no válido → ValueError con mensaje para la UI."""
    with pytest.raises(ValueError, match="clave de proyecto válida"):
        GuidedStart(container).propose("DEMO-3", project)


# --- 4 · tipo de incidencia y modo -------------------------------------------------------


def test_propose_epic_offers_new_story_in_epic(container: Container) -> None:
    """RF-19 (T-53, PA-285): épica en modo funcional → «HU nueva en la épica DEMO-1»."""
    proposal = GuidedStart(container).propose("algo para DEMO-1", "DEMO")

    (option,) = proposal.options
    assert option.kind == "new_story_in_epic"
    assert option.label == "HU nueva en la épica DEMO-1"  # PA-285
    assert option.origin == {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}
    _assert_origin_valid(option, "functional")


def test_propose_spanish_epic_type_offers_new_story_in_epic(container: Container) -> None:
    """RF-19 (T-53): el tipo «Épica» (Jira en español) se trata como épica."""
    (option,) = GuidedStart(container).propose("DEMO-24", "DEMO").options
    assert option.kind == "new_story_in_epic"


def test_propose_epic_in_qa_has_no_option(container: Container) -> None:
    """RF-19 (T-53, negativo): en QA una épica no da opción (QA parte de una HU), aunque se
    reconoce."""
    proposal = GuidedStart(container).propose("DEMO-1", "DEMO", mode="qa")

    assert [i.key for i in proposal.recognized] == ["DEMO-1"]
    assert proposal.options == []
    assert proposal.similar == []


@pytest.mark.parametrize("key", ["DEMO-20", "DEMO-21", "DEMO-22", "DEMO-23"])
@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_propose_subtask_or_task_has_no_option(container: Container, key: str, mode: str) -> None:
    """RF-19 (T-53, negativo): subtareas y tareas no son origen; en funcional, «Crear HU nueva»."""
    proposal = GuidedStart(container).propose(f"mira {key}", "DEMO", mode=mode)  # type: ignore[arg-type]

    assert [i.key for i in proposal.recognized] == [key]
    assert [o.kind for o in proposal.options] == (["new_need"] if mode == "functional" else [])
    assert proposal.similar == []  # reconocida: no se buscan HU parecidas
    assert proposal.project_changed is False


def test_propose_story_in_qa_offers_tests(container: Container) -> None:
    """RF-19 (T-53): HU en modo QA → «Preparar pruebas de DEMO-3» con origen story."""
    (option,) = GuidedStart(container).propose("demo-3", "DEMO", mode="qa").options

    assert option.kind == "tests"
    assert option.label == "Preparar pruebas de DEMO-3"
    assert option.origin == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    _assert_origin_valid(option, "qa")


def test_propose_mixed_types_only_valid_options(container: Container) -> None:
    """RF-19 (T-53): épica + subtarea + HU → opciones solo para la épica y la HU."""
    proposal = GuidedStart(container).propose("DEMO-1 DEMO-20 DEMO-3", "DEMO")

    assert [i.key for i in proposal.recognized] == ["DEMO-1", "DEMO-20", "DEMO-3"]
    assert _kinds(proposal.options) == ["new_story_in_epic", "evolve"]


# --- 5 · HU parecidas por búsqueda de texto ----------------------------------------------


def test_similar_filters_non_stories_and_caps_at_three(tmp_path: Path) -> None:
    """RF-14 (T-53): se descartan épicas, subtareas y tareas; como máximo 3 HU parecidas."""
    container = _spy_container(tmp_path)
    proposal = GuidedStart(container).propose(NEED_TEXT, "DEMO")

    assert proposal.recognized == []
    assert len(proposal.similar) <= 3
    assert {i.issue_type for i in proposal.similar} == {"Story"}
    assert {i.key for i in proposal.similar} <= {"DEMO-2", "DEMO-3", "DEMO-4"}


def test_similar_returns_three_when_enough_stories(tmp_path: Path) -> None:
    """RF-14 (T-53, límite): con 3+ HU candidatas se devuelven exactamente 3."""
    stories = [_summary(s) for s in dataset.STORIES.values()]
    extra = _summary(_issue("DEMO-30", "Story", "Préstamo ficticio adicional"))
    container = _spy_container(tmp_path, [*stories, extra])

    proposal = GuidedStart(container).propose(NEED_TEXT, "DEMO")

    assert len(proposal.similar) == 3
    assert _kinds(proposal.options) == ["evolve", "evolve", "evolve", "new_need"]


def test_similar_cap_applies_after_filtering_non_stories(tmp_path: Path) -> None:
    """RF-14 (T-53, límite): las épicas/tareas no deben ocupar el hueco de las HU: si Jira
    devuelve primero 3 no-HU y después 3 HU, se esperan las 3 HU."""
    noise = [_summary(EXTRA_ISSUES[k]) for k in ("DEMO-20", "DEMO-22", "DEMO-24")]
    stories = [_summary(s) for s in dataset.STORIES.values()]
    container = _spy_container(tmp_path, [*noise, *stories])

    proposal = GuidedStart(container).propose("ficticio texto", "DEMO")

    assert len(proposal.similar) == 3


def test_similar_options_evolve_and_new_need(tmp_path: Path) -> None:
    """RF-14, RF-19 (T-53): cada HU parecida da «Evolucionar» y al final «Crear HU nueva»
    con el texto sin espacios y el proyecto dado."""
    container = _spy_container(tmp_path)
    text = f"   {NEED_TEXT}  \n"
    proposal = GuidedStart(container).propose(text, "DEMO")

    *evolve, new_need = proposal.options
    assert evolve and all(o.kind == "evolve" for o in evolve)
    assert [o.origin.get("key") for o in evolve] == [i.key for i in proposal.similar]
    assert all(o.label == f"Evolucionar {o.origin.get('key')}" for o in evolve)
    assert all(o.origin.get("project") == "DEMO" for o in evolve)
    assert new_need.kind == "new_need"
    assert new_need.label == "Crear HU nueva"
    assert new_need.origin == {"kind": "need", "text": NEED_TEXT, "project": "DEMO"}
    assert new_need.issue is None
    assert proposal.project == "DEMO" and proposal.project_changed is False
    for option in proposal.options:
        _assert_origin_valid(option, "functional")


def test_similar_jql_uses_given_project_not_env_default(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """RF-14 (T-50, T-53): la JQL usa el proyecto de la conversación, no `JIRA_PROJECT_KEY`."""
    base = _spy_container(tmp_path)
    settings = Settings(_env_file=None, jira_project_key="ENVDEF")  # type: ignore[call-arg]
    container = replace(base, config=AppConfig(settings, load_models_config()))

    GuidedStart(container).propose(NEED_TEXT, "prueba")

    jqls = [j for j in _spy(container).jqls if "text ~" in j]
    assert jqls and all(j.startswith('project = "PRUEBA"') for j in jqls)
    assert not any("ENVDEF" in j for j in _spy(container).jqls)


def test_similar_stories_service_uses_explicit_project() -> None:
    """RF-14 (T-53): `ContextService.similar_stories` busca en el proyecto que recibe, aunque
    el servicio se construyera con otro."""
    spy = SpyIssueTracker(candidates=_candidates())
    service = ContextService(
        spy,
        FakeEmbeddingProvider(),
        FakeVectorStore(),
        top_k=3,
        memory_boost=1.0,
        token_budget=6000,
        project_key="ENVDEF",
    )

    result = service.similar_stories(NEED_TEXT, "DEMO")

    assert spy.jqls and spy.jqls[-1].startswith('project = "DEMO"')
    assert all(i.issue_type == "Story" for i in result)


def test_similar_stories_invalid_project_no_search() -> None:
    """RF-14 (T-53, error): clave de proyecto no válida → sin búsqueda y lista vacía."""
    spy = SpyIssueTracker(candidates=_candidates())
    service = ContextService(
        spy,
        FakeEmbeddingProvider(),
        FakeVectorStore(),
        top_k=3,
        memory_boost=1.0,
        token_budget=6000,
    )
    assert service.similar_stories(NEED_TEXT, "no válido") == []
    assert spy.jqls == []


def test_similar_in_qa_offers_tests_without_new_need(tmp_path: Path) -> None:
    """RF-19 (T-53): en QA las HU parecidas dan «Preparar pruebas de…» y no hay `new_need`."""
    container = _spy_container(tmp_path)
    proposal = GuidedStart(container).propose(NEED_TEXT, "DEMO", mode="qa")

    assert proposal.similar
    assert set(_kinds(proposal.options)) == {"tests"}
    assert all(o.label.startswith("Preparar pruebas de ") for o in proposal.options)
    for option in proposal.options:
        _assert_origin_valid(option, "qa")


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_similar_empty_text_does_not_search(tmp_path: Path, text: str, mode: str) -> None:
    """RF-14 (T-53, límite): texto vacío → no se busca en Jira y no hay opciones."""
    container = _spy_container(tmp_path)
    proposal = GuidedStart(container).propose(text, "DEMO", mode=mode)  # type: ignore[arg-type]

    assert _spy(container).jqls == []
    assert proposal.similar == [] and proposal.options == []
    assert proposal.project == "DEMO" and proposal.project_changed is False


def test_similar_no_candidates_only_new_need(tmp_path: Path) -> None:
    """RF-14 (T-53): sin HU parecidas en modo funcional, solo «Crear HU nueva»."""
    container = _spy_container(tmp_path, [])
    proposal = GuidedStart(container).propose(NEED_TEXT, "DEMO")

    assert proposal.similar == []
    assert _kinds(proposal.options) == ["new_need"]


def test_similar_only_stopwords_still_offers_new_need(tmp_path: Path) -> None:
    """RF-14 (T-53, límite): texto sin palabras clave (solo vacías) → sin búsqueda, pero sí
    «Crear HU nueva»."""
    container = _spy_container(tmp_path)
    proposal = GuidedStart(container).propose("como quiero para", "DEMO")

    assert _spy(container).jqls == []
    assert _kinds(proposal.options) == ["new_need"]


# --- 6 · sin LLM -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("demo-3", "functional"),
        ("DEMO-1", "functional"),
        ("OTRO-7", "qa"),
        ("COVID-19", "functional"),
        (NEED_TEXT, "functional"),
        (NEED_TEXT, "qa"),
        ("", "functional"),
    ],
)
def test_propose_never_calls_llm(tmp_path: Path, text: str, mode: str) -> None:
    """RF-14 (T-53): el arranque guiado no llama al LLM en ningún caso."""
    container = _spy_container(tmp_path)
    GuidedStart(container).propose(text, "DEMO", mode=mode)  # type: ignore[arg-type]
    assert _llm(container).calls == []


@pytest.mark.parametrize(
    "origin",
    [
        {"kind": "story", "key": "DEMO-3", "project": "DEMO"},
        {"kind": "epic", "key": "DEMO-1", "project": "DEMO"},
        {"kind": "need", "text": NEED_TEXT, "project": "DEMO"},
    ],
)
def test_preview_sources_never_calls_llm(container: Container, origin: Origin) -> None:
    """RF-21 (T-53): la vista previa de fuentes no llama al LLM."""
    GuidedStart(container).preview_sources(origin, excluded=["doc-glosario"])
    assert _llm(container).calls == []


# --- 7 · preview_sources -----------------------------------------------------------------


def test_preview_sources_origin_is_required(container: Container) -> None:
    """RF-21 (T-51, T-53): la incidencia de origen va primera y como `required`; el resto no."""
    rows = GuidedStart(container).preview_sources(
        {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    )

    assert rows[0].model_copy(update={"tokens": None}) == SourcePreview(
        ref="DEMO-3",
        kind="jira",
        title=dataset.STORIES["DEMO-3"].summary,
        category="Story",
        required=True,
    )
    assert rows[0].tokens and rows[0].tokens > 0  # PA-330
    assert [r.ref for r in rows if r.required] == ["DEMO-3"]


def test_preview_sources_refs_unique_and_kinds(container: Container) -> None:
    """RF-21 (T-53): refs sin repetir y con los tipos jira, rag y memory."""
    _add_memory(container, "mem-demo-3", "Memoria ficticia: renovar un préstamo DEMO-3.")
    rows = GuidedStart(container).preview_sources(
        {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    )

    refs = [r.ref for r in rows]
    assert len(refs) == len(set(refs))
    assert {r.kind for r in rows} == {"jira", "rag", "memory"}
    jira = {r.ref for r in rows if r.kind == "jira"}
    assert {"DEMO-3", "DEMO-1", "DEMO-2"} <= jira  # origen, épica y vínculo
    memory = next(r for r in rows if r.kind == "memory")
    assert memory.ref == "mem-demo-3"
    assert memory.category == "memoria"
    assert memory.title == "Memoria ficticia de DEMO-3"
    rag = next(r for r in rows if r.ref == "doc-reglamento")
    assert rag.kind == "rag"
    assert rag.title == dataset.DOCUMENTS["doc-reglamento"]["title"]  # de la sección
    assert rag.category == "politicas"
    assert not any(r.required for r in rows if r.kind != "jira")


def test_preview_sources_rag_chunks_of_same_document_once(container: Container) -> None:
    """RF-21 (T-53, límite): dos fragmentos del mismo documento → una sola fila."""
    store = container.vector_store
    assert isinstance(store, FakeVectorStore)
    content = "Artículo 9 ficticio: renovar un préstamo dos veces como máximo."
    (vector,) = container.embeddings.embed([content])
    store.upsert(
        [
            Chunk(
                id="doc-reglamento-1",
                document_id="doc-reglamento",
                ordinal=1,
                section="Reglamento de préstamo (ficticio)",
                content=content,
                embedding=vector,
                metadata={"category": "politicas"},
            )
        ]
    )
    rows = GuidedStart(container).preview_sources(
        {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    )
    assert [r.ref for r in rows].count("doc-reglamento") == 1


def test_preview_sources_excluded_respected(container: Container) -> None:
    """RF-21 (T-51, T-53): las fuentes excluidas no aparecen; el origen no se puede excluir."""
    origin: Origin = {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    service = GuidedStart(container)
    before = {r.ref for r in service.preview_sources(origin)}
    assert {"DEMO-2", "doc-reglamento"} <= before

    rows = service.preview_sources(origin, excluded=["DEMO-2", "doc-reglamento"])

    refs = {r.ref for r in rows}
    assert "DEMO-2" not in refs and "doc-reglamento" not in refs
    assert "DEMO-3" in refs
    assert next(r for r in rows if r.ref == "DEMO-3").required is True
    # PA-223: como en el grafo, excluir el origen es un error (antes se ignoraba).
    with pytest.raises(ValueError, match="no se puede excluir"):
        service.preview_sources(origin, excluded=["DEMO-2", "DEMO-3"])


def test_preview_sources_need_has_no_required(tmp_path: Path) -> None:
    """RF-21 (T-53): con una necesidad nueva no hay incidencia de origen obligatoria."""
    container = _spy_container(tmp_path, [_summary(dataset.STORIES["DEMO-3"])])
    rows = GuidedStart(container).preview_sources(
        {"kind": "need", "text": NEED_TEXT, "project": "DEMO"}
    )

    assert rows and not any(r.required for r in rows)
    assert "DEMO-3" in {r.ref for r in rows}


def test_preview_sources_epic_lists_children(container: Container) -> None:
    """RF-21 (T-53): con una épica, el origen es obligatorio y aparecen sus HU hijas."""
    rows = GuidedStart(container).preview_sources(
        {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}
    )
    assert rows[0].ref == "DEMO-1" and rows[0].required is True
    assert {"DEMO-2", "DEMO-3", "DEMO-4"} <= {r.ref for r in rows}


def _graph_sources(container: Container, mode: str, origin: Origin, excluded: list[str]) -> list:
    graph = build_graph(container)
    config: dict[str, Any] = {"configurable": {"thread_id": f"hilo-{uuid4()}"}}
    user = QA_USER if mode == "qa" else AF_USER
    graph.invoke(initial_state(user, mode, origin, excluded_sources=excluded), config)  # type: ignore[arg-type]
    values = graph.get_state(config).values
    refs = [i.key for i in values["jira_context"]]
    for hit in values["rag_context"]:
        if hit.source.ref not in refs:
            refs.append(hit.source.ref)
    return refs


@pytest.mark.parametrize(
    ("mode", "origin", "excluded"),
    [
        ("functional", {"kind": "story", "key": "DEMO-3", "project": "DEMO"}, []),
        ("functional", {"kind": "story", "key": "DEMO-3", "project": "DEMO"}, ["DEMO-2"]),
        ("functional", {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}, ["doc-glosario"]),
        ("functional", {"kind": "need", "text": NEED_TEXT, "project": "DEMO"}, []),
        ("qa", {"kind": "story", "key": "DEMO-3", "project": "DEMO"}, ["doc-reglamento"]),
    ],
)
def test_preview_sources_match_graph_retrieve_context(
    tmp_path: Path, mode: str, origin: Origin, excluded: list[str]
) -> None:
    """RF-21 (T-53): la vista previa coincide con las fuentes que reúne `retrieve_context` en
    el grafo para el mismo origen y las mismas exclusiones."""
    preview = GuidedStart(fake_container(tmp_path / "a")).preview_sources(origin, excluded)
    graph_refs = _graph_sources(fake_container(tmp_path / "b"), mode, origin, excluded)

    assert [r.ref for r in preview] == graph_refs


# --- 8 · las opciones arrancan el grafo --------------------------------------------------


def _pauses_in_review(container: Container, user: str, mode: str, option: StartOption) -> None:
    graph = build_graph(container)
    config: dict[str, Any] = {"configurable": {"thread_id": f"hilo-{uuid4()}"}}
    result = graph.invoke(initial_state(user, mode, option.origin), config)  # type: ignore[arg-type]
    assert graph.get_state(config).next == ("human_review",)
    (pending,) = result["__interrupt__"]
    assert pending.value["artifact"]["version"] == 1


@pytest.mark.parametrize(
    ("text", "mode", "kind"),
    [
        ("demo-3", "functional", "evolve"),
        ("DEMO-1", "functional", "new_story_in_epic"),
        ("demo-3", "qa", "tests"),
    ],
)
def test_recognized_option_starts_graph_until_review(
    tmp_path: Path, text: str, mode: str, kind: str
) -> None:
    """RF-19 (T-53): la opción de una clave reconocida arranca el grafo hasta `human_review`."""
    container = fake_container(tmp_path)
    (option,) = GuidedStart(container).propose(text, "DEMO", mode=mode).options  # type: ignore[arg-type]
    assert option.kind == kind

    _pauses_in_review(container, QA_USER if mode == "qa" else AF_USER, mode, option)


@pytest.mark.parametrize(("mode", "kind"), [("functional", "evolve"), ("qa", "tests")])
def test_similar_option_starts_graph_until_review(tmp_path: Path, mode: str, kind: str) -> None:
    """RF-14, RF-19 (T-53): la opción de una HU parecida arranca el grafo hasta la revisión."""
    container = _spy_container(tmp_path, [_summary(dataset.STORIES["DEMO-3"])])
    proposal = GuidedStart(container).propose(NEED_TEXT, "DEMO", mode=mode)  # type: ignore[arg-type]
    option = next(o for o in proposal.options if o.kind == kind)

    _pauses_in_review(container, QA_USER if mode == "qa" else AF_USER, mode, option)


def test_new_need_option_starts_graph_until_review(tmp_path: Path) -> None:
    """RF-19 (T-53): «Crear HU nueva» arranca el grafo con la necesidad hasta la revisión."""
    container = _spy_container(tmp_path, [])
    (option,) = GuidedStart(container).propose(NEED_TEXT, "DEMO").options
    assert option.kind == "new_need"

    _pauses_in_review(container, AF_USER, "functional", option)


def test_other_project_option_starts_graph_until_review(tmp_path: Path) -> None:
    """RF-14 (T-50, T-53): la opción con clave de otro proyecto arranca el grafo en él."""
    tracker = _tracker_with_extras()
    container = fake_container(tmp_path, issue_tracker=tracker)
    (option,) = GuidedStart(container).propose("OTRO-7", "DEMO").options

    _pauses_in_review(container, AF_USER, "functional", option)


# --- 9 · regresión: build_context_service y GraphNodes._context_service ------------------


def test_build_context_service_matches_graph_context_service(container: Container) -> None:
    """Regresión (T-53): `GraphNodes._context_service` usa `build_context_service` con el
    proyecto del origen y la misma configuración del contenedor."""
    state = initial_state(AF_USER, "functional", {"kind": "need", "text": "x", "project": "DEMO"})
    from_graph = GraphNodes(container)._context_service(state)
    built = build_context_service(container, "DEMO")

    assert vars(from_graph) == vars(built)
    assert built._project_key == "DEMO"
    assert built._token_budget == 3300  # sin AppConfig: DEFAULT_TOKEN_BUDGET (PA-114)
    assert built._top_k == container.top_k
    assert built._memory_boost == container.memory_boost


def test_build_context_service_reads_budget_from_config(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """Regresión (T-53): con AppConfig, el presupuesto sale de `models.yaml`."""
    base = fake_container(tmp_path)
    config = AppConfig(Settings(_env_file=None), load_models_config())  # type: ignore[call-arg]
    container = replace(base, config=config)

    service = build_context_service(container, None)

    assert service._token_budget == config.models.limits.context_token_budget
    assert service._project_key is None


def test_only_subtasks_recognized_still_offers_new_need(tmp_path: Path) -> None:
    """Si solo se reconocen subtareas o tareas, en modo funcional se ofrece «Crear HU nueva»."""
    container = fake_container(tmp_path)
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    tracker.issues["DEMO-77"] = IssueDetail(
        key="DEMO-77", summary="Subtarea ficticia", issue_type="Subtarea", status="Por hacer"
    )
    proposal = GuidedStart(container).propose("revisa demo-77 por favor", "DEMO")

    assert [o.kind for o in proposal.options] == ["new_need"]
    assert proposal.options[0].origin["project"] == "DEMO"


def _add(container: Container, key: str, issue_type: str = "Story") -> None:
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    tracker.issues[key] = IssueDetail(
        key=key, summary=f"Incidencia ficticia {key}", issue_type=issue_type, status="Por hacer"
    )


def test_keys_from_several_projects_only_offer_the_winning_project(tmp_path: Path) -> None:
    """Seguridad T-53: con claves de varios proyectos no se arranca en otro sin aviso."""
    container = fake_container(tmp_path)
    _add(container, "OTRO-7")
    proposal = GuidedStart(container).propose("DEMO-3 y OTRO-7", "DEMO")

    assert proposal.project == "DEMO" and proposal.project_changed is False
    assert {o.origin["project"] for o in proposal.options} == {"DEMO"}
    assert proposal.ignored_projects == ["OTRO"]


def test_project_follows_first_key_with_an_option(tmp_path: Path) -> None:
    """Una subtarea de otro proyecto no cambia el de la conversación; manda la que da opción."""
    container = fake_container(tmp_path)
    _add(container, "OTRO-8", "Subtarea")
    proposal = GuidedStart(container).propose("OTRO-8 y DEMO-3", "DEMO")

    assert proposal.project == "DEMO" and proposal.project_changed is False
    assert [o.label for o in proposal.options] == ["Evolucionar DEMO-3"]


def test_rate_limited_key_is_skipped_but_auth_error_propagates(tmp_path: Path) -> None:
    from adapters.errors import AuthenticationError, RateLimitError

    container = fake_container(tmp_path)
    tracker = container.issue_tracker
    original = tracker.get_issue

    def flaky(key: str) -> IssueDetail:
        if key == "DEMO-2":
            raise RateLimitError("Jira ha alcanzado su límite.", service="jira")
        return original(key)

    tracker.get_issue = flaky  # type: ignore[method-assign]
    proposal = GuidedStart(container).propose("DEMO-2 y DEMO-3", "DEMO")
    assert [i.key for i in proposal.recognized] == ["DEMO-3"]

    def denied(key: str) -> IssueDetail:
        raise AuthenticationError("Jira ha rechazado las credenciales.", service="jira")

    tracker.get_issue = denied  # type: ignore[method-assign]
    with pytest.raises(AuthenticationError):
        GuidedStart(container).propose("DEMO-3", "DEMO")


def test_preview_sources_rejects_key_of_other_project(tmp_path: Path) -> None:
    container = fake_container(tmp_path)
    with pytest.raises(ValueError, match="no pertenece"):
        GuidedStart(container).preview_sources(
            {"kind": "story", "key": "DEMO-3", "project": "OTRO"}
        )
