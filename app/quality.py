"""Mixta 5 · «Revisar la calidad» (`docs/specs/UI.md` §4.8, T-48, RF-18): lógica pura.

El informe (`QualityReport`) viene del LLM: la UI lo pinta campo a campo y escapado, nunca con
`to_markdown()` en `st.markdown`; ese `.md` es solo para *Descargar informe* (PA-64).
*Evolucionar con esto* abre una conversación nueva de evolución con las propuestas del informe
como feedback previo (`evolve_feedback_of`).

PA-277: las revisiones se guardan en `QualityReviewStore` (como en la API), así que estas
funciones reciben la clave y el informe, no el resultado en memoria del revisor.
"""

from dataclasses import dataclass, replace

from app.origin import StartRequest, fix_origin
from core.quality import QualityState, StoredQualityReview, evolve_feedback_of
from schemas.quality import FINDING_LABELS, INVEST_NAMES, QualityReport

REVIEW_STEPS: tuple[str, ...] = (
    "Leer la HU y su contexto en Jira, documentos y memoria",
    "Pasar la HU a la plantilla (una llamada al modelo)",
    "Redactar el informe INVEST y los hallazgos (otra llamada al modelo)",
)
VERDICTS = {"ok": "Bien", "improvable": "Mejorable"}
# Estado de cada revisión en la lista de la barra lateral (PA-277, como «Informe listo» en la API).
STATE_LABELS: dict[QualityState, str] = {
    "done": "Informe listo",
    "running": "En marcha",
    "error": "Error",
}


@dataclass(frozen=True)
class InvestRow:
    letter: str
    name: str
    verdict: str  # «Bien» o «Mejorable»
    reason: str


@dataclass(frozen=True)
class FindingRow:
    kind: str  # etiqueta en español (`FINDING_LABELS`)
    target: str  # «CA-02», «RN-01» o «HU»
    explanation: str
    proposal: str


def invest_rows(report: QualityReport) -> list[InvestRow]:
    """Seis filas I, N, V, E, S, T en orden, con «Bien» / «Mejorable»."""
    return [
        InvestRow(
            letter=check.letter,
            name=INVEST_NAMES[check.letter],
            verdict=VERDICTS[check.verdict],
            reason=check.reason,
        )
        for check in report.invest_in_order()
    ]


def finding_rows(report: QualityReport) -> list[FindingRow]:
    return [
        FindingRow(
            kind=FINDING_LABELS[finding.kind],
            target=finding.target_id or "HU",
            explanation=finding.explanation,
            proposal=finding.proposal,
        )
        for finding in report.findings
    ]


def review_message(key: str, report: QualityReport) -> str:
    """Mensaje del asistente al terminar (UI.md §4.8)."""
    count = len(report.findings)
    points = "ningún punto a mejorar" if count == 0 else f"{count} puntos a mejorar"
    if count == 1:
        points = "1 punto a mejorar"
    return (
        f"He revisado {key} con INVEST y contra las fuentes. Hay {points}. "
        "No he cambiado nada en Jira."
    )


def report_filename(jira_key: str) -> str:
    return f"calidad-{jira_key}.md"


def report_download(key: str, report: QualityReport) -> bytes:
    """Contenido de *Descargar informe* (PA-64): el `.md` escapado de `schemas/quality`."""
    return report.to_markdown(key).encode("utf-8")


def review_item(review: StoredQualityReview) -> tuple[str, str]:
    """Botón de la lista «Revisiones de calidad»: título y estado (nunca texto del informe)."""
    return review.title, STATE_LABELS.get(review.state, review.state)


def evolve_request(
    key: str,
    report: QualityReport,
    project: str,
    excluded_sources: tuple[str, ...] = (),
) -> StartRequest:
    """*Evolucionar con esto*: conversación nueva de evolución con las mejoras como feedback.

    Conserva las fuentes desmarcadas al revisar: no vuelven a entrar sin avisar.
    """
    request = fix_origin("evolve", project, key=key)
    return replace(
        request,
        excluded_sources=tuple(excluded_sources),
        extra_feedback=tuple(evolve_feedback_of(report)),
    )
