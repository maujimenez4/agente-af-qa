"""Informe de calidad de una HU existente (RF-18, T-48): INVEST, ambigüedades, huecos y fuentes.

Salida estructurada del LLM en el flujo «Revisar la calidad», que no publica nada en Jira.
"""

import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from schemas.common import SourceRef

InvestLetter = Literal["I", "N", "V", "E", "S", "T"]
INVEST_LETTERS: tuple[InvestLetter, ...] = ("I", "N", "V", "E", "S", "T")
INVEST_NAMES = {
    "I": "Independiente",
    "N": "Negociable",
    "V": "Valiosa",
    "E": "Estimable",
    "S": "Pequeña",
    "T": "Testeable",
}
FindingKind = Literal["ambiguity", "gap", "no_source", "invest", "inconsistency"]
FINDING_LABELS = {
    "ambiguity": "Ambigüedad",
    "gap": "Hueco",
    "no_source": "Sin fuente",
    "invest": "INVEST",
    "inconsistency": "Incoherencia con las fuentes",
}
TARGET_ID = r"^(CA|RN)-\d+$"
MAX_TEXT = 500  # texto del LLM: acotado (UI, .md y feedback de «Evolucionar con esto»)
MAX_ITEMS = 30
_MD_SPECIAL = re.compile(r"([\\`*_\[\]()!<>#|])")


class InvestCheck(BaseModel):
    letter: InvestLetter
    verdict: Literal["ok", "improvable"]
    reason: str = Field(min_length=1, max_length=MAX_TEXT)


class QualityFinding(BaseModel):
    kind: FindingKind
    target_id: str | None = Field(default=None, pattern=TARGET_ID)  # «CA-02», «RN-01» o nada
    explanation: str = Field(min_length=1, max_length=MAX_TEXT)
    proposal: str = Field(min_length=1, max_length=MAX_TEXT)


class QualityReport(BaseModel):
    summary: str = Field(min_length=1, max_length=MAX_TEXT)
    invest: list[InvestCheck] = Field(min_length=6, max_length=6)
    findings: list[QualityFinding] = Field(max_length=MAX_ITEMS)
    open_questions: list[Annotated[str, Field(max_length=MAX_TEXT)]] = Field(
        default=[], max_length=MAX_ITEMS
    )
    sources: list[SourceRef] = Field(default=[], max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _one_check_per_letter(self) -> Self:
        letters = [check.letter for check in self.invest]
        if sorted(letters) != sorted(INVEST_LETTERS):
            raise ValueError("El informe necesita una valoración por cada letra de INVEST.")
        return self

    def invest_in_order(self) -> list[InvestCheck]:
        by_letter = {check.letter: check for check in self.invest}
        return [by_letter[letter] for letter in INVEST_LETTERS]

    def to_markdown(self, jira_key: str) -> str:
        """Informe descargable (Mixta 5 · «Descargar informe», PA-64).

        El texto viene del LLM: se escapa el markdown para que no cuele enlaces, imágenes ni
        títulos (la UI tampoco lo pinta con `st.markdown`: lo muestra campo a campo).
        """
        lines = [f"# Calidad de {jira_key}", "", _md(self.summary), "", "## INVEST", ""]
        for check in self.invest_in_order():
            verdict = "Bien" if check.verdict == "ok" else "Mejorable"
            lines.append(
                f"- **{check.letter} · {INVEST_NAMES[check.letter]}**: {verdict}. "
                f"{_md(check.reason)}"
            )
        lines += ["", "## Hallazgos", ""]
        if not self.findings:
            lines.append("Sin hallazgos.")
        for finding in self.findings:
            target = f" · {finding.target_id}" if finding.target_id else ""
            lines.append(
                f"- **{FINDING_LABELS[finding.kind]}{target}**: {_md(finding.explanation)} "
                f"Propuesta: {_md(finding.proposal)}"
            )
        if self.open_questions:
            lines += ["", "## Preguntas para negocio", ""]
            lines += [f"- {_md(question)}" for question in self.open_questions]
        if self.sources:
            lines += ["", "## Fuentes", ""]
            lines += [f"- {_md(source.ref)}" for source in self.sources]
        return "\n".join(lines) + "\n"


def _md(text: str) -> str:
    """Texto plano en markdown: sin saltos de línea y con los caracteres especiales escapados."""
    return _MD_SPECIAL.sub(lambda m: "\\" + m.group(1), " ".join(text.split()))
