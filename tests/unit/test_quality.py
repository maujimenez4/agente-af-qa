"""Pruebas del flujo «Revisar la calidad de una HU» (T-48 · RF-18).

Cubren el esquema `QualityReport` (seis letras INVEST, `target_id`, `to_markdown`), los permisos,
el orden de las dos llamadas al LLM (estructurar y revisar), las fuentes excluidas, el reintento
por IDs o citas inventados, los extractos reales, el feedback para «Evolucionar con esto» y que
el flujo es de solo lectura: nada en Jira, ni auditoría, ni artefactos, ni conversaciones.
Todos los datos son sintéticos (`tests/fakes/dataset.py`).
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pydantic
import pytest
from pydantic import BaseModel, ValidationError
from structlog.testing import capture_logs

from adapters.base import IssueDetail, Message, TaskType, User
from adapters.errors import AgentError, AuthenticationError, NotFoundError
from core.container import Container
from core.functional.citations import CitationError
from core.functional.context import StoryContext
from core.graph import build_graph, initial_state
from core.quality import QualityReview, QualityReviewer, QualityReviewError, report_errors
from core.rag.prompts import load_prompt
from schemas.common import ArtifactStatus, SourceRef
from schemas.quality import INVEST_LETTERS, InvestCheck, QualityFinding, QualityReport, _md
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider, renewal_quality_report
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore

AF = dataset.DEMO_USERS["af-demo"][1]
QA = dataset.DEMO_USERS["qa-demo"][1]
ADMIN = dataset.DEMO_USERS["admin-demo"][1]
KEY = "DEMO-3"
INVENTED_ID = "CA-99"
INVENTED_REF = "DOC-INVENTADO-77"
SOURCE_TAG = re.compile(r'<fuente ref="([^"]+)"')


# --- utilidades --------------------------------------------------------------------------


class SpyIssueTracker(FakeIssueTracker):
    """FakeIssueTracker que además registra cada lectura (para comprobar que no se llama)."""

    def __init__(self) -> None:
        super().__init__()
        self.reads: list[tuple[str, Any]] = []

    def get_issue(self, key: str) -> IssueDetail:
        self.reads.append(("get_issue", key))
        return super().get_issue(key)

    def search(self, jql: str, limit: int = 50) -> list[Any]:
        self.reads.append(("search", jql))
        return super().search(jql, limit)

    def list_children(self, epic_key: str) -> list[Any]:
        self.reads.append(("list_children", epic_key))
        return super().list_children(epic_key)


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path / "memoria", issue_tracker=SpyIssueTracker())


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _tracker(container: Container) -> SpyIssueTracker:
    assert isinstance(container.issue_tracker, SpyIssueTracker)
    return container.issue_tracker


def _review(container: Container, key: str = KEY, **kwargs: Any) -> QualityReview:
    return QualityReviewer(container).review(AF, key, **kwargs)


def _checks(letters: tuple[str, ...] | list[str]) -> list[InvestCheck]:
    return [
        InvestCheck(letter=letter, verdict="ok", reason="Motivo ficticio.") for letter in letters
    ]  # type: ignore[arg-type]


def _report(**update: Any) -> QualityReport:
    return renewal_quality_report().model_copy(update=update)


def _origin_cited(**update: Any) -> QualityReport:
    """Informe válido para DEMO-3: cita la incidencia de origen, que siempre está en el contexto."""
    return _report(sources=[SourceRef(kind="jira", ref=KEY)], **update)


def _with_bad_id() -> QualityReport:
    bad = QualityFinding(
        kind="ambiguity",
        target_id=INVENTED_ID,
        explanation="Criterio ficticio inexistente.",
        proposal="Propuesta ficticia.",
    )
    return _origin_cited(findings=[bad])


def _with_bad_citation() -> QualityReport:
    return _report(sources=[SourceRef(kind="rag", ref=INVENTED_REF)])


def _sequence(*reports: QualityReport) -> Callable[[list[Message]], BaseModel]:
    """Builder que devuelve los informes en orden (el último se repite si hay más llamadas)."""
    pending = list(reports)

    def build(_messages: list[Message]) -> BaseModel:
        return pending.pop(0) if len(pending) > 1 else pending[0]

    return build


def _quality_calls(container: Container) -> list[dict[str, Any]]:
    return [c for c in _llm(container).calls if c["schema"] is QualityReport]


def _user_text(call: dict[str, Any]) -> str:
    return "\n".join(m.content for m in call["messages"] if m.role == "user")


def _first_user_text(call: dict[str, Any]) -> str:
    return next(m.content for m in call["messages"] if m.role == "user")


def _system_text(call: dict[str, Any]) -> str:
    return next(m.content for m in call["messages"] if m.role == "system")


# --- 1 · Esquema: seis letras INVEST ----------------------------------------------------------


def test_quality_report_accepts_six_distinct_invest_letters_in_any_order() -> None:
    """RF-18 · esquema: seis letras distintas, en cualquier orden, son válidas."""
    report = _report(invest=_checks(["T", "S", "E", "V", "N", "I"]))

    validated = QualityReport.model_validate(report.model_dump())

    assert sorted(c.letter for c in validated.invest) == sorted(INVEST_LETTERS)


def test_quality_report_rejects_missing_invest_letter() -> None:
    """RF-18 · esquema (negativa): faltan letras → ValidationError."""
    with pytest.raises(ValidationError):
        QualityReport(summary="Resumen ficticio.", invest=_checks(INVEST_LETTERS[:5]), findings=[])


def test_quality_report_rejects_repeated_invest_letter() -> None:
    """RF-18 · esquema (negativa): seis valoraciones con una letra repetida → ValidationError."""
    letters = ["I", "N", "V", "E", "S", "S"]
    with pytest.raises(ValidationError, match="INVEST"):
        QualityReport(summary="Resumen ficticio.", invest=_checks(letters), findings=[])


def test_quality_report_rejects_extra_invest_letter() -> None:
    """RF-18 · esquema (límite): siete valoraciones (una de más) → ValidationError."""
    letters = [*INVEST_LETTERS, "T"]
    with pytest.raises(ValidationError):
        QualityReport(summary="Resumen ficticio.", invest=_checks(letters), findings=[])


def test_quality_report_rejects_empty_invest() -> None:
    """RF-18 · esquema (límite): sin valoraciones → ValidationError."""
    with pytest.raises(ValidationError):
        QualityReport(summary="Resumen ficticio.", invest=[], findings=[])


@pytest.mark.parametrize("letter", ["X", "i", "", "IN"])
def test_invest_check_rejects_unknown_letter(letter: str) -> None:
    """RF-18 · esquema (negativa): solo las letras I, N, V, E, S y T."""
    with pytest.raises(ValidationError):
        InvestCheck(letter=letter, verdict="ok", reason="Motivo ficticio.")  # type: ignore[arg-type]


def test_invest_check_rejects_unknown_verdict_and_empty_reason() -> None:
    """RF-18 · esquema (negativa): veredicto ok/improvable y motivo no vacío."""
    with pytest.raises(ValidationError):
        InvestCheck(letter="I", verdict="bad", reason="Motivo ficticio.")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        InvestCheck(letter="I", verdict="ok", reason="")


def test_invest_in_order_returns_invest_order() -> None:
    """RF-18 · esquema: `invest_in_order` ordena I, N, V, E, S, T aunque lleguen desordenadas."""
    report = _report(invest=_checks(["S", "T", "I", "E", "N", "V"]))

    assert [c.letter for c in report.invest_in_order()] == list(INVEST_LETTERS)


# --- 2 · Esquema: target_id -----------------------------------------------------------------


@pytest.mark.parametrize("target", ["CA-02", "RN-01", "CA-1", "RN-100", None])
def test_quality_finding_accepts_valid_target_id(target: str | None) -> None:
    """RF-18 · esquema: `target_id` es CA-n, RN-n o nada."""
    finding = QualityFinding(
        kind="gap", target_id=target, explanation="Explicación ficticia.", proposal="Propuesta."
    )

    assert finding.target_id == target


@pytest.mark.parametrize(
    "target", ["ca-02", "CA02", "CP-01", "CA-", "CA-02 ", " RN-01", "XCA-02", "CA-0A", ""]
)
def test_quality_finding_rejects_invalid_target_id(target: str) -> None:
    """RF-18 · esquema (negativa): cualquier otro formato de `target_id` → ValidationError."""
    with pytest.raises(ValidationError):
        QualityFinding(
            kind="gap", target_id=target, explanation="Explicación ficticia.", proposal="Propuesta."
        )


def test_quality_finding_rejects_unknown_kind_and_empty_texts() -> None:
    """RF-18 · esquema (negativa): tipo conocido, explicación y propuesta no vacías."""
    with pytest.raises(ValidationError):
        QualityFinding(kind="otro", explanation="Ficticia.", proposal="Ficticia.")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        QualityFinding(kind="gap", explanation="", proposal="Ficticia.")
    with pytest.raises(ValidationError):
        QualityFinding(kind="gap", explanation="Ficticia.", proposal="")


# --- 3 · Esquema: to_markdown --------------------------------------------------------------


def test_to_markdown_renders_invest_findings_questions_and_sources() -> None:
    """RF-18 · PA-64: informe con INVEST (Bien/Mejorable), hallazgos, preguntas y fuentes."""
    report = _report(
        invest=list(reversed(renewal_quality_report().invest)),
        sources=[SourceRef(kind="jira", ref=KEY), SourceRef(kind="rag", ref="doc-glosario")],
    )

    md = report.to_markdown(KEY)

    assert md.startswith(f"# Calidad de {KEY}\n")
    assert md.endswith("\n")
    assert _md(renewal_quality_report().summary) in md  # texto del LLM escapado
    assert "- **I · Independiente**: Bien. Motivo ficticio de I." in md
    assert "- **T · Testeable**: Mejorable. Motivo ficticio de T." in md
    # Las letras salen en el orden INVEST aunque el informe las traiga al revés.
    positions = [md.index(f"- **{letter} · ") for letter in INVEST_LETTERS]
    assert positions == sorted(positions)
    assert "## Hallazgos" in md
    assert (
        "- **Ambigüedad · CA-02**: «Avisar pronto» no se puede probar. "
        "Propuesta: Avisar en menos de 15 minutos." in md
    )
    assert "- **Hueco**: No dice qué pasa si la renovación falla." in md
    assert "## Preguntas para negocio" in md
    assert r"- ¿Hay un máximo de renovaciones por año? \(ficticio\)" in md
    assert "## Fuentes" in md
    assert f"- {KEY}" in md and "- doc-glosario" in md


def test_to_markdown_without_findings_questions_or_sources() -> None:
    """RF-18 · PA-64 (límite): «Sin hallazgos.» y sin secciones de preguntas ni fuentes."""
    report = _report(findings=[], open_questions=[], sources=[])

    md = report.to_markdown(KEY)

    assert "## Hallazgos\n\nSin hallazgos." in md
    assert "## Preguntas para negocio" not in md
    assert "## Fuentes" not in md


# --- 4 · Permisos ------------------------------------------------------------------------------


def test_review_allowed_for_functional_user(container: Container) -> None:
    """RF-18 · permisos: el analista funcional puede revisar la calidad."""
    review = _review(container)

    assert isinstance(review, QualityReview)
    assert review.jira_key == KEY


@pytest.mark.parametrize("user", [QA, ADMIN, None])
def test_review_denied_without_permission_and_without_calls(
    container: Container, user: User | None
) -> None:
    """RF-18 · permisos (negativa): qa, admin o anónimo → AuthenticationError,
    sin ninguna llamada al LLM ni lectura de Jira."""
    with pytest.raises(AuthenticationError):
        QualityReviewer(container).review(user, KEY)  # type: ignore[arg-type]

    assert _llm(container).calls == []
    assert _tracker(container).reads == []
    assert _tracker(container).writes == []


def test_permission_checked_before_key_validation(container: Container) -> None:
    """RF-18 · permisos: sin permiso falla por permiso aunque la clave tampoco sea válida."""
    with pytest.raises(AuthenticationError):
        QualityReviewer(container).review(QA, "no es una clave")


# --- 5 · Claves --------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", "DEMO", "DEMO 3", "3-DEMO", "DEMO-3-1", "DEMO-x"])
def test_review_invalid_key_raises_value_error_without_calls(
    container: Container, raw: str
) -> None:
    """RF-18 (negativa): clave inválida → ValueError, sin llamadas al LLM ni a Jira."""
    with pytest.raises(ValueError, match="no es una clave de Jira válida"):
        _review(container, raw)

    assert _llm(container).calls == []
    assert _tracker(container).reads == []


def test_review_unknown_key_raises_not_found_without_llm(container: Container) -> None:
    """RF-18 (error): clave inexistente → NotFoundError y ninguna llamada al LLM."""
    with pytest.raises(NotFoundError):
        _review(container, "DEMO-999")

    assert _llm(container).calls == []
    assert _tracker(container).writes == []


def test_review_normalizes_lowercase_key(container: Container) -> None:
    """RF-18: «  demo-3 » se normaliza a DEMO-3 antes de leer Jira."""
    review = _review(container, "  demo-3 ")

    assert review.jira_key == KEY
    assert review.story.jira_key == KEY
    assert _tracker(container).reads[0] == ("get_issue", KEY)


# --- 6 · Orden de las llamadas al LLM -----------------------------------------------------------


def test_review_structures_then_reviews_with_review_story_task(container: Container) -> None:
    """RF-18: dos llamadas; primero `structure` (prompt structure_story, solo el origen y sin
    RAG) y después el informe con `review_quality` y `TaskType.REVIEW_STORY`."""
    _review(container)

    structure, review = _llm(container).calls
    assert structure["schema"] is UserStory
    assert structure["task"] is TaskType.EVOLVE_STORY
    assert _system_text(structure) == load_prompt("structure_story").text
    # Solo la incidencia de origen: ni épica, ni vínculos, ni hermanas, ni documentos del RAG.
    assert SOURCE_TAG.findall(_first_user_text(structure)) == [KEY]
    assert 'tipo="rag"' not in _first_user_text(structure)

    assert review["schema"] is QualityReport
    assert review["task"] is TaskType.REVIEW_STORY
    assert _system_text(review) == load_prompt("review_quality").text


def test_review_sends_structured_story_in_hu_actual(container: Container) -> None:
    """RF-18: la HU estructurada viaja en `<hu_actual>` junto al contexto completo."""
    review = _review(container)

    text = _first_user_text(_quality_calls(container)[0])
    hu_actual = text.split("<hu_actual>", 1)[1].split("</hu_actual>", 1)[0]
    for criterion in review.story.acceptance_criteria:
        assert criterion.id in hu_actual
    for rule in review.story.business_rules:
        assert rule.id in hu_actual
    refs = SOURCE_TAG.findall(text)
    # El contexto del informe sí incluye épica, vínculos y RAG (como `gather` del grafo).
    assert refs[0] == KEY
    assert {"DEMO-1", "DEMO-2"} <= set(refs)
    assert 'tipo="rag"' in text


def test_review_returns_traceability_of_the_call(container: Container) -> None:
    """RF-18 · trazabilidad: proveedor, modelo, versión del prompt y tokens de ambas llamadas."""
    review = _review(container)

    assert review.provider == "fake"
    assert review.model == "fake-model"
    assert review.prompt_version == load_prompt("review_quality").version
    expected_in = sum(
        max(1, len(m.content) // 4) for call in _llm(container).calls for m in call["messages"]
    )
    assert review.input_tokens == expected_in
    assert review.output_tokens > 0


def test_prompt_version_matches_review_quality_header(container: Container) -> None:
    """RF-18 · trazabilidad: `prompt_version` coincide con la cabecera del archivo del prompt."""
    raw = (Path(__file__).parents[2] / "prompts" / "review_quality.md").read_text(encoding="utf-8")
    header = re.search(r"^version:\s*(\S+)\s*$", raw, re.MULTILINE)
    assert header is not None

    assert _review(container).prompt_version == header.group(1)


def test_review_returns_structured_story_without_changes(container: Container) -> None:
    """RF-18: el resultado incluye la HU estructurada desde Jira, sin cambios declarados."""
    review = _review(container)

    assert review.story.jira_key == KEY
    assert review.story.changes_from_previous == []
    assert review.report.findings == renewal_quality_report().findings


# --- 7 · Fuentes excluidas -----------------------------------------------------------------------


def test_review_respects_excluded_sources(container: Container) -> None:
    """RF-18 · T-51: las fuentes desmarcadas (Jira y RAG) no llegan al informe."""
    _review(container, excluded_sources=["DEMO-2", "doc-reglamento"])

    refs = SOURCE_TAG.findall(_first_user_text(_quality_calls(container)[0]))
    assert "DEMO-2" not in refs
    assert "doc-reglamento" not in refs
    assert KEY in refs
    assert "doc-glosario" in refs


def test_review_cannot_exclude_origin(container: Container) -> None:
    """RF-18 · T-51 (negativa): excluir el origen se rechaza igual que en el grafo, sin llamadas."""
    with pytest.raises(ValueError, match="no se puede excluir"):
        _review(container, excluded_sources=[KEY])
    assert _llm(container).calls == []


@pytest.mark.parametrize(
    "excluded",
    [[f"DOC-{n:03d}" for n in range(51)], ["texto libre con espacios"]],
    ids=["demasiadas", "texto_libre"],
)
def test_review_validates_excluded_sources_like_the_graph(
    container: Container, excluded: list[str]
) -> None:
    with pytest.raises(ValueError):
        _review(container, excluded_sources=excluded)
    assert _llm(container).calls == []


def test_review_without_excluded_sources_keeps_all(container: Container) -> None:
    """RF-18 · T-51 (límite): `excluded_sources=None` o lista vacía no quitan nada."""
    _review(container, excluded_sources=None)
    _review(container, excluded_sources=[])

    first, second = (SOURCE_TAG.findall(_first_user_text(c)) for c in _quality_calls(container))
    assert first == second
    assert "DEMO-2" in first and "doc-reglamento" in first


# --- 8 · Reintento por IDs inexistentes ----------------------------------------------------------


def test_report_errors_flags_unknown_target_id() -> None:
    """RF-18: `report_errors` señala un `target_id` que no está en la HU."""
    story = dataset.renewal_story()
    ctx = StoryContext(origin_kind="story", origin_key=KEY, jira=[dataset.STORIES[KEY]])
    sources = ctx.sources()

    errors = report_errors(_with_bad_id(), story, sources)

    assert errors == [f"«{INVENTED_ID}» no es un criterio ni una regla de la HU"]
    assert report_errors(_origin_cited(), story, sources) == []


def test_review_retries_unknown_id_and_recovers(container: Container) -> None:
    """RF-18: un ID inventado provoca un reintento con `quality_retry`; si se corrige, vale."""
    _llm(container).builders[QualityReport] = _sequence(_with_bad_id(), _origin_cited())

    review = _review(container)

    first, retry = _quality_calls(container)
    assert retry["task"] is TaskType.REVIEW_STORY
    assert len(retry["messages"]) == len(first["messages"]) + 2
    assert retry["messages"][-2].role == "assistant"
    feedback = retry["messages"][-1].content
    assert feedback.startswith(load_prompt("quality_retry").text.split("<errores>")[0])
    assert INVENTED_ID in feedback.split("</errores>")[0]
    ids = feedback.split("<ids_hu>")[1].split("</ids_hu>")[0]
    for allowed_id in ("CA-01", "CA-02", "RN-01", "RN-02"):
        assert allowed_id in ids
    assert f"- jira: {KEY}" in feedback.split("<fuentes_permitidas>")[1]
    assert {f.target_id for f in review.report.findings} == {"CA-02", None}


def test_review_unknown_id_persisting_raises_quality_review_error(container: Container) -> None:
    """RF-18 (error): si el ID inventado persiste tras el reintento → QualityReviewError en
    español y sin repetir el ID inventado."""
    _llm(container).builders[QualityReport] = _sequence(_with_bad_id())

    with pytest.raises(QualityReviewError) as error:
        _review(container)

    assert isinstance(error.value, AgentError)
    assert INVENTED_ID not in str(error.value)
    assert "no existen en la HU" in str(error.value)
    assert len(_quality_calls(container)) == 2  # un solo reintento


# --- 9 · Reintento por citas inexistentes --------------------------------------------------------


def test_review_retries_invented_citation_and_recovers(container: Container) -> None:
    """RF-18 · RNF-14: una cita fuera del contexto provoca un reintento; si se corrige, vale."""
    _llm(container).builders[QualityReport] = _sequence(_with_bad_citation(), _origin_cited())

    review = _review(container)

    retry = _quality_calls(container)[-1]
    assert INVENTED_REF in retry["messages"][-1].content.split("</errores>")[0]
    assert [s.ref for s in review.report.sources] == [KEY]


def test_review_retries_report_without_citations(container: Container) -> None:
    """RF-18 · RNF-14 (límite): sin citas habiendo fuentes también se reintenta."""
    _llm(container).builders[QualityReport] = _sequence(_report(sources=[]), _origin_cited())

    review = _review(container)

    assert len(_quality_calls(container)) == 2
    assert "no cita ninguna fuente" in _quality_calls(container)[-1]["messages"][-1].content
    assert review.report.sources


def test_review_invented_citation_persisting_raises_citation_error(container: Container) -> None:
    """RF-18 · RNF-14 (error): la cita inventada persiste → CitationError sin repetir la ref."""
    _llm(container).builders[QualityReport] = _sequence(_with_bad_citation())

    with pytest.raises(CitationError) as error:
        _review(container)

    assert INVENTED_REF not in str(error.value)
    assert len(_quality_calls(container)) == 2


def test_review_citation_error_takes_precedence_over_unknown_id(container: Container) -> None:
    """RF-18 (error): si tras el reintento persisten cita e ID inventados, gana CitationError."""
    both = _with_bad_id().model_copy(update={"sources": [SourceRef(kind="rag", ref=INVENTED_REF)]})
    _llm(container).builders[QualityReport] = _sequence(both)

    with pytest.raises(CitationError) as error:
        _review(container)

    assert INVENTED_ID not in str(error.value) and INVENTED_REF not in str(error.value)


def test_review_valid_report_has_no_retry(container: Container) -> None:
    """RF-18 (positiva): un informe válido a la primera no se reintenta."""
    _review(container)

    assert len(_quality_calls(container)) == 1
    assert len(_llm(container).calls) == 2


# --- 10 · Citas con extracto real ----------------------------------------------------------------


def test_review_replaces_excerpts_with_real_ones(container: Container) -> None:
    """RF-18 · RF-21: el extracto de cada cita es el real de la fuente, no el del LLM."""
    invented = _report(sources=[SourceRef(kind="jira", ref=KEY, excerpt="Extracto inventado.")])
    _llm(container).builders[QualityReport] = _sequence(invented)

    review = _review(container)

    (source,) = review.report.sources
    assert source.ref == KEY
    assert "inventado" not in source.excerpt
    assert source.excerpt.startswith(dataset.STORIES[KEY].summary)


def test_review_deduplicates_repeated_citations(container: Container) -> None:
    """RF-18 · RF-21 (límite): la misma fuente citada dos veces queda una sola vez."""
    twice = _report(sources=[SourceRef(kind="jira", ref=KEY), SourceRef(kind="jira", ref=KEY)])
    _llm(container).builders[QualityReport] = _sequence(twice)

    review = _review(container)

    assert [s.ref for s in review.report.sources] == [KEY]


# --- 11 · Feedback para «Evolucionar con esto» ---------------------------------------------------


def _review_result(report: QualityReport) -> QualityReview:
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


def test_evolve_feedback_prefixes_target_id() -> None:
    """RF-18 · RF-20: «CA-xx: propuesta» por hallazgo, y la propuesta sola sin `target_id`."""
    feedback = _review_result(renewal_quality_report()).evolve_feedback()

    assert feedback == ["CA-02: Avisar en menos de 15 minutos.", "Añadir un criterio de error."]


def test_evolve_feedback_empty_without_findings() -> None:
    """RF-18 · RF-20 (límite): sin hallazgos no hay feedback."""
    assert _review_result(_report(findings=[])).evolve_feedback() == []


def test_evolve_feedback_starts_graph_until_human_review(container: Container) -> None:
    """RF-18 · RF-20: el feedback sirve como `initial_state(..., feedback=...)`; el grafo pausa en
    `human_review` con la HU evolucionada y el feedback llega al LLM, sin escribir en Jira."""
    feedback = _review(container).evolve_feedback()
    graph = build_graph(container)
    config = {"configurable": {"thread_id": f"hilo-{uuid4()}"}}

    state = initial_state(
        AF.username, "functional", {"kind": "story", "key": KEY}, feedback=feedback
    )
    result = graph.invoke(state, config)  # type: ignore[arg-type]

    (pending,) = result["__interrupt__"]
    assert graph.get_state(config).next == ("human_review",)
    assert pending.value["artifact"]["status"] == ArtifactStatus.IN_REVIEW.value
    assert pending.value["artifact"]["content"]["jira_key"] == KEY
    assert graph.get_state(config).values["feedback"] == feedback
    last_user = _user_text(_llm(container).calls[-1])
    assert all(item in last_user for item in feedback)
    assert _tracker(container).writes == []


# --- 12 · Solo lectura ---------------------------------------------------------------------------


def test_review_writes_nothing(container: Container, tmp_path: Path) -> None:
    """RF-18 · principio 1: cero escrituras en Jira y en QA, sin auditoría, sin artefactos en
    aprobaciones ni en el estado, sin conversaciones y sin memoria."""
    _review(container, excluded_sources=["DEMO-2"])

    assert _tracker(container).writes == []
    assert isinstance(container.test_management, FakeTestManagement)
    assert container.test_management.publish_calls == 0
    assert container.audit.recorded == []  # type: ignore[attr-defined]
    assert container.state_store.states == {}  # type: ignore[attr-defined]
    # El registro de aprobaciones no expone un listado: se miran sus tablas internas.
    assert container.approvals._offers == {}
    assert container.approvals._approvals == {}
    assert container.approvals._targets == {}
    assert container.conversations.rows == {}  # type: ignore[attr-defined]
    assert isinstance(container.vector_store, FakeVectorStore)
    memory = [
        c for c in container.vector_store.chunks.values() if c.metadata.get("category") == "memoria"
    ]
    assert memory == []
    assert not (tmp_path / "memoria").exists() or not any((tmp_path / "memoria").iterdir())


def test_review_failure_writes_nothing(container: Container) -> None:
    """RF-18 · principio 1 (error): tampoco escribe nada cuando el informe no es válido."""
    _llm(container).builders[QualityReport] = _sequence(_with_bad_id())

    with pytest.raises(QualityReviewError):
        _review(container)

    assert _tracker(container).writes == []
    assert container.audit.recorded == []  # type: ignore[attr-defined]
    assert container.state_store.states == {}  # type: ignore[attr-defined]


# --- 13 · Log -----------------------------------------------------------------------------------


def test_review_logs_action_without_content(container: Container) -> None:
    """RF-18 · RNF-02: un evento `review_quality` con usuario, modelo y duración, sin contenido."""
    with capture_logs() as logs:
        review = _review(container)

    (event,) = [e for e in logs if e.get("action") == "review_quality"]
    assert event["user"] == AF.username
    assert event["model"] == "fake/fake-model"
    assert isinstance(event["duration_ms"], int)
    assert event["findings"] == len(review.report.findings)
    rendered = " ".join(str(value) for value in event.values())
    assert review.report.summary not in rendered
    assert all(f.proposal not in rendered for f in review.report.findings)
    assert load_prompt("review_quality").text[:40] not in rendered


def test_to_markdown_escapes_llm_text_against_links_images_and_html() -> None:
    """Seguridad T-48: el texto del LLM no puede colar enlaces, imágenes, HTML ni títulos."""
    report = renewal_quality_report().model_copy(
        update={"summary": "Mira [esto](http://x.example) ![i](http://y.example) <b>a</b>\n# Falso"}
    )
    md = report.to_markdown(KEY)
    summary_line = md.splitlines()[2]
    assert r"\[esto\]\(http" in summary_line and r"\!\[i\]" in summary_line
    assert r"\<b\>" in summary_line and r"\# Falso" in summary_line  # sin salto de línea
    assert not any(line.startswith("# Falso") for line in md.splitlines())


def test_report_limits_text_and_list_sizes() -> None:
    """Seguridad T-48: textos de 500 caracteres como máximo y listas de 30 como máximo."""
    base = renewal_quality_report()
    with pytest.raises(pydantic.ValidationError):
        base.model_validate({**base.model_dump(), "summary": "x" * 501})
    with pytest.raises(pydantic.ValidationError):
        base.model_validate({**base.model_dump(), "open_questions": ["¿?"] * 31})


# --- PA-232 / PA-321: desempate del orden de la lista de revisiones ---------------------------


def test_in_memory_review_list_breaks_timestamp_ties_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PA-232 / PA-321: con el reloj de Windows (15,6 ms) dos revisiones pueden tener la misma
    fecha; la lista sigue saliendo de la más reciente a la más antigua."""
    from datetime import UTC, datetime

    import core.quality as quality_module
    from core.quality import InMemoryQualityReviewStore, new_review

    frozen = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def,override]
            return frozen

    monkeypatch.setattr(quality_module, "datetime", FrozenClock)
    store = InMemoryQualityReviewStore()
    for review_id, key in (("r-1", "DEMO-3"), ("r-2", "DEMO-2"), ("r-3", "DEMO-4")):
        store.create(new_review(review_id, "af-ficticia", key))

    listed = store.list_for("af-ficticia")

    assert {r.updated_at for r in listed} == {frozen}  # empate total
    assert [r.id for r in listed] == ["r-3", "r-2", "r-1"]
    assert [r.id for r in store.list_for("af-ficticia", limit=1)] == ["r-3"]
