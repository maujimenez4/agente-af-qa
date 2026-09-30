"""Pruebas de la validación de citas contra las fuentes del contexto (T-20: RF-21, RNF-14).

Datos 100 % sintéticos del dominio ficticio de Villaficticia (DEMO-N, DOC-NN).
"""

import pytest

from adapters.errors import AgentError
from core.functional.citations import (
    CitationError,
    allowed_refs_text,
    citation_errors,
    with_real_excerpts,
)
from core.functional.context import CitableSource
from schemas.common import SourceRef
from schemas.user_story import UserStory
from tests.fakes import dataset

JIRA = CitableSource(
    kind="jira",
    ref="DEMO-2",
    title="[HU-01] Reservar un libro disponible",
    excerpt="Extracto real de DEMO-2",
    content="Story · Hecho",
)
DOC = CitableSource(
    kind="rag",
    ref="DOC-01",
    title="Reglamento de préstamo",
    excerpt="Extracto real de DOC-01",
    content="Artículo 5 ficticio.",
    aliases=("uuid-ficticio-01",),
)
SOURCES = [JIRA, DOC]


def story_citing(*refs: tuple[str, str, str | None]) -> UserStory:
    """HU sintética que cita las referencias (kind, ref, excerpt) indicadas."""
    return dataset.renewal_story().model_copy(
        update={"sources": [SourceRef(kind=k, ref=r, excerpt=e) for k, r, e in refs]}
    )


# --- citation_errors ----------------------------------------------------------------------


def test_citation_errors_is_empty_when_all_refs_were_received() -> None:
    """RF-21: citas a fuentes del contexto son válidas."""
    story = story_citing(("jira", "DEMO-2", None), ("rag", "DOC-01", None))

    assert citation_errors(story, SOURCES) == []


def test_citation_errors_reports_ref_not_received() -> None:
    """RNF-14: una referencia inventada se rechaza con mensaje en español."""
    story = story_citing(("rag", "DOC-01", None), ("rag", "DOC-99", None))

    errors = citation_errors(story, SOURCES)

    assert errors == ["«rag:DOC-99» no está entre las fuentes recibidas"]


def test_citation_errors_reports_each_invented_ref() -> None:
    """RNF-14: se informa de todas las referencias inventadas, no solo de la primera."""
    story = story_citing(("rag", "DOC-98", None), ("jira", "DEMO-404", None))

    errors = citation_errors(story, SOURCES)

    assert len(errors) == 2
    assert "DOC-98" in errors[0] and "DEMO-404" in errors[1]


@pytest.mark.parametrize(
    "kind, ref",
    [("rag", "DEMO-2"), ("jira", "DOC-01"), ("memory", "DOC-01")],
)
def test_citation_errors_reports_wrong_kind_for_known_ref(kind: str, ref: str) -> None:
    """RNF-14: el tipo debe coincidir (jira vs rag con la misma ref es un error)."""
    story = story_citing((kind, ref, None))

    errors = citation_errors(story, SOURCES)

    assert errors == [f"«{kind}:{ref}» no está entre las fuentes recibidas"]


def test_citation_errors_accepts_alias_of_received_source() -> None:
    """RF-21: el UUID del documento (alias) es una cita válida de DOC-01."""
    story = story_citing(("rag", "uuid-ficticio-01", None))

    assert citation_errors(story, SOURCES) == []


def test_citation_errors_reports_missing_citations_when_sources_exist() -> None:
    """RNF-14: si el contexto traía fuentes, la HU debe citar al menos una."""
    story = story_citing()

    errors = citation_errors(story, SOURCES)

    assert errors == ["la propuesta no cita ninguna fuente y el contexto sí traía fuentes"]


def test_citation_errors_is_empty_without_sources_and_without_citations() -> None:
    """RNF-14 (límite): sin fuentes y sin citas la HU es válida."""
    assert citation_errors(story_citing(), []) == []


def test_citation_errors_rejects_any_citation_without_sources() -> None:
    """RNF-14 (límite): sin fuentes, cualquier cita es inventada."""
    errors = citation_errors(story_citing(("rag", "DOC-01", None)), [])

    assert errors == ["«rag:DOC-01» no está entre las fuentes recibidas"]


def test_citation_errors_is_case_sensitive() -> None:
    """RNF-14 (límite): la ref debe copiarse literalmente."""
    errors = citation_errors(story_citing(("rag", "doc-01", None)), SOURCES)

    assert len(errors) == 1


# --- with_real_excerpts -------------------------------------------------------------------


def test_with_real_excerpts_replaces_invented_excerpt() -> None:
    """RF-21: el extracto inventado por el LLM se sustituye por el real."""
    story = story_citing(("rag", "DOC-01", "Texto inventado por el modelo"))

    result = with_real_excerpts(story, SOURCES)

    assert result.sources == [SourceRef(kind="rag", ref="DOC-01", excerpt=DOC.excerpt)]


def test_with_real_excerpts_fills_empty_excerpt() -> None:
    """RF-21: un extracto vacío se rellena con el real."""
    result = with_real_excerpts(story_citing(("jira", "DEMO-2", None)), SOURCES)

    assert result.sources[0].excerpt == JIRA.excerpt


def test_with_real_excerpts_normalizes_alias_to_canonical_ref() -> None:
    """RF-21: una cita por alias se guarda con la ref canónica DOC-NN."""
    result = with_real_excerpts(story_citing(("rag", "uuid-ficticio-01", "x")), SOURCES)

    assert result.sources == [SourceRef(kind="rag", ref="DOC-01", excerpt=DOC.excerpt)]


def test_with_real_excerpts_deduplicates_repeated_and_alias_citations() -> None:
    """RF-21: citas repetidas (o por alias) de la misma fuente quedan una sola vez, en orden."""
    story = story_citing(
        ("rag", "DOC-01", "a"),
        ("jira", "DEMO-2", "b"),
        ("rag", "uuid-ficticio-01", "c"),
        ("rag", "DOC-01", "d"),
    )

    result = with_real_excerpts(story, SOURCES)

    assert [(s.kind, s.ref) for s in result.sources] == [("rag", "DOC-01"), ("jira", "DEMO-2")]


def test_with_real_excerpts_does_not_mutate_original_story() -> None:
    """RF-21: se devuelve una copia; la HU original conserva sus citas."""
    story = story_citing(("rag", "DOC-01", "inventado"))

    with_real_excerpts(story, SOURCES)

    assert story.sources[0].excerpt == "inventado"


def test_with_real_excerpts_keeps_other_fields() -> None:
    """RF-15: solo cambian las citas; CA, RN y título se mantienen."""
    story = story_citing(("rag", "DOC-01", None))

    result = with_real_excerpts(story, SOURCES)

    assert result.model_dump(exclude={"sources"}) == story.model_dump(exclude={"sources"})


# --- allowed_refs_text y CitationError -----------------------------------------------------


def test_allowed_refs_text_lists_kind_and_ref_of_each_source() -> None:
    """RNF-14: la lista de refs permitidas que recibe el reintento."""
    assert allowed_refs_text(SOURCES) == "- jira: DEMO-2\n- rag: DOC-01"


def test_allowed_refs_text_says_none_when_no_sources() -> None:
    """RNF-14 (límite): sin fuentes se indica «(ninguna)»."""
    assert allowed_refs_text([]) == "- (ninguna)"


def test_citation_error_is_agent_error() -> None:
    """RNF-14: CitationError se muestra en la UI como cualquier AgentError."""
    assert issubclass(CitationError, AgentError)


def test_with_real_excerpts_raises_citation_error_for_unknown_ref() -> None:
    """Una cita fuera del contexto se rechaza con CitationError, no con KeyError."""
    from tests.fakes import dataset

    story = dataset.renewal_story().model_copy(
        update={"sources": [SourceRef(kind="rag", ref="DOC-99")]}
    )

    with pytest.raises(CitationError, match="DOC-99"):
        with_real_excerpts(story, [])
