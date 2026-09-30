"""Pruebas de la validación de suites de QA (T-26: RF-22, RF-24, RF-25; RF-21 y RNF-14).

Cubre `coverage_errors` (CA/RN existentes, todo CA cubierto, tipos positivo y negativo),
`personal_data_errors` (datos sintéticos que parecen personales) y `suite_errors`.

Datos 100 % sintéticos del dominio ficticio de Villaficticia (DEMO-N, SOC-NNNN). Los valores
que simulan datos personales tienen forma realista pero son INVENTADOS: no corresponden a
ninguna persona, teléfono, documento ni cuenta real; solo sirven para probar el detector.
"""

import pytest

from adapters.errors import AgentError
from core.functional.context import CitableSource
from core.qa.validation import (
    REQUIRED_TYPES,
    CoverageError,
    coverage_errors,
    personal_data_errors,
    suite_errors,
)
from schemas.common import Priority, SourceRef
from schemas.test_case import TestCase, TestCaseType, TestStep, TestSuite
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory
from tests.fakes import dataset
from tests.fakes.llm import renewal_test_suite

DOC = CitableSource(
    kind="rag",
    ref="DOC-01",
    title="Reglamento de préstamo (ficticio)",
    excerpt="Extracto real de DOC-01",
    content="Artículo 7 ficticio.",
)


def case(
    internal_id: str,
    criteria: list[str],
    rules: list[str] | None = None,
    case_type: TestCaseType = TestCaseType.POSITIVE,
) -> TestCase:
    """Caso de prueba sintético mínimo."""
    return TestCase(
        internal_id=internal_id,
        title=f"Caso ficticio {internal_id}",
        criterion_ids=criteria,
        rule_ids=rules or [],
        type=case_type,
        preconditions=["Persona socia ficticia SOC-0001 con sesión iniciada"],
        steps=[TestStep(action="Pulsar «Renovar»", data="SOC-0001", expected="Resultado")],
        priority=Priority.MUST,
    )


def suite_of(*cases: TestCase, **update: object) -> TestSuite:
    return TestSuite(
        story_jira_key="DEMO-3",
        cases=list(cases),
        strategy_md="# Estrategia (ficticia)",
        **update,  # type: ignore[arg-type]
    )


def with_data(**row: str) -> TestSuite:
    return renewal_test_suite().model_copy(update={"synthetic_data": [row]})


def suspension_story() -> UserStory:
    """HU coherente con [HU-12] Suspensión por devolución tardía del seed (3 CA y 3 RN)."""
    return UserStory(
        internal_id="HU-12",
        jira_key="DEMO-16",
        title="Suspensión por devolución tardía",
        role="responsable de sala",
        action="que el sistema suspenda automáticamente a quien devuelve con retraso",
        benefit="aplicar el reglamento de forma homogénea",
        description="Cálculo automático de la suspensión al registrar la devolución.",
        business_goal="Aplicar las sanciones sin cálculos manuales.",
        scope_includes=["Cálculo automático de la suspensión"],
        scope_excludes=["Sanciones económicas"],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="CA-01",
                title="Suspensión aplicada",
                given=["un préstamo devuelto con N días naturales de retraso"],
                when=["se registra la devolución"],
                then=["la persona socia queda suspendida N días"],
            ),
            AcceptanceCriterion(
                id="CA-02",
                title="Bloqueo durante la suspensión",
                given=["una persona socia suspendida"],
                when=["intenta reservar o renovar"],
                then=["la operación se rechaza"],
            ),
            AcceptanceCriterion(
                id="CA-03",
                title="Devolución en plazo",
                given=["un préstamo devuelto el mismo día del vencimiento"],
                when=["se registra la devolución"],
                then=["no se aplica ninguna suspensión"],
            ),
        ],
        business_rules=[
            BusinessRule(id="RN-01", description="Un día de suspensión por día de retraso."),
            BusinessRule(id="RN-02", description="Durante la suspensión no se reserva ni renueva."),
            BusinessRule(
                id="RN-03", description="Los préstamos en curso mantienen su vencimiento."
            ),
        ],
        assumptions=[],
        constraints=[],
        dependencies=["DEMO-2", "DEMO-3"],
        alternate_flows=[],
        exceptions=[],
        related_features=["AvisosVF (ficticio)"],
        priority=Priority.MUST,
    )


# --- coverage_errors ----------------------------------------------------------------------


def test_coverage_errors_is_empty_when_suite_covers_story() -> None:
    """RF-24: la suite de renovación cubre CA-01 y CA-02 con casos positivo y negativo."""
    assert coverage_errors(renewal_test_suite(), dataset.renewal_story()) == []


def test_coverage_errors_is_empty_for_seed_story_fully_covered() -> None:
    """RF-22 · RF-24: HU del seed (HU-12) con sus 3 CA cubiertos y tipos variados."""
    suite = suite_of(
        case("CP-01", ["CA-01"], ["RN-01"]),
        case("CP-02", ["CA-02"], ["RN-02"], TestCaseType.NEGATIVE),
        case("CP-03", ["CA-03"], ["RN-03"], TestCaseType.ALTERNATE),
        case("CP-04", ["CA-01"], ["RN-01"], TestCaseType.EXCEPTION),
    )

    assert coverage_errors(suite, suspension_story()) == []


def test_coverage_errors_reports_unknown_criterion() -> None:
    """RF-24 (negativa): un caso que referencia un CA inexistente se señala."""
    suite = renewal_test_suite()
    suite.cases[0].criterion_ids.append("CA-09")

    errors = coverage_errors(suite, dataset.renewal_story())

    assert errors == ["CP-01 referencia CA/RN que no existen en la HU: CA-09"]


def test_coverage_errors_reports_unknown_rule() -> None:
    """RF-24 (negativa): un caso que referencia una RN inexistente se señala."""
    suite = renewal_test_suite()
    suite.cases[1].rule_ids.append("RN-07")

    errors = coverage_errors(suite, dataset.renewal_story())

    assert errors == ["CP-02 referencia CA/RN que no existen en la HU: RN-07"]


def test_coverage_errors_lists_all_unknown_ids_of_a_case() -> None:
    """RF-24: se enumeran todos los CA y RN inexistentes del mismo caso."""
    suite = suite_of(
        case("CP-01", ["CA-01", "CA-05"], ["RN-09"]),
        case("CP-02", ["CA-02"], case_type=TestCaseType.NEGATIVE),
    )

    [error] = coverage_errors(suite, dataset.renewal_story())

    assert error.startswith("CP-01 ")
    assert "CA-05" in error and "RN-09" in error


def test_coverage_errors_reports_criterion_without_case() -> None:
    """RF-24 (negativa): todo CA de la HU debe tener al menos un caso."""
    suite = suite_of(
        case("CP-01", ["CA-01"], ["RN-01"]),
        case("CP-02", ["CA-02"], ["RN-02"], TestCaseType.NEGATIVE),
    )

    errors = coverage_errors(suite, suspension_story())

    assert errors == ["criterios sin ningún caso de prueba: CA-03"]


def test_coverage_errors_does_not_require_every_rule_to_be_covered() -> None:
    """RF-24 (límite): la obligación es por CA; una RN sin caso no es un error."""
    suite = suite_of(
        case("CP-01", ["CA-01"]),
        case("CP-02", ["CA-02"], case_type=TestCaseType.NEGATIVE),
    )

    assert coverage_errors(suite, dataset.renewal_story()) == []


def test_coverage_errors_reports_missing_negative_case() -> None:
    """RF-22 (negativa): debe haber al menos un caso negativo."""
    suite = suite_of(case("CP-01", ["CA-01"]), case("CP-02", ["CA-02"], [], TestCaseType.ALTERNATE))

    errors = coverage_errors(suite, dataset.renewal_story())

    assert errors == ["faltan casos de tipo: negativo"]


def test_coverage_errors_reports_missing_positive_case() -> None:
    """RF-22 (negativa): debe haber al menos un caso positivo."""
    suite = suite_of(
        case("CP-01", ["CA-01"], case_type=TestCaseType.NEGATIVE),
        case("CP-02", ["CA-02"], case_type=TestCaseType.EXCEPTION),
    )

    errors = coverage_errors(suite, dataset.renewal_story())

    assert errors == ["faltan casos de tipo: positivo"]


def test_coverage_errors_reports_both_types_missing() -> None:
    """RF-22 (límite): sin positivo ni negativo se mencionan ambos tipos."""
    suite = suite_of(case("CP-01", ["CA-01", "CA-02"], case_type=TestCaseType.ALTERNATE))

    errors = coverage_errors(suite, dataset.renewal_story())

    assert errors == ["faltan casos de tipo: positivo, negativo"]


def test_coverage_errors_reports_several_problems_at_once() -> None:
    """RF-22 · RF-24: CA inexistente, CA sin caso y tipo ausente se informan juntos."""
    suite = suite_of(case("CP-01", ["CA-01", "CA-08"], ["RN-04"]))

    errors = coverage_errors(suite, suspension_story())

    assert errors == [
        "CP-01 referencia CA/RN que no existen en la HU: CA-08, RN-04",
        "criterios sin ningún caso de prueba: CA-02, CA-03",
        "faltan casos de tipo: negativo",
    ]


def test_required_types_are_positive_and_negative() -> None:
    """RF-22: la decisión de T-26 exige positivo y negativo."""
    assert REQUIRED_TYPES == (TestCaseType.POSITIVE, TestCaseType.NEGATIVE)


def test_coverage_error_is_agent_error() -> None:
    """CLAUDE.md: CoverageError se muestra en la UI como cualquier AgentError."""
    assert issubclass(CoverageError, AgentError)


# --- personal_data_errors: emails ---------------------------------------------------------


def test_personal_data_errors_is_empty_without_synthetic_data() -> None:
    """RF-25 (límite): una suite sin datos sintéticos no tiene errores."""
    assert personal_data_errors(renewal_test_suite()) == []


def test_personal_data_errors_flags_email_of_real_domain() -> None:
    """RF-25 (negativa): email con dominio no reservado (valor inventado) se marca."""
    errors = personal_data_errors(with_data(email="persona.inventada@correo-inventado.es"))

    assert errors == ["synthetic_data[0].email parece un email real; usa un valor ficticio"]


@pytest.mark.parametrize(
    "email",
    [
        "socia.ficticia@example.com",
        "socia.ficticia@example.org",
        "socia.ficticia@example.net",
        "socia.ficticia@sub.example.com",
        "socia.ficticia@EXAMPLE.COM",
        "socia.ficticia@villaficticia.example",
        "socia.ficticia@villaficticia.invalid",
    ],
)
def test_personal_data_errors_accepts_fictitious_email_domains(email: str) -> None:
    """RF-25: se admiten example.com/org/net, *.example y *.invalid (RFC 2606)."""
    assert personal_data_errors(with_data(email=email)) == []


@pytest.mark.parametrize(
    "email",
    [
        "socia@example.com.es",  # parece example.com pero es otro dominio
        "socia@notexample.com",
        "socia@villaficticia.es",
        "socia@villaficticia.test",
    ],
)
def test_personal_data_errors_flags_lookalike_domains(email: str) -> None:
    """RF-25 (límite): dominios parecidos a los reservados no se admiten."""
    assert len(personal_data_errors(with_data(email=email))) == 1


def test_personal_data_errors_flags_real_email_among_fictitious_ones() -> None:
    """RF-25 (límite): basta un email no ficticio en el valor para marcarlo."""
    value = "a@example.com, b@correo-inventado.es"

    assert len(personal_data_errors(with_data(contactos=value))) == 1


# --- personal_data_errors: teléfonos, documentos e IBAN -----------------------------------
# Todos los valores son inventados; tienen forma realista solo para ejercitar el detector.


@pytest.mark.parametrize(
    "phone",
    [
        "612345678",
        "+34 612 34 56 78",
        "+34612345678",
        "612-345-678",
        "612.34.56.78",
        "912 345 678",
        "Llamar al 712 345 678 antes de las 9",
    ],
)
def test_personal_data_errors_flags_spanish_phone(phone: str) -> None:
    """RF-25 (negativa): teléfonos españoles con y sin +34 y con separadores."""
    errors = personal_data_errors(with_data(telefono=phone))

    assert errors == ["synthetic_data[0].telefono parece un teléfono real; usa un valor ficticio"]


@pytest.mark.parametrize("dni", ["12345678Z", "DNI 87654321x"])
def test_personal_data_errors_flags_dni(dni: str) -> None:
    """RF-25 (negativa): DNI (inventado) se marca como documento de identidad."""
    errors = personal_data_errors(with_data(documento=dni))

    assert errors == [
        "synthetic_data[0].documento parece un documento de identidad real; usa un valor ficticio"
    ]


@pytest.mark.parametrize("nie", ["X1234567L", "Y7654321g", "Z0000001R"])
def test_personal_data_errors_flags_nie(nie: str) -> None:
    """RF-25 (negativa): NIE (inventado) se marca como documento de identidad."""
    [error] = personal_data_errors(with_data(documento=nie))

    assert "documento de identidad" in error


@pytest.mark.parametrize("iban", ["ES00 0000 0000 0000 0000 0000", "ES0012345678901234567890"])
def test_personal_data_errors_flags_iban(iban: str) -> None:
    """RF-25 (negativa): IBAN español (inventado) con y sin espacios."""
    errors = personal_data_errors(with_data(cuenta=iban))

    assert errors == ["synthetic_data[0].cuenta parece un IBAN real; usa un valor ficticio"]


@pytest.mark.parametrize(
    "value",
    [
        "SOC-0001",
        "SOC-9999",
        "DEMO-10",
        "CP-01",
        "2026-09-30",
        "30/09/2026",
        "21 días",
        "12,50 €",
        "1.250,00 €",
        "3 reservas activas",
        "Ana Inventada Ficticia",
        "ISBN-FICTICIO-0001",
    ],
)
def test_personal_data_errors_ignores_ids_dates_and_amounts(value: str) -> None:
    """RF-25 (límite): identificadores ficticios, fechas e importes no se marcan."""
    assert personal_data_errors(with_data(valor=value)) == []


@pytest.mark.parametrize("amount", ["7500000", "700.000.000 €"])
def test_personal_data_errors_ignores_large_amounts(amount: str) -> None:
    """RF-25 (límite): un importe no es un teléfono (los móviles españoles tienen 9 cifras)."""
    assert personal_data_errors(with_data(importe=amount)) == []


@pytest.mark.parametrize("document", ["12345678-Z", "X-1234567-L"])
def test_personal_data_errors_flags_documents_with_hyphen(document: str) -> None:
    """RF-25 (límite): formatos habituales con guion también son documentos (inventados)."""
    assert len(personal_data_errors(with_data(documento=document))) == 1


@pytest.mark.parametrize(
    "key, value",
    [
        ("email", "persona.inventada@correo-inventado.es"),
        ("telefono", "+34 612 34 56 78"),
        ("documento", "12345678Z"),
        ("documento", "X1234567L"),
        ("cuenta", "ES00 0000 0000 0000 0000 0000"),
    ],
)
def test_personal_data_errors_message_does_not_repeat_value(key: str, value: str) -> None:
    """RF-25 · CLAUDE.md: el mensaje nunca repite el valor sospechoso."""
    [error] = personal_data_errors(with_data(**{key: value}))

    assert value not in error
    assert value.replace(" ", "") not in error.replace(" ", "")


def test_personal_data_errors_reports_row_and_key_of_each_value() -> None:
    """RF-25: cada valor sospechoso se señala con su fila y su clave."""
    suite = renewal_test_suite().model_copy(
        update={
            "synthetic_data": [
                {"socio": "SOC-0001", "email": "socia@example.com"},
                {"socio": "SOC-0002", "telefono": "612345678", "email": "x@correo-inventado.es"},
            ]
        }
    )

    errors = personal_data_errors(suite)

    assert len(errors) == 2
    assert errors[0].startswith("synthetic_data[1].telefono ")
    assert errors[1].startswith("synthetic_data[1].email ")


# --- suite_errors -------------------------------------------------------------------------


def test_suite_errors_is_empty_for_valid_suite_with_citation() -> None:
    """RF-21 · RF-24 · RF-25: suite cubierta, con cita válida y datos ficticios."""
    suite = renewal_test_suite().model_copy(
        update={
            "sources": [SourceRef(kind="rag", ref="DOC-01")],
            "synthetic_data": [{"socio": "SOC-0001", "email": "socia@example.com"}],
        }
    )

    assert suite_errors(suite, dataset.renewal_story(), [DOC]) == []


def test_suite_errors_combines_coverage_citation_and_personal_data() -> None:
    """RF-21 · RF-24 · RF-25: los tres tipos de error se acumulan en ese orden."""
    suite = suite_of(
        case("CP-01", ["CA-01"]),
        sources=[SourceRef(kind="rag", ref="DOC-99")],
        synthetic_data=[{"telefono": "612345678"}],
    )

    errors = suite_errors(suite, dataset.renewal_story(), [DOC])

    assert errors == [
        "criterios sin ningún caso de prueba: CA-02",
        "faltan casos de tipo: negativo",
        "«rag:DOC-99» no está entre las fuentes recibidas",
        "synthetic_data[0].telefono parece un teléfono real; usa un valor ficticio",
    ]


def test_suite_errors_requires_citation_when_context_has_sources() -> None:
    """RNF-14: si el contexto trae fuentes, la suite debe citar al menos una."""
    errors = suite_errors(renewal_test_suite(), dataset.renewal_story(), [DOC])

    assert errors == ["la propuesta no cita ninguna fuente y el contexto sí traía fuentes"]


def test_personal_data_errors_flags_lowercase_iban() -> None:
    """RF-25: un IBAN en minúsculas también se detecta (valor inventado)."""
    assert len(personal_data_errors(with_data(cuenta="es00 0000 0000 0000 0000 0000"))) == 1


def test_personal_data_errors_checks_case_steps_and_gherkin() -> None:
    """RF-25: los datos de los pasos y el Gherkin de un caso también se revisan."""
    suite = renewal_test_suite()
    case = suite.cases[0]
    step = case.steps[0].model_copy(update={"data": "persona.inventada@correo-inventado.es"})
    bad_case = case.model_copy(update={"steps": [step], "gherkin": "Dado el DNI 12345678Z"})
    suite = suite.model_copy(update={"cases": [bad_case, *suite.cases[1:]]})

    errors = personal_data_errors(suite)

    assert any(".steps[0].data" in e for e in errors)
    assert any(".gherkin" in e for e in errors)
    assert all("correo-inventado" not in e and "12345678" not in e for e in errors)


def test_personal_data_errors_checks_keys_without_repeating_them() -> None:
    """RF-25: una clave con forma de email se marca y no se repite en el mensaje (inventado)."""
    errors = personal_data_errors(
        with_data(**{"persona.inventada@correo-inventado.es": "SOC-0001"})
    )

    assert len(errors) == 1
    assert "correo-inventado" not in errors[0]
    assert "<clave 1>" in errors[0]


@pytest.mark.parametrize(
    "field, value, where",
    [
        ("risks", ["Riesgo con el teléfono 612 34 56 78"], "risks[0]"),
        ("dependencies", ["Depende del DNI 12345678Z"], "dependencies[0]"),
        ("impact_areas", ["Área del NIE X1234567L"], "impact_areas[0]"),
        ("strategy_md", "Contactar con persona.inventada@correo-inventado.es", "strategy_md"),
    ],
)
def test_personal_data_errors_checks_suite_level_texts(
    field: str, value: object, where: str
) -> None:
    """RF-25: riesgos, dependencias, impacto y estrategia también se revisan (inventados)."""
    suite = renewal_test_suite().model_copy(update={field: value})

    errors = personal_data_errors(suite)

    assert [e for e in errors if e.startswith(where)]


def test_personal_data_errors_checks_case_title() -> None:
    """RF-25: el título de un caso también se revisa (valor inventado)."""
    suite = renewal_test_suite()
    case = suite.cases[0].model_copy(update={"title": "Llamar al 612 345 678"})
    suite = suite.model_copy(update={"cases": [case, *suite.cases[1:]]})

    assert any(e.startswith(f"{case.internal_id}.title") for e in personal_data_errors(suite))
