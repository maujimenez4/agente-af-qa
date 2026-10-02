"""Prueba cruzada T-34 (RNF-19): el área A prueba `core/quality.py` (T-48 · RF-18, SPEC-00 §11).

Completa `tests/unit/test_quality.py` sin repetir sus casos: tipo de la incidencia revisada, IDs
inventados fuera de `target_id`, tokens y modelo con reintento, errores externos en cada llamada,
validación de `excluded_sources` antes de leer Jira y `evolve_feedback` sin `target_id`.
Los defectos confirmados van con `xfail(strict=True)`. Datos 100 % sintéticos; sin LLM ni red.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from adapters.base import IssueDetail, Message, StructuredResult, TaskType
from adapters.errors import AgentError, ExternalServiceError, RateLimitError
from core.container import Container
from core.functional.context import StoryContext
from core.quality import QualityReview, QualityReviewer, QualityReviewError, report_errors
from schemas.quality import QualityFinding, QualityReport
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider, renewal_quality_report
from tests.unit.test_quality import (
    AF,
    INVENTED_ID,
    KEY,
    SpyIssueTracker,
    _origin_cited,
    _sequence,
    _with_bad_id,
)

PROVIDERS = ("prov-estructura", "prov-revision", "prov-reintento")


# --- utilidades --------------------------------------------------------------------------


@dataclass
class ScriptedLLM(FakeLLMProvider):
    """FakeLLMProvider que cambia de proveedor/modelo en cada llamada, guarda los resultados y
    puede fallar en la llamada `fail_on` (0 = estructurar, 1 = revisar, 2 = reintento)."""

    fail_on: int | None = None
    failure: Exception | None = None
    results: list[StructuredResult[Any]] = field(default_factory=list)

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        n = len(self.calls)
        self.provider = PROVIDERS[n] if n < len(PROVIDERS) else f"prov-{n}"
        self.model = f"modelo-{n}"
        if self.fail_on == n and self.failure is not None:
            self.calls.append({"task": task, "schema": schema, "messages": list(messages)})
            raise self.failure
        result = super().generate_structured(messages, schema, task)
        self.results.append(result)
        return result


def _container(tmp_path: Path, llm: FakeLLMProvider | None = None) -> Container:
    tracker = SpyIssueTracker()
    return fake_container(tmp_path / "memoria", issue_tracker=tracker, llm=llm or ScriptedLLM())


def _spy(container: Container) -> SpyIssueTracker:
    assert isinstance(container.issue_tracker, SpyIssueTracker)
    return container.issue_tracker


def _llm(container: Container) -> ScriptedLLM:
    assert isinstance(container.llm, ScriptedLLM)
    return container.llm


def _add_issue(container: Container, key: str, issue_type: str) -> None:
    _spy(container).issues[key] = IssueDetail(
        key=key,
        summary=f"Incidencia ficticia {key} para renovar un préstamo",
        issue_type=issue_type,
        status="Por hacer",
        description_text=f"Descripción ficticia de {key}.",
    )


def _review(container: Container, key: str = KEY, **kwargs: Any) -> QualityReview:
    return QualityReviewer(container).review(AF, key, **kwargs)


def _sources() -> list:
    return StoryContext(origin_kind="story", origin_key=KEY, jira=[dataset.STORIES[KEY]]).sources()


def _finding(**update: Any) -> QualityFinding:
    base = QualityFinding(
        kind="gap",
        target_id=None,
        explanation="Explicación ficticia sin referencias.",
        proposal="Propuesta ficticia sin referencias.",
    )
    return base.model_copy(update=update)


# --- QUALITY-1 · Tipo de la incidencia revisada ---------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-222): "
        "review() no comprueba issue_type; revisa épicas, subtareas y tareas como "
        "si fueran HU, mientras T-53 las excluye con NOT_STORIES (core/quality.py:82)"
    ),
)
@pytest.mark.parametrize(
    ("key", "issue_type"),
    [("DEMO-1", "Epic"), ("DEMO-40", "Subtarea"), ("DEMO-41", "Sub-task"), ("DEMO-42", "Task")],
    ids=["epica", "subtarea", "sub-task", "tarea"],
)
def test_review_rejects_non_story_issue_before_llm(
    tmp_path: Path, key: str, issue_type: str
) -> None:
    """RF-18 (negativa): solo se revisa la calidad de una HU; una épica, subtarea o tarea se
    rechaza con un error en español y sin llamar al LLM."""
    container = _container(tmp_path)
    if key != "DEMO-1":
        _add_issue(container, key, issue_type)

    with pytest.raises((ValueError, AgentError)):
        _review(container, key)
    assert _llm(container).calls == []


def test_review_bug_type_is_reviewed_as_story(tmp_path: Path) -> None:
    """RF-18 · comportamiento fijado: un «Bug» no está en NOT_STORIES y se revisa como una HU
    (dos llamadas al LLM e informe devuelto)."""
    container = _container(tmp_path)
    _add_issue(container, "DEMO-43", "Bug")

    review = _review(container, "DEMO-43")

    assert review.jira_key == "DEMO-43"
    assert len(_llm(container).calls) == 2


# --- QUALITY-2 · IDs inventados fuera de target_id -----------------------------------------------


def _report_mentioning_invented_id(field_name: str) -> QualityReport:
    text = f"Revisar {INVENTED_ID}: no se entiende el plazo (ficticio)."
    if field_name == "summary":
        return _origin_cited(summary=text)
    if field_name == "open_questions":
        return _origin_cited(open_questions=[f"¿Qué dice {INVENTED_ID}? (ficticio)"])
    return _origin_cited(findings=[_finding(**{field_name: text})])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-222): report_errors solo valida target_id; un ID inventado (CA-99) en "
        "explanation, proposal, summary u open_questions no se detecta (core/quality.py:171-173)"
    ),
)
@pytest.mark.parametrize("field_name", ["explanation", "proposal", "summary", "open_questions"])
def test_report_errors_flags_invented_id_in_free_text(field_name: str) -> None:
    """RF-18 (negativa): «hallazgos solo sobre IDs de la HU»; un CA/RN inexistente citado en
    el texto del informe también es un error que provoca el reintento."""
    report = _report_mentioning_invented_id(field_name)

    assert report_errors(report, dataset.renewal_story(), _sources()) != []


def test_report_errors_accepts_existing_id_in_free_text() -> None:
    """RF-18 (positiva): mencionar en el texto un CA que sí existe (CA-01) no es un error."""
    report = _origin_cited(findings=[_finding(proposal="Concretar el plazo de CA-01.")])

    assert report_errors(report, dataset.renewal_story(), _sources()) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-222): "
        "un ID inventado en proposal llega a evolve_feedback() y de ahí al grafo "
        "como feedback de la evolución (core/quality.py:58-64, 171-173)"
    ),
)
def test_evolve_feedback_never_carries_invented_id(tmp_path: Path) -> None:
    """RF-18 · RF-20 (negativa): el feedback de «Evolucionar con esto» no lleva IDs que no
    existen en la HU; o se corrige con el reintento o el flujo falla con QualityReviewError."""
    container = _container(tmp_path)
    invented = _origin_cited(findings=[_finding(proposal=f"Reescribir {INVENTED_ID} (ficticio).")])
    _llm(container).builders[QualityReport] = _sequence(invented)

    try:
        review = _review(container)
    except QualityReviewError:
        return
    assert all(INVENTED_ID not in item for item in review.evolve_feedback())


# --- QUALITY-3/4 · Tokens, proveedor y modelo con reintento --------------------------------------


def test_tokens_sum_structure_review_and_retry(tmp_path: Path) -> None:
    """RF-18 · trazabilidad: con reintento, los tokens suman estructurar + revisar + reintento."""
    container = _container(tmp_path)
    _llm(container).builders[QualityReport] = _sequence(_with_bad_id(), _origin_cited())

    review = _review(container)

    results = _llm(container).results
    assert len(results) == 3
    assert review.input_tokens == sum(r.input_tokens for r in results)
    assert review.output_tokens == sum(r.output_tokens for r in results)


def test_tokens_without_retry_sum_two_calls(tmp_path: Path) -> None:
    """RF-18 · trazabilidad (límite): sin reintento solo cuentan estructurar y revisar."""
    container = _container(tmp_path)

    review = _review(container)

    results = _llm(container).results
    assert len(results) == 2
    assert review.input_tokens == sum(r.input_tokens for r in results)
    assert review.output_tokens == sum(r.output_tokens for r in results)


def test_provider_and_model_come_from_retry(tmp_path: Path) -> None:
    """RF-18 · trazabilidad: proveedor y modelo son los de la llamada que dio el informe final
    (el reintento), no los de estructurar ni los de la primera revisión."""
    container = _container(tmp_path)
    _llm(container).builders[QualityReport] = _sequence(_with_bad_id(), _origin_cited())

    review = _review(container)

    assert (review.provider, review.model) == ("prov-reintento", "modelo-2")


def test_provider_and_model_come_from_review_without_retry(tmp_path: Path) -> None:
    """RF-18 · trazabilidad (límite): sin reintento, los de la revisión, no los de estructurar."""
    container = _container(tmp_path)

    review = _review(container)

    assert (review.provider, review.model) == ("prov-revision", "modelo-1")


# --- QUALITY-5/6 · Errores externos --------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        RateLimitError("Límite de uso ficticio alcanzado.", service="llm", retry_after=1),
        ExternalServiceError("Error ficticio del proveedor.", service="llm"),
    ],
    ids=["429", "5xx"],
)
def test_retry_external_error_propagates_without_writes(
    tmp_path: Path, failure: ExternalServiceError
) -> None:
    """RF-18 (error) · principio 1: un error externo en el reintento se propaga tal cual y no
    se escribe nada (Jira, auditoría, estado)."""
    container = _container(tmp_path)
    llm = _llm(container)
    llm.builders[QualityReport] = _sequence(_with_bad_id(), _origin_cited())
    llm.fail_on, llm.failure = 2, failure

    with pytest.raises(type(failure)) as error:
        _review(container)

    assert error.value is failure
    assert len(llm.calls) == 3
    assert _spy(container).writes == []
    assert container.audit.recorded == []  # type: ignore[attr-defined]
    assert container.state_store.states == {}  # type: ignore[attr-defined]


def test_structure_failure_skips_review_quality(tmp_path: Path) -> None:
    """RF-18 (error): si falla `structure`, no se llama a `review_quality` ni se escribe nada."""
    container = _container(tmp_path)
    llm = _llm(container)
    llm.fail_on = 0
    llm.failure = ExternalServiceError("Error ficticio al estructurar.", service="llm")

    with pytest.raises(ExternalServiceError):
        _review(container)

    assert [c["schema"] for c in llm.calls] == [UserStory]
    assert not any(c["schema"] is QualityReport for c in llm.calls)
    assert _spy(container).writes == []


def test_first_review_failure_has_no_retry(tmp_path: Path) -> None:
    """RF-18 (error): un error externo en la primera revisión no provoca el reintento."""
    container = _container(tmp_path)
    llm = _llm(container)
    llm.fail_on = 1
    llm.failure = RateLimitError("Límite ficticio.", service="llm")

    with pytest.raises(RateLimitError):
        _review(container)

    assert len(llm.calls) == 2


# --- QUALITY-7 · excluded_sources antes de leer Jira ---------------------------------------------


def test_excluded_sources_fifty_is_accepted(tmp_path: Path) -> None:
    """RF-18 · T-51 (límite): exactamente 50 referencias son válidas."""
    container = _container(tmp_path)

    review = _review(container, excluded_sources=[f"DOC-FICT-{n:03d}" for n in range(50)])

    assert review.jira_key == KEY


def test_excluded_sources_duplicates_count_once(tmp_path: Path) -> None:
    """RF-18 · T-51 (límite): 51 entradas con repetidas y espacios (50 distintas) son válidas."""
    container = _container(tmp_path)
    refs = [f"DOC-FICT-{n:03d}" for n in range(50)] + [" DOC-FICT-000 "]

    assert _review(container, excluded_sources=refs).jira_key == KEY


@pytest.mark.parametrize(
    "excluded",
    [
        [f"DOC-FICT-{n:03d}" for n in range(51)],
        ["texto libre con espacios"],
        ["DOC<script>"],
        ["x" * 101],
        [f" {KEY} "],
    ],
    ids=["51", "texto_libre", "caracteres", "demasiado_larga", "origen_con_espacios"],
)
def test_invalid_excluded_sources_fail_before_reading_jira(
    tmp_path: Path, excluded: list[str]
) -> None:
    """RF-18 · T-51 (negativa): ValueError antes de cualquier lectura de Jira o llamada al LLM."""
    container = _container(tmp_path)

    with pytest.raises(ValueError):
        _review(container, excluded_sources=excluded)

    assert _spy(container).reads == []
    assert _llm(container).calls == []


def test_excluded_origin_in_lowercase_is_validated_after_normalizing_key(tmp_path: Path) -> None:
    """RF-18 · comportamiento fijado: la clave se normaliza («demo-3» → DEMO-3) pero la
    exclusión no; excluir «demo-3» no cuenta como excluir el origen y no se rechaza."""
    container = _container(tmp_path)

    review = _review(container, "demo-3", excluded_sources=["demo-3"])

    assert review.jira_key == KEY


# --- QUALITY-8 · evolve_feedback sin target_id ---------------------------------------------------


def _review_with(report: QualityReport) -> QualityReview:
    return QualityReview(
        jira_key=KEY,
        report=report,
        story=dataset.renewal_story(),
        provider="fake",
        model="fake-model",
        prompt_version="1",
        input_tokens=1,
        output_tokens=1,
    )


def test_evolve_feedback_without_target_id_has_no_prefix() -> None:
    """RF-18 · RF-20: hallazgos sin `target_id` dan la propuesta sola, sin «: » delante y en
    el orden del informe."""
    findings = [
        _finding(proposal="Añadir un criterio de error (ficticio)."),
        _finding(kind="invest", proposal="Dividir la HU en dos (ficticio)."),
    ]
    report = renewal_quality_report().model_copy(update={"findings": findings})

    feedback = _review_with(report).evolve_feedback()

    assert feedback == [
        "Añadir un criterio de error (ficticio).",
        "Dividir la HU en dos (ficticio).",
    ]
    assert not any(item.startswith(":") or item.startswith("None") for item in feedback)


def test_evolve_feedback_ignores_explanation() -> None:
    """RF-18 · RF-20 · comportamiento fijado: solo viaja la propuesta, no la explicación."""
    report = renewal_quality_report().model_copy(
        update={"findings": [_finding(target_id="RN-01", explanation="Motivo ficticio X.")]}
    )

    assert _review_with(report).evolve_feedback() == ["RN-01: Propuesta ficticia sin referencias."]
