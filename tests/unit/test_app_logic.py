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
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from adapters.base import TaskType, User
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
from app.models import AUTOMATIC, SELECTABLE_TASKS, apply_model, model_options
from app.origin import (
    StartRequest,
    build_feedback,
    build_initial_state,
    build_origin,
    change_request,
    find_issue_key,
    fix_origin,
    with_excluded,
    with_restrictions,
)
from app.progress import STEPS, completed_steps, nodes_in_update, phase_label, phase_of
from app.review import (
    describe_operation,
    discard_answer,
    edit_answer,
    iterate_answer,
    parse_payload,
    pending_from_result,
    pending_from_state,
    summarize,
)
from app.text import md_escape, md_lines
from core.approvals import ApprovalError
from core.config import ROOT_DIR, AppConfig, Settings, load_models_config
from core.factories import model_router
from core.permissions import Permission
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem, StoryDiff
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.llm import FakeLLMProvider

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


def test_flow_cards_functional_review_is_pending_t48() -> None:
    """UI.md §3: Revisar la calidad está permitida al analista pero llega con T-48."""
    card = _cards(AF_USER)["review"]
    assert card.allowed is True
    assert card.enabled is False
    assert card.hint == f"{card.flow.hint} Disponible pronto (T-48)."


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("quiero evolucionar demo-3 cuanto antes", "DEMO-3"),
        ("Revisar DEMO-12 y luego DEMO-4", "DEMO-12"),
        ("Partir de Otro_2-7 (ficticio)", "OTRO_2-7"),
        ("Necesito avisos por correo antes del vencimiento", None),
        ("", None),
        ("versión 2-3 del documento", None),
        ("clave corta A-1 no válida", None),
    ],
)
def test_find_issue_key_in_free_text(text: str, expected: str | None) -> None:
    """T-53 parcial · UI.md §4.1: reconoce la primera clave del texto y la normaliza."""
    assert find_issue_key(text) == expected


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


def test_fix_origin_evolve_with_key_in_text() -> None:
    """UI.md §4.1: «Evolucionar una HU» reconoce la clave escrita (minúsculas → normalizada)."""
    request = fix_origin("evolve", "DEMO", text="Cambiar demo-3: renovar desde la app")
    assert request.flow == "evolve"
    assert request.kind == "story"
    assert request.key == "DEMO-3"
    assert request.project == "DEMO"
    assert request.describe() == "Evolucionar DEMO-3"


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
    in_text = fix_origin("evolve", "DEMO", text="Evolucionar otro-7 (ficticio)")
    assert (in_text.project, in_text.key) == ("OTRO", "OTRO-7")
    explicit = fix_origin("need", "DEMO", key="OTRO-5", kind="epic")
    assert (explicit.project, explicit.key) == ("OTRO", "OTRO-5")


def test_fix_origin_tests_flow_is_qa_mode() -> None:
    """UI.md §6.1: Preparar pruebas parte de una HU y trabaja en modo QA."""
    request = fix_origin("tests", "DEMO", text="Casos de prueba para DEMO-3")
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
    request = fix_origin("evolve", "DEMO", text="DEMO-3 permitir renovar desde la app ficticia")
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
    assert change_request(fix_origin("evolve", "DEMO", text=text)) == expected


def test_change_request_of_need_is_normalized_text() -> None:
    """Límite: sin clave, `change_request` es el texto normalizado."""
    request = fix_origin("need", "DEMO", text="  Avisar   por correo ficticio.  ")
    assert change_request(request) == "Avisar por correo ficticio"


def test_build_feedback_with_change_request_and_restrictions() -> None:
    """T-51 · RF-20: con clave de origen, lo pedido y las restricciones van como feedback."""
    request = with_restrictions(
        fix_origin("evolve", "DEMO", text="DEMO-3: añadir la renovación por app."), RESTRICTIONS
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
    assert build_feedback(fix_origin("evolve", "DEMO", text="DEMO-3")) == []


def test_build_feedback_need_never_has_feedback() -> None:
    """UI.md §4.3: en una necesidad todo va a `origin.text`; el feedback queda vacío."""
    request = with_restrictions(fix_origin("need", "DEMO", text=NEED_TEXT), RESTRICTIONS)
    assert build_feedback(request) == []


@pytest.mark.parametrize(
    ("prefer", "expected"),
    [("DEMO", "DEMO-3"), (" demo ", "DEMO-3"), (None, "UTF-8"), ("OTRO", "UTF-8"), ("", "UTF-8")],
    ids=["proyecto", "minusculas", "sin-preferencia", "proyecto-ausente", "vacio"],
)
def test_find_issue_key_prefers_project_of_conversation(prefer: str | None, expected: str) -> None:
    """T-53 parcial: «UTF-8» no gana a la clave real del proyecto; si no hay, la primera."""
    assert find_issue_key("Exportar en UTF-8 la HU DEMO-3", prefer_project=prefer) == expected


def test_fix_origin_prefers_key_of_selected_project() -> None:
    """T-50 · T-53 parcial: con el proyecto DEMO elegido, «UTF-8» no cambia el proyecto."""
    request = fix_origin("evolve", "DEMO", text="UTF-8 en DEMO-3")
    assert (request.key, request.project) == ("DEMO-3", "DEMO")


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
        ValueError("Escribe la clave de la HU de Jira, por ejemplo DEMO-3."),
        ApprovalError("La aprobación ficticia no corresponde."),
    ],
    ids=["agent", "external", "notfound", "ratelimit", "value", "approval"],
)
def test_message_for_domain_errors_returns_their_message(exc: Exception) -> None:
    """SPEC-00 §8 · UI.md §7: las excepciones del dominio muestran su mensaje en español."""
    assert message_for(exc) == str(exc)


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("detalle interno ficticio"), KeyError("clave"), TypeError("tipo")],
    ids=["runtime", "key", "type"],
)
def test_message_for_other_errors_returns_generic(exc: Exception) -> None:
    """UI.md §7 (seguridad): otros errores no exponen detalles internos."""
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
