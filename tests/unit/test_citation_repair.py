"""Pruebas de `repair_citations`: citas de Jira corregidas sin reintento (PA-281, RF-21, RNF-14).

Reproduce el fallo del e2e local (docs/pruebas/E2E-local-2026-10-02.md §5.3): el modelo citaba
la épica o padre con el extracto de la HU. Datos 100 % sintéticos (AFQP/DEMO de Villaficticia).
"""

import pytest
from structlog.testing import capture_logs

from adapters.base import Chunk, IssueDetail, RetrievedChunk
from core.functional.citations import (
    MIN_REPAIR_EXCERPT,
    CitationRepair,
    citation_errors,
    repair_citations,
    with_real_excerpts,
)
from core.functional.context import CitableSource, StoryContext
from schemas.common import SourceRef
from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.citations import (
    AFQP_ISSUES,
    CAPTURED_PAIRS,
    HU_TEXTS,
    old_format_excerpt,
)
from tests.fakes.llm import renewal_quality_report, renewal_test_suite


def rag_hit(doc_id: str, content: str) -> RetrievedChunk:
    document_id = f"uuid-ficticio-{doc_id.lower()}"
    chunk = Chunk(
        id=f"{document_id}-0",
        document_id=document_id,
        ordinal=0,
        content=content,
        metadata={"doc_id": doc_id, "date": "2026-04-20", "category": "normativa"},
    )
    return RetrievedChunk(
        chunk=chunk, score=0.8, source=SourceRef(kind="rag", ref=document_id, excerpt=None)
    )


def afqp_sources(*extra_rag: RetrievedChunk) -> list[CitableSource]:
    return StoryContext(origin_kind="need", jira=AFQP_ISSUES, rag=list(extra_rag)).sources()


def story_with(*cites: SourceRef) -> UserStory:
    return dataset.renewal_story(jira_key=None).model_copy(update={"sources": list(cites)})


def jira_cite(ref: str, excerpt: str | None) -> SourceRef:
    return SourceRef(kind="jira", ref=ref, excerpt=excerpt)


# --- Caso medido y pares de la captura ---------------------------------------------------


def test_repair_citations_fixes_epic_citation_with_hu_excerpt() -> None:
    """Criterio 2: cita `jira:AFQP-10` (épica) con el texto de AFQP-12 → AFQP-12."""
    sources = afqp_sources()
    story = story_with(jira_cite("AFQP-10", HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, sources)

    assert [(s.kind, s.ref) for s in repaired.sources] == [("jira", "AFQP-12")]
    assert repairs == [CitationRepair(kind="jira", original="AFQP-10", ref="AFQP-12")]
    assert citation_errors(repaired, sources) == []


def test_repair_citations_keeps_the_cited_excerpt_and_other_fields() -> None:
    """Criterio 2: solo cambia la clave; `with_real_excerpts` pone luego el extracto real."""
    sources = afqp_sources()
    story = story_with(jira_cite("AFQP-10", HU_TEXTS["AFQP-12"]))

    repaired, _ = repair_citations(story, sources)
    final = with_real_excerpts(repaired, sources)

    assert repaired.sources[0].excerpt == HU_TEXTS["AFQP-12"]
    assert repaired.model_dump(exclude={"sources"}) == story.model_dump(exclude={"sources"})
    [real] = [s for s in sources if s.ref == "AFQP-12"]
    assert final.sources == [SourceRef(kind="jira", ref="AFQP-12", excerpt=real.excerpt)]


def test_repair_citations_does_not_mutate_the_original_artifact() -> None:
    """Criterio 2: la reparación devuelve una copia (los modelos son inmutables de hecho)."""
    story = story_with(jira_cite("AFQP-10", HU_TEXTS["AFQP-12"]))

    repair_citations(story, afqp_sources())

    assert story.sources[0].ref == "AFQP-10"


@pytest.mark.parametrize("cited, real, with_parent", CAPTURED_PAIRS)
def test_repair_citations_fixes_captured_pairs_by_longest_line(
    cited: str, real: str, with_parent: bool
) -> None:
    """Criterio 3: extractos del formato antiguo («Historia · …», «Épica/padre: X», texto) se
    reparan por su línea más larga."""
    excerpt = old_format_excerpt(real, with_parent=with_parent)

    repaired, repairs = repair_citations(story_with(jira_cite(cited, excerpt)), afqp_sources())

    assert [s.ref for s in repaired.sources] == [real]
    assert repairs == [CitationRepair("jira", cited, real)]


def test_repair_citations_fixes_all_three_captured_pairs_in_one_artifact() -> None:
    """Criterio 3: las tres citas de la captura juntas, más las RAG válidas, en una sola pasada."""
    cites = [
        jira_cite(cited, old_format_excerpt(real, with_parent=with_parent))
        for cited, real, with_parent in CAPTURED_PAIRS
    ]
    doc = rag_hit("DOC-02", "Reglamento de reservas ficticio de Villaficticia.")
    sources = afqp_sources(doc)
    story = story_with(*cites, SourceRef(kind="rag", ref="DOC-02", excerpt="Reglamento"))

    repaired, repairs = repair_citations(story, sources)

    assert [(s.kind, s.ref) for s in repaired.sources] == [
        ("jira", "AFQP-12"),
        ("jira", "AFQP-2"),
        ("jira", "AFQP-25"),
        ("rag", "DOC-02"),
    ]
    assert [r.original for r in repairs] == ["AFQP-10", "AFQP-1", "AFQP-17"]
    assert citation_errors(repaired, sources) == []


def test_old_format_whole_excerpt_does_not_match_new_source_text() -> None:
    """Criterio 3 (premisa): el extracto antiguo entero ya no está en la fuente; sin la línea más
    larga no se repararía."""
    [source] = [s for s in afqp_sources() if s.ref == "AFQP-12"]

    assert "Épica/padre" not in source.content
    assert old_format_excerpt("AFQP-12") not in source.content


# --- Ambigüedad, extractos insuficientes e invenciones ------------------------------------


def _shared_issue(key: str, parent: str) -> IssueDetail:
    return IssueDetail(
        key=key,
        summary=f"HU ficticia {key}",
        issue_type="Historia",
        status="Tareas por hacer",
        parent_key=parent,
        description_text=(
            "Texto compartido: la persona socia consulta el catálogo de Villaficticia desde la "
            f"web. Detalle propio de {key}."
        ),
    )


SHARED = "la persona socia consulta el catálogo de Villaficticia desde la web"


def test_repair_citations_skips_excerpt_found_in_two_jira_sources() -> None:
    """Criterio 4 (ambigua): el extracto aparece en dos fuentes de Jira → no se repara."""
    sources = StoryContext(
        origin_kind="need",
        jira=[_shared_issue("DEMO-21", "DEMO-20"), _shared_issue("DEMO-22", "DEMO-20")],
    ).sources()
    story = story_with(jira_cite("DEMO-20", SHARED))

    repaired, repairs = repair_citations(story, sources)

    assert repaired is story
    assert repairs == []
    assert citation_errors(repaired, sources)


def test_repair_citations_skips_when_longest_line_is_ambiguous() -> None:
    """Criterio 4 (ambigua): el extracto entero no está y su línea más larga está en dos."""
    sources = StoryContext(
        origin_kind="need",
        jira=[_shared_issue("DEMO-21", "DEMO-20"), _shared_issue("DEMO-22", "DEMO-20")],
    ).sources()
    excerpt = f"Historia · Tareas por hacer\nÉpica/padre: DEMO-20\n{SHARED}"

    repaired, repairs = repair_citations(story_with(jira_cite("DEMO-20", excerpt)), sources)

    assert repairs == []
    assert repaired.sources[0].ref == "DEMO-20"


@pytest.mark.parametrize(
    "excerpt",
    [None, "", "   ", "Como persona socia, quiero ver"],
    ids=["sin-extracto", "vacio", "espacios", "corto"],
)
def test_repair_citations_skips_missing_or_short_excerpt(excerpt: str | None) -> None:
    """Criterio 4 (límite): sin extracto, vacío o de menos de 40 caracteres → no se repara."""
    story = story_with(jira_cite("AFQP-10", excerpt))

    repaired, repairs = repair_citations(story, afqp_sources())

    assert repaired is story
    assert repairs == []


def test_repair_citations_accepts_excerpt_of_exactly_min_length() -> None:
    """Criterio 4 (límite): 40 caracteres normalizados bastan; 39, no."""
    text = HU_TEXTS["AFQP-2"]
    exact, short = text[:MIN_REPAIR_EXCERPT], text[1:MIN_REPAIR_EXCERPT]
    assert len(exact) == MIN_REPAIR_EXCERPT == len(short) + 1
    assert exact == exact.strip() and short == short.strip()

    _, repairs_exact = repair_citations(story_with(jira_cite("AFQP-1", exact)), afqp_sources())
    _, repairs_short = repair_citations(story_with(jira_cite("AFQP-1", short)), afqp_sources())

    assert [r.ref for r in repairs_exact] == ["AFQP-2"]
    assert repairs_short == []


def test_repair_citations_skips_invented_citation_without_match() -> None:
    """Criterio 4: una cita inventada cuyo extracto no está en ninguna fuente se queda igual."""
    excerpt = "Texto inventado por el modelo que no aparece en ninguna fuente del contexto."
    story = story_with(jira_cite("AFQP-99", excerpt))

    repaired, repairs = repair_citations(story, afqp_sources())

    assert repaired is story
    assert repairs == []


def test_repair_citations_skips_when_all_lines_are_short() -> None:
    """Criterio 4 (límite): el extracto entero no coincide y ninguna línea llega a 40."""
    excerpt = "Historia · Tareas por hacer\nÉpica/padre: AFQP-10\n## Historia de usuario"

    _, repairs = repair_citations(story_with(jira_cite("AFQP-10", excerpt)), afqp_sources())

    assert repairs == []


# --- Solo Jira ---------------------------------------------------------------------------

REGLAMENTO = "Artículo 4. Cada persona socia puede tener hasta 3 reservas activas a la vez."


def test_repair_citations_does_not_repair_rag_citations() -> None:
    """Criterio 5: una cita `rag` inexistente con el texto de un documento no se repara."""
    sources = afqp_sources(rag_hit("DOC-02", REGLAMENTO))
    story = story_with(SourceRef(kind="rag", ref="DOC-99", excerpt=REGLAMENTO))

    repaired, repairs = repair_citations(story, sources)

    assert repaired is story
    assert repairs == []


def test_repair_citations_does_not_repair_memory_citations() -> None:
    """Criterio 5: tampoco las de memoria, aunque el extracto sea de una HU de Jira."""
    story = story_with(SourceRef(kind="memory", ref="MEM-01", excerpt=HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, afqp_sources())

    assert repaired is story
    assert repairs == []


def test_repair_citations_corrects_valid_citation_whose_excerpt_is_another_hu() -> None:
    """PA-283: una cita `jira` válida con el texto de OTRA HU (y no el suyo) se corrige a esa."""
    story = story_with(jira_cite("AFQP-2", HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, afqp_sources())

    assert [r.ref for r in repaired.sources] == ["AFQP-12"]
    assert [(r.original, r.ref, r.reason) for r in repairs] == [
        ("AFQP-2", "AFQP-12", "extracto_de_otra_fuente")
    ]


def test_repair_citations_corrects_epic_citation_when_epic_is_in_context() -> None:
    """PA-283: la épica está en el contexto, pero el extracto es el de la HU: se corrige."""
    epic = IssueDetail(
        key="AFQP-10", summary="Catálogo (épica ficticia)", issue_type="Epic", status="En curso"
    )
    sources = StoryContext(origin_kind="epic", jira=[epic, *AFQP_ISSUES]).sources()
    story = story_with(jira_cite("AFQP-10", HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, sources)

    assert [r.ref for r in repaired.sources] == ["AFQP-12"]
    assert [r.reason for r in repairs] == ["extracto_de_otra_fuente"]


def test_repair_citations_ignores_rag_sources_when_matching_jira_citation() -> None:
    """Criterio 5: una cita `jira` cuyo extracto solo está en una fuente RAG no se repara."""
    sources = afqp_sources(rag_hit("DOC-02", REGLAMENTO))
    story = story_with(jira_cite("AFQP-10", REGLAMENTO))

    repaired, repairs = repair_citations(story, sources)

    assert repaired is story
    assert repairs == []
    assert citation_errors(repaired, sources)


def test_repair_citations_prefers_jira_when_text_is_also_in_a_document() -> None:
    """Criterio 5: si el texto está en una HU y en un documento RAG, solo cuenta la de Jira."""
    sources = afqp_sources(rag_hit("DOC-03", f"Copia ficticia: {HU_TEXTS['AFQP-12']}"))

    _, repairs = repair_citations(story_with(jira_cite("AFQP-10", HU_TEXTS["AFQP-12"])), sources)

    assert [r.ref for r in repairs] == ["AFQP-12"]


# --- Normalización -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "excerpt",
    [
        HU_TEXTS["AFQP-12"].upper(),
        HU_TEXTS["AFQP-12"].replace(" ", "   ").replace(", ", ",\n  "),
        HU_TEXTS["AFQP-12"].rstrip(".") + "…",
        HU_TEXTS["AFQP-12"].rstrip(".") + "...",
        HU_TEXTS["AFQP-12"] + " … …",
        "  " + HU_TEXTS["AFQP-12"] + "\n\n",
    ],
    ids=["mayusculas", "espacios-y-saltos", "elipsis", "tres-puntos", "elipsis-repetida", "bordes"],
)
def test_repair_citations_normalizes_excerpt_before_matching(excerpt: str) -> None:
    """Criterio 6: mayúsculas, espacios, saltos de línea y «…» finales no impiden reparar."""
    _, repairs = repair_citations(story_with(jira_cite("AFQP-10", excerpt)), afqp_sources())

    assert [r.ref for r in repairs] == ["AFQP-12"]


def test_repair_citations_unescapes_html_entities_in_excerpt() -> None:
    """Criterio 6: el modelo copia el texto escapado del contexto (&lt; &quot;) y se repara."""
    issue = IssueDetail(
        key="DEMO-31",
        summary="HU ficticia con símbolos",
        issue_type="Historia",
        status="Tareas por hacer",
        parent_key="DEMO-30",
        description_text=(
            'Si quedan <3 ejemplares se muestra el aviso "Últimos ejemplares" en la ficha.'
        ),
    )
    sources = StoryContext(origin_kind="need", jira=[issue]).sources()
    escaped = (
        "Si quedan &lt;3 ejemplares se muestra el aviso &quot;Últimos ejemplares&quot; en la ficha."
    )

    _, repairs = repair_citations(story_with(jira_cite("DEMO-30", escaped)), sources)

    assert [r.ref for r in repairs] == ["DEMO-31"]


@pytest.mark.parametrize("cited, real", [("AFQP-10", "AFQP-12"), ("AFQP-17", "AFQP-25")])
def test_repair_citations_matches_the_source_excerpt(cited: str, real: str) -> None:
    """Criterio 6: el extracto real de la fuente (resumen + descripción, recortado con «…» si es
    largo) también identifica la fuente aunque no esté entero en su contenido."""
    [source] = [s for s in afqp_sources() if s.ref == real]
    assert source.excerpt not in source.content

    _, repairs = repair_citations(story_with(jira_cite(cited, source.excerpt)), afqp_sources())

    assert [r.ref for r in repairs] == [real]


def test_afqp_12_source_excerpt_is_truncated_with_ellipsis() -> None:
    """Criterio 6 (premisa): el extracto de AFQP-12 supera 200 caracteres y acaba en «…»."""
    [source] = [s for s in afqp_sources() if s.ref == "AFQP-12"]

    assert source.excerpt.endswith("…")


def test_repair_citations_skips_partial_match_with_foreign_words() -> None:
    """Criterio 6 (negativa): un extracto con palabras que no están en la fuente no repara."""
    excerpt = HU_TEXTS["AFQP-12"].replace("en qué estado", "en qué estado y su ubicación exacta")

    repaired, repairs = repair_citations(story_with(jira_cite("AFQP-10", excerpt)), afqp_sources())

    assert repairs == []
    assert repaired.sources[0].ref == "AFQP-10"


# --- Duplicados --------------------------------------------------------------------------


def test_with_real_excerpts_keeps_one_citation_when_repair_creates_duplicate() -> None:
    """Criterio 7: la cita reparada coincide con otra ya presente → queda una sola."""
    sources = afqp_sources()
    story = story_with(jira_cite("AFQP-12", "inventado"), jira_cite("AFQP-10", HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, sources)
    final = with_real_excerpts(repaired, sources)

    assert len(repairs) == 1
    assert [s.ref for s in repaired.sources] == ["AFQP-12", "AFQP-12"]
    assert [s.ref for s in final.sources] == ["AFQP-12"]


# --- Sin reparaciones y log --------------------------------------------------------------


def test_repair_citations_returns_same_object_and_no_log_when_nothing_to_repair() -> None:
    """Criterio 9: sin reparaciones devuelve el mismo objeto, lista vacía y no registra log."""
    story = story_with(jira_cite("AFQP-12", "inventado"))

    with capture_logs() as logs:
        repaired, repairs = repair_citations(story, afqp_sources())

    assert repaired is story
    assert repairs == []
    assert logs == []


def test_repair_citations_without_sources_returns_same_object() -> None:
    """Criterio 9 (límite): sin fuentes no hay nada que reparar."""
    story = story_with(jira_cite("AFQP-10", HU_TEXTS["AFQP-12"]))

    repaired, repairs = repair_citations(story, [])

    assert repaired is story
    assert repairs == []


def test_repair_citations_logs_count_without_refs_or_content() -> None:
    """Criterio 2: el log «citas reparadas» lleva action/repaired/kind, sin refs ni extractos."""
    excerpts = [old_format_excerpt(real, with_parent=p) for _, real, p in CAPTURED_PAIRS]
    story = story_with(
        *(jira_cite(c, e) for (c, _, _), e in zip(CAPTURED_PAIRS, excerpts, strict=True))
    )

    with capture_logs() as logs:
        repair_citations(story, afqp_sources())

    [event] = logs
    assert event["event"] == "citas reparadas"
    assert event["action"] == "repair_citations"
    assert event["repaired"] == 3
    assert event["kind"] == "jira"
    dump = repr(event)
    assert "AFQP" not in dump
    assert all(text not in dump for text in HU_TEXTS.values())


# --- Otros artefactos con citas ----------------------------------------------------------


@pytest.mark.parametrize(
    "artifact",
    [renewal_test_suite("AFQP-12"), renewal_quality_report()],
    ids=["suite", "informe-calidad"],
)
def test_repair_citations_works_on_suites_and_quality_reports(
    artifact: TestSuite | QualityReport,
) -> None:
    """Criterio 8: la reparación es la misma para suites (T-26) e informes de calidad (T-48)."""
    cited = artifact.model_copy(update={"sources": [jira_cite("AFQP-10", HU_TEXTS["AFQP-12"])]})

    repaired, repairs = repair_citations(cited, afqp_sources())

    assert type(repaired) is type(artifact)
    assert [s.ref for s in repaired.sources] == ["AFQP-12"]
    assert len(repairs) == 1


def test_citation_repair_is_immutable() -> None:
    """Criterio 2: `CitationRepair` solo lleva referencias y no se puede modificar."""
    repair = CitationRepair("jira", "AFQP-10", "AFQP-12")

    with pytest.raises(AttributeError):
        repair.ref = "AFQP-99"  # type: ignore[misc]


# --- Endurecimiento tras security-reviewer (coste y metadatos) ----------------------------------


def _issue(key: str, description: str, parent: str | None = None) -> IssueDetail:
    return IssueDetail(
        key=key,
        summary=f"HU ficticia {key}",
        issue_type="Historia",
        status="Tareas por hacer",
        description_text=description,
        parent_key=parent,
    )


def _citing(ref: str, excerpt: str) -> UserStory:
    return dataset.renewal_story(jira_key=None).model_copy(
        update={"sources": [SourceRef(kind="jira", ref=ref, excerpt=excerpt)]}
    )


def test_repair_is_fast_with_adversarial_dots_in_sources_and_excerpt() -> None:
    """Muchos puntos seguidos (en Jira o en la respuesta del LLM) no bloquean el proceso."""
    import time

    dots = "." * 90_000
    text = "Como persona socia de Villaficticia quiero renovar un préstamo desde la web"
    sources = StoryContext(
        origin_kind="need", jira=[_issue("AFQP-12", f"{text}\n{dots}"), _issue("AFQP-2", dots)]
    ).sources()
    started = time.perf_counter()

    fixed, repairs = repair_citations(_citing("AFQP-10", f"{text}…"), sources)
    _same, none = repair_citations(_citing("AFQP-10", f"{text}{dots}…"), sources)

    assert time.perf_counter() - started < 2.0
    assert [r.ref for r in repairs] == ["AFQP-12"]
    assert fixed.sources[0].ref == "AFQP-12"
    assert none == []  # un extracto lleno de puntos no coincide limpio: no se repara


def test_metadata_line_alone_does_not_repair() -> None:
    """Una línea de metadatos («Pertenece a la épica o padre …») no identifica la HU."""
    parent = "AFQPLARGOFICTICIO-1000"
    sources = StoryContext(
        origin_kind="need", jira=[_issue("AFQPLARGOFICTICIO-12", "Texto breve.", parent)]
    ).sources()
    excerpt = f"Pertenece a la épica o padre {parent}\nOtro texto"

    assert len(f"pertenece a la épica o padre {parent}".casefold()) >= 40
    fixed, repairs = repair_citations(_citing(parent, excerpt), sources)
    _alone, repairs_alone = repair_citations(
        _citing(parent, f"Pertenece a la épica o padre {parent}"), sources
    )

    assert repairs == [] and repairs_alone == []
    assert fixed.sources[0].ref == parent
