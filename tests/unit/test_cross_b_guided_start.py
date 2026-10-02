"""Prueba cruzada T-34 (RNF-19): el área A prueba `core/guided_start.py` (T-53 · RF-14, RF-19;
SPEC-00 §11, fila «Arranque guiado sin IA»).

Completa `tests/unit/test_guided_start.py` sin repetir sus casos: límite de claves frente a su
existencia, `excluded` de la vista previa frente al grafo, errores de Jira en las HU parecidas,
tipos Bug/Error y «Épica» en NFD, proyectos ignorados en QA, claves en URL, textos largos,
proyecto en minúsculas y memoria/documento con la misma referencia.
Los defectos confirmados van con `xfail(strict=True)`. Datos 100 % sintéticos; sin LLM ni red.
"""

import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pytest

from adapters.base import Chunk, IssueDetail, IssueSummary
from adapters.errors import AuthenticationError, ExternalServiceError, RateLimitError
from core.container import Container
from core.context.service import build_context_service
from core.graph import Origin, initial_state
from core.graph.nodes import validate_origin
from core.guided_start import MAX_KEYS, GuidedStart, find_issue_keys
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.vector_store import FakeVectorStore
from tests.unit.test_guided_start import (
    AF_USER,
    NEED_TEXT,
    SpyIssueTracker,
    _graph_sources,
    _issue,
    _summary,
    _tracker_with_extras,
)

STORY: Origin = {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
NFD_EPIC = unicodedata.normalize("NFD", "Épica")
FAKE_TERMS = "COVID-19, SARS-2, ABC-1, XYZ-2 y FOO-3"  # forma de clave, inexistentes


# --- utilidades --------------------------------------------------------------------------


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path, issue_tracker=_tracker_with_extras())


def _add(container: Container, key: str, issue_type: str, summary: str | None = None) -> None:
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    tracker.issues[key] = _issue(key, issue_type, summary or f"Incidencia ficticia {key}")


def _refs(container: Container, origin: Origin, excluded: list[str] | None = None) -> list[str]:
    return [r.ref for r in GuidedStart(container).preview_sources(origin, excluded)]


@dataclass
class FailingSearchTracker(SpyIssueTracker):
    """Jira que falla en la búsqueda de texto (HU parecidas) con el error indicado."""

    failure: Exception | None = None

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        self.jqls.append(jql)
        if self.failure is not None:
            raise self.failure
        return super().search(jql, limit)


def _llm_calls(container: Container) -> list:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm.calls


# --- GUIDED-1 · Límite de 5 claves antes de comprobar si existen ---------------------------------


def test_limit_counts_nonexistent_candidates_and_hides_real_key(container: Container) -> None:
    """RF-14 (T-53) · comportamiento fijado: el límite de MAX_KEYS se aplica a las candidatas
    del texto antes de mirar si existen; cinco términos con forma de clave delante hacen que
    DEMO-3 no se reconozca y se pase a HU parecidas (sin «Evolucionar DEMO-3»)."""
    text = f"Según {FAKE_TERMS}, quiero evolucionar DEMO-3."
    assert len(find_issue_keys(text)) == MAX_KEYS
    assert "DEMO-3" not in find_issue_keys(text)

    proposal = GuidedStart(container).propose(text, "DEMO")

    assert proposal.recognized == []
    assert "Evolucionar DEMO-3" not in [o.label for o in proposal.options]
    assert proposal.options[-1].kind == "new_need"


def test_four_nonexistent_candidates_keep_real_key(container: Container) -> None:
    """RF-14 (T-53, límite): con cuatro términos delante, DEMO-3 (la quinta) sí se reconoce."""
    text = "COVID-19, SARS-2, ABC-1 y XYZ-2; quiero evolucionar DEMO-3."

    proposal = GuidedStart(container).propose(text, "DEMO")

    assert [i.key for i in proposal.recognized] == ["DEMO-3"]
    assert [o.label for o in proposal.options] == ["Evolucionar DEMO-3"]


# --- GUIDED-2 · `excluded` de la vista previa frente al grafo ------------------------------------


def test_preview_excluded_with_spaces_matches_graph(container: Container) -> None:
    """RF-21 (T-51, T-53): la vista previa da las mismas fuentes que `retrieve_context` con la
    misma exclusión, también si la referencia llega con espacios."""
    assert "DEMO-4" in _refs(container, STORY)
    graph = _graph_sources(container, "functional", STORY, [" DEMO-4 "])
    assert "DEMO-4" not in graph

    assert "DEMO-4" not in _refs(container, STORY, [" DEMO-4 "])


def test_preview_rejects_excluding_origin_like_graph(container: Container) -> None:
    """RF-21 (T-51) · PA-223: excluir el origen da ValueError en la vista previa, igual que en
    `initial_state` (antes se ignoraba en silencio)."""
    with pytest.raises(ValueError, match="no se puede excluir"):
        GuidedStart(container).preview_sources(STORY, ["DEMO-3"])
    with pytest.raises(ValueError, match="no se puede excluir"):
        initial_state(AF_USER, "functional", STORY, excluded_sources=["DEMO-3"])


@pytest.mark.parametrize(
    "excluded",
    [[f"DOC-FICT-{n:03d}" for n in range(51)], ["texto libre con espacios"], ["x" * 101]],
    ids=["51", "texto_libre", "demasiado_larga"],
)
def test_preview_rejects_excluded_that_graph_rejects(
    container: Container, excluded: list[str]
) -> None:
    """RF-21 (T-51) · PA-223: la vista previa valida `excluded` como el grafo (límite de 50,
    texto libre, longitud), antes de leer Jira."""
    with pytest.raises(ValueError):
        GuidedStart(container).preview_sources(STORY, excluded)
    with pytest.raises(ValueError):
        initial_state(AF_USER, "functional", STORY, excluded_sources=excluded)


# --- GUIDED-3 · Errores de Jira en las HU parecidas ----------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        RateLimitError("Jira ficticio ha alcanzado su límite.", service="jira", retry_after=1),
        ExternalServiceError("Error ficticio 503 de Jira.", service="jira"),
    ],
    ids=["429", "5xx"],
)
def test_similar_search_error_aborts_whole_proposal(tmp_path: Path, failure: Exception) -> None:
    """RF-14 (T-53) · comportamiento fijado: un 429/5xx en la búsqueda de HU parecidas corta
    la propuesta entera (ni siquiera queda «Crear HU nueva»), mientras que en el camino de
    claves el mismo error solo se salta la clave (SPEC-00 §11 solo lo promete para claves)."""
    tracker = FailingSearchTracker(failure=failure)
    container = fake_container(tmp_path, issue_tracker=tracker)

    with pytest.raises(type(failure)):
        GuidedStart(container).propose(NEED_TEXT, "DEMO")


def test_similar_search_auth_error_propagates(tmp_path: Path) -> None:
    """RF-14 (T-53, error): un 401/403 en la búsqueda de HU parecidas se propaga."""
    failure = AuthenticationError("Credenciales ficticias rechazadas.", service="jira")
    container = fake_container(tmp_path, issue_tracker=FailingSearchTracker(failure=failure))

    with pytest.raises(AuthenticationError):
        GuidedStart(container).propose(NEED_TEXT, "DEMO")


def test_key_path_tolerates_rate_limit_and_offers_new_need(tmp_path: Path) -> None:
    """RF-14 (T-53): en el camino de claves un 429 se salta; sin otra clave se pasa a HU
    parecidas y en modo funcional queda «Crear HU nueva»."""
    container = fake_container(tmp_path)
    tracker = container.issue_tracker

    def limited(key: str) -> IssueDetail:
        raise RateLimitError("Límite ficticio.", service="jira")

    tracker.get_issue = limited  # type: ignore[method-assign]
    proposal = GuidedStart(container).propose("Evolucionar DEMO-3", "DEMO")

    assert proposal.recognized == []
    assert [o.kind for o in proposal.options][-1] == "new_need"


# --- GUIDED-4 · Bug y Error ofrecen «Evolucionar» ------------------------------------------------


@pytest.mark.parametrize("issue_type", ["Bug", "Error", "Incidencia"])
@pytest.mark.parametrize(("mode", "kind"), [("functional", "evolve"), ("qa", "tests")])
def test_bug_like_types_are_offered_as_story(
    container: Container, issue_type: str, mode: str, kind: str
) -> None:
    """RF-19 (T-53) · comportamiento fijado: Bug, Error o Incidencia no están en NOT_STORIES
    (core/context/service.py:30) y se ofrecen como HU («Evolucionar» o «Preparar pruebas»)."""
    _add(container, "DEMO-30", issue_type)

    proposal = GuidedStart(container).propose("DEMO-30", "DEMO", mode)  # type: ignore[arg-type]

    assert [o.kind for o in proposal.options] == [kind]
    assert proposal.options[0].origin == {"kind": "story", "key": "DEMO-30", "project": "DEMO"}


def test_similar_stories_keep_bug_type(tmp_path: Path) -> None:
    """RF-14 (T-53) · comportamiento fijado: un Bug también sale como «HU parecida»."""
    bug = _summary(_issue("DEMO-31", "Bug", "Error ficticio al renovar un préstamo"))
    tracker = SpyIssueTracker(candidates=[bug])
    container = fake_container(tmp_path, issue_tracker=tracker)

    proposal = GuidedStart(container).propose("renovar préstamo", "DEMO")

    assert [i.key for i in proposal.similar] == ["DEMO-31"]


# --- GUIDED-5 · «Épica» en Unicode NFD -----------------------------------------------------------


def test_nfd_epic_type_offers_new_story_in_epic(container: Container) -> None:
    """RF-19 (T-53): «Épica» en forma NFD (E + acento combinante) se trata como épica."""
    assert NFD_EPIC != "Épica" and unicodedata.normalize("NFC", NFD_EPIC) == "Épica"
    _add(container, "DEMO-32", NFD_EPIC)

    proposal = GuidedStart(container).propose("DEMO-32", "DEMO")

    assert [o.kind for o in proposal.options] == ["new_story_in_epic"]


def test_nfd_epic_type_not_in_similar_stories(tmp_path: Path) -> None:
    """RF-14 (T-53): una épica con el tipo en NFD no se propone como «HU parecida»."""
    epic = _summary(_issue("DEMO-33", NFD_EPIC, "Épica ficticia de renovar un préstamo"))
    container = fake_container(tmp_path, issue_tracker=SpyIssueTracker(candidates=[epic]))

    proposal = GuidedStart(container).propose("renovar préstamo", "DEMO")

    assert proposal.similar == []


def test_nfc_epic_type_with_spaces_and_case_is_epic(container: Container) -> None:
    """RF-19 (T-53, límite): «  ÉPICA » (NFC, mayúsculas y espacios) sí es épica."""
    _add(container, "DEMO-34", "  ÉPICA ")

    proposal = GuidedStart(container).propose("demo-34", "DEMO")

    assert [o.kind for o in proposal.options] == ["new_story_in_epic"]


# --- GUIDED-6 · QA con épicas de otro proyecto ----------------------------------------------------


def test_qa_only_other_project_epic_not_in_ignored_projects(container: Container) -> None:
    """RF-14, RF-19 (T-53) · comportamiento fijado: en QA, una épica de otro proyecto no da
    opción y tampoco aparece en `ignored_projects` (se calcula solo con las opciones), aunque
    el campo dice «claves de otros proyectos sin opción». El proyecto no cambia."""
    _add(container, "OTRO-5", "Epic")

    proposal = GuidedStart(container).propose("OTRO-5", "DEMO", "qa")

    assert [i.key for i in proposal.recognized] == ["OTRO-5"]
    assert proposal.options == []
    assert proposal.ignored_projects == []
    assert (proposal.project, proposal.project_changed) == ("DEMO", False)


def test_qa_other_project_epic_and_story_changes_project(container: Container) -> None:
    """RF-14 (T-50, T-53): en QA, épica de OTRO + HU de OTRO → manda la HU y cambia el
    proyecto; no hay proyectos ignorados."""
    _add(container, "OTRO-5", "Epic")

    proposal = GuidedStart(container).propose("OTRO-5 y OTRO-7", "DEMO", "qa")

    assert [o.label for o in proposal.options] == ["Preparar pruebas de OTRO-7"]
    assert (proposal.project, proposal.project_changed) == ("OTRO", True)
    assert proposal.ignored_projects == []


# --- GUIDED-7 · Clave dentro de una URL o seguida de «-» ------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "https://jira.ejemplo.test/browse/DEMO-3",
        "https://jira.ejemplo.test/browse/DEMO-3?focus=1",
        "https://jira.ejemplo.test/browse/demo-3#comentario",
    ],
)
def test_key_inside_url_is_recognized(text: str) -> None:
    """RF-14 (T-53): una clave dentro de un enlace de Jira se reconoce."""
    assert find_issue_keys(text) == ["DEMO-3"]


@pytest.mark.parametrize("text", ["DEMO-3-bis", "DEMO-3-2", "ver DEMO-3- y nada más"])
def test_key_followed_by_hyphen_is_not_recognized(text: str) -> None:
    """RF-14 (T-53) · comportamiento fijado: una clave seguida de «-» no se reconoce."""
    assert find_issue_keys(text) == []


def test_key_with_hyphen_suffix_falls_back_to_similar(container: Container) -> None:
    """RF-14 (T-53) · comportamiento fijado: «DEMO-3-bis» no da «Evolucionar DEMO-3»."""
    proposal = GuidedStart(container).propose("Evolucionar DEMO-3-bis", "DEMO")

    assert proposal.recognized == []
    assert "Evolucionar DEMO-3" not in [o.label for o in proposal.options]


# --- GUIDED-8 · new_need con un texto muy largo ---------------------------------------------------


def test_new_need_long_text_is_kept_whole_and_valid(tmp_path: Path) -> None:
    """RF-14, RF-19 (T-53) · comportamiento fijado: el texto de la necesidad no se recorta
    (20 000 caracteres) y el origen pasa `validate_origin`; la búsqueda en Jira sí se acota."""
    text = ("Avisar del vencimiento ficticio del préstamo. " * 450).strip()
    assert len(text) > 20_000
    tracker = SpyIssueTracker()
    container = fake_container(tmp_path, issue_tracker=tracker)

    proposal = GuidedStart(container).propose(f"  {text}  ", "DEMO")

    need = proposal.options[-1]
    assert need.kind == "new_need"
    assert need.origin == {"kind": "need", "text": text, "project": "DEMO"}
    validate_origin(initial_state(AF_USER, "functional", need.origin))
    assert tracker.jqls and all(len(jql) < 2_000 for jql in tracker.jqls)
    assert _llm_calls(container) == []


# --- GUIDED-9 · Vista previa de una necesidad con proyecto en minúsculas -------------------------


def test_preview_need_lowercase_project_has_no_jira_rows(tmp_path: Path) -> None:
    """RF-21 (T-53) · comportamiento fijado: con origen need y proyecto «demo», la vista previa
    no falla ni busca en Jira (JQL no válida → sin HU), solo da filas del RAG; el grafo rechaza
    ese origen en `validate_origin`."""
    tracker = SpyIssueTracker(candidates=[_summary(_issue("DEMO-3", "Story", "Renovar"))])
    container = fake_container(tmp_path, issue_tracker=tracker)
    origin: Origin = {"kind": "need", "text": NEED_TEXT, "project": "demo"}

    rows = GuidedStart(container).preview_sources(origin)

    assert tracker.jqls == []
    assert rows and {r.kind for r in rows} <= {"rag", "memory"}
    upper = GuidedStart(container).preview_sources({**origin, "project": "DEMO"})
    assert "DEMO-3" in {r.ref for r in upper}
    with pytest.raises(ValueError, match="proyecto"):
        validate_origin(initial_state(AF_USER, "functional", origin))


# --- GUIDED-10 · Memoria y documento del RAG con la misma ref ------------------------------------


def test_memory_and_document_with_same_ref_collapse_to_one_row(container: Container) -> None:
    """RF-21 (T-53) · comportamiento fijado: si una memoria y un documento comparten `ref`, la
    vista previa los deduplica por `ref` sin mirar `kind`: queda una sola fila (la memoria,
    que llega primero) y el documento no aparece por separado."""
    store = container.vector_store
    assert isinstance(store, FakeVectorStore)
    content = "Memoria ficticia: renovar un préstamo con reservas pendientes."
    (vector,) = container.embeddings.embed([content])
    store.upsert(
        [
            Chunk(
                id="mem-colision-0",
                document_id="doc-reglamento",
                ordinal=0,
                section="Memoria ficticia con la misma ref",
                content=content,
                embedding=vector,
                metadata={"category": "memoria", "title": "Memoria ficticia con la misma ref"},
            )
        ]
    )
    issue = container.issue_tracker.get_issue("DEMO-3")
    gathered = build_context_service(container, "DEMO").gather(STORY, issue)
    kinds = {h.source.kind for h in gathered.rag if h.source.ref == "doc-reglamento"}
    assert kinds == {"memory", "rag"}

    rows = [r for r in GuidedStart(container).preview_sources(STORY) if r.ref == "doc-reglamento"]

    assert len(rows) == 1
    assert rows[0].kind == "memory"
