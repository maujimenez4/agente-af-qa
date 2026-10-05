"""Prueba cruzada T-34 (RNF-19): el área A prueba `core.memory.generator` del área B.

Cubre RF-36 y RNF-25 en el generador, y los bordes que `test_memory_generator.py` no fija:
falsos positivos de secretos, objetivo o alcance vacíos, CP inventados en una suite, formato
de los IDs, errores del proveedor en el reintento, topes, referencias y estado del artefacto.
Todo contra `FakeLLMProvider`; datos 100 % ficticios (biblioteca de Villaficticia).
"""

from typing import Any
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from adapters.base import Message
from adapters.errors import ExternalServiceError, RateLimitError
from core.memory.generator import (
    LLMMemoryGenerator,
    MemorySynthesisError,
    artifact_facts,
    memory_errors,
    sanitize,
)
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, Priority, SourceRef
from schemas.memory import Memory
from schemas.test_case import TestSuite
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory
from tests.fakes import dataset
from tests.fakes.llm import FakeLLMProvider, renewal_test_suite

SOURCES = [SourceRef(kind="rag", ref="doc-reglamento"), SourceRef(kind="jira", ref="DEMO-2")]


# --- utilidades --------------------------------------------------------------------------


def _story(**update: Any) -> UserStory:
    return dataset.renewal_story().model_copy(update={"sources": SOURCES, **update})


def _artifact(
    content: UserStory | TestSuite | None = None,
    *,
    status: ArtifactStatus = ArtifactStatus.PUBLISHED,
    origin_key: str | None = "DEMO-3",
) -> Artifact:
    content = content if content is not None else _story()
    kind = ArtifactType.TEST_SUITE if isinstance(content, TestSuite) else ArtifactType.USER_STORY
    return Artifact(
        id=uuid4(),
        type=kind,
        status=status,
        version=1,
        origin_key=origin_key,
        content=content,
        created_by="af-ficticio",
    )


def _memory(**update: Any) -> Memory:
    """Memoria válida para `_story()`; `update` la modifica a propósito."""
    base = Memory(
        artifact_type=ArtifactType.USER_STORY,
        jira_key="DEMO-3",
        version=1,
        objective="Reducir las visitas al mostrador por renovaciones.",
        scope="Incluye la renovación web; excluye materiales audiovisuales.",
        business_rules=[
            "RN-01: Máximo 2 renovaciones por préstamo.",
            "RN-02: No se renueva si hay reservas pendientes.",
        ],
        decisions=["La persona socia ha iniciado sesión."],
        dependencies=["DEMO-2"],
        changes=[],
        acceptance_criteria=[
            "CA-01: Renovación permitida amplía 21 días.",
            "CA-02: Renovación rechazada si hay reservas.",
        ],
        references=["doc-reglamento"],
    )
    return base.model_copy(update=update)


def _llm(*answers: Memory | Exception) -> FakeLLMProvider:
    """LLM falso con respuestas en orden (la última se repite); una excepción se lanza."""
    count = {"n": 0}

    def builder(_messages: list[Message]) -> Memory:
        answer = answers[min(count["n"], len(answers) - 1)]
        count["n"] += 1
        if isinstance(answer, Exception):
            raise answer
        return answer

    llm = FakeLLMProvider()
    llm.builders[Memory] = builder
    return llm


def _errors(memory: Memory, artifact: Artifact | None = None) -> list[str]:
    artifact = artifact or _artifact()
    facts = artifact_facts(artifact)
    return memory_errors(sanitize(memory, artifact, facts), facts)


def _password_story() -> UserStory:
    """HU ficticia de política de contraseñas: texto de negocio, sin ningún secreto."""
    return UserStory(
        jira_key="DEMO-8",
        title="Política de contraseñas del portal ficticio",
        role="persona socia",
        action="crear una contraseña conforme a la política",
        benefit="proteger su cuenta",
        description="La contraseña: mínimo ocho caracteres y un dígito.",
        business_goal="Reducir las cuentas con contraseñas débiles.",
        scope_includes=["Alta y cambio de contraseña"],
        scope_excludes=["Recuperación por SMS"],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="CA-01",
                title="Contraseña corta rechazada",
                given=["el formulario de alta"],
                when=["se introduce una contraseña de siete caracteres"],
                then=["se muestra el aviso de longitud mínima"],
            )
        ],
        business_rules=[
            BusinessRule(id="RN-01", description="La contraseña: mínimo ocho caracteres."),
        ],
        assumptions=[],
        constraints=[],
        dependencies=[],
        alternate_flows=[],
        exceptions=[],
        related_features=[],
        priority=Priority.MUST,
    )


def _password_memory(rule: str) -> Memory:
    return Memory(
        artifact_type=ArtifactType.USER_STORY,
        jira_key="DEMO-8",
        version=1,
        objective="Reducir las cuentas con contraseñas débiles.",
        scope="Alta y cambio de contraseña.",
        business_rules=[rule],
        decisions=[],
        dependencies=[],
        changes=[],
        acceptance_criteria=["CA-01: Contraseña corta rechazada."],
        references=[],
    )


# --- 1 · falsos positivos de secretos (Principio 2 frente a RF-36) -------------------------

POLICY_TEXTS = [
    pytest.param("RN-01: La contraseña: mínimo ocho caracteres.", id="contrasena-minimo"),
    pytest.param("RN-01: Clave: identificador del cliente ficticio.", id="clave-identificador"),
    pytest.param("RN-01: password = obligatoria en el alta.", id="password-obligatoria"),
]


@pytest.mark.parametrize("rule", POLICY_TEXTS)
def test_policy_text_is_not_a_secret_when_value_is_prose(rule: str) -> None:
    """RF-36 · Principio 2: una regla de política de contraseñas no es un secreto."""
    artifact = _artifact(_password_story(), origin_key="DEMO-8")

    assert _errors(_password_memory(rule), artifact) == []


def test_generate_succeeds_when_story_is_about_password_policy() -> None:
    """RF-36: la memoria de una HU de contraseñas se genera a la primera, sin reintento."""
    llm = _llm(_password_memory("RN-01: La contraseña: mínimo ocho caracteres."))

    memory = LLMMemoryGenerator(llm).generate(_artifact(_password_story(), origin_key="DEMO-8"))

    assert memory.business_rules == ["RN-01: La contraseña: mínimo ocho caracteres."]
    assert len(llm.calls) == 1


def test_short_policy_value_is_not_a_secret_when_under_six_chars() -> None:
    """Principio 2 (límite, comportamiento fijado): «contraseña: corta» (5) no salta."""
    artifact = _artifact(_password_story(), origin_key="DEMO-8")

    assert _errors(_password_memory("RN-01: La contraseña: corta"), artifact) == []


def test_real_looking_secret_is_still_rejected_when_policy_story() -> None:
    """Principio 2 (negativo): en la misma HU, un valor tipo secreto sí se rechaza."""
    artifact = _artifact(_password_story(), origin_key="DEMO-8")

    errors = _errors(_password_memory("RN-01: password: dummy-password-123"), artifact)

    assert errors == ["«business_rules» parece contener un secreto"]


# --- 2 · objetivo y alcance vacíos (RF-36) --------------------------------------------------

EMPTY_VALUES = [
    pytest.param("", id="vacio"),
    pytest.param("   \n\t", id="espacios"),
    pytest.param("---", id="regla"),
    pytest.param("## ", id="encabezado-vacio"),
]


@pytest.mark.parametrize("value", EMPTY_VALUES)
def test_empty_objective_is_an_error_when_sanitized_to_nothing(value: str) -> None:
    """RF-36 (negativo): la memoria debe recoger el objetivo; vacío → error y reintento."""
    assert _errors(_memory(objective=value))


@pytest.mark.parametrize("value", EMPTY_VALUES)
def test_empty_scope_is_an_error_when_sanitized_to_nothing(value: str) -> None:
    """RF-36 (negativo): la memoria debe recoger el alcance; vacío → error y reintento."""
    assert _errors(_memory(scope=value))


def test_empty_objective_is_retried_and_then_rejected() -> None:
    """RF-36 · PA-219 (corregido): «---» o vacío pide reintento y, si sigue vacío, es un error."""
    llm = _llm(_memory(objective="---", scope=""))

    with pytest.raises(MemorySynthesisError):
        LLMMemoryGenerator(llm).generate(_artifact())

    assert len(llm.calls) == 2


# --- 3 · CP inventados en una suite (Principio 4, RNF-25) ----------------------------------


def _suite_memory(**update: Any) -> Memory:
    return _memory(
        **(
            {
                "objective": "Artefactos de QA de la renovación (ficticio).",
                "artifact_type": ArtifactType.TEST_SUITE,
                "references": [],
            }
            | update
        )
    )


def test_invented_case_id_triggers_retry_when_suite_memory() -> None:
    """Principio 4 · RNF-25 (negativo): un CP que no está en la suite provoca reintento."""
    bad = _suite_memory(decisions=["CP-99 cubre la renovación por correo (inventado)."])
    llm = _llm(bad, _suite_memory())

    LLMMemoryGenerator(llm).generate(_artifact(renewal_test_suite()))

    assert len(llm.calls) == 2
    assert "CP-99" in llm.calls[1]["messages"][-1].content


def test_existing_case_id_is_accepted_when_suite_memory() -> None:
    """RNF-25 (positivo): citar un CP real de la suite (CP-01) no provoca reintento."""
    llm = _llm(_suite_memory(decisions=["CP-01 cubre la renovación sin reservas."]))

    memory = LLMMemoryGenerator(llm).generate(_artifact(renewal_test_suite()))

    assert memory.decisions == ["CP-01 cubre la renovación sin reservas."]
    assert len(llm.calls) == 1


def test_suite_facts_include_case_ids() -> None:
    """RNF-25 · PA-219: los hechos de una suite traen sus CA, sus RN y también sus CP."""
    suite = renewal_test_suite()
    facts = artifact_facts(_artifact(suite))

    assert facts.cases == tuple(c.internal_id for c in suite.cases)
    assert facts.ids == ("CA-01", "CA-02", "RN-01", "RN-02", *facts.cases)


# --- 4 · formato de los IDs -----------------------------------------------------------------


def test_unpadded_id_counts_as_unknown_and_missing() -> None:
    """Principio 4 (comportamiento fijado): «CA-1» no equivale a «CA-01»; se pide corregir."""
    errors = _errors(
        _memory(acceptance_criteria=["CA-1: Renovación permitida.", "CA-02: Rechazada."])
    )

    assert "IDs que no existen en el artefacto: CA-1" in errors
    assert "faltan criterios de aceptación: CA-01" in errors


def test_lowercase_id_does_not_count_as_present() -> None:
    """Principio 4 (comportamiento fijado): «ca-01» no se reconoce como el CA-01."""
    errors = _errors(
        _memory(acceptance_criteria=["ca-01: Renovación permitida.", "CA-02: Rechazada."])
    )

    assert errors == ["faltan criterios de aceptación: CA-01"]


def test_lowercase_invented_id_is_not_detected() -> None:
    """Principio 4 (comportamiento fijado, riesgo): un «rn-99» inventado no se detecta."""
    assert _errors(_memory(decisions=["Se aplica rn-99 del reglamento (inventada)."])) == []


def test_unpadded_id_in_both_answers_raises() -> None:
    """RF-36 (error): si el LLM insiste en «CA-1», MemorySynthesisError tras un reintento."""
    bad = _memory(acceptance_criteria=["CA-1: Renovación permitida.", "CA-2: Rechazada."])
    llm = _llm(bad, bad)

    with pytest.raises(MemorySynthesisError, match="DEMO-3"):
        LLMMemoryGenerator(llm).generate(_artifact())

    assert len(llm.calls) == 2


def test_longer_number_is_unknown_when_prefix_matches() -> None:
    """Principio 4 (límite): «CA-010» no es «CA-01» ni se acepta por prefijo."""
    errors = _errors(_memory(decisions=["CA-010 queda fuera (inventado)."]))

    assert errors == ["IDs que no existen en el artefacto: CA-010"]


def test_several_ids_on_one_line_count_as_present() -> None:
    """RF-36 (límite, comportamiento fijado): una sola línea con CA-01 y CA-02 basta."""
    assert _errors(_memory(acceptance_criteria=["CA-01 y CA-02: renovación (ficticio)."])) == []


def test_rule_mention_is_unknown_when_story_has_no_rules() -> None:
    """RF-36 (negativo): sin RN en la HU, citar RN-01 es un ID inexistente."""
    artifact = _artifact(_story(business_rules=[]))

    errors = _errors(_memory(business_rules=["RN-01: Máximo 2 renovaciones."]), artifact)

    assert errors == ["IDs que no existen en el artefacto: RN-01"]


def test_empty_rules_are_valid_when_story_has_no_rules() -> None:
    """RF-36 (límite): sin RN en la HU, una sección de reglas vacía es válida."""
    artifact = _artifact(_story(business_rules=[]))

    assert _errors(_memory(business_rules=[]), artifact) == []


# --- 5 · errores del proveedor en el reintento ---------------------------------------------


def test_external_error_on_retry_propagates_without_result() -> None:
    """RF-36 (error): un ExternalServiceError en el reintento se propaga tal cual, sin log OK."""
    bad = _memory(acceptance_criteria=["CA-01: Solo uno."])
    failure = ExternalServiceError("Proveedor ficticio caído.", service="fake")
    llm = _llm(bad, failure)

    with capture_logs() as logs, pytest.raises(ExternalServiceError) as info:
        LLMMemoryGenerator(llm).generate(_artifact())

    assert info.value is failure
    assert not isinstance(info.value, MemorySynthesisError)
    assert len(llm.calls) == 2
    assert not [e for e in logs if e.get("event") == "memoria sintetizada"]


def test_rate_limit_on_retry_keeps_retry_after() -> None:
    """D-14 (error): un 429 en el reintento conserva retry_after para la cadena de proveedores."""
    bad = _memory(business_rules=["RN-01: Solo una."])
    llm = _llm(bad, RateLimitError("Límite ficticio.", service="fake", retry_after=3.0))

    with pytest.raises(RateLimitError) as info:
        LLMMemoryGenerator(llm).generate(_artifact())

    assert info.value.retry_after == 3.0


def test_external_error_on_first_call_does_not_retry() -> None:
    """RF-36 (error): un fallo del proveedor en la primera llamada no provoca reintento."""
    llm = _llm(ExternalServiceError("Proveedor ficticio caído.", service="fake"))

    with pytest.raises(ExternalServiceError):
        LLMMemoryGenerator(llm).generate(_artifact())

    assert len(llm.calls) == 1


def test_generate_is_repeatable_after_provider_failure() -> None:
    """RF-36: el generador no guarda estado; tras un fallo, la siguiente llamada funciona."""
    llm = _llm(ExternalServiceError("Caída ficticia.", service="fake"), _memory())
    generator = LLMMemoryGenerator(llm)

    with pytest.raises(ExternalServiceError):
        generator.generate(_artifact())
    memory = generator.generate(_artifact())

    assert memory.jira_key == "DEMO-3"
    assert len(llm.calls) == 2


# --- 6 · sin topes de longitud ni de entradas ----------------------------------------------


def test_long_objective_is_accepted_without_cap() -> None:
    """RF-36 (límite, comportamiento fijado): no hay tope de longitud en el objetivo."""
    long_text = "Objetivo ficticio " * 2_000

    memory = LLMMemoryGenerator(_llm(_memory(objective=long_text))).generate(_artifact())

    assert len(memory.objective) == len(long_text.strip())


def test_many_entries_are_accepted_without_cap() -> None:
    """RF-36 (límite, comportamiento fijado): no hay tope de número de entradas."""
    decisions = [f"Decisión ficticia número {i}." for i in range(500)]

    memory = LLMMemoryGenerator(_llm(_memory(decisions=decisions))).generate(_artifact())

    assert len(memory.decisions) == 500


# --- 7 · referencias -----------------------------------------------------------------------


def test_jira_reference_outside_sources_is_dropped() -> None:
    """RF-36 · RNF-14 (negativo): «jira:OTRO-1» no citado por la HU se descarta sin reintento."""
    llm = _llm(_memory(references=["jira:OTRO-1", "OTRO-1", "jira:DEMO-99"]))

    memory = LLMMemoryGenerator(llm).generate(_artifact())

    assert memory.references == []
    assert len(llm.calls) == 1


def test_duplicated_reference_with_and_without_prefix_is_kept_once() -> None:
    """RF-36: «DEMO-2», «jira:DEMO-2» y «jira: DEMO-2» quedan en una sola referencia."""
    llm = _llm(_memory(references=["DEMO-2", "jira:DEMO-2", "jira: DEMO-2", "doc-reglamento"]))

    memory = LLMMemoryGenerator(llm).generate(_artifact())

    assert memory.references == ["DEMO-2", "doc-reglamento"]


def test_uppercase_prefix_is_not_normalized() -> None:
    """RF-36 (comportamiento fijado): «JIRA:DEMO-2» no se normaliza y se descarta."""
    memory = LLMMemoryGenerator(_llm(_memory(references=["JIRA:DEMO-2"]))).generate(_artifact())

    assert memory.references == []


def test_prefix_kind_is_not_checked_against_source_kind() -> None:
    """RF-36 (comportamiento fijado): «rag:DEMO-2» se acepta aunque DEMO-2 sea de Jira."""
    memory = LLMMemoryGenerator(_llm(_memory(references=["rag:DEMO-2"]))).generate(_artifact())

    assert memory.references == ["DEMO-2"]


def test_unknown_prefix_is_not_stripped() -> None:
    """RF-36 (negativo): un prefijo ajeno («http:») no se quita; la referencia se descarta."""
    memory = LLMMemoryGenerator(_llm(_memory(references=["http:doc-reglamento"]))).generate(
        _artifact()
    )

    assert memory.references == []


# --- 8 · estado del artefacto (contrato) ---------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [ArtifactStatus.DRAFT, ArtifactStatus.IN_REVIEW, ArtifactStatus.DISCARDED],
)
def test_generator_does_not_check_status(status: ArtifactStatus) -> None:
    """RF-36 (comportamiento fijado): el generador no mira el estado; lo exige `memorize`."""
    llm = _llm(_memory())

    memory = LLMMemoryGenerator(llm).generate(_artifact(status=status))

    assert memory.jira_key == "DEMO-3"
    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    "rule",
    [
        "RN-01: contraseña: Sup3rClaveFicticia",
        "RN-01: clave=valor_ficticio",
        "RN-01: secret: a1b2c3d4",
        "RN-01: contraseña: CorrectoCaballoBateria",  # frase de paso solo de letras
        "RN-01: password: Ficticiopassword",  # 16 letras
        "RN-01: api_key: abcdefghijklmnopqrstuvwxyzABCDEF",
    ],
)
def test_value_with_digits_or_symbols_is_still_a_secret(rule: str) -> None:
    """PA-218 (negativo): un valor que parece un secreto (dígitos, símbolos, mayúscula en medio
    o 16 letras o más) tras «contraseña:» sigue rechazándose."""
    artifact = _artifact(_password_story(), origin_key="DEMO-8")
    assert _errors(_password_memory(rule), artifact) == [
        "«business_rules» parece contener un secreto"
    ]


def test_policy_word_followed_by_period_is_not_a_secret() -> None:
    """PA-218 (límite): una palabra con punto final («obligatoria.») no es un secreto."""
    artifact = _artifact(_password_story(), origin_key="DEMO-8")
    assert _errors(_password_memory("RN-01: La contraseña: obligatoria."), artifact) == []


# --- PA-226: palabras clave y formatos de secreto que faltaban -------------------------------

# Los tokens se componen por partes para que el escáner de secretos de CI no los tome por reales.
_FAKE_SECRETS = [
    "token: " + "ghF1ct1c10" + "Tok3n",
    "pwd: Cl4veFicticia",
    "pass=Sup3rSecreta!",
    "PIN: 4821",
    "secreto: Fict1cio_99",
    "credencial: abc123xyz",
    "client_secret: s3cr3t-f1ct1c10",
    "Authorization: " + "Basic " + "dXN1YXJpbzpmaWN0aWNpbw==",
    "AI" + "za" + "SyFICTICIO0123456789abcdefghijklm",
    "gl" + "pat-" + "FICTICIO1234567890abcd",
    "github" + "_pat_" + "11FICTICIO0123456789abcdef",
    "-----BEGIN RSA " + "PRIVATE KEY-----",
    "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----",
    "PIN 4821",  # sin separador
    "PIN: 123456789",
    "gh" + "s_" + "FICTICIO0123456789abcd",
    "xo" + "xs-" + "1234567890-ficticio",
    # Frases de paso con guiones tras una palabra de credencial fuerte (security-reviewer).
    "password: correcto-caballo-bateria",
    "contraseña: Caballo-Correcto-Grapa",
    "secret: abcdef-ghijkl",
    "api_key: kjhqwe-poiuyt-zxcvbn",
    "password: ABCDEF-GHIJKL",
]


@pytest.mark.parametrize("secret", _FAKE_SECRETS)
def test_more_secret_formats_are_rejected(secret: str) -> None:
    """PA-226: el detector reconoce más palabras clave y formatos de credencial."""
    artifact = _artifact(_password_story(), origin_key="DEMO-8")
    assert _errors(_password_memory(f"RN-01: {secret}"), artifact) == [
        "«business_rules» parece contener un secreto"
    ]


@pytest.mark.parametrize(
    "rule",
    [
        "RN-01: El token: caduca a los 30 minutos.",
        "RN-01: PIN: 4 dígitos numéricos.",
        "RN-01: El pase: válido un año.",
        "RN-01: Plan basic con soporte ficticio.",
        "RN-01: bypass: obligatorio en la revisión.",
        "RN-01: Clave: identificador-del-carné.",  # palabra ambigua: el guion no cuenta
        "RN-01: El token: identificador-del-carné se muestra en la web.",
    ],
)
def test_business_text_with_new_keywords_is_not_a_secret(rule: str) -> None:
    """PA-226 (falsos positivos): las palabras nuevas con texto de negocio no saltan."""
    artifact = _artifact(_password_story(), origin_key="DEMO-8")
    assert _errors(_password_memory(rule), artifact) == []


@pytest.mark.parametrize(
    "adversarial",
    ["token:" * 10_000, "password:" * 10_000, "secret: " + "a" * 60_000, "-----BEGIN " * 5_000],
    ids=["token-repetido", "password-repetido", "valor-enorme", "begin-repetido"],
)
def test_secret_detector_is_linear_on_adversarial_input(adversarial: str) -> None:
    """PA-226 (ReDoS): lookahead y valor acotados; antes, «token:»×10 000 tardaba unos 25 s."""
    import time

    from core.memory.generator import _SECRET

    started = time.perf_counter()
    _SECRET.search(adversarial)
    assert time.perf_counter() - started < 1.0
