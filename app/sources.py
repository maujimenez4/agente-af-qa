"""Panel «Antes de generar» y tarjeta «HU parecida» (Mixta 2, `docs/specs/UI.md` §4.3).

Funciones puras sobre `SourcePreview` (T-53) e `IssueDetail`: sin LLM. Las fuentes desmarcadas
van a `excluded_sources` (T-51); la incidencia de origen (`required`) no se puede desmarcar.
"""

import re
from dataclasses import dataclass

from adapters.base import IssueDetail
from core.guided_start import SourcePreview

_CA = re.compile(r"\bCA-\d+\b")
_RN = re.compile(r"\bRN-\d+\b")
KIND_LABELS = {"jira": "Jira", "rag": "Documento", "memory": "Memoria · prioritaria"}


@dataclass(frozen=True)
class IssueCard:
    """Lo que muestra la tarjeta de una HU (clave, épica, nº de CA y RN)."""

    key: str
    summary: str
    epic: str | None
    criteria: int
    rules: int


def issue_card(issue: IssueDetail) -> IssueCard:
    """Cuenta los CA y RN distintos de la descripción (plantilla de HU), sin IA."""
    text = issue.description_text or ""
    return IssueCard(
        key=issue.key,
        summary=issue.summary,
        epic=issue.parent_key,
        criteria=len(set(_CA.findall(text))),
        rules=len(set(_RN.findall(text))),
    )


def describe_card(card: IssueCard) -> str:
    epic = f"épica {card.epic}" if card.epic else "sin épica"
    return f"{epic} · {card.criteria} CA · {card.rules} RN"


def source_label(source: SourcePreview) -> str:
    """«DOC-03 · Título · politicas · Documento» (texto plano, se escapa al pintarlo)."""
    parts = [source.ref, source.title]
    if source.category:
        parts.append(source.category)
    parts.append(KIND_LABELS.get(source.kind, source.kind))
    if source.required:
        parts.append("origen, obligatoria")
    return " · ".join(part for part in parts if part)


def excluded_refs(sources: list[SourcePreview], checked: dict[str, bool]) -> list[str]:
    """Referencias desmarcadas; las obligatorias nunca se excluyen."""
    return sorted(
        source.ref
        for source in sources
        if not source.required and not checked.get(source.ref, True)
    )
