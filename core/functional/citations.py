"""Validación de citas: solo se admiten fuentes recibidas en el contexto (RF-21, RNF-14)."""

from adapters.errors import AgentError
from core.functional.context import CitableSource, escape_data
from schemas.common import SourceRef
from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

# Artefactos con citas: HU (T-20), suites de QA (T-26) e informes de calidad (T-48).
type CitedArtifact = UserStory | TestSuite | QualityReport


class CitationError(AgentError):
    """La propuesta cita fuentes que no estaban en el contexto; mensaje en español para la UI."""


def citation_errors(story: CitedArtifact, sources: list[CitableSource]) -> list[str]:
    """Problemas de las citas de `story`; lista vacía si son válidas."""
    index = _index(sources)
    # Las referencias las inventa el LLM: se escapan y recortan antes de reenviarlas.
    errors = [
        f"«{_shown(ref)}» no está entre las fuentes recibidas"
        for ref in story.sources
        if (ref.kind, ref.ref) not in index
    ]
    if sources and not story.sources:
        errors.append("la propuesta no cita ninguna fuente y el contexto sí traía fuentes")
    return errors


def without_forced_citations[T: (UserStory, TestSuite)](
    artifact: T, sources: list[CitableSource]
) -> T:
    """Sin fuentes en el contexto, las citas de la respuesta solo pueden ser inventadas: se quitan.

    El esquema que se envía al LLM pide al menos una cita (`adapters/llm/schema_hints.py`, para que
    los modelos pequeños no las omitan); si el contexto no trae ninguna fuente (una necesidad sin
    resultados del RAG, o con todas las fuentes excluidas), esa cita sería falsa (RNF-14).
    """
    if sources or not artifact.sources:
        return artifact
    return artifact.model_copy(update={"sources": []})


def with_real_excerpts[T: (UserStory, TestSuite, QualityReport)](
    story: T, sources: list[CitableSource]
) -> T:
    """Sustituye cada cita por la referencia canónica y su extracto real, sin duplicados."""
    index = _index(sources)
    refs: list[SourceRef] = []
    seen: set[tuple[str, str]] = set()
    for cited in story.sources:
        source = index.get((cited.kind, cited.ref))
        if source is None:
            raise CitationError(f"La cita «{_shown(cited)}» no está entre las fuentes recibidas.")
        if (source.kind, source.ref) in seen:
            continue
        seen.add((source.kind, source.ref))
        refs.append(SourceRef(kind=source.kind, ref=source.ref, excerpt=source.excerpt))
    return story.model_copy(update={"sources": refs})


MAX_SHOWN_REF = 80


def _shown(ref: SourceRef) -> str:
    return escape_data(f"{ref.kind}:{ref.ref}"[:MAX_SHOWN_REF])


def allowed_refs_text(sources: list[CitableSource]) -> str:
    return "\n".join(f"- {s.kind}: {escape_data(s.ref)}" for s in sources) or "- (ninguna)"


def _index(sources: list[CitableSource]) -> dict[tuple[str, str], CitableSource]:
    index: dict[tuple[str, str], CitableSource] = {}
    for source in sources:
        for ref in (source.ref, *source.aliases):
            index.setdefault((source.kind, ref), source)
    return index
