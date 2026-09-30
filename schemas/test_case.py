"""Casos de prueba y suite de QA con matriz de cobertura (RF-22 a RF-27)."""

import re
from enum import StrEnum
from typing import ClassVar, Self

from pydantic import BaseModel, Field, model_validator

from schemas.common import Priority, SourceRef, duplicated_ids
from schemas.user_story import CRITERION_ID, RULE_ID

CASE_ID = r"^CP-\d+$"


class TestCaseType(StrEnum):
    __test__ = False  # evita que pytest lo tome por una clase de pruebas

    POSITIVE = "positivo"
    NEGATIVE = "negativo"
    ALTERNATE = "alterno"
    EXCEPTION = "excepcion"


class TestStep(BaseModel):
    __test__: ClassVar[bool] = False

    action: str = Field(min_length=1)
    data: str | None = None
    expected: str = Field(min_length=1)


class TestCase(BaseModel):
    """Caso de prueba trazable a CA y RN (RF-23)."""

    __test__: ClassVar[bool] = False

    internal_id: str = Field(pattern=CASE_ID)  # "CP-01"
    title: str = Field(min_length=1)
    criterion_ids: list[str] = Field(min_length=1)  # CA vinculados
    rule_ids: list[str] = []  # RN vinculadas
    type: TestCaseType
    preconditions: list[str]
    steps: list[TestStep] = Field(min_length=1)
    gherkin: str | None = None
    priority: Priority

    @model_validator(mode="after")
    def _valid_references(self) -> Self:
        bad = [i for i in self.criterion_ids if not re.match(CRITERION_ID, i)]
        bad += [i for i in self.rule_ids if not re.match(RULE_ID, i)]
        if bad:
            raise ValueError(
                f"{self.internal_id}: referencias no válidas a CA/RN: {', '.join(bad)}"
            )
        return self


class TestSuite(BaseModel):
    """Artefactos de QA de una HU; se publica en Jira nativo (D-09)."""

    __test__: ClassVar[bool] = False

    story_jira_key: str = Field(min_length=1)
    cases: list[TestCase] = Field(min_length=1)
    strategy_md: str  # estrategia de pruebas (RF-26) → adjunto
    synthetic_data: list[dict[str, str]] = []
    risks: list[str] = []
    dependencies: list[str] = []
    impact_areas: list[str] = []
    sources: list[SourceRef] = []

    @model_validator(mode="after")
    def _unique_case_ids(self) -> Self:
        repeated = duplicated_ids([c.internal_id for c in self.cases])
        if repeated:
            raise ValueError(f"IDs de caso repetidos: {', '.join(repeated)}")
        return self

    def coverage(self) -> dict[str, list[str]]:
        """CA/RN-id → [CP-id], calculada a partir de los casos (RF-24)."""
        matrix: dict[str, list[str]] = {}
        for case in self.cases:
            for ref in [*case.criterion_ids, *case.rule_ids]:
                ids = matrix.setdefault(ref, [])
                if case.internal_id not in ids:
                    ids.append(case.internal_id)
        return {ref: sorted(matrix[ref], key=_id_order) for ref in sorted(matrix, key=_id_order)}

    def coverage_md(self) -> str:
        """Matriz de cobertura en Markdown → adjunto `matriz-<CLAVE>.md` (§6.2)."""
        lines = [
            f"# Matriz de cobertura · {self.story_jira_key}",
            "",
            "| CA/RN | Casos de prueba | Nº |",
            "|---|---|---|",
        ]
        for ref, cases in self.coverage().items():
            lines.append(f"| {ref} | {', '.join(cases)} | {len(cases)} |")
        return "\n".join(lines) + "\n"


def _id_order(identifier: str) -> tuple[int, str, int]:
    """Ordena CA antes que RN y por número (CA-2 antes que CA-10)."""
    prefix, _, number = identifier.partition("-")
    group = {"CA": 0, "RN": 1, "CP": 2}.get(prefix, 3)
    return group, prefix, int(number) if number.isdigit() else 0
