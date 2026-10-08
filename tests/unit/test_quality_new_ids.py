"""PA-467 (ronda 18): CA y RN nuevos en el informe de calidad (RF-18 · RF-20 · PA-445).

Un ID que es uno de los siguientes libres de la HU (los `MAX_NEW_IDS` tras el último CA o RN)
es una propuesta, no un error, esté donde esté:
- en `target_id`, `with_proposed_targets` lo normaliza sin LLM (`target_id` vacío y propuesta
  «Nueva RN-06: …» / «Nuevo CA-07: …»), en el primer intento y en el reintento;
- en el texto libre (`summary`, `explanation`, `open_questions`, `proposal`) se admite.
Un ID lejano (CA-99) o que no es de los siguientes libres (RN-12) sigue siendo error →
reintento `quality_retry` → `QualityReviewError` si persiste.

La HU de estas pruebas tiene CA-01…CA-06 y RN-01…RN-05: los siguientes libres son CA-07…CA-11
y RN-06…RN-10. Solo fakes (sin red, sin `.env`, sin LLM ni Jira reales); datos ficticios.
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from structlog.testing import capture_logs

from adapters.base import Message
from core.container import Container
from core.quality import (
    MAX_NEW_IDS,
    QualityReview,
    QualityReviewError,
    evolve_feedback_of,
    report_errors,
    with_proposed_targets,
)
from core.rag.prompts import load_prompt
from schemas.quality import MAX_TEXT, QualityFinding, QualityReport
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.llm import FakeLLMProvider
from tests.unit.test_api_app import Api, _nothing_written
from tests.unit.test_cross_b_quality import (
    ScriptedLLM,
    _container,
    _finding,
    _llm,
    _review,
    _sources,
)
from tests.unit.test_quality import _origin_cited, _sequence

LOG_EVENT = "informe de calidad con IDs que no existen en la HU"
PROPOSAL = "Limitar las renovaciones a tres por año (ficticio)."


# --- utilidades --------------------------------------------------------------------------


def _story() -> UserStory:
    """HU ficticia con CA-01…CA-06 y RN-01…RN-05 (siguientes libres: CA-07… y RN-06…)."""
    base = dataset.renewal_story()
    criteria = [
        AcceptanceCriterion(
            id=f"CA-{n:02d}",
            title=f"Criterio ficticio {n}",
            given=["un préstamo activo ficticio"],
            when=["la persona socia pulsa «Renovar»"],
            then=[f"resultado ficticio {n}"],
        )
        for n in range(1, 7)
    ]
    rules = [
        BusinessRule(id=f"RN-{n:02d}", description=f"Regla ficticia {n}.") for n in range(1, 6)
    ]
    return base.model_copy(update={"acceptance_criteria": criteria, "business_rules": rules})


def _with_story(llm: FakeLLMProvider) -> None:
    """La estructuración devuelve `_story()` citando lo mismo que la HU por defecto del fake."""
    default = llm.builders[UserStory]

    def build(messages: list[Message]) -> BaseModel:
        cited = default(messages)
        assert isinstance(cited, UserStory)
        story = _story()
        return story.model_copy(update={"jira_key": cited.jira_key, "sources": cited.sources})

    llm.builders[UserStory] = build


def _scripted(tmp_path: Path, *reports: QualityReport) -> Container:
    container = _container(tmp_path)
    _with_story(_llm(container))
    _llm(container).builders[QualityReport] = _sequence(*reports)
    return container


def _report_with(**finding: Any) -> QualityReport:
    return _origin_cited(findings=[_finding(**finding)])


def _quality_calls(container: Container) -> list[dict[str, Any]]:
    return [c for c in _llm(container).calls if c["schema"] is QualityReport]


def _last_user_text(call: dict[str, Any]) -> str:
    return [m.content for m in call["messages"] if m.role == "user"][-1]


def _review_of(report: QualityReport) -> QualityReview:
    return QualityReview(
        jira_key="DEMO-3",
        report=report,
        story=_story(),
        provider="fake",
        model="fake-model",
        prompt_version="4",
        input_tokens=1,
        output_tokens=1,
    )


# --- with_proposed_targets: normalización sin LLM ----------------------------------------


@pytest.mark.parametrize(
    ("target", "label"),
    [
        ("RN-06", "Nueva RN-06"),
        ("RN-6", "Nueva RN-6"),
        ("RN-10", "Nueva RN-10"),
        ("CA-07", "Nuevo CA-07"),
        ("CA-11", "Nuevo CA-11"),
    ],
    ids=["rn-06", "rn-6-sin-cero", "rn-10-ultimo-libre", "ca-07", "ca-11-ultimo-libre"],
)
def test_with_proposed_targets_normalizes_next_free_id_to_proposal(target: str, label: str) -> None:
    """PA-467 (positiva y límite): un siguiente libre en `target_id` (con o sin cero, hasta el
    quinto) queda sin `target_id` y la propuesta empieza por «Nueva RN-06: » / «Nuevo CA-07: »."""
    report = _report_with(target_id=target, proposal=PROPOSAL)

    (finding,) = with_proposed_targets(report, _story()).findings

    assert finding.target_id is None
    assert finding.proposal == f"{label}: {PROPOSAL}"


def test_with_proposed_targets_does_not_duplicate_label() -> None:
    """PA-467 (límite): si la propuesta ya empieza por «Nueva RN-06», no se repite."""
    proposal = f"Nueva RN-06: {PROPOSAL}"
    report = _report_with(target_id="RN-06", proposal=proposal)

    (finding,) = with_proposed_targets(report, _story()).findings

    assert finding.target_id is None
    assert finding.proposal == proposal


def test_with_proposed_targets_truncates_to_max_text() -> None:
    """PA-467 (límite): con la etiqueta delante, la propuesta sigue acotada a `MAX_TEXT`."""
    long_proposal = "x" * MAX_TEXT
    report = _report_with(target_id="CA-07", proposal=long_proposal)

    (finding,) = with_proposed_targets(report, _story()).findings

    assert len(finding.proposal) == MAX_TEXT
    assert finding.proposal.startswith("Nuevo CA-07: x")
    QualityFinding.model_validate(finding.model_dump())  # sigue cumpliendo el esquema


@pytest.mark.parametrize("target", ["RN-01", "CA-06", "CA-99", "RN-12", "RN-11", None])
def test_with_proposed_targets_leaves_other_targets_untouched(target: str | None) -> None:
    """PA-467 (negativa): IDs existentes, lejanos (CA-99), fuera de los cinco libres (RN-11,
    RN-12) o sin `target_id` no se tocan; el informe se devuelve tal cual."""
    report = _report_with(target_id=target, proposal=PROPOSAL)

    normalized = with_proposed_targets(report, _story())

    assert normalized == report
    assert normalized.findings[0].target_id == target
    assert normalized.findings[0].proposal == PROPOSAL


def test_with_proposed_targets_only_changes_the_new_findings() -> None:
    """PA-467: en un informe mixto, solo cambian los hallazgos con un ID nuevo; el orden y el
    resto de campos se conservan."""
    report = _origin_cited(
        findings=[
            _finding(target_id="RN-02", proposal="Aclarar la RN-02 (ficticio)."),
            _finding(target_id="RN-06", proposal=PROPOSAL, explanation="Falta un límite."),
            _finding(target_id=None, proposal="Dividir la HU (ficticio)."),
        ]
    )

    normalized = with_proposed_targets(report, _story())

    assert [f.target_id for f in normalized.findings] == ["RN-02", None, None]
    assert [f.proposal for f in normalized.findings] == [
        "Aclarar la RN-02 (ficticio).",
        f"Nueva RN-06: {PROPOSAL}",
        "Dividir la HU (ficticio).",
    ]
    assert normalized.findings[1].explanation == "Falta un límite."
    assert normalized.summary == report.summary and normalized.invest == report.invest


def test_evolve_feedback_of_normalized_new_rule_adds_instead_of_changing() -> None:
    """PA-467 · RF-20: el feedback de «Evolucionar con esto» dice «Nueva RN-06: …» (añadir) y
    no «RN-06: …» (cambiar una regla existente)."""
    report = with_proposed_targets(_report_with(target_id="RN-06", proposal=PROPOSAL), _story())

    feedback = evolve_feedback_of(report)

    assert feedback == [f"Nueva RN-06: {PROPOSAL}"]
    assert not any(item.startswith("RN-06") for item in feedback)
    assert _review_of(report).evolve_feedback() == feedback


# --- report_errors: siguientes libres en cualquier campo; el resto, error ----------------


@pytest.mark.parametrize("target", ["RN-06", "RN-6", "RN-10", "CA-07", "CA-11"])
def test_report_errors_accepts_next_free_id_in_target(target: str) -> None:
    """PA-467 (positiva): un siguiente libre en `target_id` no es error."""
    assert report_errors(_report_with(target_id=target), _story(), _sources()) == []


@pytest.mark.parametrize("field_name", ["summary", "explanation", "open_questions", "proposal"])
def test_report_errors_accepts_next_free_id_in_free_text(field_name: str) -> None:
    """PA-467 (positiva): RN-06 en `summary`, `explanation`, `open_questions` o `proposal`."""
    text = "Falta RN-06 con el límite anual de renovaciones (ficticio)."
    report = _free_text_report(field_name, text)

    assert report_errors(report, _story(), _sources()) == []


def _free_text_report(field_name: str, text: str) -> QualityReport:
    if field_name == "summary":
        return _origin_cited(summary=text)
    if field_name == "open_questions":
        return _origin_cited(open_questions=[text])
    return _report_with(**{field_name: text})


@pytest.mark.parametrize("bad", ["CA-99", "RN-12", "RN-11", "CA-12", "RN-00"])
def test_report_errors_rejects_far_id_in_target(bad: str) -> None:
    """PA-467 (negativa y límite): CA-99, RN-11/CA-12 (sexto libre) y RN-12 en `target_id`."""
    errors = report_errors(_report_with(target_id=bad), _story(), _sources())

    assert errors == [f"«{bad}» no es un criterio ni una regla de la HU"]


@pytest.mark.parametrize("field_name", ["summary", "explanation", "open_questions", "proposal"])
@pytest.mark.parametrize("bad", ["CA-99", "RN-12"])
def test_report_errors_rejects_far_id_in_free_text(field_name: str, bad: str) -> None:
    """PA-467 (negativa): un ID lejano o que no es de los siguientes libres, en cualquier texto."""
    report = _free_text_report(field_name, f"Revisar {bad} (ficticio).")

    assert report_errors(report, _story(), _sources()) == [
        f"«{bad}» se cita en el informe pero no existe en la HU"
    ]


def test_next_free_window_is_max_new_ids() -> None:
    """PA-445 · PA-467 (límite): la ventana de libres es de `MAX_NEW_IDS` (5) por tipo."""
    story = _story()
    accepted = [f"RN-{n:02d}" for n in range(6, 6 + MAX_NEW_IDS)]
    rejected = f"RN-{6 + MAX_NEW_IDS:02d}"

    assert MAX_NEW_IDS == 5
    for target in accepted:
        assert report_errors(_report_with(target_id=target), story, _sources()) == []
    assert report_errors(_report_with(target_id=rejected), story, _sources()) != []


# --- Flujo QualityReviewer: primer intento, reintento y error ----------------------------


def test_review_new_rule_in_target_is_accepted_without_retry(tmp_path: Path) -> None:
    """PA-467: RN-06 en `target_id` (HU con RN-01…05) → aceptado a la primera, `target_id`
    vacío, propuesta «Nueva RN-06: …» y lo mismo en «Evolucionar con esto»."""
    container = _scripted(tmp_path, _report_with(target_id="RN-06", proposal=PROPOSAL))

    review = _review(container)

    assert len(_quality_calls(container)) == 1
    assert [r.id for r in review.story.business_rules][-1] == "RN-05"
    (finding,) = review.report.findings
    assert finding.target_id is None
    assert finding.proposal == f"Nueva RN-06: {PROPOSAL}"
    assert review.evolve_feedback() == [f"Nueva RN-06: {PROPOSAL}"]
    assert evolve_feedback_of(review.report) == review.evolve_feedback()


def test_review_new_criterion_in_target_is_accepted_without_retry(tmp_path: Path) -> None:
    """PA-467: CA-07 en `target_id` (HU con CA-01…06) → «Nuevo CA-07: …» sin reintento."""
    container = _scripted(tmp_path, _report_with(target_id="CA-07", proposal=PROPOSAL))

    review = _review(container)

    assert len(_quality_calls(container)) == 1
    assert review.report.findings[0].target_id is None
    assert review.evolve_feedback() == [f"Nuevo CA-07: {PROPOSAL}"]


@pytest.mark.parametrize("field_name", ["summary", "explanation", "open_questions"])
def test_review_new_rule_in_free_text_is_accepted_without_retry(
    tmp_path: Path, field_name: str
) -> None:
    """PA-467: RN-06 en `summary`, `explanation` u `open_questions` → aceptado sin reintento y
    el texto llega sin cambios."""
    text = "Falta RN-06 con el límite anual de renovaciones (ficticio)."
    container = _scripted(tmp_path, _free_text_report(field_name, text))

    review = _review(container)

    assert len(_quality_calls(container)) == 1
    report = review.report
    found = {
        "summary": report.summary,
        "explanation": report.findings[0].explanation if report.findings else "",
        "open_questions": " ".join(report.open_questions),
    }[field_name]
    assert found == text


@pytest.mark.parametrize("where", ["target_id", "explanation"])
def test_review_far_id_persisting_raises_and_logs_the_ids(tmp_path: Path, where: str) -> None:
    """PA-467 (error): CA-99 en `target_id` o en el texto → reintento con `quality_retry` y, si
    persiste, `QualityReviewError` con el log de los IDs rechazados (solo IDs)."""
    bad = (
        _report_with(target_id="CA-99")
        if where == "target_id"
        else _report_with(explanation="Revisar CA-99 (ficticio).")
    )
    expected = (
        "«CA-99» no es un criterio ni una regla de la HU"
        if where == "target_id"
        else "«CA-99» se cita en el informe pero no existe en la HU"
    )
    container = _scripted(tmp_path, bad)

    with capture_logs() as logs, pytest.raises(QualityReviewError) as excinfo:
        _review(container)

    assert len(_quality_calls(container)) == 2  # revisión + reintento
    assert expected in _last_user_text(_quality_calls(container)[1])
    assert "no existen en la HU" in str(excinfo.value)
    warnings = [e for e in logs if e.get("event") == LOG_EVENT]
    assert len(warnings) == 1
    assert warnings[0]["errors"] == [expected]


def test_review_not_next_free_rule_persisting_raises(tmp_path: Path) -> None:
    """PA-467 (negativa): RN-12 (con RN-01…05 no es de los siguientes libres) → error."""
    container = _scripted(tmp_path, _report_with(target_id="RN-12"))

    with capture_logs() as logs, pytest.raises(QualityReviewError):
        _review(container)

    (warning,) = [e for e in logs if e.get("event") == LOG_EVENT]
    assert warning["errors"] == ["«RN-12» no es un criterio ni una regla de la HU"]


def test_review_far_id_fixed_by_retry_is_accepted(tmp_path: Path) -> None:
    """PA-467: si el reintento corrige CA-99, el informe se acepta."""
    fixed = _report_with(target_id="RN-02", proposal="Aclarar la RN-02 (ficticio).")
    container = _scripted(tmp_path, _report_with(target_id="CA-99"), fixed)

    review = _review(container)

    assert len(_quality_calls(container)) == 2
    assert review.report.findings[0].target_id == "RN-02"
    assert review.evolve_feedback() == ["RN-02: Aclarar la RN-02 (ficticio)."]


def test_review_normalizes_new_target_in_the_retry(tmp_path: Path) -> None:
    """PA-467: la normalización también se aplica al informe del reintento (RN-06 → propuesta)."""
    retry = _report_with(target_id="RN-06", proposal=PROPOSAL)
    container = _scripted(tmp_path, _report_with(target_id="CA-99"), retry)

    review = _review(container)

    assert len(_quality_calls(container)) == 2
    (finding,) = review.report.findings
    assert finding.target_id is None
    assert review.evolve_feedback() == [f"Nueva RN-06: {PROPOSAL}"]


def test_review_retry_feedback_lists_only_the_far_id(tmp_path: Path) -> None:
    """PA-467: con RN-06 y CA-99 en `target_id`, el reintento solo señala CA-99 como error."""
    mixed = _origin_cited(findings=[_finding(target_id="RN-06"), _finding(target_id="CA-99")])
    container = _scripted(tmp_path, mixed, _report_with(target_id="RN-06"))

    _review(container)

    feedback = _last_user_text(_quality_calls(container)[1])
    assert "«CA-99» no es un criterio ni una regla de la HU" in feedback
    assert "«RN-06»" not in feedback


# --- API: POST /quality-reviews ------------------------------------------------------------


def _api_llm(*reports: QualityReport) -> FakeLLMProvider:
    llm = ScriptedLLM()
    _with_story(llm)
    llm.builders[QualityReport] = _sequence(*reports)
    return llm


def _post_review(tmp_path: Path, llm: FakeLLMProvider) -> tuple[Any, dict[str, Any]]:
    rt = fake_runtime(tmp_path, llm=llm)
    af = Api(rt)
    assert af.login().status_code == 200
    created = af.post("/quality-reviews", {"issue_key": "DEMO-3"})
    assert created.status_code == 202, created.text
    return rt, af.get(f"/quality-reviews/{created.json()['id']}").json()


def test_api_review_with_new_rule_target_is_done(tmp_path: Path) -> None:
    """PA-467 · API: un informe con RN-06 en `target_id` termina `done` (no `error`), con
    `target_id` null y la propuesta «Nueva RN-06: …» en el informe y en `evolve_feedback`."""
    llm = _api_llm(_report_with(target_id="RN-06", proposal=PROPOSAL))

    rt, detail = _post_review(tmp_path, llm)

    assert detail["state"] == "done", detail
    assert detail["error"] is None
    (finding,) = detail["report"]["findings"]
    assert finding["target_id"] is None
    assert finding["proposal"] == f"Nueva RN-06: {PROPOSAL}"
    assert detail["evolve_feedback"] == [f"Nueva RN-06: {PROPOSAL}"]
    assert len([c for c in llm.calls if c["schema"] is QualityReport]) == 1
    _nothing_written(rt)


def test_api_review_with_far_id_persisting_is_error(tmp_path: Path) -> None:
    """PA-467 · API (negativa): CA-99 que persiste tras el reintento → `error` con
    `quality_failed` y el mensaje en español; nada se escribe en Jira."""
    rt, detail = _post_review(tmp_path, _api_llm(_report_with(target_id="CA-99")))

    assert detail["state"] == "error"
    assert detail["report"] is None
    assert detail["error"]["code"] == "quality_failed"
    assert "no existen en la HU" in detail["error"]["message"]
    _nothing_written(rt)


# --- Prompts en la versión 4 ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["review_quality", "quality_retry"])
def test_prompts_are_version_4(name: str) -> None:
    """PA-467: `review_quality` y `quality_retry` pasan a la versión 4."""
    assert load_prompt(name).version == "4"


def test_review_quality_prompt_explains_new_ids_criterion() -> None:
    """PA-467: el prompt explica que los nuevos van a continuación del último (también en
    `target_id`), como mucho cinco, y que nunca se usan otros números (CA-99)."""
    text = load_prompt("review_quality").text

    assert "a continuación del último" in text
    assert "como mucho cinco" in text
    assert "`target_id`" in text and "en cualquier texto" in text
    assert "Nunca uses otros números" in text
    assert "CA-99" in text


def test_quality_retry_prompt_explains_new_ids_criterion() -> None:
    """PA-467: el reintento admite en cualquier campo (incluido `target_id`) los IDs de la
    lista o los siguientes libres, y prohíbe cualquier otro número."""
    text = load_prompt("quality_retry").text

    assert "En cualquier campo" in text
    for field_name in ("`target_id`", "`summary`", "`explanation`", "`proposal`"):
        assert field_name in text
    assert "a continuación del último" in text
    assert "como mucho cinco" in text
    assert "No uses ningún otro número" in text
    assert "Los únicos criterios y reglas de la HU que puedes señalar en `target_id`" not in text


def test_quality_retry_prompt_keeps_placeholders() -> None:
    """PA-467 (regresión): la versión 4 conserva los marcadores que rellena el reintento."""
    text = load_prompt("quality_retry").text

    for placeholder in ("{errors}", "{ids}", "{allowed}"):
        assert placeholder in text


@pytest.mark.parametrize(
    ("target", "proposal"),
    [
        ("RN-6", "Nueva RN-06: algo ficticio"),
        ("RN-06", "nueva RN-06: algo ficticio"),
        ("RN-06", "Nueva regla RN-06: algo ficticio"),
        ("CA-07", "Nuevo criterio CA-7: algo ficticio"),
    ],
)
def test_with_proposed_targets_keeps_label_variants(target: str, proposal: str) -> None:
    """PA-467 (test-writer): si la propuesta ya dice que es nuevo, en cualquier variante, no se
    antepone otra etiqueta."""
    report = _report_with(target_id=target, proposal=proposal)
    normalized = with_proposed_targets(report, _story()).findings[0]
    assert normalized.target_id is None
    assert normalized.proposal == proposal
