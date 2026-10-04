"""PA-283: `repair_citations` corrige citas `jira` cuya ref SÍ está en el contexto cuando el
extracto no sale de la fuente citada y sí de **una sola** de las demás fuentes de Jira.

Solo fakes y datos 100 % sintéticos (proyectos ficticios AFQP y DEMO de Villaficticia).
"""

import pytest
from structlog.testing import capture_logs

from adapters.base import IssueDetail
from core.functional.citations import (
    CitationRepair,
    citation_errors,
    repair_citations,
    with_real_excerpts,
)
from core.functional.context import CitableSource, StoryContext
from core.functional.writer import StoryWriter
from schemas.common import SourceRef
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.citations import AFQP_ISSUES, HU_TEXTS, PARENTS
from tests.fakes.llm import FakeLLMProvider

OTHER = "extracto_de_otra_fuente"
MISSING = "ref_inexistente"
DEMO_3_TEXT = dataset.STORIES["DEMO-3"].description_text
SHARED = "la persona socia consulta el catálogo de Villaficticia desde la web"


def afqp_sources() -> list[CitableSource]:
    return StoryContext(origin_kind="need", jira=AFQP_ISSUES).sources()


def demo_sources_with_epic() -> list[CitableSource]:
    """Contexto de la épica DEMO-1 con sus HU (la épica SÍ está en el contexto)."""
    return StoryContext(
        origin_kind="epic",
        origin_key=dataset.EPIC_KEY,
        jira=[dataset.EPIC, *dataset.STORIES.values()],
    ).sources()


def story_with(*cites: SourceRef) -> UserStory:
    return dataset.renewal_story(jira_key=None).model_copy(update={"sources": list(cites)})


def jira_cite(ref: str, excerpt: str | None) -> SourceRef:
    return SourceRef(kind="jira", ref=ref, excerpt=excerpt)


def _issue(key: str, description: str) -> IssueDetail:
    return IssueDetail(
        key=key,
        summary=f"HU ficticia {key}",
        issue_type="Historia",
        status="Tareas por hacer",
        parent_key="DEMO-20",
        description_text=description,
    )


# --- Correcciones --------------------------------------------------------------------------


def test_repair_valid_ref_with_excerpt_of_another_hu_points_to_that_hu() -> None:
    """Criterio 1 (PA-283): AFQP-2 está en el contexto pero el texto es de AFQP-12 → AFQP-12."""
    sources = afqp_sources()
    story = story_with(jira_cite("AFQP-2", HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, sources)

    assert [(s.kind, s.ref) for s in repaired.sources] == [("jira", "AFQP-12")]
    assert repairs == [CitationRepair("jira", "AFQP-2", "AFQP-12", OTHER)]
    assert citation_errors(repaired, sources) == []


def test_repair_epic_in_context_with_hu_text_points_to_the_hu() -> None:
    """Criterio 1 (PA-283): cita a la épica DEMO-1 (en el contexto) con el texto de DEMO-3."""
    story = story_with(jira_cite(dataset.EPIC_KEY, DEMO_3_TEXT))

    repaired, repairs = repair_citations(story, demo_sources_with_epic())

    assert [s.ref for s in repaired.sources] == ["DEMO-3"]
    assert [(r.original, r.ref, r.reason) for r in repairs] == [(dataset.EPIC_KEY, "DEMO-3", OTHER)]


def test_repair_other_source_uses_longest_non_metadata_line() -> None:
    """Criterio 1 (PA-283): extracto con líneas de metadatos + texto de AFQP-12 citado como
    AFQP-25 → la línea más larga identifica AFQP-12."""
    excerpt = (
        f"Historia · Tareas por hacer\nÉpica/padre: {PARENTS['AFQP-12']}\n"
        f"## Historia de usuario\n{HU_TEXTS['AFQP-12']}"
    )

    repaired, repairs = repair_citations(story_with(jira_cite("AFQP-25", excerpt)), afqp_sources())

    assert [s.ref for s in repaired.sources] == ["AFQP-12"]
    assert [r.reason for r in repairs] == [OTHER]


def test_missing_ref_repair_keeps_reason_ref_inexistente() -> None:
    """Criterio 1 (PA-281 sin cambios): la ref que no está en el contexto lleva «ref_inexistente»
    (también el valor por defecto de `CitationRepair`)."""
    _, repairs = repair_citations(
        story_with(jira_cite("AFQP-10", HU_TEXTS["AFQP-12"])), afqp_sources()
    )

    assert [(r.original, r.ref, r.reason) for r in repairs] == [("AFQP-10", "AFQP-12", MISSING)]
    assert CitationRepair("jira", "AFQP-10", "AFQP-12").reason == MISSING


def test_repair_with_real_excerpts_puts_the_real_excerpt_of_the_hu() -> None:
    """Criterio 1: tras corregir, `with_real_excerpts` pone el extracto real de la HU."""
    sources = afqp_sources()
    repaired, _ = repair_citations(story_with(jira_cite("AFQP-2", HU_TEXTS["AFQP-12"])), sources)

    final = with_real_excerpts(repaired, sources)

    [real] = [s for s in sources if s.ref == "AFQP-12"]
    assert final.sources == [SourceRef(kind="jira", ref="AFQP-12", excerpt=real.excerpt)]


# --- Lo que no se toca ---------------------------------------------------------------------


def test_repair_leaves_citation_whose_excerpt_is_in_the_cited_source() -> None:
    """Criterio 1 (negativa): el extracto está en la fuente citada → no se toca."""
    story = story_with(jira_cite("AFQP-12", HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, afqp_sources())

    assert repaired is story
    assert repairs == []


def test_repair_leaves_citation_when_excerpt_is_in_cited_and_in_another_source() -> None:
    """Criterio 1 (negativa): el extracto está en la citada y en otra → no se toca."""
    sources = StoryContext(
        origin_kind="need",
        jira=[_issue("DEMO-21", f"Texto: {SHARED}."), _issue("DEMO-22", f"Otro: {SHARED}.")],
    ).sources()
    story = story_with(jira_cite("DEMO-21", SHARED))

    repaired, repairs = repair_citations(story, sources)

    assert repaired is story
    assert repairs == []


def test_repair_leaves_citation_when_excerpt_is_in_two_other_sources() -> None:
    """Criterio 1 (ambigua): el extracto no está en la citada y sí en otras dos → no se toca."""
    sources = StoryContext(
        origin_kind="need",
        jira=[
            _issue("DEMO-21", f"Texto compartido: {SHARED}."),
            _issue("DEMO-22", f"Texto compartido: {SHARED}."),
            _issue("DEMO-23", "Descripción propia y distinta de la HU ficticia DEMO-23."),
        ],
    ).sources()
    story = story_with(jira_cite("DEMO-23", SHARED))

    repaired, repairs = repair_citations(story, sources)

    assert repaired is story
    assert repairs == []
    assert citation_errors(repaired, sources) == []  # la cita sigue siendo válida


@pytest.mark.parametrize(
    "excerpt",
    [
        None,
        "",
        "   ",
        "Como persona socia, quiero ver",
        HU_TEXTS["AFQP-12"][1:40],
        f"Historia · Tareas por hacer\nPertenece a la épica o padre {PARENTS['AFQP-12']} ficticio",
    ],
    ids=["sin-extracto", "vacio", "espacios", "corto", "39-caracteres", "solo-metadatos"],
)
def test_repair_leaves_valid_ref_with_short_empty_or_metadata_excerpt(excerpt: str | None) -> None:
    """Criterio 1 (límite): extracto corto, vacío o solo de metadatos → no se toca."""
    story = story_with(jira_cite("AFQP-2", excerpt))

    repaired, repairs = repair_citations(story, afqp_sources())

    assert repaired is story
    assert repairs == []


def test_repair_leaves_valid_ref_whose_excerpt_is_nowhere_without_error() -> None:
    """Criterio 1 (negativa): el extracto no aparece en ninguna fuente → no se toca, sin error,
    y la cita sigue siendo válida (la ref existe)."""
    excerpt = (
        "Texto inventado por el modelo que no aparece en ninguna fuente ficticia del contexto."
    )
    story = story_with(jira_cite("AFQP-2", excerpt))
    sources = afqp_sources()

    repaired, repairs = repair_citations(story, sources)

    assert repaired is story
    assert repairs == []
    assert citation_errors(repaired, sources) == []


@pytest.mark.parametrize("kind", ["rag", "memory"])
def test_repair_never_touches_rag_or_memory_citations_with_jira_text(kind: str) -> None:
    """Criterio 1: las citas `rag`/`memory` no se tocan aunque su extracto sea de una HU."""
    story = story_with(SourceRef(kind=kind, ref="DOC-FICTICIO-01", excerpt=HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, afqp_sources())

    assert repaired is story
    assert repairs == []


# --- Log -----------------------------------------------------------------------------------


def test_repair_log_counts_both_reasons_without_refs_or_text() -> None:
    """Criterio 1: el log lleva contadores (`missing_ref`, `other_source`) y nada de contenido."""
    story = story_with(
        jira_cite("AFQP-10", HU_TEXTS["AFQP-12"]),  # ref inexistente
        jira_cite("AFQP-2", HU_TEXTS["AFQP-25"]),  # ref válida, texto de otra HU
        jira_cite("AFQP-12", HU_TEXTS["AFQP-12"]),  # correcta
    )

    with capture_logs() as logs:
        repair_citations(story, afqp_sources())

    [event] = [e for e in logs if e["event"] == "citas reparadas"]
    assert event["action"] == "repair_citations"
    assert (event["repaired"], event["missing_ref"], event["other_source"]) == (2, 1, 1)
    assert event["kind"] == "jira"
    dump = repr(event)
    assert "AFQP" not in dump
    assert all(text not in dump for text in HU_TEXTS.values())


def test_repair_log_only_other_source() -> None:
    """Criterio 1 (límite): solo correcciones PA-283 → `missing_ref=0`, `other_source=1`."""
    with capture_logs() as logs:
        repair_citations(story_with(jira_cite("AFQP-2", HU_TEXTS["AFQP-12"])), afqp_sources())

    [event] = logs
    assert (event["missing_ref"], event["other_source"]) == (0, 1)


# --- En el writer de HU --------------------------------------------------------------------


def test_story_writer_corrects_valid_but_wrong_citation_without_extra_llm_call() -> None:
    """Criterio 1: en el writer, una cita válida pero equivocada se corrige sin otra llamada al
    LLM y el extracto final es el real de la HU."""
    wrong = story_with(jira_cite("AFQP-2", HU_TEXTS["AFQP-12"]))
    llm = FakeLLMProvider(builders={UserStory: lambda _messages: wrong})
    ctx = StoryContext(
        origin_kind="need",
        need="Consultar ejemplares desde la web (necesidad ficticia).",
        jira=AFQP_ISSUES,
    )

    draft = StoryWriter(llm).generate(ctx)

    assert len(llm.calls) == 1
    [real] = [s for s in ctx.sources() if s.ref == "AFQP-12"]
    assert draft.story.sources == [SourceRef(kind="jira", ref="AFQP-12", excerpt=real.excerpt)]
