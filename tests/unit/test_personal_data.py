"""PA-142 · Detector común y lineal de datos que parecen personales (`core/personal_data.py`).

Cubre: tiempo acotado con textos largos (sin `@`, con muchas `@`, con un email al final),
equivalencia con la implementación anterior (patrón de email sobre el texto entero), emails en el
límite de los tramos alrededor de cada `@`, y que la validación de la suite y la evidencia de la
ejecución usan el mismo detector (sin copias).

Datos 100 % ficticios: dominios reservados (example.com, .invalid) o inventados
(`correo-ficticio.es`), documentos y cuentas con cifras de relleno.
"""

import inspect
import time

import pytest

import core.graph.execution as execution
import core.qa.validation as validation
from core.graph.execution import ExecutionRejectedError, _reject_sensitive_evidence
from core.personal_data import (
    DNI,
    EMAIL,
    FICTITIOUS_DOMAIN,
    IBAN,
    NIE,
    PHONE,
    personal_data_kind,
)
from schemas.test_case import MAX_EVIDENCE_CHARS

TIME_LIMIT_S = 0.5
EMAIL_BEFORE = 64  # parte local realista (antes, el tramo ante cada `@`)
EMAIL_AFTER = 255  # dominio máximo (antes, el tramo tras cada `@`)
REAL_SHAPED_EMAIL = "persona.ficticia@correo-ficticio.es"


def _reference_kind(text: str) -> str | None:
    """Implementación anterior a PA-142: el patrón de email sobre el texto entero."""
    for match in EMAIL.finditer(text):
        if not FICTITIOUS_DOMAIN.search(match.group(1)):
            return "email"
    if DNI.search(text) or NIE.search(text):
        return "documento de identidad"
    if IBAN.search(text):
        return "IBAN"
    if PHONE.search(text):
        return "teléfono"
    return None


def _timed(text: str) -> tuple[str | None, float]:
    start = time.perf_counter()
    kind = personal_data_kind(text)
    return kind, time.perf_counter() - start


# --- Tiempo acotado ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "a" * MAX_EVIDENCE_CHARS,
        "a." * (MAX_EVIDENCE_CHARS // 2),
        "a-" * (MAX_EVIDENCE_CHARS // 2),
        "@" * MAX_EVIDENCE_CHARS,
        "a@" * (MAX_EVIDENCE_CHARS // 2),
        "a.@" * (MAX_EVIDENCE_CHARS // 3),
        ("a" * 318 + "@") * (MAX_EVIDENCE_CHARS // 319),  # tramos unidos, el peor hueco
        ("a." * 159 + "@b") * (MAX_EVIDENCE_CHARS // 321),
    ],
    ids=["a", "a-punto", "a-guion", "arrobas", "a-arroba", "a-punto-arroba", "hueco", "dominios"],
)
def test_detection_is_fast_when_long_adversarial_text(text: str) -> None:
    """PA-142: 20 000 caracteres sin `@` o con muchas `@` se analizan en < 0,5 s."""
    assert len(text) <= MAX_EVIDENCE_CHARS + 2
    _kind, elapsed = _timed(text)
    assert elapsed < TIME_LIMIT_S


def test_email_at_end_is_found_fast_when_text_is_long() -> None:
    """PA-142: un email al final de un texto largo se detecta, y rápido."""
    text = "a." * 9_900 + " " + REAL_SHAPED_EMAIL
    kind, elapsed = _timed(text)
    assert kind == "email"
    assert elapsed < TIME_LIMIT_S


def test_reference_was_slow_but_detector_is_fast_when_text_has_no_at() -> None:
    """PA-142: con un texto sin `@` el patrón sobre el texto entero era cuadrático; el detector
    da el mismo resultado sin ese coste (medido con un texto más corto para la referencia)."""
    text = "a." * 2_500
    start = time.perf_counter()
    reference = _reference_kind(text)
    reference_elapsed = time.perf_counter() - start
    kind, elapsed = _timed(text)
    assert kind == reference is None
    assert elapsed < reference_elapsed


# --- Equivalencia con la implementación anterior -------------------------------------------


EQUIVALENCE_TEXTS = [
    "",
    "Texto sin datos personales sobre la renovación de un préstamo (ficticio).",
    f"Contacto: {REAL_SHAPED_EMAIL}.",
    "Escribe a soporte@biblioteca-ficticia.es o a ana@example.com",
    "Solo ficticios: ana@example.com, luis@example.org, eva@example.net, x@demo.invalid",
    "a@example",
    "usuario@sub.example.com y usuaria@correo.example",
    "dominio sin punto: nombre@localhost",
    "arroba suelta @ y doble @@ y final @",
    "a@x.invalid@correo-ficticio.es",
    "DNI 12345678Z del socio ficticio",
    "DNI con guion 12345678-Z",
    "NIE X1234567L o Y-1234567-T",
    "IBAN ES00 0000 0000 0000 0000 0000",
    "IBAN ES0000000000000000000000",
    "Teléfono 600 000 000",
    "Teléfono +34 699 11 22 33",
    "Teléfono 912-345-678",
    "Importe de 700.000.000 € en la operación ficticia",
    "Referencia 123456789012 y código 12345678",
    "Préstamo DEMO-3, versión 2, 3 renovaciones máximas",
    "ana@example.com 12345678Z 600 000 000",
    "primero 600 000 000 y luego " + REAL_SHAPED_EMAIL,
    "x" * 500 + "@" + "correo-ficticio.es",
    "a." * 300 + "@b.es " + "c" * 400 + "@d.example.com",
]


@pytest.mark.parametrize("text", EQUIVALENCE_TEXTS)
def test_result_matches_reference_when_text_is_realistic(text: str) -> None:
    """PA-142: el detector por tramos devuelve lo mismo que el patrón sobre el texto entero."""
    assert personal_data_kind(text) == _reference_kind(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"Contacto: {REAL_SHAPED_EMAIL}.", "email"),
        ("ana@example.com y x@demo.invalid", None),
        ("DNI 12345678Z", "documento de identidad"),
        ("NIE X1234567L", "documento de identidad"),
        ("IBAN ES00 0000 0000 0000 0000 0000", "IBAN"),
        ("Teléfono 600 000 000", "teléfono"),
        ("Importe de 700.000.000 €", None),
        ("Sin datos personales.", None),
    ],
)
def test_kind_is_reported_when_text_contains_each_type(text: str, expected: str | None) -> None:
    """PA-142 · RF-25: el tipo detectado (nunca el valor) para cada clase de dato."""
    assert personal_data_kind(text) == expected


def test_email_takes_precedence_when_text_has_several_kinds() -> None:
    """PA-142: el orden de los patrones se conserva (email antes que documento y teléfono)."""
    text = "DNI 12345678Z, teléfono 600 000 000 y " + REAL_SHAPED_EMAIL
    assert personal_data_kind(text) == "email" == _reference_kind(text)


# --- Límites de los tramos alrededor de cada `@` --------------------------------------------


def test_email_is_found_when_local_part_and_domain_fill_the_window() -> None:
    """PA-142 (límite): parte local de 64 caracteres y dominio largo (dentro de los 255)."""
    local = "n" * EMAIL_BEFORE
    domain = ".".join(["sub" + "d" * 56] * 4) + ".es"  # etiquetas de 59 + «.es», < 255
    assert len(domain) < EMAIL_AFTER
    text = "texto ficticio " * 50 + f"{local}@{domain}" + " fin" * 50
    assert personal_data_kind(text) == "email" == _reference_kind(text)


def test_email_is_found_when_local_part_is_longer_than_window() -> None:
    """PA-142 (límite): una parte local más larga que el tramo se recorta, pero el email
    se sigue detectando (el dominio es lo que decide)."""
    text = "n" * (EMAIL_BEFORE * 3) + "@correo-ficticio.es"
    assert personal_data_kind(text) == "email" == _reference_kind(text)


def test_fictitious_email_is_ignored_when_domain_ends_exactly_at_window() -> None:
    """PA-142 (límite): un dominio reservado que acaba justo en el borde del tramo."""
    domain = "d" * (EMAIL_AFTER - len(".example.com")) + ".example.com"
    assert len(domain) == EMAIL_AFTER
    text = "ana@" + domain + " resto del texto"
    assert personal_data_kind(text) is None is _reference_kind(text)


def test_emails_are_found_when_spans_overlap_with_several_at_signs() -> None:
    """PA-142: tramos solapados (varias `@` cercanas) se unen y no se pierde ningún email."""
    text = "ana@example.com, " * 5 + REAL_SHAPED_EMAIL + ", luis@example.org"
    assert personal_data_kind(text) == "email" == _reference_kind(text)
    only_fictitious = "ana@example.com " * 40
    assert personal_data_kind(only_fictitious) is None is _reference_kind(only_fictitious)


def test_emails_are_found_when_spans_are_separate() -> None:
    """PA-142: tramos separados (más de 64 + 255 caracteres entre `@`) se miran todos."""
    gap = " relleno ficticio" * 40
    text = "ana@example.com" + gap + "luis@example.org" + gap + REAL_SHAPED_EMAIL
    assert personal_data_kind(text) == "email" == _reference_kind(text)


def test_real_domain_is_detected_when_domain_is_longer_than_window() -> None:
    """PA-142 (límite): un dominio > EMAIL_AFTER no se recorta en «.example.com»."""
    text = "x@" + "a" * 243 + ".example.com.correo-ficticio.es"
    assert _reference_kind(text) == "email"
    assert personal_data_kind(text) == "email"


def test_fictitious_domain_is_ignored_when_domain_is_longer_than_window() -> None:
    """PA-142 (límite): dominio reservado > EMAIL_AFTER caracteres, sin falso positivo."""
    text = "x@" + "b." * 150 + "example.com"
    assert _reference_kind(text) is None
    assert personal_data_kind(text) is None


# --- Un solo detector ----------------------------------------------------------------------


def test_suite_validation_alias_is_the_common_detector() -> None:
    """PA-142: `core.qa.validation._personal_data_kind` es el detector común."""
    assert validation._personal_data_kind is personal_data_kind


def test_execution_uses_common_detector_without_own_copy() -> None:
    """PA-142: `core/graph/execution.py` usa `personal_data_kind` y no define su copia."""
    assert execution.personal_data_kind is personal_data_kind
    assert not hasattr(execution, "_personal_data_kind")
    assert not hasattr(execution, "_around_at")
    source = inspect.getsource(execution)
    assert "def _personal_data_kind" not in source
    assert "EMAIL.finditer" not in source


def test_evidence_is_rejected_when_it_contains_real_shaped_email() -> None:
    """PA-142: la evidencia de la ejecución rechaza un email con forma real (detector común)."""
    with pytest.raises(ExecutionRejectedError, match="dato personal \\(email\\)"):
        _reject_sensitive_evidence("DEMO-7", "Resultado ficticio enviado a " + REAL_SHAPED_EMAIL)


def test_evidence_check_is_fast_when_evidence_is_long_without_at() -> None:
    """PA-142: la evidencia más larga admitida sin `@` se comprueba rápido y se acepta."""
    evidence = "a." * (MAX_EVIDENCE_CHARS // 2)
    start = time.perf_counter()
    _reject_sensitive_evidence("DEMO-7", evidence)
    assert time.perf_counter() - start < TIME_LIMIT_S


@pytest.mark.parametrize(
    "text",
    [
        "x@" + "b" * 20_000,
        "x@" + "b." * 10_000,
        "a" * 64 + "@" + "b-" * 10_000,
        ("x@" + "b" * 2_000) * 10,
    ],
    ids=["dominio-sin-punto", "dominio-con-puntos", "dominio-con-guiones", "varios-dominios"],
)
def test_long_domain_runs_stay_linear(text: str) -> None:
    """PA-142: el tramo llega hasta el final del dominio sin volver a ser cuadrático."""
    _kind, elapsed = _timed(text)
    assert elapsed < TIME_LIMIT_S


def test_email_verdict_matches_reference_on_random_texts() -> None:
    """PA-142: el detector anclado en cada `@` decide lo mismo que `EMAIL.finditer` (5000
    textos aleatorios con semilla fija sobre un alfabeto que provoca bordes: `@`, `.`, `-`,
    `+`, espacios y trozos de dominios reservados)."""
    import random

    rng = random.Random(142)  # noqa: S311 (datos de prueba, no criptografía)
    pieces = ["a", "b", ".", "@", "-", "+", " ", "example", ".com", ".invalid", "es"]
    for _ in range(5000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 14)))
        expected = "email" if _reference_kind(text) == "email" else None
        got = "email" if personal_data_kind(text) == "email" else None
        assert got == expected, text
