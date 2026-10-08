"""Validación de citas: solo se admiten fuentes recibidas en el contexto (RF-21, RNF-14).

`repair_citations` (PA-281) corrige sin volver a llamar al LLM una cita de Jira con la clave
equivocada cuando su extracto identifica sin ambigüedad la fuente recibida (los modelos pequeños
citaban la épica que leían en el texto de la HU). Si no es inequívoco, la cita se queda como está
y la decide el reintento: nunca se inventa trazabilidad.
"""

import html
from dataclasses import dataclass

from adapters.errors import AgentError
from core.functional.context import CitableSource
from core.logging import get_logger
from core.text import escape_data
from schemas.common import SourceRef
from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

# Artefactos con citas: HU (T-20), suites de QA (T-26) e informes de calidad (T-48).
type CitedArtifact = UserStory | TestSuite | QualityReport


log = get_logger("core.functional.citations")

# Extracto mínimo (normalizado) para identificar una fuente: más corto podría ser genérico.
MIN_REPAIR_EXCERPT = 40
# El extracto lo devuelve el LLM sin límite: se compara como mucho este principio.
MAX_REPAIR_EXCERPT = 2000
# Líneas de metadatos de la fuente (y del formato anterior): no identifican una HU por su texto.
_METADATA_LINES = ("clave:", "pertenece a la épica o padre", "vínculo:", "épica/padre:")


class CitationError(AgentError):
    """La propuesta cita fuentes que no estaban en el contexto; mensaje en español para la UI."""


@dataclass(frozen=True)
class CitationRepair:
    """Una cita corregida: solo referencias (para la auditoría o el log), nunca contenido."""

    kind: str
    original: str
    ref: str
    reason: str = "ref_inexistente"  # o «extracto_de_otra_fuente» (PA-283)


type _Normalized = list[tuple[CitableSource, str, str]]


def repair_citations[T: (UserStory, TestSuite, QualityReport)](
    artifact: T, sources: list[CitableSource]
) -> tuple[T, list[CitationRepair]]:
    """Corrige sin LLM las citas de Jira cuyo extracto identifica sin ambigüedad otra fuente.

    El extracto de la cita (normalizado: sin escapado HTML, espacios simples, minúsculas y sin
    puntos suspensivos finales; el entero o su línea más larga que no sea de metadatos) tiene
    que tener al menos `MIN_REPAIR_EXCERPT` caracteres.

    - Ref que no está en el contexto (PA-281): se corrige si el extracto aparece en **una sola**
      fuente de Jira.
    - Ref que sí está (PA-283, p. ej. la épica con el texto de la HU): si el extracto **no**
      aparece en la fuente citada y sí en **una sola** de las demás, se corrige a esa.

    En cualquier otro caso la cita se queda como está: nunca se inventa trazabilidad.
    """
    index = _index(sources)
    # Cada fuente se normaliza una sola vez por llamada (no por cita ni por búsqueda).
    jira = [(s, _plain(s.content), _plain(s.excerpt)) for s in sources if s.kind == "jira"]
    repaired: list[SourceRef] = []
    repairs: list[CitationRepair] = []
    for cited in artifact.sources:
        source, reason = None, "ref_inexistente"
        if cited.kind == "jira":
            own = index.get((cited.kind, cited.ref))
            if own is None:
                source = _unique_match(cited.excerpt, jira)
            else:
                source, reason = _other_source(cited.excerpt, own, jira), "extracto_de_otra_fuente"
        if source is None:
            repaired.append(cited)
            continue
        repaired.append(cited.model_copy(update={"ref": source.ref}))
        repairs.append(CitationRepair(cited.kind, cited.ref, source.ref, reason))
    if not repairs:
        return artifact, []
    log.info(
        "citas reparadas",
        action="repair_citations",
        repaired=len(repairs),
        kind="jira",
        missing_ref=sum(r.reason == "ref_inexistente" for r in repairs),
        other_source=sum(r.reason == "extracto_de_otra_fuente" for r in repairs),
    )
    return artifact.model_copy(update={"sources": repaired}), repairs


def _needles(excerpt: str | None) -> list[str]:
    """El extracto entero y su línea más larga, si sirven para identificar una fuente."""
    text = (excerpt or "")[:MAX_REPAIR_EXCERPT]
    lines = [_needle(line) for line in text.splitlines()]
    lines = [line for line in lines if not line.startswith(_METADATA_LINES)]
    candidates = (_needle(text), max(lines, key=len, default=""))
    return [
        n
        for n in dict.fromkeys(candidates)
        if len(n) >= MIN_REPAIR_EXCERPT and not n.startswith(_METADATA_LINES)
    ]


def _contains(entry: tuple[CitableSource, str, str], needle: str) -> bool:
    _source, content, source_excerpt = entry
    return needle in content or needle in source_excerpt


def _unique_match(
    excerpt: str | None, sources: _Normalized, exclude: str | None = None
) -> CitableSource | None:
    """La única fuente que contiene el extracto entero o, si ninguna, su línea más larga.

    La línea más larga sirve cuando el modelo mezcla una línea de metadatos (por ejemplo, la del
    padre) con el texto de la HU; las líneas de metadatos no cuentan. Si cualquiera de las dos
    búsquedas da más de una fuente, nada. `exclude` deja fuera la fuente ya citada.
    """
    for needle in _needles(excerpt):
        matches = {
            entry[0].ref: entry[0]
            for entry in sources
            if entry[0].ref != exclude and _contains(entry, needle)
        }
        if matches:
            return next(iter(matches.values())) if len(matches) == 1 else None
    return None


def _other_source(
    excerpt: str | None, own: CitableSource, sources: _Normalized
) -> CitableSource | None:
    """PA-283: la otra fuente de la que sale el extracto, si no sale de la citada."""
    needles = _needles(excerpt)
    entry = next((e for e in sources if e[0].ref == own.ref), None)
    if not needles or entry is None or any(_contains(entry, n) for n in needles):
        return None  # sin pruebas, o el extracto sí está en la fuente citada: no se toca
    return _unique_match(excerpt, sources, exclude=own.ref)


def _plain(text: str) -> str:
    """Sin escapado HTML, con espacios simples y en minúsculas (tiempo lineal)."""
    return " ".join(html.unescape(text).split()).casefold()


def _needle(text: str) -> str:
    """El extracto del LLM normalizado y sin puntos suspensivos finales, sin expresiones
    regulares (una de ellas era cuadrática con muchos puntos seguidos)."""
    needle = _plain(text)
    while True:
        needle = needle.rstrip()
        if needle.endswith("…"):
            needle = needle[:-1]
        elif needle.endswith("..."):
            needle = needle[:-3]
        else:
            return needle


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


def without_forced_citations[T: (UserStory, TestSuite, QualityReport)](
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
