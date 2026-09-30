"""Validación de citas: solo se admiten fuentes recibidas en el contexto (RF-21, RNF-14)."""

from adapters.errors import AgentError
from core.functional.context import CitableSource, escape_data
from schemas.common import SourceRef
from schemas.user_story import UserStory


class CitationError(AgentError):
    """La propuesta cita fuentes que no estaban en el contexto; mensaje en español para la UI."""


def citation_errors(story: UserStory, sources: list[CitableSource]) -> list[str]:
    """Problemas de las citas de `story`; lista vacía si son válidas."""
    index = _index(sources)
    errors = [
        f"«{ref.kind}:{ref.ref}» no está entre las fuentes recibidas"
        for ref in story.sources
        if (ref.kind, ref.ref) not in index
    ]
    if sources and not story.sources:
        errors.append("la propuesta no cita ninguna fuente y el contexto sí traía fuentes")
    return errors


def with_real_excerpts(story: UserStory, sources: list[CitableSource]) -> UserStory:
    """Sustituye cada cita por la referencia canónica y su extracto real, sin duplicados."""
    index = _index(sources)
    refs: list[SourceRef] = []
    seen: set[tuple[str, str]] = set()
    for cited in story.sources:
        source = index.get((cited.kind, cited.ref))
        if source is None:
            raise CitationError(
                f"La cita «{cited.kind}:{cited.ref}» no está entre las fuentes recibidas."
            )
        if (source.kind, source.ref) in seen:
            continue
        seen.add((source.kind, source.ref))
        refs.append(SourceRef(kind=source.kind, ref=source.ref, excerpt=source.excerpt))
    return story.model_copy(update={"sources": refs})


def allowed_refs_text(sources: list[CitableSource]) -> str:
    return "\n".join(f"- {s.kind}: {escape_data(s.ref)}" for s in sources) or "- (ninguna)"


def _index(sources: list[CitableSource]) -> dict[tuple[str, str], CitableSource]:
    index: dict[tuple[str, str], CitableSource] = {}
    for source in sources:
        for ref in (source.ref, *source.aliases):
            index.setdefault((source.kind, ref), source)
    return index
