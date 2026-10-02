"""Lógica pura de la UI «Propuesta mixta» (T-24 · `docs/specs/UI.md` §3, §4.1–4.5, §5 y §8).

Cubre `app/flows.py`, `app/origin.py`, `app/review.py` (sin grafo), `app/editing.py`,
`app/progress.py`, `app/models.py`, `app/anim.py`, `app/text.py`, `message_for` y una revisión
estática de seguridad de `app/`. Las pruebas con el grafo real están en
`tests/unit/test_app_conversation.py`.

Solo fakes de `tests/fakes/` y datos 100 % ficticios.
"""

import ast
import json
import re
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

import core.projects as core_projects
from adapters.base import IssueDetail, IssueSummary, TaskType, User
from adapters.errors import (
    AgentError,
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
)
from adapters.llm.router import ModelChoice, ModelRouter
from app.anim import phase_q, typing_q
from app.conversation import UNEXPECTED, Conversation, authorize, message_for
from app.editing import form_to_content, story_to_form
from app.flows import FLOWS, FlowCard, default_flow, flow_by_id, flow_cards, shows_flows
from app.listing import day_label, flow_label, group_by_day, status_label
from app.models import AUTOMATIC, SELECTABLE_TASKS, apply_model, model_options
from app.origin import (
    EPIC_NOT_ALLOWED,
    KEY_REQUIRED,
    NEED_TEXT_REQUIRED,
    QA_NEEDS_STORY,
    StartPlan,
    StartRequest,
    build_feedback,
    build_initial_state,
    build_origin,
    change_request,
    fix_origin,
    plan_start,
    preview_origin,
    request_from_option,
    request_from_state,
    with_excluded,
    with_restrictions,
)
from app.progress import STEPS, completed_steps, nodes_in_update, phase_label, phase_of
from app.quality import (
    REVIEW_STEPS,
    FindingRow,
    InvestRow,
    evolve_request,
    finding_rows,
    invest_rows,
    report_download,
    report_filename,
    review_message,
)
from app.review import (
    ReceiptItem,
    ReviewView,
    approve_answer,
    change_marks,
    describe_operation,
    describe_target,
    discard_answer,
    edit_answer,
    field_label,
    iterate_answer,
    outcome_from_state,
    parse_payload,
    pending_from_result,
    pending_from_state,
    receipt_items,
    receipt_progress,
    source_count,
    summarize,
)
from app.session import (
    LOGIN_LOCK_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    SessionState,
    login_locked,
    record_login_failure,
    record_login_success,
)
from app.sources import IssueCard, describe_card, excluded_refs, issue_card, source_label
from app.text import md_escape, md_lines
from core.approvals import ApprovalError
from core.config import ROOT_DIR, AppConfig, Settings, load_models_config
from core.conversations import ConversationSummary, new_summary
from core.factories import model_router
from core.graph import Origin, initial_state
from core.graph.nodes import ReviewRejectedError
from core.guided_start import GuidedStart, SourcePreview, StartOption, StartProposal
from core.permissions import Permission
from core.projects import normalize_issue_key
from core.quality import QualityReview, QualityReviewer
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem, StoryDiff
from schemas.quality import FINDING_LABELS, INVEST_NAMES, InvestCheck, QualityFinding, QualityReport
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider, renewal_quality_report, renewal_test_suite

AF_USER = dataset.DEMO_USERS["af-demo"][1]
QA_USER = dataset.DEMO_USERS["qa-demo"][1]
ADMIN_USER = dataset.DEMO_USERS["admin-demo"][1]
NEED_TEXT = "Avisar por correo tres días antes del vencimiento del préstamo (ficticio)."
RESTRICTIONS = "Mismas reglas que en la web ficticia."
AF_HINT = "Disponible para el rol de analista funcional."
QA_HINT = "Disponible para el rol QA."
MODELS_FIXTURE = ROOT_DIR / "tests" / "fixtures" / "models.yaml"
APP_DIR = ROOT_DIR / "app"
FAKE_GROQ_KEY = "test-key-groq-ficticia"
FAKE_OPENROUTER_KEY = "test-key-openrouter-ficticia"
GROQ_120B = ModelChoice("groq", "openai/gpt-oss-120b")
GROQ_20B = ModelChoice("groq", "openai/gpt-oss-20b")
OPENROUTER_FREE = ModelChoice("openrouter", "POR_DEFINIR:free")


# --- 1 · Roles y tarjetas de flujo (UI.md §3 y §4.1) -------------------------------------------


def _cards(user: Any) -> dict[str, FlowCard]:
    return {card.flow.id: card for card in flow_cards(user)}


def test_flows_are_the_four_cards_in_order() -> None:
    """UI.md §4.1: cuatro tarjetas (rejilla 2×2) en el orden del diseño."""
    assert [flow.id for flow in FLOWS] == ["need", "evolve", "review", "tests"]
    assert [card.flow.id for card in flow_cards(AF_USER)] == ["need", "evolve", "review", "tests"]


def test_flow_by_id_returns_flow_with_its_permission() -> None:
    """UI.md §3: cada tarjeta exige su permiso de `core/permissions.py`."""
    assert flow_by_id("need").permission is Permission.GENERATE_STORY
    assert flow_by_id("evolve").permission is Permission.GENERATE_STORY
    assert flow_by_id("review").permission is Permission.GENERATE_STORY
    assert flow_by_id("tests").permission is Permission.GENERATE_TESTS


@pytest.mark.parametrize("flow_id", ["need", "evolve"])
def test_flow_cards_functional_enables_story_flows(flow_id: str) -> None:
    """UI.md §3: el analista funcional puede usar Nueva necesidad y Evolucionar una HU."""
    card = _cards(AF_USER)[flow_id]
    assert card.allowed and card.enabled
    assert card.hint == card.flow.hint


def test_flow_cards_review_enabled_for_functional_role() -> None:
    """UI.md §3 · T-48 (RF-18): Revisar la calidad está activa para el analista funcional."""
    card = _cards(AF_USER)["review"]
    assert card.flow.pending_task is None
    assert card.allowed is True
    assert card.enabled is True
    assert card.hint == card.flow.hint


def test_flow_cards_review_disabled_for_qa_with_af_hint() -> None:
    """UI.md §3 · T-48 (negativa): QA ve Revisar la calidad desactivada con la ayuda del AF."""
    card = _cards(QA_USER)["review"]
    assert (card.allowed, card.enabled) == (False, False)
    assert card.hint == "Disponible para el rol de analista funcional."


def test_flow_cards_review_hidden_for_admin() -> None:
    """UI.md §3 · D-01 (negativa): el administrador no ve tarjetas ni puede revisar la calidad."""
    assert shows_flows(ADMIN_USER) is False
    card = _cards(ADMIN_USER)["review"]
    assert (card.allowed, card.enabled) == (False, False)


def test_flow_cards_functional_tests_card_is_for_qa_role() -> None:
    """UI.md §3: Preparar pruebas se muestra desactivada con «Disponible para el rol QA.»."""
    card = _cards(AF_USER)["tests"]
    assert card.allowed is False
    assert card.enabled is False
    assert card.hint == QA_HINT


@pytest.mark.parametrize("flow_id", ["need", "evolve", "review"])
def test_flow_cards_qa_disables_story_flows_with_af_hint(flow_id: str) -> None:
    """UI.md §3: QA ve las tarjetas de HU desactivadas con la ayuda del rol de analista."""
    card = _cards(QA_USER)[flow_id]
    assert card.allowed is False
    assert card.enabled is False
    assert card.hint == AF_HINT


def test_flow_cards_qa_tests_card_is_pending_t28() -> None:
    """UI.md §3: Preparar pruebas está permitida a QA, pero su pantalla llega con T-28."""
    card = _cards(QA_USER)["tests"]
    assert card.allowed is True
    assert card.enabled is False
    assert card.hint == f"{card.flow.hint} Disponible pronto (T-28)."
    assert not any(c.enabled for c in flow_cards(QA_USER))


def test_shows_flows_false_for_admin_and_anonymous() -> None:
    """UI.md §3 · D-01: el administrador configura, no genera; no ve las tarjetas."""
    assert shows_flows(ADMIN_USER) is False
    assert shows_flows(None) is False
    assert not any(card.allowed or card.enabled for card in flow_cards(ADMIN_USER))


@pytest.mark.parametrize("user", [AF_USER, QA_USER], ids=["functional", "qa"])
def test_shows_flows_true_for_generating_roles(user: Any) -> None:
    """UI.md §3: analista y QA ven las tarjetas de flujo."""
    assert shows_flows(user) is True


@pytest.mark.parametrize(
    ("user", "expected"),
    [(AF_USER, "need"), (QA_USER, None), (ADMIN_USER, None), (None, None)],
    ids=["functional", "qa", "admin", "anonimo"],
)
def test_default_flow_by_role(user: Any, expected: str | None) -> None:
    """UI.md §4.1: el primer flujo habilitado; QA no tiene ninguno hasta T-28."""
    assert default_flow(user) == expected


# --- 2 · Origen (UI.md §4.1–4.3, T-50, T-51, T-53 parcial) -------------------------------------


def test_fix_origin_need_with_text() -> None:
    """UI.md §4.1: una necesidad nueva con texto; el proyecto se normaliza."""
    request = fix_origin("need", " demo ", text=f"  {NEED_TEXT}  ")
    assert request == StartRequest(flow="need", kind="need", project="DEMO", text=NEED_TEXT)
    assert request.mode == "functional"
    assert request.describe() == "Crear una HU nueva en el proyecto DEMO"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_fix_origin_need_without_text_raises(text: str) -> None:
    """UI.md §4.1 (error): una necesidad sin texto no se puede fijar."""
    with pytest.raises(ValueError, match="Describe la necesidad antes de continuar"):
        fix_origin("need", "DEMO", text=text)


def test_fix_origin_need_with_key_in_text_stays_need() -> None:
    """UI.md §4.3: en una necesidad, la clave del texto se ofrece después (no fija el origen)."""
    request = fix_origin("need", "DEMO", text="Algo parecido a DEMO-3 pero por correo")
    assert request.kind == "need"
    assert request.key is None
    assert request.flow == "need"


def test_fix_origin_evolve_with_explicit_key_normalizes_it() -> None:
    """UI.md §4.1 · T-53: la clave llega en `key=` (la reconoce `GuidedStart`) y se normaliza."""
    request = fix_origin("evolve", "DEMO", key="demo-3", text="Cambiar demo-3: renovar")
    assert request.flow == "evolve"
    assert request.kind == "story"
    assert request.key == "DEMO-3"
    assert request.project == "DEMO"
    assert request.text == "Cambiar demo-3: renovar"
    assert request.describe() == "Evolucionar DEMO-3"


@pytest.mark.parametrize("flow", ["evolve", "review", "tests"])
def test_fix_origin_does_not_extract_key_from_text(flow: Any) -> None:
    """T-53 (error): `fix_origin` ya no extrae la clave del texto; sin `key=` la exige."""
    with pytest.raises(ValueError, match="Escribe la clave de la HU de Jira"):
        fix_origin(flow, "DEMO", text="Cambiar DEMO-3: renovar desde la app")


@pytest.mark.parametrize("flow", ["evolve", "review", "tests"])
def test_fix_origin_key_flows_without_key_raise(flow: Any) -> None:
    """UI.md §4.1 (error): los flujos sobre una HU exigen su clave."""
    with pytest.raises(ValueError, match="Escribe la clave de la HU de Jira"):
        fix_origin(flow, "DEMO", text="Quiero mejorar la renovación")


def test_fix_origin_need_with_epic_key_is_epic() -> None:
    """UI.md §4.2: elegir una épica en una necesidad crea una HU nueva dentro de ella."""
    request = fix_origin("need", "DEMO", key="demo-1", kind="epic")
    assert request.flow == "need"
    assert request.kind == "epic"
    assert request.key == "DEMO-1"
    assert request.describe() == "Crear una HU nueva en la épica DEMO-1"


def test_fix_origin_need_with_story_key_becomes_evolution() -> None:
    """UI.md §4.3: partir de una HU parecida en una necesidad es evolucionarla."""
    request = fix_origin("need", "DEMO", key="DEMO-3")
    assert (request.flow, request.kind, request.key) == ("evolve", "story", "DEMO-3")


@pytest.mark.parametrize("flow", ["evolve", "review", "tests"])
def test_fix_origin_epic_outside_need_raises(flow: Any) -> None:
    """UI.md §4.2 (error): solo una necesidad nueva puede partir de una épica."""
    with pytest.raises(ValueError, match="Para este flujo elige una HU, no una épica"):
        fix_origin(flow, "DEMO", key="DEMO-1", kind="epic")


def test_fix_origin_key_of_other_project_changes_project() -> None:
    """UI.md §4.1 · T-50: una clave de otro proyecto cambia el proyecto de la conversación."""
    in_text = fix_origin("evolve", "DEMO", key="otro-7", text="Evolucionar otro-7 (ficticio)")
    assert (in_text.project, in_text.key) == ("OTRO", "OTRO-7")
    explicit = fix_origin("need", "DEMO", key="OTRO-5", kind="epic")
    assert (explicit.project, explicit.key) == ("OTRO", "OTRO-5")


def test_fix_origin_tests_flow_is_qa_mode() -> None:
    """UI.md §6.1: Preparar pruebas parte de una HU y trabaja en modo QA."""
    request = fix_origin("tests", "DEMO", key="DEMO-3", text="Casos de prueba para DEMO-3")
    assert (request.flow, request.kind, request.key) == ("tests", "story", "DEMO-3")
    assert request.mode == "qa"
    assert request.describe() == "Suite de pruebas de DEMO-3"


def test_fix_origin_invalid_project_raises() -> None:
    """T-50 (error): una clave de proyecto mal escrita se rechaza con mensaje para la UI."""
    with pytest.raises(ValueError, match="no es una clave de proyecto válida"):
        fix_origin("need", "de mo", text=NEED_TEXT)


@pytest.mark.parametrize("key", ["../x", "DEMO", "DEMO-", "DEMO-3; DROP"])
def test_fix_origin_invalid_explicit_key_raises(key: str) -> None:
    """T-50 (error): una clave de incidencia inválida no llega al grafo."""
    with pytest.raises(ValueError, match="no es una clave de Jira válida"):
        fix_origin("evolve", "DEMO", key=key)


def test_with_restrictions_strips_and_keeps_the_rest() -> None:
    """UI.md §4.3: las restricciones se guardan recortadas sin perder el resto del origen."""
    base = with_excluded(fix_origin("evolve", "DEMO", key="DEMO-3"), ["doc-glosario"])
    request = with_restrictions(base, f"  {RESTRICTIONS}  ")
    assert request.restrictions == RESTRICTIONS
    assert request.excluded_sources == ("doc-glosario",)
    assert (request.flow, request.kind, request.key) == ("evolve", "story", "DEMO-3")
    assert base.restrictions == ""  # inmutable


def test_with_excluded_dedupes_sorts_and_drops_empty() -> None:
    """T-51 · RF-21: fuentes excluidas únicas, ordenadas y sin vacías; conserva restricciones."""
    base = with_restrictions(fix_origin("evolve", "DEMO", key="DEMO-3"), RESTRICTIONS)
    request = with_excluded(base, ["doc-glosario", "", "DEMO-2", "doc-glosario"])
    assert request.excluded_sources == ("DEMO-2", "doc-glosario")
    assert request.restrictions == RESTRICTIONS


def test_build_origin_need_appends_restrictions_to_text() -> None:
    """UI.md §4.3: en una necesidad nueva las restricciones se añaden a `origin.text`."""
    request = with_restrictions(fix_origin("need", "DEMO", text=NEED_TEXT), RESTRICTIONS)
    assert build_origin(request) == {
        "kind": "need",
        "project": "DEMO",
        "text": f"{NEED_TEXT}\n\nRestricciones: {RESTRICTIONS}",
    }
    assert build_feedback(request) == []


def test_build_origin_need_without_restrictions_keeps_text() -> None:
    """UI.md §4.3: sin restricciones, el texto de la necesidad llega tal cual."""
    request = fix_origin("need", "DEMO", text=NEED_TEXT)
    assert build_origin(request)["text"] == NEED_TEXT
    assert build_feedback(request) == []


def test_build_origin_evolution_sends_restrictions_as_feedback() -> None:
    """UI.md §4.3 · T-51: al evolucionar, las restricciones van como feedback, no a `text`."""
    request = with_restrictions(fix_origin("evolve", "DEMO", key="DEMO-3"), RESTRICTIONS)
    assert build_origin(request) == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    assert build_feedback(request) == [RESTRICTIONS]


def test_build_origin_epic_sends_restrictions_as_feedback() -> None:
    """T-51: con una épica de origen, las restricciones también van como feedback."""
    request = with_restrictions(fix_origin("need", "DEMO", key="DEMO-1", kind="epic"), "Breve")
    assert build_origin(request) == {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}
    assert build_feedback(request) == ["Breve"]


def test_build_feedback_evolution_without_restrictions_is_empty() -> None:
    """T-51 (límite): sin restricciones no hay feedback previo."""
    assert build_feedback(fix_origin("evolve", "DEMO", key="DEMO-3")) == []


def test_build_origin_story_without_key_raises() -> None:
    """Error: un origen de HU sin clave no se puede construir."""
    request = StartRequest(flow="evolve", kind="story", project="DEMO")
    with pytest.raises(ValueError, match="Falta la clave de Jira del origen"):
        build_origin(request)


def test_build_initial_state_passes_excluded_sources_and_feedback() -> None:
    """T-51 · RF-21 · RF-20: `excluded_sources` y `feedback` llegan al `AgentState`."""
    request = with_excluded(
        with_restrictions(fix_origin("evolve", "DEMO", key="DEMO-3"), RESTRICTIONS),
        ["doc-glosario", "DEMO-2"],
    )
    state = build_initial_state(AF_USER.username, request)
    assert state["user"] == AF_USER.username
    assert state["mode"] == "functional"
    assert state["origin"] == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    assert state["excluded_sources"] == ["DEMO-2", "doc-glosario"]
    assert state["feedback"] == [RESTRICTIONS]
    assert state["artifact"] is None
    assert state["decision"] is None
    assert state["jira_context"] == [] and state["rag_context"] == []
    assert state["published_keys"] == [] and state["errors"] == []


def test_build_initial_state_need_has_restrictions_in_text_and_no_feedback() -> None:
    """UI.md §4.3: necesidad nueva → restricciones en `origin.text`, feedback vacío."""
    request = with_restrictions(fix_origin("need", "DEMO", text=NEED_TEXT), RESTRICTIONS)
    state = build_initial_state(AF_USER.username, request)
    assert state["origin"]["text"].endswith(f"Restricciones: {RESTRICTIONS}")
    assert state["feedback"] == []
    assert state["excluded_sources"] == []


def test_build_initial_state_tests_flow_is_qa() -> None:
    """UI.md §6.1: el flujo de pruebas arranca el grafo en modo QA con su feedback."""
    request = with_restrictions(fix_origin("tests", "DEMO", key="DEMO-3"), "Solo negativos")
    state = build_initial_state(QA_USER.username, request)
    assert state["mode"] == "qa"
    assert state["feedback"] == ["Solo negativos"]


def test_build_initial_state_rejects_excluding_the_origin() -> None:
    """T-51 (error): la incidencia de origen no se puede excluir de las fuentes."""
    request = with_excluded(fix_origin("evolve", "DEMO", key="DEMO-3"), ["DEMO-3"])
    with pytest.raises(ValueError, match="no se puede excluir"):
        build_initial_state(AF_USER.username, request)


def test_build_initial_state_keeps_change_request_written_with_the_key() -> None:
    """UI.md §4.1: «Escribe la clave de la HU, por ejemplo DEMO-3, y qué quieres cambiar.»."""
    request = fix_origin(
        "evolve", "DEMO", key="DEMO-3", text="DEMO-3 permitir renovar desde la app ficticia"
    )
    state = build_initial_state(AF_USER.username, request)
    assert state["feedback"] == ["permitir renovar desde la app ficticia"]
    assert all("DEMO-3" not in item for item in state["feedback"])
    assert "text" not in state["origin"]  # en `origin.text` sustituiría la consulta al RAG


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("DEMO-3 permitir renovar desde la app ficticia", "permitir renovar desde la app ficticia"),
        ("DEMO-3: añadir la renovación por app.", "añadir la renovación por app"),
        ("Añadir la renovación por app en demo-3.", "Añadir la renovación por app en"),
        ("  DEMO-3   con   espacios   de sobra  ", "con espacios de sobra"),
        ("DEMO-3 sin tocar DEMO-30", "sin tocar DEMO-30"),
        ("DEMO-3", ""),
        ("  demo-3 .  ", ""),
    ],
    ids=["inicio", "dos-puntos", "final", "espacios", "otra-clave", "solo", "puntuacion"],
)
def test_change_request_is_text_without_the_key(text: str, expected: str) -> None:
    """UI.md §4.1: lo pedido junto a la clave, sin ella ni espacios o puntuación sobrantes."""
    assert change_request(fix_origin("evolve", "DEMO", key="DEMO-3", text=text)) == expected


def test_change_request_of_need_is_normalized_text() -> None:
    """Límite: sin clave, `change_request` es el texto normalizado."""
    request = fix_origin("need", "DEMO", text="  Avisar   por correo ficticio.  ")
    assert change_request(request) == "Avisar por correo ficticio"


def test_build_feedback_with_change_request_and_restrictions() -> None:
    """T-51 · RF-20: con clave de origen, lo pedido y las restricciones van como feedback."""
    request = with_restrictions(
        fix_origin("evolve", "DEMO", key="DEMO-3", text="DEMO-3: añadir la renovación por app."),
        RESTRICTIONS,
    )
    assert build_feedback(request) == ["añadir la renovación por app", RESTRICTIONS]


def test_build_feedback_epic_with_text_and_restrictions() -> None:
    """T-51: una épica de origen también lleva lo pedido junto a la clave como feedback."""
    request = with_restrictions(
        fix_origin("need", "DEMO", key="DEMO-1", kind="epic", text="DEMO-1 con avisos"), "Breve"
    )
    assert build_feedback(request) == ["con avisos", "Breve"]


def test_build_feedback_only_key_and_no_restrictions_is_empty() -> None:
    """T-51 (límite): si solo se escribió la clave, no hay feedback vacío."""
    assert build_feedback(fix_origin("evolve", "DEMO", key="DEMO-3", text="DEMO-3")) == []


def test_build_feedback_need_never_has_feedback() -> None:
    """UI.md §4.3: en una necesidad todo va a `origin.text`; el feedback queda vacío."""
    request = with_restrictions(fix_origin("need", "DEMO", text=NEED_TEXT), RESTRICTIONS)
    assert build_feedback(request) == []


def test_fix_origin_epic_keeps_composer_text_as_feedback() -> None:
    """B3 · UI.md §4.2: al elegir una épica, el texto del compositor llega como feedback."""
    request = fix_origin(
        "need", "DEMO", key="DEMO-1", kind="epic", text="Necesidad ficticia de avisos"
    )
    assert request.kind == "epic"
    assert request.text == "Necesidad ficticia de avisos"
    assert build_feedback(request) == ["Necesidad ficticia de avisos"]
    assert build_origin(request) == {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}


# --- 3–4 · Pausa de revisión y respuestas (UI.md §5) -------------------------------------------


def _payload(
    version: int = 1, impact: ImpactAnalysis | None = None, error: str | None = None
) -> dict[str, Any]:
    artifact = Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.IN_REVIEW,
        version=version,
        origin_key="DEMO-3",
        content=dataset.renewal_story(),
        impact=impact,
        created_by=AF_USER.username,
        model_used="fake/fake-model",
    )
    return {
        "artifact": artifact.model_dump(mode="json"),
        "version": version,
        "fingerprint": f"{version:x}" * 64,
        "target": "Evolucionar DEMO-3 (ficticio)",
        "plan": [{"op": "update_story", "project": "DEMO", "key": "DEMO-3"}],
        "impact": impact.model_dump(mode="json") if impact else None,
        "decisions": ["iterate", "edit", "approve", "discard"],
        "error": error,
    }


def _impact() -> ImpactAnalysis:
    return ImpactAnalysis(
        diffs=[
            StoryDiff(field="title", before="Renovar", after="Renovar un préstamo"),
            StoryDiff(field="description", before="Antes ficticio", after="Después ficticio"),
        ],
        affected=[
            ImpactItem(jira_key="DEMO-4", reason="Historial ficticio", kind="rule"),
            ImpactItem(jira_key="DEMO-2", reason="Comparte la RN de reservas", kind="rule"),
            ImpactItem(jira_key="DEMO-2", reason="Otro motivo ficticio", kind="rule"),
        ],
        regression_notes=["Revisar el flujo de reservas."],
    )


def test_parse_payload_reads_the_review_contract() -> None:
    """UI.md §5.1: payload {artifact, version, target, fingerprint, impact, plan, decisions}."""
    payload = _payload(impact=_impact())
    view = parse_payload(payload)
    assert view.artifact == Artifact.model_validate(payload["artifact"])
    assert view.version == 1
    assert view.fingerprint == payload["fingerprint"]
    assert view.target == "Evolucionar DEMO-3 (ficticio)"
    assert view.plan == payload["plan"]
    assert view.impact == _impact()
    assert view.decisions == ["iterate", "edit", "approve", "discard"]
    assert view.error is None


def test_parse_payload_tolerates_missing_optional_fields() -> None:
    """UI.md §5.1 (límite): sin plan, impacto, target ni decisiones; error vacío → None."""
    payload = _payload(error="")
    for name in ("plan", "impact", "target", "decisions"):
        del payload[name]
    view = parse_payload(payload)
    assert (view.plan, view.impact, view.target, view.decisions) == ([], None, "", [])
    assert view.error is None


def test_parse_payload_keeps_error_message() -> None:
    """UI.md §5.3: una respuesta rechazada vuelve con `error`, que la UI muestra."""
    view = parse_payload(_payload(error="La edición no parte de la versión revisada."))
    assert view.error == "La edición no parte de la versión revisada."


def test_pending_from_result_takes_last_mapping_interrupt() -> None:
    """UI.md §5.1: la pausa se lee de `__interrupt__` (la última con payload)."""
    result = {
        "__interrupt__": (
            SimpleNamespace(value=_payload(version=1)),
            SimpleNamespace(value="no es un payload"),
            SimpleNamespace(value=_payload(version=2)),
        )
    }
    view = pending_from_result(result)
    assert view is not None
    assert view.version == 2


@pytest.mark.parametrize(
    "result",
    [{}, {"__interrupt__": ()}, {"__interrupt__": [SimpleNamespace(value=None)]}],
    ids=["terminado", "vacio", "sin-payload"],
)
def test_pending_from_result_none_when_no_pause(result: dict[str, Any]) -> None:
    """UI.md §5.1: sin interrupciones con payload, el grafo ha terminado."""
    assert pending_from_result(result) is None


def test_pending_from_state_reads_task_interrupts() -> None:
    """UI.md §5.1: la pausa se detecta por `get_state(config).tasks[*].interrupts`, no `next`."""
    snapshot = SimpleNamespace(
        next=(),
        tasks=[
            SimpleNamespace(interrupts=()),
            SimpleNamespace(interrupts=(SimpleNamespace(value=_payload(version=3)),)),
        ],
    )
    view = pending_from_state(snapshot)
    assert view is not None
    assert view.version == 3


def test_pending_from_state_none_without_tasks() -> None:
    """UI.md §5.1 (límite): sin tareas pendientes no hay pausa."""
    assert pending_from_state(SimpleNamespace(tasks=())) is None
    assert pending_from_state(object()) is None


def test_iterate_answer_strips_feedback() -> None:
    """UI.md §5.3 · RF-20: iterar → {"decision": "iterate", "feedback": texto}."""
    assert iterate_answer("  Añade un CA de error ficticio \n") == {
        "decision": "iterate",
        "feedback": "Añade un CA de error ficticio",
    }


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_iterate_answer_empty_raises(text: str) -> None:
    """RF-20 (error): un cambio vacío no se envía al grafo."""
    with pytest.raises(ValueError, match="Escribe qué quieres cambiar de la propuesta"):
        iterate_answer(text)


def test_edit_answer_returns_fingerprint_of_last_payload() -> None:
    """UI.md §5.3–5.4 · RF-32: editar devuelve el contenido completo y la huella recibida."""
    view = parse_payload(_payload())
    content = {"title": "Título ficticio"}
    answer = edit_answer(view, content)
    assert answer == {"decision": "edit", "content": content, "fingerprint": view.fingerprint}
    assert answer["content"] is not content  # copia: la UI no comparte su diccionario


def test_discard_answer() -> None:
    """UI.md §5.3: descartar → {"decision": "discard"}."""
    assert discard_answer() == {"decision": "discard"}


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        (
            {"op": "update_story", "project": "DEMO", "key": "DEMO-3"},
            "Actualizar DEMO-3 con la versión revisada",
        ),
        (
            {"op": "create_story", "project": "DEMO", "epic": "DEMO-1"},
            "Crear una HU nueva en la épica DEMO-1",
        ),
        (
            {"op": "create_story", "project": "DEMO", "epic": ""},
            "Crear una HU nueva en el proyecto DEMO",
        ),
        (
            {"op": "link", "from": "DEMO-3", "to": "DEMO-2", "type": "relates to"},
            "Vincular DEMO-3 con DEMO-2 (relates to)",
        ),
        (
            {"op": "publish_suite", "project": "DEMO", "story": "DEMO-3", "cases": "2"},
            "Publicar 2 casos de prueba en DEMO-3",
        ),
        ({"op": "operacion_desconocida"}, "operacion_desconocida"),
    ],
    ids=["update", "create-epica", "create-proyecto", "link", "suite", "desconocida"],
)
def test_describe_operation_by_plan_op(op: dict[str, str], expected: str) -> None:
    """UI.md §5.2 · RF-31: texto de cada operación del `plan` de `core/graph/nodes._plan`."""
    assert describe_operation(op) == expected


def test_summarize_without_impact() -> None:
    """UI.md §4.4: mensaje del asistente al llegar una versión sin impacto."""
    assert summarize(parse_payload(_payload())) == (
        "Versión 1 lista. Revisa la propuesta en el panel y pídeme los cambios que quieras."
    )


def test_summarize_with_changes_and_affected_stories() -> None:
    """UI.md §4.5: nº de cambios y HU afectadas, sin repetir y ordenadas."""
    assert summarize(parse_payload(_payload(version=2, impact=_impact()))) == (
        "Versión 2 lista: 2 cambios frente a la versión de partida. "
        "Afecta también a DEMO-2, DEMO-4. "
        "Revisa la propuesta en el panel y pídeme los cambios que quieras."
    )


# --- 5 · Editar a mano (RF-32, T-51) -----------------------------------------------------------


def _story() -> UserStory:
    return dataset.renewal_story().model_copy(
        update={
            "sources": [SourceRef(kind="rag", ref="doc-reglamento", excerpt="Art. 7 ficticio.")],
            "changes_from_previous": ["Cambio ficticio anterior"],
            "related_requirements": ["RF-99-ficticio"],
        }
    )


def test_story_to_form_exposes_text_lists_criteria_and_rules() -> None:
    """RF-32: el formulario parte de la HU; listas como una línea por elemento."""
    story = _story()
    form = story_to_form(story)
    assert form["title"] == story.title
    assert form["business_goal"] == story.business_goal
    assert form["scope_includes"] == "Renovación desde la ficha del préstamo"
    assert form["assumptions"] == "La persona socia ha iniciado sesión."
    assert [ca["id"] for ca in form["criteria"]] == ["CA-01", "CA-02"]
    assert form["criteria"][0]["given"] == (
        "un préstamo activo con menos de 2 renovaciones\nsin reservas pendientes"
    )
    assert form["rules"] == [
        {"id": "RN-01", "description": "Máximo 2 renovaciones por préstamo."},
        {"id": "RN-02", "description": "No se renueva si hay reservas pendientes."},
    ]


def test_form_to_content_round_trip_with_one_change() -> None:
    """RF-32: ida y vuelta sin pérdidas; solo cambia lo editado (recortado)."""
    story = _story()
    form = story_to_form(story)
    form["title"] = "  Renovar un préstamo desde la app ficticia  "
    content = form_to_content(story, form)
    expected = story.model_copy(update={"title": "Renovar un préstamo desde la app ficticia"})
    assert UserStory.model_validate(content) == expected


def test_form_to_content_without_changes_raises() -> None:
    """RF-32 · UI.md §5.3 (error): una edición sin cambios no se envía."""
    story = _story()
    with pytest.raises(ValueError, match="No has cambiado nada de la propuesta"):
        form_to_content(story, story_to_form(story))


@pytest.mark.parametrize("title", ["", "   "])
def test_form_to_content_empty_title_raises_with_message(title: str) -> None:
    """RF-32 (error): la HU editada debe seguir siendo válida; el mensaje indica el campo."""
    story = _story()
    form = story_to_form(story)
    form["title"] = title
    with pytest.raises(ValueError, match="La HU editada no es válida: title"):
        form_to_content(story, form)


def test_form_to_content_empty_then_step_raises() -> None:
    """RF-16 · RF-32 (error): un CA sin «Entonces» no es válido."""
    story = _story()
    form = story_to_form(story)
    form["criteria"][1]["then"] = "  \n "
    with pytest.raises(ValueError, match="acceptance_criteria"):
        form_to_content(story, form)


def test_form_to_content_empty_rule_description_raises() -> None:
    """RF-17 · RF-32 (error): una RN sin descripción no es válida."""
    story = _story()
    form = story_to_form(story)
    form["rules"][0]["description"] = "   "
    with pytest.raises(ValueError, match="business_rules"):
        form_to_content(story, form)


def test_form_to_content_keeps_keys_ids_and_sources() -> None:
    """RF-32 · Trazabilidad: `jira_key`, `internal_id`, IDs de CA y RN y fuentes se conservan."""
    story = _story()
    form = story_to_form(story)
    form["description"] = "Descripción editada a mano (ficticia)."
    form["criteria"][0]["id"] = "CA-99"  # el ID no es editable: ese CA se conserva tal cual
    form["rules"][1]["id"] = "RN-77"
    edited = UserStory.model_validate(form_to_content(story, form))
    assert edited.jira_key == "DEMO-3"
    assert edited.internal_id == "HU-02"
    assert [ca.id for ca in edited.acceptance_criteria] == ["CA-01", "CA-02"]
    assert edited.acceptance_criteria == story.acceptance_criteria
    assert [rn.id for rn in edited.business_rules] == ["RN-01", "RN-02"]
    assert edited.business_rules == story.business_rules
    assert edited.sources == story.sources
    assert edited.priority == story.priority
    assert edited.changes_from_previous == story.changes_from_previous
    assert edited.related_requirements == story.related_requirements
    assert edited.description == "Descripción editada a mano (ficticia)."


def test_form_to_content_edits_criteria_rules_and_lists_line_by_line() -> None:
    """RF-32: CA, RN y listas se editan como una línea por elemento, sin líneas en blanco."""
    story = _story()
    form = story_to_form(story)
    form["assumptions"] = "Primera ficticia\n\n   \n  Segunda ficticia  "
    form["criteria"][0]["then"] = "el vencimiento se amplía 14 días (ficticio)\n"
    form["criteria"][0]["title"] = "  Renovación ficticia  "
    form["rules"][0]["description"] = "  Máximo 3 renovaciones (ficticio).  "
    edited = UserStory.model_validate(form_to_content(story, form))
    assert edited.assumptions == ["Primera ficticia", "Segunda ficticia"]
    assert edited.acceptance_criteria[0].then == ["el vencimiento se amplía 14 días (ficticio)"]
    assert edited.acceptance_criteria[0].title == "Renovación ficticia"
    assert edited.acceptance_criteria[0].given == story.acceptance_criteria[0].given
    assert edited.business_rules[0].description == "Máximo 3 renovaciones (ficticio)."


def test_form_to_content_keeps_criteria_missing_from_form() -> None:
    """RF-32 (límite): un CA que no está en el formulario se conserva tal cual."""
    story = _story()
    form = story_to_form(story)
    form["criteria"] = form["criteria"][:1]
    form["title"] = "Título editado ficticio"
    edited = UserStory.model_validate(form_to_content(story, form))
    assert edited.acceptance_criteria[1] == story.acceptance_criteria[1]


# --- 6 · Progreso y fase (UI.md §2, §4.4 y §8) -------------------------------------------------


@pytest.mark.parametrize(
    ("status", "phase"),
    [
        (None, 1),
        (ArtifactStatus.DRAFT, 2),
        (ArtifactStatus.IN_REVIEW, 2),
        (ArtifactStatus.APPROVED, 3),
        (ArtifactStatus.PUBLISHED, 4),
    ],
)
def test_phase_of_by_artifact_status(status: ArtifactStatus | None, phase: int) -> None:
    """UI.md §2: fase 1 Contexto, 2 Generar/Iterar, 3 Revisión (aprobada), 4 Publicado."""
    assert phase_of(status) == phase


def test_phase_label() -> None:
    """UI.md §2: etiqueta «Fase N de 4 · Nombre»."""
    assert phase_label(1) == "Fase 1 de 4 · Contexto"
    assert phase_label(2) == "Fase 2 de 4 · Generar"
    assert phase_label(4) == "Fase 4 de 4 · Publicado"


def test_steps_are_the_streamed_nodes() -> None:
    """UI.md §4.4 · PA-66: hoy solo se distinguen los nodos del grafo."""
    assert [step.node for step in STEPS] == ["load_origin", "retrieve_context", "generate"]


@pytest.mark.parametrize(
    ("nodes", "done"),
    [
        ([], 0),
        (["load_origin"], 1),
        (["load_origin", "retrieve_context"], 2),
        (["load_origin", "retrieve_context", "generate"], 3),
        (["generate"], 3),
        (["human_review", "publish"], 0),
    ],
)
def test_completed_steps(nodes: list[str], done: int) -> None:
    """UI.md §4.4: pasos terminados según los nodos emitidos; otros nodos no cuentan."""
    assert completed_steps(nodes) == done


@pytest.mark.parametrize(
    ("update", "nodes"),
    [
        ({"generate": {"artifact": None}}, ["generate"]),
        ({"__interrupt__": ()}, []),
        ({"retrieve_context": {}, "__interrupt__": ()}, ["retrieve_context"]),
        (None, []),
        (("generate", {}), []),
    ],
    ids=["nodo", "interrupt", "mixto", "none", "tupla"],
)
def test_nodes_in_update_ignores_interrupt(update: object, nodes: list[str]) -> None:
    """UI.md §4.4: `__interrupt__` (y lo que no es un dict) no es un paso de la generación."""
    assert nodes_in_update(update) == nodes


# --- 7 · Selector de modelo (RF-42) ------------------------------------------------------------


def _config(**keys: str) -> AppConfig:
    settings = Settings(_env_file=None, **keys)  # type: ignore[call-arg]
    return AppConfig(settings, load_models_config(MODELS_FIXTURE))


def _fake_provider(choice: ModelChoice) -> FakeLLMProvider:
    return FakeLLMProvider(provider=choice.provider, model=choice.model)


def _router(config: AppConfig) -> ModelRouter:
    return model_router(config, provider_factory=_fake_provider)


def test_selectable_tasks_are_the_proposal_tasks() -> None:
    """RF-42: el selector afecta a generar, evolucionar y revisar la HU, y a generar casos."""
    assert set(SELECTABLE_TASKS) == {
        TaskType.GENERATE_STORY,
        TaskType.EVOLVE_STORY,
        TaskType.REVIEW_STORY,
        TaskType.GENERATE_TESTS,
    }


@pytest.mark.usefixtures("clean_env")
def test_model_options_without_keys_is_only_automatic() -> None:
    """RF-42 (límite): sin claves solo queda «Modelo automático»."""
    options = model_options(_config())
    assert [(o.label, o.choice) for o in options] == [(AUTOMATIC, None)]


@pytest.mark.usefixtures("clean_env")
def test_model_options_lists_only_available_providers_after_automatic() -> None:
    """RF-42: «Modelo automático» primero y solo modelos con proveedor disponible."""
    options = model_options(_config(groq_api_key=FAKE_GROQ_KEY))
    assert options[0].label == AUTOMATIC
    assert options[0].choice is None
    assert [o.choice for o in options[1:]] == [GROQ_120B]
    assert options[1].label == "groq · openai/gpt-oss-120b"
    assert not any("openrouter" in o.label or "local" in o.label for o in options)


@pytest.mark.usefixtures("clean_env")
def test_model_options_without_duplicates_with_all_keys() -> None:
    """RF-42: cada modelo aparece una vez aunque esté en varias tareas."""
    config = _config(groq_api_key=FAKE_GROQ_KEY, openrouter_api_key=FAKE_OPENROUTER_KEY)
    options = model_options(config)
    assert [o.choice for o in options] == [None, GROQ_120B, OPENROUTER_FREE]
    assert len({o.label for o in options}) == len(options)


@pytest.mark.usefixtures("clean_env")
def test_apply_model_overrides_the_four_tasks_and_none_clears() -> None:
    """RF-42: el modelo elegido va primero en las 4 tareas; «automático» lo quita."""
    router = _router(_config(groq_api_key=FAKE_GROQ_KEY))
    before = {task: router.models_for(task) for task in TaskType}

    apply_model(router, GROQ_20B)

    for task in SELECTABLE_TASKS:
        assert router.models_for(task) == [GROQ_20B, *before[task]]
    for task in set(TaskType) - set(SELECTABLE_TASKS):
        assert router.models_for(task) == before[task]

    apply_model(router, None)

    assert {task: router.models_for(task) for task in TaskType} == before


@pytest.mark.usefixtures("clean_env")
def test_apply_model_unavailable_provider_raises_and_changes_nothing() -> None:
    """RF-42 (error): un proveedor sin clave se rechaza y no deja overrides a medias."""
    router = _router(_config(groq_api_key=FAKE_GROQ_KEY))
    before = {task: router.models_for(task) for task in TaskType}
    with pytest.raises(ValueError, match="no está disponible"):
        apply_model(router, OPENROUTER_FREE)
    assert {task: router.models_for(task) for task in TaskType} == before


# --- 8 · Animaciones y texto no fiable (UI.md §8, PA-44) ---------------------------------------


@pytest.mark.parametrize(("phase", "y"), [(1, 244.5), (2, 163.0), (3, 81.5), (4, 0.0)])
def test_phase_q_fills_a_quarter_per_phase(phase: int, y: float) -> None:
    """UI.md §8 #1: el `rect` del `clipPath` se traslada a 244,5 / 163 / 81,5 / 0."""
    html = phase_q(phase)
    assert f"translateY({y:.1f}px)" in html
    assert f'aria-label="Avance: fase {phase} de 4"' in html
    assert ".42s" in html and "cubic-bezier(.2,.7,.2,1)" in html


def test_phase_q_animates_from_previous_phase() -> None:
    """UI.md §8 #1: la Q sube desde la fase anterior."""
    html = phase_q(2, previous=1)
    assert "from{transform:translateY(244.5px)}to{transform:translateY(163.0px)}" in html


def test_phase_q_ignores_out_of_range_previous() -> None:
    """UI.md §8 (límite): una fase anterior fuera de rango no anima (parte de la actual)."""
    html = phase_q(3, previous=9)
    assert "from{transform:translateY(81.5px)}to{transform:translateY(81.5px)}" in html


@pytest.mark.parametrize("phase", [0, 5, -1])
def test_phase_q_rejects_invalid_phase(phase: int) -> None:
    """UI.md §8 (error): la fase es un entero validado entre 1 y 4."""
    with pytest.raises(ValueError, match="La fase debe estar entre 1 y 4"):
        phase_q(phase)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"phase": "<script>alert(1)</script>"},
        {"phase": 2, "previous": "<img src=x>"},
        {"phase": 2, "size": "<b>ficticio</b>"},
    ],
    ids=["fase", "anterior", "tamano"],
)
def test_phase_q_does_not_accept_free_text(kwargs: dict[str, Any]) -> None:
    """UI.md §8 · PA-44 (seguridad): `phase_q` no admite texto libre en ningún parámetro."""
    with pytest.raises((TypeError, ValueError)):
        phase_q(**kwargs)


@pytest.mark.parametrize("html", [phase_q(1), phase_q(4, previous=3), typing_q()])
def test_animations_respect_reduced_motion_and_have_no_script(html: str) -> None:
    """UI.md §8: se desactivan con «reducir movimiento» y no llevan JavaScript."""
    assert "@media (prefers-reduced-motion: reduce)" in html
    assert "animation:none!important" in html
    lowered = html.lower()
    assert "<script" not in lowered and "javascript:" not in lowered and "onload" not in lowered


def test_typing_q_is_a_status_with_text() -> None:
    """UI.md §8 #3: «Escribiendo la respuesta» accesible (role=status) con la Q parpadeando."""
    html = typing_q()
    assert 'role="status"' in html
    assert "Escribiendo la respuesta" in html
    assert "qa-blink" in html


@pytest.mark.parametrize(
    ("text", "forbidden"),
    [
        ("![x](http://e)", ["![", "]("]),
        ("<b>hola</b>", ["<b>", "</b>"]),
        ("[a](b)", ["[a]", "]("]),
        ("**negrita** y __subrayado__", ["**", "__"]),
    ],
)
def test_md_escape_neutralizes_markdown(text: str, forbidden: list[str]) -> None:
    """UI.md §1 (seguridad): el texto no fiable no cuela imágenes, enlaces, HTML ni formato."""
    escaped = md_escape(text)
    for fragment in forbidden:
        assert fragment not in escaped
    assert re.sub(r"\\(.)", r"\1", escaped) == text  # solo añade barras: el texto se conserva


def test_md_escape_exact_output_for_image() -> None:
    """UI.md §1: `![x](http://e)` queda como texto literal (también `:`)."""
    assert md_escape("![x](http://e)") == r"\!\[x\]\(http\://e\)"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$x$", r"\$x\$"),
        ("Título\n===", "Título\n\\=\\=\\="),
        (":material/home:", r"\:material/home\:"),
    ],
    ids=["formula", "setext", "icono"],
)
def test_md_escape_neutralizes_formulas_setext_and_icons(text: str, expected: str) -> None:
    """UI.md §1 (seguridad): `$` (fórmulas), `=` (encabezado setext) y `:` (iconos)."""
    escaped = md_escape(text)
    assert escaped == expected
    assert re.sub(r"\\(.)", r"\1", escaped) == text


def test_md_escape_accepts_non_strings() -> None:
    """Límite: valores no textuales se convierten a texto."""
    assert md_escape(21) == "21"
    assert md_escape(None) == "None"


def test_md_lines_escapes_each_item() -> None:
    """UI.md §4.5: listas de viñetas con cada elemento escapado."""
    assert md_lines(["a*b", "[x](y)"]) == "- a\\*b\n- \\[x\\]\\(y\\)"
    assert md_lines([]) == ""


# --- 9 · Seguridad estática de app/ ------------------------------------------------------------


def _app_files() -> list[Path]:
    files = sorted(APP_DIR.rglob("*.py"))
    assert files, "no se encontraron módulos en app/"
    return files


def _trees() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in _app_files()
    ]


def test_app_never_uses_unsafe_allow_html() -> None:
    """UI.md §1 · PA-44 (seguridad): ningún widget de app/ usa `unsafe_allow_html`."""
    for path, tree in _trees():
        assert "unsafe_allow_html=" not in path.read_text(encoding="utf-8"), path
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword):
                assert node.arg != "unsafe_allow_html", path
            if isinstance(node, ast.Constant):
                assert node.value != "unsafe_allow_html", path


def test_app_html_only_renders_own_animations() -> None:
    """UI.md §8 · PA-44 (seguridad): `st.html` solo recibe `phase_q(...)` o `typing_q(...)`."""
    allowed = {"phase_q", "typing_q"}
    calls = 0
    for path, tree in _trees():
        text = path.read_text(encoding="utf-8")
        textual = re.findall(r"\.html\(\s*(\w*)", text)
        assert set(textual) <= allowed, f"{path}: {textual}"
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "html":
                continue
            calls += 1
            assert len(node.args) == 1 and not node.keywords, path
            (arg,) = node.args
            assert isinstance(arg, ast.Call), path
            assert isinstance(arg.func, ast.Name) and arg.func.id in allowed, path
    assert calls >= 1, "se esperaba al menos una animación en st.html"


def test_app_does_not_use_streamlit_components() -> None:
    """UI.md §8 (seguridad): sin componentes con JavaScript (`streamlit.components`)."""
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("streamlit.components"), path
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("streamlit.components") for a in node.names)
            if isinstance(node, ast.Attribute):
                assert node.attr != "components", path


def test_app_never_calls_jira_write_methods() -> None:
    """Principio 1 · UI.md §5.7: la UI nunca escribe en Jira (solo el nodo `publish`)."""
    writes = {"create_story", "update_story", "link", "publish_suite"}
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in writes, f"{path}: {node.func.attr}"


def test_app_imports_only_protocols_errors_and_router_from_adapters() -> None:
    """CLAUDE.md · PROMPT-06 §1: app/ no instancia adaptadores concretos ni importa tests."""
    allowed = {"adapters.base", "adapters.errors", "adapters.llm.router"}
    seen: set[str] = set()
    for path, tree in _trees():
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                assert not module.startswith("tests"), f"{path}: {module}"
                if module.startswith("adapters"):
                    assert module in allowed, f"{path}: {module}"
                    seen.add(module)
    assert "adapters.base" in seen  # los Protocol y tipos (p. ej. `User`) sí se usan


# --- 10 · Mensajes de error para la UI ---------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        AgentError("Mensaje de dominio ficticio."),
        ExternalServiceError("Jira no responde (ficticio).", service="jira"),
        NotFoundError("La incidencia DEMO-99 no existe.", service="jira"),
        RateLimitError("Límite de uso ficticio alcanzado.", service="fake"),
        ApprovalError("La aprobación ficticia no corresponde."),
        ReviewRejectedError("Respuesta de revisión rechazada (ficticia)."),
    ],
    ids=["agent", "external", "notfound", "ratelimit", "approval", "review"],
)
def test_message_for_domain_errors_returns_their_message(exc: Exception) -> None:
    """SPEC-00 §8 · UI.md §7: las excepciones del dominio muestran su mensaje en español."""
    assert message_for(exc) == str(exc)


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("detalle interno ficticio"),
        KeyError("clave"),
        TypeError("tipo"),
        ValueError("Escribe la clave de la HU de Jira, por ejemplo DEMO-3."),
    ],
    ids=["runtime", "key", "type", "value-sin-traceback"],
)
def test_message_for_other_errors_returns_generic(exc: Exception) -> None:
    """UI.md §7 (seguridad): otros errores (y un ValueError sin traceback) dan el genérico."""
    assert message_for(exc) == UNEXPECTED
    assert str(exc) not in message_for(exc)


def test_message_for_empty_domain_message_returns_generic() -> None:
    """UI.md §7 (límite): un error del dominio sin mensaje muestra el genérico."""
    assert message_for(AgentError()) == UNEXPECTED
    assert message_for(ValueError("")) == UNEXPECTED


def test_message_for_pydantic_validation_error_returns_generic() -> None:
    """Seguridad: un `ValidationError` (subclase de ValueError) no expone su detalle."""
    with pytest.raises(ValidationError) as raised:
        UserStory.model_validate({})
    assert isinstance(raised.value, ValueError)
    assert message_for(raised.value) == UNEXPECTED


@pytest.mark.parametrize(
    "exc",
    [
        json.JSONDecodeError("Expecting value", '{"ficticio": ', 13),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["json", "unicode"],
)
def test_message_for_internal_value_errors_returns_generic(exc: ValueError) -> None:
    """Seguridad: errores de decodificación (ValueError) muestran el mensaje genérico."""
    assert isinstance(exc, ValueError)
    assert message_for(exc) == UNEXPECTED


# --- 11 · Permisos antes de ejecutar (UI.md §3: `require`) -------------------------------------


def _need_conversation(owner: str = AF_USER.username) -> Conversation:
    return Conversation(request=fix_origin("need", "DEMO", text=NEED_TEXT), user=owner)


def test_authorize_functional_owner_on_need_is_allowed() -> None:
    """UI.md §3: el analista dueño de la conversación puede ejecutar el flujo de HU."""
    authorize(AF_USER, _need_conversation())


def test_authorize_qa_owner_on_tests_is_allowed() -> None:
    """UI.md §3: QA puede ejecutar el flujo de pruebas de su conversación."""
    conv = Conversation(request=fix_origin("tests", "DEMO", key="DEMO-3"), user=QA_USER.username)
    authorize(QA_USER, conv)


@pytest.mark.parametrize("actor", [QA_USER, ADMIN_USER, None], ids=["qa", "admin", "anonimo"])
def test_authorize_without_flow_permission_raises(actor: User | None) -> None:
    """UI.md §3 (error): sin el permiso del flujo → «No tienes permiso para realizar…»."""
    with pytest.raises(AuthenticationError, match="No tienes permiso para realizar esta acción"):
        authorize(actor, _need_conversation())


def test_authorize_functional_on_tests_flow_raises() -> None:
    """UI.md §3 (error): el analista no ejecuta el flujo de pruebas."""
    conv = Conversation(request=fix_origin("tests", "DEMO", key="DEMO-3"), user=AF_USER.username)
    with pytest.raises(AuthenticationError, match="No tienes permiso"):
        authorize(AF_USER, conv)


def test_authorize_other_person_raises() -> None:
    """Seguridad (error): otra persona con el mismo rol no ejecuta una conversación ajena."""
    other = User(username="af-otra-demo", role="functional")
    with pytest.raises(AuthenticationError, match="Esta conversación es de otra persona"):
        authorize(other, _need_conversation())


def test_conversation_is_not_started_by_default() -> None:
    """Mixta 2b: `started` es False hasta llamar a `start`."""
    assert _need_conversation().started is False


# --- 12 · Lista blanca de `message_for` con errores reales (UI.md §7, T-24) ---------------------


def _raised(fn: Any, *args: Any, **kwargs: Any) -> Exception:
    """La excepción que lanza `fn` de verdad, con su traceback."""
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # se devuelve para inspeccionarla
        return exc
    raise AssertionError("se esperaba una excepción")


def _raise_internal_value_error() -> None:
    raise ValueError("secreto interno ficticio")


class _OwnValueError(ValueError):
    """Subclase propia de ValueError para simular pydantic/json lanzados en `core.projects`."""


def test_message_for_value_error_from_core_projects_shows_its_message() -> None:
    """UI.md §7 · T-50: un ValueError exacto de `core.projects` muestra su mensaje."""
    exc = _raised(normalize_issue_key, "x")
    assert type(exc) is ValueError
    assert message_for(exc) == str(exc)
    assert "no es una clave de Jira válida" in message_for(exc)


def test_message_for_value_error_from_initial_state_shows_its_message() -> None:
    """UI.md §7 · T-51: el ValueError de `core.graph.state.initial_state` muestra su mensaje."""
    origin: Origin = {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    exc = _raised(initial_state, AF_USER.username, "functional", origin, ["DEMO-3"])
    assert message_for(exc) == str(exc)
    assert "no se puede excluir" in message_for(exc)


def test_message_for_value_error_from_app_origin_shows_its_message() -> None:
    """UI.md §7 · §4.1: el ValueError de `app.origin.fix_origin` muestra su mensaje."""
    exc = _raised(fix_origin, "evolve", "DEMO")
    assert message_for(exc) == KEY_REQUIRED


def test_message_for_value_error_raised_in_other_module_is_generic() -> None:
    """UI.md §7 (seguridad): un ValueError lanzado fuera de la lista blanca → UNEXPECTED."""
    exc = _raised(_raise_internal_value_error)
    assert type(exc) is ValueError
    assert message_for(exc) == UNEXPECTED
    assert "secreto" not in message_for(exc)


def test_message_for_value_error_from_builtin_is_generic() -> None:
    """UI.md §7 (seguridad): `int("x")` (sin frame de la lista blanca) → UNEXPECTED."""
    exc = _raised(int, "no-es-un-numero")
    assert message_for(exc) == UNEXPECTED


def test_message_for_value_error_subclass_in_core_projects_is_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI.md §7 (seguridad): subclase de ValueError lanzada en core.projects → genérico."""
    monkeypatch.setattr(core_projects, "ValueError", _OwnValueError, raising=False)
    exc = _raised(normalize_issue_key, "x")
    assert type(exc) is _OwnValueError
    assert message_for(exc) == UNEXPECTED


def test_message_for_review_rejected_and_approval_errors_show_message() -> None:
    """UI.md §5.3 · §7: `ReviewRejectedError` y `ApprovalError` (subclases) sí muestran texto."""
    assert message_for(ReviewRejectedError("Huella ficticia no válida.")) == (
        "Huella ficticia no válida."
    )
    assert message_for(ApprovalError("Aprobación ficticia caducada.")) == (
        "Aprobación ficticia caducada."
    )


@pytest.mark.parametrize(
    "exc",
    [KeyError("clave-ficticia"), RuntimeError("detalle interno ficticio")],
    ids=["key", "runtime"],
)
def test_message_for_raised_non_value_errors_are_generic(exc: Exception) -> None:
    """UI.md §7 (seguridad): KeyError/RuntimeError lanzados de verdad → UNEXPECTED."""

    def boom() -> None:
        raise exc

    assert message_for(_raised(boom)) == UNEXPECTED


# --- 13 · Lista de conversaciones (app/listing.py, UI.md §2, T-52) -----------------------------


def _summary(**update: Any) -> ConversationSummary:
    row = new_summary(
        thread_id="hilo-ficticio-1",
        username=AF_USER.username,
        project="DEMO",
        mode="functional",
        origin_kind="story",
        origin_key="DEMO-3",
    )
    return row.model_copy(update=update)


@pytest.mark.parametrize(
    ("update", "label"),
    [
        ({"status": "in_review", "version": 2}, "Versión 2"),
        ({"status": "in_review", "version": None}, "En revisión"),
        ({"status": "simulated"}, "Simulado"),
        ({"status": "published"}, "Publicado"),
        ({"status": "started"}, "Empezada"),
        ({"status": "approved"}, "Aprobada"),
        ({"status": "discarded"}, "Descartada"),
    ],
    ids=["v2", "sin-version", "simulated", "published", "started", "approved", "discarded"],
)
def test_status_label_by_status(update: dict[str, Any], label: str) -> None:
    """UI.md §2 y §9 · T-52: etiqueta del estado de cada conversación en la barra lateral."""
    assert status_label(_summary(**update)) == label


@pytest.mark.parametrize(
    ("mode", "kind", "label"),
    [
        ("functional", "need", "Nueva necesidad"),
        ("functional", "epic", "Nueva necesidad"),
        ("functional", "story", "Evolucionar una HU"),
        ("qa", "story", "Preparar pruebas"),
        ("qa", "need", "Conversación"),
    ],
)
def test_flow_label_by_mode_and_origin(mode: str, kind: str, label: str) -> None:
    """UI.md §2 · T-52: el flujo de la conversación; combinación desconocida → «Conversación»."""
    assert flow_label(_summary(mode=mode, origin_kind=kind)) == label


def test_day_label_today_yesterday_and_date() -> None:
    """UI.md §2: grupos «Hoy», «Ayer» y fecha dd/mm/aaaa."""
    today = date(2026, 3, 10)
    assert day_label(today, today) == "Hoy"
    assert day_label(date(2026, 3, 9), today) == "Ayer"
    assert day_label(date(2026, 3, 1), today) == "01/03/2026"
    assert day_label(date(2025, 12, 31), date(2026, 1, 1)) == "Ayer"


def test_new_summary_title_has_no_free_text() -> None:
    """T-52: el título se compone con flujo y clave, sin texto libre."""
    assert _summary().title == "Evolucionar DEMO-3"


def test_group_by_day_keeps_order_and_groups_consecutive() -> None:
    """UI.md §2 · T-52: agrupa por día en el orden recibido; días no consecutivos no se unen."""
    tz = datetime.now().astimezone().tzinfo
    today = date(2026, 3, 10)

    def at(day: int, hour: int, tid: str) -> ConversationSummary:
        return _summary(thread_id=tid, updated_at=datetime(2026, 3, day, hour, tzinfo=tz))

    rows = [at(10, 12, "a"), at(10, 9, "b"), at(9, 20, "c"), at(5, 8, "d"), at(10, 1, "e")]
    groups = group_by_day(rows, today=today)
    assert [(label, [r.thread_id for r in g]) for label, g in groups] == [
        ("Hoy", ["a", "b"]),
        ("Ayer", ["c"]),
        ("05/03/2026", ["d"]),
        ("Hoy", ["e"]),
    ]
    assert group_by_day([], today=today) == []


# --- 14 · Fuentes y tarjeta de HU (app/sources.py, UI.md §4.3, T-53) ---------------------------


def _issue(description: str, parent: str | None = "DEMO-1") -> IssueDetail:
    return IssueDetail(
        key="DEMO-9",
        summary="HU ficticia",
        issue_type="Story",
        status="Por hacer",
        parent_key=parent,
        description_text=description,
    )


def test_issue_card_counts_distinct_criteria_and_rules() -> None:
    """UI.md §4.3 · PA-56: CA y RN distintos de la descripción; los repetidos cuentan una vez."""
    text = "CA-01 y CA-02; otra vez CA-01. RN-01 aplica. CA-1x no cuenta. XCA-03 tampoco."
    card = issue_card(_issue(text))
    assert card == IssueCard(
        key="DEMO-9", summary="HU ficticia", epic="DEMO-1", criteria=2, rules=1
    )


def test_issue_card_without_description_or_epic() -> None:
    """UI.md §4.3 (límite): sin descripción (vacía o None) → 0 CA y 0 RN; sin padre → sin épica."""
    card = issue_card(_issue("", parent=None))
    assert (card.criteria, card.rules, card.epic) == (0, 0, None)
    # `description_text` es str en el modelo; `model_construct` simula un None de un adaptador.
    raw = IssueDetail.model_construct(**{**_issue("").model_dump(), "description_text": None})
    assert (issue_card(raw).criteria, issue_card(raw).rules) == (0, 0)


def test_describe_card_with_and_without_epic() -> None:
    """UI.md §4.3: «épica DEMO-1 · 2 CA · 1 RN» o «sin épica · …»."""
    card = IssueCard(key="DEMO-9", summary="HU ficticia", epic="DEMO-1", criteria=2, rules=1)
    assert describe_card(card) == "épica DEMO-1 · 2 CA · 1 RN"
    assert describe_card(IssueCard("DEMO-9", "HU", None, 0, 0)) == "sin épica · 0 CA · 0 RN"


@pytest.mark.parametrize(
    ("source", "label"),
    [
        (
            SourcePreview(
                ref="doc-reglamento", kind="rag", title="Reglamento", category="politicas"
            ),
            "doc-reglamento · Reglamento · politicas · Documento",
        ),
        (
            SourcePreview(ref="doc-glosario", kind="rag", title="Glosario"),
            "doc-glosario · Glosario · Documento",
        ),
        (
            SourcePreview(ref="mem-ficticia", kind="memory", title="Memoria de DEMO-2"),
            "mem-ficticia · Memoria de DEMO-2 · Memoria · prioritaria",
        ),
        (
            SourcePreview(
                ref="DEMO-3", kind="jira", title="Renovar", category="Story", required=True
            ),
            "DEMO-3 · Renovar · Story · Jira · origen, obligatoria",
        ),
    ],
    ids=["categoria", "sin-categoria", "memoria", "obligatoria"],
)
def test_source_label(source: SourcePreview, label: str) -> None:
    """UI.md §4.3 · T-53: etiqueta de cada fuente del panel «Antes de generar»."""
    assert source_label(source) == label


def test_excluded_refs_never_excludes_required_and_is_sorted() -> None:
    """T-51 · UI.md §4.3: solo las desmarcadas, ordenadas; la obligatoria nunca se excluye."""
    sources = [
        SourcePreview(ref="DEMO-3", kind="jira", title="Origen", required=True),
        SourcePreview(ref="doc-reglamento", kind="rag", title="Reglamento"),
        SourcePreview(ref="DEMO-2", kind="jira", title="Reservar"),
        SourcePreview(ref="doc-glosario", kind="rag", title="Glosario"),
    ]
    checked = {"DEMO-3": False, "doc-reglamento": False, "DEMO-2": False}  # glosario: por defecto
    assert excluded_refs(sources, checked) == ["DEMO-2", "doc-reglamento"]
    assert excluded_refs(sources, {}) == []


# --- 15 · Arranque guiado en la UI (app/origin.py, UI.md §4.1–4.3, T-53) -----------------------


def _issue_summary(key: str, kind: str = "Story") -> IssueSummary:
    return IssueSummary(key=key, summary=f"HU ficticia {key}", issue_type=kind, status="Por hacer")


def _option(
    kind: str, key: str | None = None, project: str = "DEMO", text: str = ""
) -> StartOption:
    if kind == "new_need":
        return StartOption(
            kind="new_need",
            label="Crear HU nueva",
            origin={"kind": "need", "text": text, "project": project},
        )
    origin_kind = "epic" if kind == "new_story_in_epic" else "story"
    return StartOption(
        kind=kind,  # type: ignore[arg-type]
        label=f"Opción ficticia {key}",
        origin={"kind": origin_kind, "key": key, "project": project},  # type: ignore[typeddict-item]
        issue=_issue_summary(key or "", "Epic" if origin_kind == "epic" else "Story"),
    )


def _proposal(
    options: list[StartOption],
    recognized: list[str] | None = None,
    project: str = "DEMO",
    changed: bool = False,
    ignored: list[str] | None = None,
) -> StartProposal:
    return StartProposal(
        project=project,
        project_changed=changed,
        ignored_projects=ignored or [],
        recognized=[_issue_summary(k) for k in recognized or []],
        similar=[],
        options=options,
    )


def _guided(tmp_path: Path, tracker: FakeIssueTracker | None = None) -> GuidedStart:
    return GuidedStart(fake_container(tmp_path, issue_tracker=tracker or FakeIssueTracker()))


def _tracker_with_other_project() -> FakeIssueTracker:
    tracker = FakeIssueTracker()
    tracker.issues["OTRO-7"] = IssueDetail(
        key="OTRO-7", summary="HU ficticia de otro proyecto", issue_type="Story", status="Por hacer"
    )
    return tracker


def test_plan_start_recognized_key_chooses_first_option() -> None:
    """UI.md §4.1 · T-53: con claves reconocidas, la primera opción y las demás alternativas."""
    first, second = _option("evolve", "DEMO-3"), _option("evolve", "DEMO-4")
    plan = plan_start("evolve", _proposal([first, second], ["DEMO-3", "DEMO-4"]), "DEMO")
    assert plan == StartPlan(chosen=first, alternatives=[second], notices=[], error=None)


def test_plan_start_recognized_key_with_real_guided_start(tmp_path: Path) -> None:
    """T-53: con `GuidedStart.propose` real, «demo-3 y DEMO-4» → DEMO-3 y alternativa DEMO-4."""
    proposal = _guided(tmp_path).propose("Quiero evolucionar demo-3 y DEMO-4", "DEMO")
    plan = plan_start("evolve", proposal, "DEMO")
    assert plan.error is None
    assert plan.chosen is not None and plan.chosen.origin.get("key") == "DEMO-3"
    assert [o.origin.get("key") for o in plan.alternatives] == ["DEMO-4"]
    assert plan.notices == []


def test_plan_start_project_changed_notice_mentions_both_projects(tmp_path: Path) -> None:
    """UI.md §4.1 · T-50: una clave de otro proyecto avisa del cambio de proyecto."""
    guided = _guided(tmp_path, _tracker_with_other_project())
    proposal = guided.propose("Evolucionar otro-7", "DEMO")
    assert proposal.project_changed and proposal.project == "OTRO"
    plan = plan_start("evolve", proposal, "DEMO")
    assert plan.chosen is not None and plan.chosen.origin.get("key") == "OTRO-7"
    assert len(plan.notices) == 1
    assert "DEMO" in plan.notices[0] and "OTRO" in plan.notices[0]


def test_plan_start_ignored_projects_notice_lists_them(tmp_path: Path) -> None:
    """UI.md §4.1 · T-53: claves de otros proyectos sin opción se avisan por su proyecto."""
    guided = _guided(tmp_path, _tracker_with_other_project())
    proposal = guided.propose("DEMO-3 y OTRO-7", "DEMO")
    assert proposal.ignored_projects == ["OTRO"]
    plan = plan_start("evolve", proposal, "DEMO")
    assert plan.chosen is not None and plan.chosen.origin.get("key") == "DEMO-3"
    assert plan.alternatives == []
    assert len(plan.notices) == 1 and "OTRO" in plan.notices[0]
    assert "un solo proyecto" in plan.notices[0]


def test_plan_start_notices_from_hand_built_proposal() -> None:
    """UI.md §4.1: los dos avisos a la vez, en orden (cambio de proyecto, claves ignoradas)."""
    option = _option("evolve", "OTRO-7", project="OTRO")
    proposal = _proposal([option], ["OTRO-7"], project="OTRO", changed=True, ignored=["ZETA"])
    plan = plan_start("evolve", proposal, "DEMO")
    assert len(plan.notices) == 2
    assert "pasa de DEMO a OTRO" in plan.notices[0]
    assert "ZETA" in plan.notices[1]


def test_plan_start_need_without_key_chooses_new_need_and_offers_similar(tmp_path: Path) -> None:
    """UI.md §4.3 · T-53: necesidad sin clave → «Crear HU nueva» y las HU parecidas."""
    proposal = _guided(tmp_path).propose("renovar", "DEMO")
    plan = plan_start("need", proposal, "DEMO")
    assert plan.error is None
    assert plan.chosen is not None and plan.chosen.kind == "new_need"
    assert [o.origin.get("key") for o in plan.alternatives] == ["DEMO-3"]
    assert all(o.kind == "evolve" for o in plan.alternatives)


@pytest.mark.parametrize(("flow", "mode"), [("evolve", "functional"), ("tests", "qa")])
def test_plan_start_key_flow_without_key_offers_similar_to_choose(
    tmp_path: Path, flow: Any, mode: Any
) -> None:
    """UI.md §4.1 · T-53: Evolucionar/Preparar pruebas sin clave → elegir entre las parecidas."""
    proposal = _guided(tmp_path).propose("renovar", "DEMO", mode)
    plan = plan_start(flow, proposal, "DEMO")
    assert plan.chosen is None and plan.error is None
    assert [o.origin.get("key") for o in plan.alternatives] == ["DEMO-3"]
    assert all(o.kind != "new_need" for o in plan.alternatives)


@pytest.mark.parametrize("flow", ["evolve", "tests"])
def test_plan_start_without_anything_requires_key(flow: Any) -> None:
    """UI.md §4.1 (error): sin clave ni parecidas → «Escribe la clave de la HU…»."""
    plan = plan_start(flow, _proposal([]), "DEMO")
    assert (plan.chosen, plan.alternatives, plan.error) == (None, [], KEY_REQUIRED)


def test_plan_start_need_without_text_requires_text(tmp_path: Path) -> None:
    """UI.md §4.1 (error): una necesidad sin texto → «Describe la necesidad…»."""
    plan = plan_start("need", _guided(tmp_path).propose("   ", "DEMO"), "DEMO")
    assert (plan.chosen, plan.error) == (None, NEED_TEXT_REQUIRED)


def test_plan_start_tests_with_epic_needs_story(tmp_path: Path) -> None:
    """UI.md §6.1 (error): en QA una épica reconocida → «El modo QA parte siempre de una HU…»."""
    proposal = _guided(tmp_path).propose("Pruebas de demo-1", "DEMO", "qa")
    assert [i.key for i in proposal.recognized] == ["DEMO-1"]
    plan = plan_start("tests", proposal, "DEMO")
    assert (plan.chosen, plan.error) == (None, QA_NEEDS_STORY)


def test_plan_start_evolve_with_epic_is_not_allowed(tmp_path: Path) -> None:
    """UI.md §4.2 (error): Evolucionar con una épica → «Para este flujo elige una HU…»."""
    plan = plan_start("evolve", _guided(tmp_path).propose("Evolucionar DEMO-1", "DEMO"), "DEMO")
    assert (plan.chosen, plan.error) == (None, EPIC_NOT_ALLOWED)


def test_plan_start_need_with_epic_chooses_new_story_in_epic(tmp_path: Path) -> None:
    """UI.md §4.2 · T-53: en una necesidad, una épica reconocida → «Nueva HU en DEMO-1»."""
    plan = plan_start("need", _guided(tmp_path).propose("Nueva HU en demo-1", "DEMO"), "DEMO")
    assert plan.chosen is not None and plan.chosen.kind == "new_story_in_epic"


def test_request_from_option_evolve() -> None:
    """T-53: opción «Evolucionar DEMO-3» → evolución de la HU con el texto escrito."""
    request = request_from_option("evolve", _option("evolve", "DEMO-3"), "DEMO-3 renovar")
    assert (request.flow, request.kind, request.key, request.project) == (
        "evolve",
        "story",
        "DEMO-3",
        "DEMO",
    )
    assert request.text == "DEMO-3 renovar"


def test_request_from_option_new_story_in_epic() -> None:
    """T-53 · UI.md §4.2: «Nueva HU en DEMO-1» → necesidad con la épica de origen."""
    request = request_from_option("need", _option("new_story_in_epic", "DEMO-1"), "con avisos")
    assert (request.flow, request.kind, request.key) == ("need", "epic", "DEMO-1")
    assert request.describe() == "Crear una HU nueva en la épica DEMO-1"


def test_request_from_option_tests_is_qa() -> None:
    """T-53 · UI.md §6.1: «Preparar pruebas de DEMO-3» → flujo de pruebas en modo QA."""
    request = request_from_option("tests", _option("tests", "DEMO-3"))
    assert (request.flow, request.kind, request.key, request.mode) == (
        "tests",
        "story",
        "DEMO-3",
        "qa",
    )


def test_request_from_option_new_need_uses_origin_text() -> None:
    """T-53: «Crear HU nueva» → necesidad con el texto del `origin` (manda sobre el escrito)."""
    request = request_from_option("need", _option("new_need", text=NEED_TEXT), "otro texto")
    assert (request.flow, request.kind, request.key, request.text) == (
        "need",
        "need",
        None,
        NEED_TEXT,
    )


def test_request_from_option_need_flow_with_story_becomes_evolution() -> None:
    """UI.md §4.3: en una necesidad, elegir una HU parecida es evolucionarla."""
    request = request_from_option("need", _option("evolve", "DEMO-3"), NEED_TEXT)
    assert (request.flow, request.kind, request.key) == ("evolve", "story", "DEMO-3")


@pytest.mark.parametrize(
    ("origin", "mode", "expected"),
    [
        (
            {"kind": "story", "key": "DEMO-3", "project": "DEMO"},
            "functional",
            ("evolve", "story", "DEMO-3", ""),
        ),
        (
            {"kind": "story", "key": "DEMO-3", "project": "DEMO"},
            "qa",
            ("tests", "story", "DEMO-3", ""),
        ),
        (
            {"kind": "need", "project": "DEMO", "text": NEED_TEXT},
            "functional",
            ("need", "need", None, NEED_TEXT),
        ),
        (
            {"kind": "epic", "key": "DEMO-1", "project": "DEMO", "text": "ignorado"},
            "functional",
            ("need", "epic", "DEMO-1", ""),
        ),
    ],
    ids=["story", "qa", "need", "epic"],
)
def test_request_from_state(origin: Any, mode: Any, expected: tuple[Any, ...]) -> None:
    """T-52: el `StartRequest` de una conversación retomada sale del estado del grafo."""
    request = request_from_state(origin, mode, ["doc-glosario"])
    assert (request.flow, request.kind, request.key, request.text) == expected
    assert request.project == "DEMO"
    assert request.excluded_sources == ("doc-glosario",)


def test_preview_origin_ignores_restrictions() -> None:
    """UI.md §4.3: la vista previa de fuentes no lleva las restricciones (no cambian el RAG)."""
    request = with_restrictions(fix_origin("need", "DEMO", text=NEED_TEXT), RESTRICTIONS)
    assert preview_origin(request) == {"kind": "need", "project": "DEMO", "text": NEED_TEXT}
    assert "Restricciones" in build_origin(request)["text"]
    evolve = with_restrictions(fix_origin("evolve", "DEMO", key="DEMO-3"), RESTRICTIONS)
    assert preview_origin(evolve) == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}


def test_with_excluded_and_restrictions_keep_other_fields() -> None:
    """T-51: `with_excluded` y `with_restrictions` no tocan flujo, clave, proyecto ni texto."""
    base = fix_origin("evolve", "DEMO", key="DEMO-3", text="DEMO-3 renovar")
    excluded = with_excluded(with_restrictions(base, RESTRICTIONS), ["doc-glosario"])
    restricted = with_restrictions(with_excluded(base, ["doc-glosario"]), RESTRICTIONS)
    for request in (excluded, restricted):
        assert (request.flow, request.kind, request.project, request.key, request.text) == (
            base.flow,
            base.kind,
            base.project,
            base.key,
            base.text,
        )
        assert request.restrictions == RESTRICTIONS
        assert request.excluded_sources == ("doc-glosario",)


# --- 16 · Límite de intentos de inicio de sesión (app/session.py, RF-45) -----------------------


def test_login_four_failures_do_not_lock() -> None:
    """RF-45 · UI.md §7: 4 fallos seguidos no bloquean el formulario."""
    session = SessionState()
    for _ in range(MAX_LOGIN_ATTEMPTS - 1):
        record_login_failure(session, now=1000.0)
    assert session.failed_logins == 4
    assert login_locked(session, now=1000.0) is False


def test_login_fifth_failure_locks_for_lock_seconds() -> None:
    """RF-45 (límite): el 5.º fallo bloquea `LOGIN_LOCK_SECONDS`; pasado ese tiempo, se libera."""
    session = SessionState()
    for _ in range(MAX_LOGIN_ATTEMPTS):
        record_login_failure(session, now=1000.0)
    assert login_locked(session, now=1000.0) is True
    assert login_locked(session, now=1000.0 + LOGIN_LOCK_SECONDS - 0.001) is True
    assert login_locked(session, now=1000.0 + LOGIN_LOCK_SECONDS) is False
    assert session.failed_logins == 0  # el contador vuelve a empezar tras el bloqueo


def test_login_success_resets_failures_and_lock() -> None:
    """RF-45: un inicio de sesión correcto pone a cero los fallos y quita el bloqueo."""
    session = SessionState()
    for _ in range(MAX_LOGIN_ATTEMPTS - 1):
        record_login_failure(session, now=1000.0)
    record_login_success(session, AF_USER)
    assert (session.failed_logins, session.user) == (0, AF_USER)
    record_login_failure(session, now=1000.0)
    assert login_locked(session, now=1000.0) is False  # vuelve a necesitar 5 fallos

    locked = SessionState()
    for _ in range(MAX_LOGIN_ATTEMPTS):
        record_login_failure(locked, now=1000.0)
    record_login_success(locked, AF_USER)
    assert login_locked(locked, now=1000.0) is False


def test_message_for_value_error_from_app_review_shows_its_message() -> None:
    """UI.md §4.5 (error): la petición de cambio vacía se explica a la persona (lista blanca)."""
    with pytest.raises(ValueError) as raised:
        iterate_answer("   ")
    assert message_for(raised.value) == "Escribe qué quieres cambiar de la propuesta."


@pytest.mark.usefixtures("clean_env")
def test_message_for_value_error_from_model_router_shows_its_message() -> None:
    """RF-42 · UI.md §7: el rechazo del selector de modelo se explica (lista blanca)."""
    router = _router(_config(groq_api_key=FAKE_GROQ_KEY))
    exc = _raised(apply_model, router, OPENROUTER_FREE)
    assert type(exc) is ValueError
    assert message_for(exc) == str(exc)
    assert "no está disponible" in message_for(exc)


def test_message_for_value_error_from_manual_edit_shows_its_message() -> None:
    """RF-32 · UI.md §4.5: «Editar a mano» sin cambios se explica a la persona (lista blanca)."""
    story = _story()
    exc = _raised(form_to_content, story, story_to_form(story))
    assert message_for(exc) == "No has cambiado nada de la propuesta."


# --- T-31 · Recibo de aprobación y resultado (UI.md §4.5–4.7, §5, §6.4–6.5) ------------------

UPDATE_OP = {"op": "update_story", "project": "DEMO", "key": "DEMO-3"}
LINK_OP = {"op": "link", "from": "DEMO-3", "to": "DEMO-2", "type": "relates to"}
CREATE_OP = {"op": "create_story", "project": "DEMO", "epic": "DEMO-1"}
SUITE_OP = {"op": "publish_suite", "project": "DEMO", "story": "DEMO-3", "cases": "5"}


def _view(
    plan: list[dict[str, str]],
    version: int = 3,
    impact: ImpactAnalysis | None = None,
) -> ReviewView:
    payload = _payload(version=version, impact=impact)
    payload["plan"] = plan
    return parse_payload(payload)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (
            {"operation": "actualizar HU", "project": "DEMO", "jira_key": "DEMO-3"},
            "Actualizar DEMO-3 · proyecto DEMO",
        ),
        (
            {"operation": "crear HU", "project": "DEMO", "jira_key": None, "epic_key": "DEMO-1"},
            "Crear una HU nueva en la épica DEMO-1 · proyecto DEMO",
        ),
        (
            {"operation": "crear HU", "project": "DEMO", "jira_key": None, "epic_key": None},
            "Crear una HU nueva · proyecto DEMO",
        ),
        (
            {"operation": "publicar casos de prueba", "project": "DEMO", "jira_key": "DEMO-3"},
            "Publicar los casos de prueba de DEMO-3 · proyecto DEMO",
        ),
    ],
    ids=["actualizar", "crear-en-epica", "crear-en-proyecto", "qa"],
)
def test_describe_target_is_readable_text(target: dict[str, str | None], expected: str) -> None:
    """UI.md §4.6 · T-31: `PublishTarget.describe()` se muestra como texto, nunca como dict."""
    text = describe_target(target)
    assert text == expected
    assert "{" not in text


def test_describe_target_unknown_operation_or_empty_is_kept() -> None:
    """UI.md §4.6 (límite): operación desconocida se muestra tal cual; vacía → texto vacío."""
    assert describe_target({"operation": "operación ficticia"}) == "operación ficticia"
    assert describe_target({}) == ""


def test_parse_payload_with_target_dict_gives_text_and_target_info() -> None:
    """UI.md §5.1 · T-31: `target` dict → `view.target` legible y `target_info` con el dict."""
    payload = _payload()
    payload["target"] = {
        "operation": "actualizar HU",
        "project": "DEMO",
        "jira_key": "DEMO-3",
        "epic_key": None,
    }
    view = parse_payload(payload)
    assert view.target == "Actualizar DEMO-3 · proyecto DEMO"
    assert view.target_info == payload["target"]


def test_parse_payload_with_target_str_is_kept_for_compatibility() -> None:
    """UI.md §5.1 (compatibilidad): un `target` en texto se conserva y no hay `target_info`."""
    view = parse_payload(_payload())
    assert view.target == "Evolucionar DEMO-3 (ficticio)"
    assert view.target_info is None


def test_approve_answer_returns_decision_and_exact_fingerprint() -> None:
    """UI.md §5.3–5.4 · T-31: aprobar = `{"decision": "approve", "fingerprint": <recibida>}`."""
    view = _view([UPDATE_OP])
    assert approve_answer(view) == {"decision": "approve", "fingerprint": view.fingerprint}


def test_receipt_items_update_story_lists_changed_fields_and_comment() -> None:
    """UI.md §4.6 · RF-31: «Actualizar DEMO-3 con la versión N» con los campos cambiados."""
    (item,) = receipt_items(_view([UPDATE_OP], version=3, impact=_impact()))
    assert item.text == "Actualizar DEMO-3 con la versión 3"
    assert item.detail == "Cambia: título, descripción. Se añade un comentario con los cambios."


def test_receipt_items_update_story_without_impact_only_mentions_comment() -> None:
    """UI.md §4.6 (límite): sin `impact` el detalle solo menciona el comentario."""
    (item,) = receipt_items(_view([UPDATE_OP], version=1))
    assert item.text == "Actualizar DEMO-3 con la versión 1"
    assert item.detail == "Se añade un comentario con los cambios."


def test_receipt_items_update_story_truncates_many_changed_fields() -> None:
    """UI.md §4.6 (límite): más de 8 campos cambiados → los 8 primeros y «y N más»."""
    impact = ImpactAnalysis(
        diffs=[StoryDiff(field=f"campo_{n}", before="a", after="b") for n in range(10)],
        affected=[],
        regression_notes=[],
    )
    (item,) = receipt_items(_view([UPDATE_OP], impact=impact))
    assert "campo_7 y 2 más." in item.detail
    assert "campo_8" not in item.detail


def test_receipt_items_create_story_in_epic() -> None:
    """UI.md §4.6 · RF-31: crear HU en la épica, con la versión revisada."""
    (item,) = receipt_items(_view([CREATE_OP]))
    assert item.text == "Crear una HU nueva en la épica DEMO-1"
    assert item.detail == "Con la versión revisada."


def test_receipt_items_link_carries_reason_from_impact() -> None:
    """UI.md §4.6: «Vincular con DEMO-2 (relates to)» con el motivo de `impact.affected`."""
    (item,) = receipt_items(_view([LINK_OP], impact=_impact()))
    assert item.text == "Vincular con DEMO-2 (relates to)"
    assert item.detail == "Comparte la RN de reservas Otro motivo ficticio"
    assert "Historial ficticio" not in item.detail  # el motivo de DEMO-4 no se mezcla


def test_receipt_items_link_without_impact_has_no_reason() -> None:
    """UI.md §4.6 (límite): sin `impact` el vínculo no lleva motivo."""
    (item,) = receipt_items(_view([LINK_OP]))
    assert item.detail == ""


def test_receipt_items_publish_suite_is_split_in_three() -> None:
    """UI.md §6.4 · D-09: subtareas «caso-prueba», `estrategia-<CLAVE>.md` y `matriz-<CLAVE>.md`."""
    items = receipt_items(_view([SUITE_OP]))
    assert [item.text for item in items] == [
        "Crear 5 subtareas en DEMO-3 con la etiqueta «caso-prueba»",
        "Adjuntar estrategia-DEMO-3.md",
        "Adjuntar matriz-DEMO-3.md",
    ]
    assert "prioridad" in items[0].detail
    assert items[2].detail == "Cobertura CA/RN ↔ CP."


def test_receipt_items_unknown_operation_is_shown_by_name() -> None:
    """UI.md §5.2 (límite): una operación desconocida tiene su casilla con su nombre."""
    (item,) = receipt_items(_view([{"op": "operacion_ficticia"}]))
    assert item.text == "operacion_ficticia"
    assert item.id == "0-operacion_ficticia"


def test_receipt_items_ids_are_unique_and_stable() -> None:
    """UI.md §4.6: un id por casilla, único y estable para la misma versión."""
    view = _view([UPDATE_OP, LINK_OP, {**LINK_OP, "to": "DEMO-4"}, SUITE_OP], impact=_impact())
    first, second = receipt_items(view), receipt_items(view)
    ids = [item.id for item in first]
    assert ids == [item.id for item in second]
    assert len(ids) == len(set(ids)) == 6
    assert ids == [
        "0-update",
        "1-link-DEMO-2",
        "2-link-DEMO-4",
        "3-cases",
        "3-strategy",
        "3-matrix",
    ]


def test_receipt_items_empty_plan_has_no_items() -> None:
    """UI.md §4.6 (límite): sin operaciones no hay casillas."""
    assert receipt_items(_view([])) == []


def test_receipt_progress_counts_checked_items() -> None:
    """UI.md §4.6 y §5.5: «N de M revisadas» → «Todo revisado» solo con todas marcadas."""
    items = [ReceiptItem("a", "Uno"), ReceiptItem("b", "Dos"), ReceiptItem("c", "Tres")]
    assert receipt_progress(items, {}) == (0, False)
    assert receipt_progress(items, {"a": True, "b": False}) == (1, False)
    assert receipt_progress(items, {"a": True, "c": True, "otra": True}) == (2, False)
    assert receipt_progress(items, {"a": True, "b": True, "c": True}) == (3, True)


def test_receipt_progress_without_items_cannot_approve() -> None:
    """UI.md §4.6 (límite): sin operaciones no se puede aprobar."""
    assert receipt_progress([], {"a": True}) == (0, False)


def test_source_count_counts_cited_sources() -> None:
    """UI.md §4.6: «Generado con IA a partir de N fuentes»."""
    payload = _payload()
    payload["artifact"]["content"]["sources"] = [
        {"kind": "rag", "ref": "doc-reglamento"},
        {"kind": "jira", "ref": "DEMO-2"},
    ]
    assert source_count(parse_payload(payload)) == 2
    assert source_count(_view([])) == 0


def _marks_impact(*diffs: StoryDiff) -> ImpactAnalysis:
    return ImpactAnalysis(diffs=list(diffs), affected=[], regression_notes=[])


def test_change_marks_changed_and_new_items() -> None:
    """UI.md §4.5 · PA-73: «Cambiado en vN» si había `before`, «Nueva» si no."""
    impact = _marks_impact(
        StoryDiff(field="acceptance_criteria[CA-02]", before="Antes ficticio", after="Después"),
        StoryDiff(field="acceptance_criteria[CA-03]", before=None, after="CA nuevo ficticio"),
        StoryDiff(field="business_rules[RN-03]", before=None, after="RN nueva ficticia"),
        StoryDiff(field="business_rules[RN-01]", before="Máx. 2", after="Máx. 3 (ficticio)"),
    )
    assert change_marks(_view([UPDATE_OP], version=2, impact=impact)) == {
        "CA-02": "Cambiado en v2",
        "CA-03": "Nueva",
        "RN-03": "Nueva",
        "RN-01": "Cambiado en v2",
    }


def test_change_marks_ignore_removed_and_other_fields() -> None:
    """UI.md §4.5 (límite): los eliminados (after None) y los campos que no son CA/RN no marcan."""
    impact = _marks_impact(
        StoryDiff(field="acceptance_criteria[CA-01]", before="CA quitado ficticio", after=None),
        StoryDiff(field="title", before="Renovar", after="Renovar un préstamo"),
        StoryDiff(field="acceptance_criteria", before="a", after="b"),
        StoryDiff(field="scope_includes[0]", before=None, after="Nuevo alcance ficticio"),
    )
    assert change_marks(_view([UPDATE_OP], impact=impact)) == {}


def test_change_marks_without_impact_is_empty() -> None:
    """UI.md §4.5 (límite): sin `impact` (versión 1 de una necesidad) no hay marcas."""
    assert change_marks(_view([UPDATE_OP])) == {}


def _artifact(status: ArtifactStatus, version: int = 2, *, suite: bool = False) -> Artifact:
    return Artifact(
        id=uuid4(),
        type=ArtifactType.TEST_SUITE if suite else ArtifactType.USER_STORY,
        status=status,
        version=version,
        origin_key="DEMO-3",
        content=renewal_test_suite() if suite else dataset.renewal_story(),
        created_by=AF_USER.username,
    )


def _state(
    artifact: Artifact | None, decision: str | None = "approve", **values: Any
) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "decision": decision,
        "published_keys": [],
        "errors": [],
        **values,
    }


def test_outcome_simulated_when_approved_without_keys_or_errors() -> None:
    """UI.md §4.7 · T-25: `APPROVED` sin claves ni errores → simulado; la aprobación sigue."""
    approved = _view([UPDATE_OP, LINK_OP], version=2)
    outcome = outcome_from_state(_state(_artifact(ArtifactStatus.APPROVED)), approved, "af-demo")
    assert outcome is not None
    assert outcome.kind == "simulated"
    assert (outcome.version, outcome.approved_by) == (2, "af-demo")
    assert outcome.operations == [
        "Actualizar DEMO-3 con la versión revisada",
        "Vincular DEMO-3 con DEMO-2 (relates to)",
    ]
    assert (outcome.published_keys, outcome.errors, outcome.message) == ([], [], None)
    assert outcome.story is True


def test_outcome_published_when_status_published() -> None:
    """UI.md §4.7 (real): `PUBLISHED` con sus claves → publicado."""
    values = _state(_artifact(ArtifactStatus.PUBLISHED), published_keys=["DEMO-3"])
    outcome = outcome_from_state(values, _view([UPDATE_OP]), "af-demo")
    assert outcome is not None
    assert outcome.kind == "published"
    assert outcome.published_keys == ["DEMO-3"]


def test_outcome_partial_when_published_with_errors() -> None:
    """UI.md §6.5 · RNF-13: publicado con `errors` (vínculo fallido) → en parte."""
    values = _state(
        _artifact(ArtifactStatus.PUBLISHED),
        published_keys=["DEMO-3"],
        errors=["No se pudo vincular DEMO-3 con DEMO-2."],
    )
    outcome = outcome_from_state(values, _view([UPDATE_OP, LINK_OP]), "af-demo")
    assert outcome is not None
    assert outcome.kind == "partial"
    assert outcome.errors == ["No se pudo vincular DEMO-3 con DEMO-2."]


def test_outcome_partial_qa_suite_approved_with_errors_and_keys() -> None:
    """UI.md §6.5 · T-30: una suite con fallos sigue `APPROVED` con claves y errores → en parte."""
    values = _state(
        _artifact(ArtifactStatus.APPROVED, suite=True),
        published_keys=["DEMO-501"],
        errors=["No se pudo publicar CP-02."],
    )
    outcome = outcome_from_state(values, _view([SUITE_OP]), "qa-demo")
    assert outcome is not None
    assert outcome.kind == "partial"
    assert outcome.story is False
    assert outcome.operations == ["Publicar 5 casos de prueba en DEMO-3"]


@pytest.mark.parametrize(
    "values",
    [
        {"published_keys": ["DEMO-501"]},
        {"errors": ["No se pudo publicar CP-01."]},
    ],
    ids=["solo-claves", "solo-errores"],
)
def test_outcome_partial_qa_suite_with_keys_or_errors(values: dict[str, list[str]]) -> None:
    """UI.md §6.5 (límite): una suite `APPROVED` con claves o con errores ya es «en parte»."""
    state = _state(_artifact(ArtifactStatus.APPROVED, suite=True), **values)
    outcome = outcome_from_state(state, _view([SUITE_OP]), "qa-demo")
    assert outcome is not None and outcome.kind == "partial"


def test_outcome_published_without_memory_carries_failure() -> None:
    """PA-251 · UI.md §4.7: publicado y la memoria falla → `published_without_memory` + motivo."""
    values = _state(_artifact(ArtifactStatus.PUBLISHED), published_keys=["DEMO-3"])
    outcome = outcome_from_state(
        values, _view([UPDATE_OP]), "af-demo", failure="Memoria ficticia caída."
    )
    assert outcome is not None
    assert outcome.kind == "published_without_memory"
    assert outcome.message == "Memoria ficticia caída."


def test_outcome_simulated_suite_is_not_a_story() -> None:
    """UI.md §6.5: el resultado de una suite no promete memoria (`story` False)."""
    state = _state(_artifact(ArtifactStatus.APPROVED, suite=True))
    outcome = outcome_from_state(state, _view([SUITE_OP]), "qa-demo")
    assert outcome is not None
    assert (outcome.kind, outcome.story) == ("simulated", False)


@pytest.mark.parametrize("decision", ["iterate", "discard", "edit", None])
def test_outcome_is_none_when_not_approved(decision: str | None) -> None:
    """UI.md §4.7 (negativa): sin `decision == "approve"` no hay resultado."""
    state = _state(_artifact(ArtifactStatus.APPROVED), decision=decision)
    assert outcome_from_state(state, _view([UPDATE_OP]), "af-demo") is None


def test_outcome_is_none_without_artifact() -> None:
    """UI.md §4.7 (negativa): sin artefacto en el estado no hay resultado."""
    assert outcome_from_state(_state(None), _view([UPDATE_OP]), "af-demo") is None
    assert outcome_from_state({}, _view([UPDATE_OP]), "af-demo") is None


@pytest.mark.parametrize(
    "status", [ArtifactStatus.IN_REVIEW, ArtifactStatus.DRAFT, ArtifactStatus.DISCARDED]
)
def test_outcome_is_none_for_status_not_approved(status: ArtifactStatus) -> None:
    """UI.md §4.7 (negativa): un artefacto que no está aprobado ni publicado no da resultado."""
    assert outcome_from_state(_state(_artifact(status)), _view([UPDATE_OP]), "af-demo") is None


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("title", "título"),
        ("acceptance_criteria[CA-03]", "CA-03"),
        ("business_rules[RN-01]", "RN-01"),
        ("sources[jira:DEMO-2]", "fuentes"),
        ("campo_raro", "campo_raro"),
    ],
)
def test_field_label_is_readable(field: str, expected: str) -> None:
    """UI.md §4.6: el recibo nombra los campos cambiados en español o por su ID de CA/RN."""
    assert field_label(field) == expected


# --- Mixta 5 · Revisar la calidad (app/quality.py, app/origin.py · UI.md §4.8, T-48, RF-18) ----


def _invest(improvable: str = "") -> list[InvestCheck]:
    """Seis valoraciones ficticias, desordenadas a propósito (T, S, E, V, N, I)."""
    return [
        InvestCheck(
            letter=letter,  # type: ignore[arg-type]
            verdict="improvable" if letter in improvable else "ok",
            reason=f"Motivo ficticio de {letter}.",
        )
        for letter in ("T", "S", "E", "V", "N", "I")
    ]


def _finding(target: str | None = "CA-02", kind: str = "ambiguity") -> QualityFinding:
    about = target or "la HU"
    return QualityFinding(
        kind=kind,  # type: ignore[arg-type]
        target_id=target,
        explanation=f"Explicación ficticia sobre {about}.",
        proposal=f"Propuesta ficticia para {about}.",
    )


def _quality(findings: list[QualityFinding] | None = None, improvable: str = "T") -> QualityReport:
    return QualityReport(
        summary="Resumen ficticio de la calidad.",
        invest=_invest(improvable),
        findings=findings or [],
    )


def _review(report: QualityReport, key: str = "DEMO-3") -> QualityReview:
    return QualityReview(
        jira_key=key,
        report=report,
        story=dataset.renewal_story(key),
        provider="fake",
        model="modelo-ficticio",
        prompt_version="1",
        input_tokens=1,
        output_tokens=1,
    )


def test_review_steps_are_three_and_mention_two_model_calls() -> None:
    """UI.md §4.8: el progreso enumera leer el contexto y las dos llamadas al modelo."""
    assert len(REVIEW_STEPS) == 3
    assert sum("llamada al modelo" in step for step in REVIEW_STEPS) == 2


def test_invest_rows_six_in_invest_order_with_spanish_names() -> None:
    """UI.md §4.8 · RF-18: seis filas I N V E S T en orden con los nombres de INVEST_NAMES."""
    rows = invest_rows(_quality(improvable="NT"))
    assert [row.letter for row in rows] == ["I", "N", "V", "E", "S", "T"]
    assert [row.name for row in rows] == [INVEST_NAMES[letter] for letter in "INVEST"]
    assert all(isinstance(row, InvestRow) for row in rows)
    assert rows[0] == InvestRow("I", "Independiente", "Bien", "Motivo ficticio de I.")


def test_invest_rows_verdicts_are_bien_or_mejorable() -> None:
    """UI.md §4.8: «ok» → «Bien» e «improvable» → «Mejorable»; nunca el valor en inglés."""
    rows = {row.letter: row.verdict for row in invest_rows(_quality(improvable="NT"))}
    assert rows == {
        "I": "Bien",
        "N": "Mejorable",
        "V": "Bien",
        "E": "Bien",
        "S": "Bien",
        "T": "Mejorable",
    }


def test_finding_rows_use_spanish_label_and_target_id() -> None:
    """UI.md §4.8 · RF-18: cada hallazgo con su etiqueta de FINDING_LABELS y su CA/RN."""
    report = _quality([_finding("CA-02"), _finding("RN-01", kind="inconsistency")])
    assert finding_rows(report) == [
        FindingRow(
            kind=FINDING_LABELS["ambiguity"],
            target="CA-02",
            explanation="Explicación ficticia sobre CA-02.",
            proposal="Propuesta ficticia para CA-02.",
        ),
        FindingRow(
            kind="Incoherencia con las fuentes",
            target="RN-01",
            explanation="Explicación ficticia sobre RN-01.",
            proposal="Propuesta ficticia para RN-01.",
        ),
    ]


@pytest.mark.parametrize("kind", sorted(FINDING_LABELS))
def test_finding_rows_label_for_each_kind_without_target_is_hu(kind: str) -> None:
    """UI.md §4.8 (límite): sin `target_id` el hallazgo es de la «HU»; todas las etiquetas."""
    (row,) = finding_rows(_quality([_finding(None, kind=kind)]))
    assert row.kind == FINDING_LABELS[kind]
    assert row.target == "HU"


def test_finding_rows_empty_without_findings() -> None:
    """UI.md §4.8 (límite): un informe sin hallazgos no da filas."""
    assert finding_rows(_quality([])) == []


@pytest.mark.parametrize(
    ("count", "points"),
    [(0, "ningún punto a mejorar"), (1, "1 punto a mejorar"), (3, "3 puntos a mejorar")],
    ids=["cero", "uno", "varios"],
)
def test_review_message_counts_findings_and_says_nothing_changed(count: int, points: str) -> None:
    """UI.md §4.8: el mensaje cuenta los hallazgos y siempre dice que no ha cambiado Jira."""
    findings = [_finding(f"CA-0{i + 1}") for i in range(count)]
    message = review_message(_review(_quality(findings), key="DEMO-4"))
    assert message.startswith("He revisado DEMO-4 con INVEST")
    assert f"Hay {points}." in message
    assert message.endswith("No he cambiado nada en Jira.")


def test_report_filename_uses_the_key() -> None:
    """UI.md §4.8 · PA-64: el informe se descarga como `calidad-<clave>.md`."""
    assert report_filename("DEMO-3") == "calidad-DEMO-3.md"


def test_report_download_is_escaped_markdown_in_utf8() -> None:
    """PA-64: *Descargar informe* = `to_markdown(clave)` en UTF-8 (con tildes ficticias)."""
    review = _review(renewal_quality_report())
    data = report_download(review)
    assert isinstance(data, bytes)
    assert data == review.report.to_markdown("DEMO-3").encode("utf-8")
    text = data.decode("utf-8")
    assert text.startswith("# Calidad de DEMO-3")
    assert "Ambigüedad" in text


def test_report_download_escapes_markdown_from_the_llm() -> None:
    """PA-64 (seguridad): un enlace o imagen del LLM llega escapado al `.md` descargable."""
    finding = QualityFinding(
        kind="gap",
        explanation="Ver ![img](https://ejemplo.invalid/x.png)",
        proposal="[pulsa](https://ejemplo.invalid)",
    )
    text = report_download(_review(_quality([finding]))).decode("utf-8")
    assert "![img](" not in text and "[pulsa](" not in text
    assert "\\!\\[img\\]" in text


def test_evolve_request_opens_evolution_with_report_proposals() -> None:
    """UI.md §4.8 · T-48: «Evolucionar con esto» → evolución de la clave con las propuestas."""
    review = _review(_quality([_finding("CA-02"), _finding(None, kind="gap")]))
    request = evolve_request(review, "DEMO")
    assert (request.flow, request.kind, request.key, request.project) == (
        "evolve",
        "story",
        "DEMO-3",
        "DEMO",
    )
    assert request.extra_feedback == tuple(review.evolve_feedback())
    assert request.extra_feedback == (
        "CA-02: Propuesta ficticia para CA-02.",
        "Propuesta ficticia para la HU.",
    )
    feedback = build_initial_state("af-demo", request)["feedback"]
    assert all(item in feedback for item in review.evolve_feedback())


def test_evolve_request_key_of_other_project_changes_project() -> None:
    """UI.md §4.8 · decisión del día 6: el proyecto sale de la clave, no del que se pasa."""
    request = evolve_request(_review(_quality([_finding()]), key="OTRO-7"), "DEMO")
    assert (request.key, request.project) == ("OTRO-7", "OTRO")


def test_evolve_request_without_findings_has_no_extra_feedback() -> None:
    """UI.md §4.8 (límite): sin hallazgos, la evolución empieza sin feedback previo."""
    request = evolve_request(_review(_quality([])), "DEMO")
    assert request.extra_feedback == ()
    assert build_initial_state("af-demo", request)["feedback"] == []


def test_evolve_request_with_real_reviewer_and_fake_llm(tmp_path: Path) -> None:
    """T-48 · RF-18: `QualityReviewer` con el fake LLM y la evolución con sus propuestas."""
    container = fake_container(tmp_path)
    review = QualityReviewer(container).review(AF_USER, "DEMO-3")
    assert review.jira_key == "DEMO-3"
    assert [row.letter for row in invest_rows(review.report)] == list("INVEST")
    rows = finding_rows(review.report)
    assert [(row.kind, row.target) for row in rows] == [("Ambigüedad", "CA-02"), ("Hueco", "HU")]
    assert "Hay 2 puntos a mejorar." in review_message(review)
    request = evolve_request(review, "DEMO")
    state = build_initial_state("af-demo", request)
    assert state["feedback"] == list(review.evolve_feedback())
    assert "CA-02: Avisar en menos de 15 minutos." in state["feedback"]
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker) and tracker.writes == []


def test_describe_review_is_read_only_operation() -> None:
    """UI.md §4.8: la operación fijada de la revisión dice que es de solo lectura."""
    request = fix_origin("review", "DEMO", key="demo-4")
    assert (request.flow, request.kind, request.key, request.mode) == (
        "review",
        "story",
        "DEMO-4",
        "functional",
    )
    assert request.describe() == "Revisar la calidad de DEMO-4 (solo lectura, no publica)"


def test_request_from_option_review_keeps_review_flow() -> None:
    """UI.md §4.8 · T-53: la opción «evolve» de `GuidedStart` en el flujo review sigue en review."""
    request = request_from_option("review", _option("evolve", "DEMO-3"), "Revisar DEMO-3")
    assert (request.flow, request.kind, request.key, request.project) == (
        "review",
        "story",
        "DEMO-3",
        "DEMO",
    )
    assert request.describe().startswith("Revisar la calidad de DEMO-3")


def test_request_from_option_review_with_epic_raises() -> None:
    """UI.md §4.8 (negativa): una épica no se puede revisar como HU."""
    with pytest.raises(ValueError, match=EPIC_NOT_ALLOWED):
        request_from_option("review", _option("new_story_in_epic", "DEMO-1"))


def test_build_feedback_story_appends_extra_feedback_after_restrictions() -> None:
    """T-48 · T-51: en una HU, lo pedido, las restricciones y después las propuestas previas."""
    request = StartRequest(
        flow="evolve",
        kind="story",
        project="DEMO",
        key="DEMO-3",
        text="DEMO-3 renovar desde la app",
        restrictions=RESTRICTIONS,
        extra_feedback=("CA-02: propuesta ficticia.", "Otra propuesta ficticia."),
    )
    assert build_feedback(request) == [
        "renovar desde la app",
        RESTRICTIONS,
        "CA-02: propuesta ficticia.",
        "Otra propuesta ficticia.",
    ]


def test_build_feedback_need_returns_only_extra_feedback() -> None:
    """T-48 · UI.md §4.3: en una necesidad las restricciones van al texto; solo va el extra."""
    common: dict[str, Any] = {"flow": "need", "kind": "need", "project": "DEMO"}
    request = StartRequest(
        **common, text=NEED_TEXT, restrictions=RESTRICTIONS, extra_feedback=("Propuesta.",)
    )
    assert build_feedback(request) == ["Propuesta."]
    assert build_feedback(StartRequest(**common, text=NEED_TEXT, restrictions=RESTRICTIONS)) == []


def test_plan_start_review_with_recognized_key_chooses_review(tmp_path: Path) -> None:
    """UI.md §4.8 · T-53: «Revisar DEMO-3» en el flujo review elige DEMO-3 y sigue en review."""
    proposal = _guided(tmp_path).propose("Revisar DEMO-3", "DEMO")
    plan = plan_start("review", proposal, "DEMO")
    assert plan.error is None
    assert plan.chosen is not None and plan.chosen.origin.get("key") == "DEMO-3"
    request = request_from_option("review", plan.chosen, "Revisar DEMO-3")
    assert (request.flow, request.key) == ("review", "DEMO-3")


def test_plan_start_review_with_epic_is_not_allowed(tmp_path: Path) -> None:
    """UI.md §4.8 (negativa): en el flujo review, una épica da EPIC_NOT_ALLOWED."""
    plan = plan_start("review", _guided(tmp_path).propose("Revisar DEMO-1", "DEMO"), "DEMO")
    assert plan.chosen is None
    assert plan.error == EPIC_NOT_ALLOWED


def test_plan_start_review_without_anything_requires_key() -> None:
    """UI.md §4.8 (negativa): sin clave ni HU parecidas, se pide la clave."""
    plan = plan_start("review", _proposal([]), "DEMO")
    assert (plan.chosen, plan.error) == (None, KEY_REQUIRED)


def test_evolve_request_keeps_sources_excluded_while_reviewing(tmp_path: Path) -> None:
    """UI.md §4.8: las fuentes desmarcadas al revisar siguen fuera al evolucionar con el informe."""
    review = QualityReviewer(fake_container(tmp_path)).review(AF_USER, "DEMO-3")
    request = evolve_request(review, "DEMO", ("doc-glosario",))
    assert request.excluded_sources == ("doc-glosario",)
    assert build_initial_state(AF_USER.username, request)["excluded_sources"] == ["doc-glosario"]
