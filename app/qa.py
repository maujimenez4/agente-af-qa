"""QA 1 … QA 3 (`docs/specs/UI.md` §6.1–6.3, T-28, RF-22 a RF-27): lógica pura.

La suite viene del LLM (`TestSuite`): la UI la muestra con texto escapado o widgets de texto
plano. La matriz se construye con `TestSuite.coverage()` (datos estructurados), no con el
Markdown de los adjuntos; la estrategia (`strategy_md`) se muestra como texto plano.
"""

from dataclasses import dataclass

from schemas.test_case import TestCase, TestCaseType, TestSuite

CASE_TYPES: tuple[tuple[TestCaseType, str], ...] = (
    (TestCaseType.POSITIVE, "Positivos"),
    (TestCaseType.NEGATIVE, "Negativos"),
    (TestCaseType.ALTERNATE, "Alternos"),
    (TestCaseType.EXCEPTION, "De excepción"),
)
# `core/qa/validation` exige al menos un caso positivo y uno negativo: no se pueden quitar.
REQUIRED_TYPES = frozenset({TestCaseType.POSITIVE, TestCaseType.NEGATIVE})
EXTRAS: tuple[tuple[str, str], ...] = (
    ("data", "Datos sintéticos (RF-25)"),
    ("risks", "Riesgos, dependencias e impacto (RF-27)"),
    ("strategy", "Estrategia de pruebas (RF-26)"),
)
_EXTRA_TEXT = {
    "data": "datos sintéticos de prueba (identificadores ficticios)",
    "risks": "riesgos, dependencias y áreas de impacto",
    "strategy": "estrategia de pruebas (alcance, niveles, entornos, criterios de entrada y "
    "salida, prioridad)",
}
TYPE_LABELS = {
    TestCaseType.POSITIVE: "positivo",
    TestCaseType.NEGATIVE: "negativo",
    TestCaseType.ALTERNATE: "alterno",
    TestCaseType.EXCEPTION: "de excepción",
}
QA_STEPS_LABELS = (
    "Leer la HU de origen en Jira",
    "Recuperar el contexto (documentos, memoria y casos de HU relacionadas)",
    "Generar casos y escenarios, validar la cobertura y preparar datos, riesgos y estrategia",
)
QA_SUGGESTIONS = (
    "Añade un caso negativo con datos no válidos",
    "Cubre también las reglas de negocio",
    "Añade un caso de excepción",
)


def qa_feedback(types: set[TestCaseType], extras: set[str]) -> tuple[str, ...]:
    """Primer feedback de QA 1 (RF-22): tipos de caso y extras (decisión del día 6)."""
    chosen = [label.lower() for kind, label in CASE_TYPES if kind in types | REQUIRED_TYPES]
    parts = [f"Incluye casos: {', '.join(chosen)}."]
    wanted = [_EXTRA_TEXT[key] for key, _ in EXTRAS if key in extras]
    if wanted:
        parts.append(f"Incluye además: {'; '.join(wanted)}.")
    return tuple(parts)


@dataclass(frozen=True)
class CaseRow:
    id: str
    title: str
    type: str
    priority: str
    verifies: str  # «Verifica CA-01, RN-02»
    new_in: str | None  # «Nuevo en v2» si no estaba en la versión anterior
    gherkin: str | None
    steps: list[tuple[str, str, str]]  # (acción, datos, resultado esperado)
    preconditions: list[str]


def case_rows(suite: TestSuite, version: int, previous: TestSuite | None) -> list[CaseRow]:
    before = {case.internal_id for case in previous.cases} if previous else set()
    return [
        _row(case, version, previous is not None and case.internal_id not in before)
        for case in suite.cases
    ]


def _row(case: TestCase, version: int, is_new: bool) -> CaseRow:
    return CaseRow(
        id=case.internal_id,
        title=case.title,
        type=TYPE_LABELS.get(case.type, str(case.type)),
        priority=str(case.priority),
        verifies="Verifica " + ", ".join([*case.criterion_ids, *case.rule_ids]),
        new_in=f"Nuevo en v{version}" if is_new else None,
        gherkin=case.gherkin,
        steps=[(step.action, step.data or "", step.expected) for step in case.steps],
        preconditions=list(case.preconditions),
    )


def coverage_rows(suite: TestSuite) -> list[dict[str, str]]:
    """Filas de la matriz CA/RN × CP (RF-24) para una tabla de texto plano."""
    return [
        {"CA/RN": ref, "Casos de prueba": ", ".join(cases), "Nº": str(len(cases))}
        for ref, cases in suite.coverage().items()
    ]


# La suite solo llega a la UI si pasó la validación de cobertura de T-26 (cada CA con al menos
# un caso, CA y RN existentes): si no, `generate` falla con `CoverageError`.
COVERAGE_BADGE = "Todos los CA cubiertos"


def suite_summary(suite: TestSuite, version: int) -> str:
    """Mensaje del asistente al llegar una versión de la suite (QA 2 y QA 3)."""
    text = f"Suite lista · versión {version}: {len(suite.cases)} casos y la cobertura comprobada"
    if suite.risks:
        text += f". Riesgo principal: {suite.risks[0]}"
    return text + ". Revisa la suite en el panel y pídeme los cambios que quieras."


def attachment_names(story_key: str) -> tuple[str, str]:
    return f"matriz-{story_key}.md", f"estrategia-{story_key}.md"


def data_rows(suite: TestSuite) -> list[dict[str, str]]:
    """Datos sintéticos (RF-25) como filas de texto; columnas unidas de todas las filas."""
    columns: list[str] = []
    for row in suite.synthetic_data:
        columns += [key for key in row if key not in columns]
    return [
        {column: str(row.get(column, "")) for column in columns} for row in suite.synthetic_data
    ]
