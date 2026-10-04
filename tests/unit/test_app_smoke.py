"""Prueba de humo de la UI «Propuesta mixta» con `streamlit.testing.v1.AppTest` (PA-74, T-24).

Se ejecuta `app/main.py` de verdad con la composición sustituida por los fakes:
`build_config` y `model_router` → None, `build_app_container` → `fake_container(...,
publish_mode="simulation", require_actor=True)` y `shared_checkpointer` → `memory_checkpointer()`.
Recorrido: login → Mixta 1 (texto con clave) → Mixta 2 (fuentes) → generar → Mixta 3.
Nunca se escribe en Jira (principio 1). Solo fakes y datos 100 % ficticios.
"""

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.errors import AppTestError

import app.session as app_session
import core.quality as core_quality
from adapters.base import ProjectSummary
from adapters.errors import ExternalServiceError, RateLimitError
from app.conversation import UNEXPECTED
from app.session import LOGIN_LOCKED, MAX_LOGIN_ATTEMPTS, SessionState, login_locked
from app.text import md_escape
from core.approvals import ApprovalError
from core.config import ROOT_DIR
from core.container import Container
from core.graph import memory_checkpointer
from core.handoff import InMemoryHandoffStore
from core.quality import InMemoryQualityReviewStore, StoredQualityReview, new_review
from schemas.quality import INVEST_NAMES
from schemas.test_case import TestSuite
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement

MAIN = str(ROOT_DIR / "app" / "main.py")
LOGIN_BUTTON = "FormSubmitter:login-Entrar"
EVOLVE_TEXT = "Quiero evolucionar demo-3: renovar desde la app"
EPIC_TEXT = "Nueva HU en demo-1: avisar del vencimiento (ficticio)"
COMPOSE_FAILURE = "No se pudo preparar el almacén de conversaciones en PostgreSQL."


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path, publish_mode="simulation", require_actor=True)


@pytest.fixture
def quality_store() -> InMemoryQualityReviewStore:
    """Revisiones de calidad guardadas (PA-277), compartidas por las sesiones de la prueba."""
    return InMemoryQualityReviewStore()


@pytest.fixture
def composed(
    monkeypatch: pytest.MonkeyPatch,
    container: Container,
    quality_store: InMemoryQualityReviewStore,
) -> Container:
    """Sustituye la composición de `app/session.py` por los fakes (sin `.env` ni PostgreSQL)."""
    checkpointer = memory_checkpointer()
    monkeypatch.setattr(app_session, "build_config", lambda: None)
    monkeypatch.setattr(app_session, "model_router", lambda _config: None)
    monkeypatch.setattr(app_session, "build_app_container", lambda *_a, **_k: container)
    monkeypatch.setattr(app_session, "shared_checkpointer", lambda _config: checkpointer)
    monkeypatch.setattr(app_session, "shared_handoffs", lambda _c: InMemoryHandoffStore())
    monkeypatch.setattr(app_session, "shared_quality_reviews", lambda _c: quality_store)
    return container


def _app() -> AppTest:
    at = AppTest.from_file(MAIN, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def _session(at: AppTest) -> SessionState:
    session = at.session_state["agente"]
    assert isinstance(session, SessionState)
    return session


def _login(at: AppTest, username: str, password: str) -> None:
    at.text_input[0].input(username)
    at.text_input[1].input(password)
    at.button(key=LOGIN_BUTTON).click().run()
    assert not at.exception, at.exception


def _password(username: str) -> str:
    return dataset.DEMO_USERS[username][0]


def _texts(at: AppTest) -> str:
    parts: list[Any] = [*at.markdown, *at.caption, *at.info, *at.warning, *at.error, *at.subheader]
    return "\n".join(str(element.value) for element in parts)


def _assert_nothing_written(container: Container) -> None:
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    assert tracker.writes == []
    testmgmt = container.test_management
    assert isinstance(testmgmt, FakeTestManagement)
    assert testmgmt.publish_calls == 0


def test_smoke_login_evolve_sources_generate_and_iterate(composed: Container) -> None:
    """PA-74 · UI.md §4.1–4.5: login → clave reconocida → fuentes → generar → Mixta 3."""
    at = _app()
    _login(at, "af-demo", _password("af-demo"))
    assert _session(at).user is not None

    at.text_area(key="start_text").input(EVOLVE_TEXT)
    at.button(key="continue").click().run()
    assert not at.exception, at.exception

    # Mixta 2: la HU de origen es obligatoria (desactivada), el resto se puede desmarcar.
    session = _session(at)
    assert session.screen == "origen"
    assert session.request is not None and session.request.key == "DEMO-3"
    boxes = {box.key: box for box in at.checkbox}
    origin_box = boxes["src-DEMO-3-DEMO-3"]
    assert origin_box.disabled is True
    others = [box for key, box in boxes.items() if key != "src-DEMO-3-DEMO-3"]
    assert others and all(not box.disabled and box.value for box in others)

    boxes["src-DEMO-3-doc-glosario"].uncheck().run()
    assert not at.exception, at.exception
    at.button(key="generate").click().run()
    assert not at.exception, at.exception

    # Mixta 3: la conversación está en la barra lateral con su versión.
    session = _session(at)
    assert session.screen == "iterar", _texts(at)
    labels = [str(button.label) for button in at.sidebar.button]
    assert any("Evolucionar DEMO\\-3" in label and "Versión 1" in label for label in labels), labels
    assert session.workspace is not None and session.current is not None
    conv = next(c for c in session.workspace.conversations if c.thread_id == session.current)
    values = session.workspace.graph.get_state(conv.config).values
    assert values["excluded_sources"] == ["doc-glosario"]
    assert values["origin"] == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    assert conv.view is not None and conv.view.version == 1
    _assert_nothing_written(composed)


def test_smoke_wrong_passwords_lock_the_login_form(composed: Container) -> None:
    """RF-45 · UI.md §7: 5 contraseñas incorrectas bloquean el formulario con LOGIN_LOCKED."""
    at = _app()
    for attempt in range(MAX_LOGIN_ATTEMPTS):
        _login(at, "af-demo", f"contrasena-incorrecta-ficticia-{attempt}")
        assert _session(at).user is None
    # El 5.º fallo ya muestra el aviso; el botón se pinta desactivado desde la ejecución siguiente.
    assert any(LOGIN_LOCKED in str(error.value) for error in at.error)
    at.run()
    assert at.button(key=LOGIN_BUTTON).disabled is True
    assert any(LOGIN_LOCKED in str(error.value) for error in at.error)

    # El botón no se puede pulsar (AppTest lo rechaza igual que el navegador) y sigue bloqueado.
    with pytest.raises(AppTestError, match="disabled"):
        at.button(key=LOGIN_BUTTON).click()
    session = _session(at)
    assert session.user is None
    assert login_locked(session)
    _assert_nothing_written(composed)


def test_smoke_wrong_password_shows_error_without_locking(composed: Container) -> None:
    """RF-45: un fallo muestra «Usuario o contraseña incorrectos.» y no bloquea."""
    at = _app()
    _login(at, "af-demo", "contrasena-incorrecta-ficticia")
    assert any("Usuario o contraseña incorrectos." in str(e.value) for e in at.error)
    assert at.button(key=LOGIN_BUTTON).disabled is False


def test_smoke_compose_failure_shows_message_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """UI.md §7: si la composición falla (PostgreSQL caído), mensaje y botón «Reintentar»."""

    def failing(*_args: object, **_kwargs: object) -> Container:
        raise ExternalServiceError(COMPOSE_FAILURE, service="postgres")

    monkeypatch.setattr(app_session, "build_config", lambda: None)
    monkeypatch.setattr(app_session, "model_router", lambda _config: None)
    monkeypatch.setattr(app_session, "build_app_container", failing)
    monkeypatch.setattr(app_session, "shared_checkpointer", lambda _config: memory_checkpointer())
    monkeypatch.setattr(app_session, "shared_handoffs", lambda _c: InMemoryHandoffStore())
    monkeypatch.setattr(
        app_session, "shared_quality_reviews", lambda _c: InMemoryQualityReviewStore()
    )

    at = _app()

    assert [str(error.value) for error in at.error] == [md_escape(COMPOSE_FAILURE)]
    assert at.button(key="retry_compose") is not None
    assert len(at.text_input) == 0  # sin composición no hay formulario de login
    assert _session(at).workspace is None


def test_smoke_qa_user_sees_tests_card_enabled(composed: Container) -> None:
    """UI.md §3 · §6.1 · T-28: QA ve «Preparar pruebas» activa y el compositor abierto."""
    at = _app()
    _login(at, "qa-demo", _password("qa-demo"))
    tests_card = at.button(key="flow-tests")
    assert "Preparar pruebas" in str(tests_card.label)
    assert tests_card.disabled is False
    assert all(at.button(key=f"flow-{flow}").disabled for flow in ("need", "evolve", "review"))
    assert at.text_area(key="start_text") is not None  # flujo por defecto: Preparar pruebas
    _assert_nothing_written(composed)


QA_STRATEGY_MD = (
    "# Título de estrategia ficticia\n\n"
    "Ver [guía ficticia](https://example.invalid/guia) antes de probar."
)
QA_GHERKIN = "Escenario: renovar sin reservas (ficticio)\n  Dado un préstamo activo"


@pytest.fixture
def qa_composed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Container:
    """Como `composed`, con un LLM fake cuya suite trae Markdown en la estrategia y Gherkin."""
    llm = FakeLLMProvider()
    base = llm.builders[TestSuite]

    def build(messages: list[Any]) -> TestSuite:
        suite = base(messages)
        assert isinstance(suite, TestSuite)
        cases = [suite.cases[0].model_copy(update={"gherkin": QA_GHERKIN}), *suite.cases[1:]]
        return suite.model_copy(
            update={
                "strategy_md": QA_STRATEGY_MD,
                "cases": cases,
                "risks": ["Reservas concurrentes (ficticio)"],
                "synthetic_data": [{"socio": "S-0001 (ficticio)"}],
            }
        )

    llm.builders[TestSuite] = build
    container = fake_container(tmp_path, llm=llm, publish_mode="simulation", require_actor=True)
    checkpointer = memory_checkpointer()
    monkeypatch.setattr(app_session, "build_config", lambda: None)
    monkeypatch.setattr(app_session, "model_router", lambda _config: None)
    monkeypatch.setattr(app_session, "build_app_container", lambda *_a, **_k: container)
    monkeypatch.setattr(app_session, "shared_checkpointer", lambda _config: checkpointer)
    monkeypatch.setattr(app_session, "shared_handoffs", lambda _c: InMemoryHandoffStore())
    monkeypatch.setattr(
        app_session, "shared_quality_reviews", lambda _c: InMemoryQualityReviewStore()
    )
    return container


def _to_qa_origin(at: AppTest) -> None:
    """Login como QA → «DEMO-3» en el compositor (flujo por defecto: Preparar pruebas) → QA 1."""
    _login(at, "qa-demo", _password("qa-demo"))
    at.text_area(key="start_text").input("DEMO-3")
    at.button(key="continue").click().run()
    assert not at.exception, at.exception


def test_smoke_qa_origin_shows_case_types_extras_and_fixed_origin(composed: Container) -> None:
    """UI.md §6.1 · RF-22 · T-28: QA 1 con tipos de caso, extras y la HU de origen fija."""
    at = _app()
    _to_qa_origin(at)
    session = _session(at)
    assert session.screen == "origen", _texts(at)
    assert session.request is not None
    assert (session.request.flow, session.request.key) == ("tests", "DEMO-3")
    assert session.request.mode == "qa"

    boxes = {box.key: box for box in at.checkbox}
    for required in ("qa-type-positivo", "qa-type-negativo"):
        assert boxes[required].disabled is True and boxes[required].value is True
    for optional in ("qa-type-alterno", "qa-type-excepcion", "qa-data", "qa-risks", "qa-strategy"):
        assert boxes[optional].disabled is False and boxes[optional].value is True
    assert boxes["src-DEMO-3-DEMO-3"].disabled is True
    texts = _texts(at)
    assert "Clave reconocida en Jira · sin IA" in texts
    assert "caso\\-prueba" in texts
    assert at.button(key="generate").label == "Generar la suite"
    assert "restrictions" not in [area.key for area in at.text_area]
    _assert_nothing_written(composed)


def test_smoke_qa_generate_iterate_and_approve_simulated(qa_composed: Container) -> None:
    """UI.md §6.1–6.4 · RF-22…RF-27 · T-28 (y T-31): QA 1 → QA 3 → recibo → simulada."""
    at = _app()
    _to_qa_origin(at)
    at.checkbox(key="qa-type-alterno").uncheck().run()
    assert not at.exception, at.exception
    at.button(key="generate").click().run()
    assert not at.exception, at.exception

    # QA 3: el primer feedback refleja las casillas y la vista es una suite.
    session = _session(at)
    assert session.screen == "iterar", _texts(at)
    assert session.workspace is not None and session.current is not None
    conv = next(c for c in session.workspace.conversations if c.thread_id == session.current)
    values = session.workspace.graph.get_state(conv.config).values
    assert "alternos" not in values["feedback"][0]
    assert "de excepción" in values["feedback"][0]
    assert conv.view is not None and isinstance(conv.view.artifact.content, TestSuite)

    labels = [str(tab.label) for tab in at.tabs]
    n_cases = len(conv.view.artifact.content.cases)
    for label in (f"Casos ({n_cases})", "Cobertura", "Datos y riesgos", "Estrategia"):
        assert label in labels, labels
    assert any("Todos los CA cubiertos" in str(s.value) for s in at.success)
    assert at.button(key="edit-suite").disabled is True

    # Estrategia en texto plano (st.text), nunca interpretada como Markdown.
    assert any(str(t.value) == QA_STRATEGY_MD for t in at.text)
    for element in at.markdown:
        value = str(element.value)
        assert "# Título de estrategia ficticia" not in value, value
        assert "](https://example.invalid/guia)" not in value, value
    assert any(str(code.value) == QA_GHERKIN for code in at.code)

    # Recibo QA: subtareas, estrategia y matriz; «Volver a la suite».
    at.button(key="approve").click().run()
    assert not at.exception, at.exception
    assert _session(at).screen == "recibo", _texts(at)
    boxes = list(at.checkbox)
    assert len(boxes) == 3, [str(box.label) for box in boxes]
    box_labels = " | ".join(str(box.label) for box in boxes)
    assert "subtareas" in box_labels
    assert "estrategia" in box_labels and "matriz" in box_labels
    assert at.button(key="receipt-back").label == "Volver a la suite"
    for box in boxes:
        box.check()
    at.run()
    at.button(key="receipt-approve").click().run()
    assert not at.exception, at.exception
    assert any("Aprobada · simulada" in str(s.value) for s in at.success)
    _assert_nothing_written(qa_composed)


def test_smoke_qa_receipt_back_returns_to_suite(composed: Container) -> None:
    """UI.md §6.4 · T-28: «Volver a la suite» vuelve a QA 3 sin aprobar."""
    at = _app()
    _to_qa_origin(at)
    at.button(key="generate").click().run()
    at.button(key="approve").click().run()
    assert _session(at).screen == "recibo", _texts(at)
    at.button(key="receipt-back").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "iterar"
    conv = next(c for c in session.workspace.conversations if c.thread_id == session.current)  # type: ignore[union-attr]
    assert conv.outcome is None and conv.view is not None
    _assert_nothing_written(composed)


def test_smoke_functional_user_sees_tests_card_disabled_with_qa_hint(composed: Container) -> None:
    """UI.md §3 · T-28 (negativa): el analista funcional ve «Preparar pruebas» desactivada."""
    at = _app()
    _login(at, "af-demo", _password("af-demo"))
    card = at.button(key="flow-tests")
    assert "Preparar pruebas" in str(card.label)
    assert card.disabled is True
    assert card.help == "Disponible para el rol QA."
    _assert_nothing_written(composed)


def test_smoke_key_of_other_project_changes_and_remembers_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PA-47 · T-50/T-53: una clave de otro proyecto avisa y se recuerda con `projects.choose`."""
    tracker = FakeIssueTracker()
    other = tracker.issues["DEMO-3"].model_copy(update={"key": "OTRO-7", "parent_key": None})
    tracker.issues["OTRO-7"] = other
    projects = [*tracker.list_projects(), ProjectSummary(key="OTRO", name="Proyecto ficticio")]
    monkeypatch.setattr(tracker, "list_projects", lambda: projects)
    container = fake_container(
        tmp_path, issue_tracker=tracker, publish_mode="simulation", require_actor=True
    )
    monkeypatch.setattr(app_session, "build_config", lambda: None)
    monkeypatch.setattr(app_session, "model_router", lambda _config: None)
    monkeypatch.setattr(app_session, "build_app_container", lambda *_a, **_k: container)
    monkeypatch.setattr(app_session, "shared_checkpointer", lambda _c: memory_checkpointer())
    monkeypatch.setattr(app_session, "shared_handoffs", lambda _c: InMemoryHandoffStore())
    monkeypatch.setattr(
        app_session, "shared_quality_reviews", lambda _c: InMemoryQualityReviewStore()
    )

    at = _app()
    _login(at, "af-demo", _password("af-demo"))
    at.text_area(key="start_text").input("Evolucionar otro-7 (ficticio)")
    at.button(key="continue").click().run()
    assert not at.exception, at.exception

    session = _session(at)
    assert session.screen == "origen", _texts(at)
    assert session.request is not None and session.request.key == "OTRO-7"
    assert session.project == "OTRO"
    assert container.last_projects.get("af-demo") == "OTRO"  # recordado como último usado
    assert md_escape("pasa de DEMO a OTRO") in _texts(at)
    _assert_nothing_written(container)


def test_smoke_similar_story_card_shows_epic_and_counts(composed: Container) -> None:
    """PA-56 · UI.md §4.3: la tarjeta «HU parecida» trae épica y nº de CA y RN con `get_issue`."""
    at = _app()
    _login(at, "af-demo", _password("af-demo"))
    # El fake de `search` exige todas las palabras de `text ~`: una sola palabra clave.
    at.text_area(key="start_text").input("renovar")
    at.button(key="continue").click().run()
    assert not at.exception, at.exception

    session = _session(at)
    assert session.screen == "origen", _texts(at)
    assert session.request is not None and session.request.kind == "need"
    assert session.alternatives, "se esperaban HU parecidas por texto"
    texts = _texts(at)
    assert "Búsqueda en Jira por texto · sin IA" in texts
    assert md_escape(f"épica {dataset.EPIC_KEY} · ") in texts
    assert "CA · " in texts and " RN" in texts
    _assert_nothing_written(composed)


# --- T-31 · Recibo de aprobación y resultado (UI.md §4.6 y §4.7) -----------------------------


def _to_receipt(at: AppTest, text: str = EVOLVE_TEXT) -> None:
    """Login → origen del texto → generar → Mixta 3 → «Revisar y aprobar» (recibo)."""
    _login(at, "af-demo", _password("af-demo"))
    at.text_area(key="start_text").input(text)
    at.button(key="continue").click().run()
    assert not at.exception, at.exception
    at.button(key="generate").click().run()
    assert not at.exception, at.exception
    assert _session(at).screen == "iterar", _texts(at)
    at.button(key="approve").click().run()
    assert not at.exception, at.exception
    assert _session(at).screen == "recibo", _texts(at)


def _sidebar_texts(at: AppTest) -> str:
    parts: list[Any] = [*at.sidebar.button, *at.sidebar.markdown, *at.sidebar.caption]
    return "\n".join(str(getattr(e, "label", None) or e.value) for e in parts)


def test_smoke_receipt_approve_enabled_only_when_all_checked(composed: Container) -> None:
    """UI.md §4.6 · §5.5 · T-31: aprobar solo con todas las casillas → «Aprobada · simulada»."""
    at = _app()
    _to_receipt(at)
    assert at.checkbox, "el recibo debe tener una casilla por operación"
    assert all(not box.value for box in at.checkbox)
    assert at.button(key="receipt-approve").disabled is True
    assert "Todo revisado" not in _texts(at)
    with pytest.raises(AppTestError, match="disabled"):
        at.button(key="receipt-approve").click()

    for box in at.checkbox:
        box.check()
    at.run()
    assert not at.exception, at.exception
    assert "Todo revisado" in _texts(at)
    assert at.button(key="receipt-approve").disabled is False

    at.button(key="receipt-approve").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "iterar", _texts(at)
    assert any("Aprobada · simulada" in str(s.value) for s in at.success)
    assert "Simulado" in _sidebar_texts(at)
    conv = next(c for c in session.workspace.conversations if c.thread_id == session.current)  # type: ignore[union-attr]
    assert conv.outcome is not None and conv.outcome.kind == "simulated"
    _assert_nothing_written(composed)


def test_smoke_receipt_partially_checked_keeps_approve_disabled(composed: Container) -> None:
    """UI.md §4.6 (límite): con alguna casilla sin marcar el botón sigue desactivado."""
    at = _app()
    _to_receipt(at, EPIC_TEXT)  # crear en la épica + vincular: dos casillas
    boxes = list(at.checkbox)
    assert len(boxes) >= 2, _texts(at)
    boxes[0].check()
    at.run()
    assert at.button(key="receipt-approve").disabled is True
    assert f"1 de {len(boxes)} revisadas" in _texts(at)


def test_smoke_receipt_back_returns_to_iterate_without_approving(composed: Container) -> None:
    """UI.md §4.6: «Volver a la propuesta» vuelve a Mixta 3 sin aprobar."""
    at = _app()
    _to_receipt(at)
    at.button(key="receipt-back").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "iterar"
    conv = next(c for c in session.workspace.conversations if c.thread_id == session.current)  # type: ignore[union-attr]
    assert conv.outcome is None and conv.finished is None
    assert conv.view is not None and conv.view.version == 1
    assert not at.success
    _assert_nothing_written(composed)


def test_smoke_receipt_discard_finishes_the_conversation(composed: Container) -> None:
    """UI.md §4.6 · §5.3: «Descartar» en el recibo termina la conversación sin escribir."""
    at = _app()
    _to_receipt(at)
    at.button(key="receipt-discard").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "iterar"
    conv = next(c for c in session.workspace.conversations if c.thread_id == session.current)  # type: ignore[union-attr]
    assert conv.finished is not None and "descartado" in conv.finished
    assert conv.view is None and conv.outcome is None
    _assert_nothing_written(composed)


def _partial_result_script() -> None:
    """Pinta solo el resultado parcial (QA 5) con datos ficticios."""
    from app.conversation import Conversation
    from app.origin import fix_origin
    from app.review import Outcome
    from app.session import SessionState
    from app.views import resultado

    conv = Conversation(request=fix_origin("tests", "DEMO", key="DEMO-3"), user="qa-demo")
    outcome = Outcome(
        kind="partial",
        version=2,
        approved_by="qa-demo",
        operations=["Publicar 3 casos de prueba en DEMO-3"],
        published_keys=["DEMO-501", "DEMO-502"],
        errors=["No se pudo publicar CP-03."],
        story=False,
    )
    resultado.render(SessionState(), conv, outcome)


def test_smoke_partial_result_lists_errors_and_disables_retry() -> None:
    """UI.md §6.5 · RNF-13 · PA-153: «Publicada en parte», errores y reintento desactivado."""
    at = AppTest.from_function(_partial_result_script, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert any("Publicada en parte" in str(w.value) for w in at.warning)
    texts = _texts(at)
    assert md_escape("No se pudo publicar CP-03.") in texts
    assert md_escape("DEMO-501") in texts
    retry = at.button(key="retry-failed")
    assert retry.disabled is True
    assert "memoria" not in texts.lower()  # una suite no genera memoria (D-07)


def test_smoke_approval_error_offers_restart_with_same_origin(
    composed: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI.md §5.3: un `ApprovalError` cierra el hilo y «Empezar de nuevo» abre otro igual."""

    def failing_record(*_args: object, **_kwargs: object) -> None:
        raise ApprovalError("El destino de publicación no puede cambiar entre iteraciones.")

    monkeypatch.setattr(composed.approvals, "record", failing_record)
    at = _app()
    _to_receipt(at)
    for box in at.checkbox:
        box.check()
    at.run()
    at.button(key="receipt-approve").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "iterar"
    old = session.current
    assert old is not None
    texts = _texts(at)
    assert md_escape("El destino de publicación no puede cambiar entre iteraciones.") in texts
    old_request = next(c for c in session.workspace.conversations if c.thread_id == old).request  # type: ignore[union-attr]

    at.button(key=f"restart-{old}").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.current is not None and session.current != old
    new = next(c for c in session.workspace.conversations if c.thread_id == session.current)  # type: ignore[union-attr]
    assert new.request == old_request
    _assert_nothing_written(composed)


# --- Mixta 5 · Revisar la calidad (app/views/calidad.py · UI.md §4.8, T-48, RF-18) -----------


def _to_quality_origin(at: AppTest, key: str = "DEMO-3") -> None:
    """Login como analista → tarjeta «Revisar la calidad» → clave → Mixta 2 (origen)."""
    _login(at, "af-demo", _password("af-demo"))
    at.button(key="flow-review").click().run()
    assert not at.exception, at.exception
    at.text_area(key="start_text").input(key)
    at.button(key="continue").click().run()
    assert not at.exception, at.exception


def _to_quality(at: AppTest) -> None:
    _to_quality_origin(at)
    at.button(key="review").click().run()
    assert not at.exception, at.exception


def _download_buttons(at: AppTest) -> list[Any]:
    return list(at.get("download_button"))


def _stored(session: SessionState) -> StoredQualityReview:
    """La revisión abierta, tal como quedó guardada (PA-277)."""
    assert session.quality is not None and session.quality_store is not None
    review = session.quality_store.get(session.quality)
    assert review is not None
    return review


def test_smoke_review_quality_shows_report_without_writing_jira(composed: Container) -> None:
    """UI.md §4.8 · T-48 (RF-18): origen sin restricciones → informe INVEST, hallazgos y .md."""
    at = _app()
    _to_quality_origin(at)
    session = _session(at)
    assert session.screen == "origen", _texts(at)
    assert session.request is not None
    assert (session.request.flow, session.request.key) == ("review", "DEMO-3")
    assert "restrictions" not in [area.key for area in at.text_area]
    assert at.button(key="review").label == "Revisar la calidad"
    assert "generate" not in [button.key for button in at.button]

    at.button(key="review").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "calidad", _texts(at)
    stored = _stored(session)  # PA-277: guardada en el almacén, con el informe
    assert (stored.issue_key, stored.username, stored.state) == ("DEMO-3", "af-demo", "done")
    assert stored.report is not None and stored.model is not None
    texts = _texts(at)
    assert md_escape("He revisado DEMO-3 con INVEST") in texts
    for letter, name in INVEST_NAMES.items():
        assert f"**{letter} · {name}**" in texts
    assert "Hallazgos" in texts
    assert md_escape("Avisar en menos de 15 minutos.") in texts
    downloads = _download_buttons(at)
    assert len(downloads) == 1
    assert "quality-download" in str(downloads[0].proto.id)
    _assert_nothing_written(composed)


def test_smoke_review_quality_report_is_not_rendered_with_to_markdown(
    composed: Container,
) -> None:
    """PA-64 · UI.md §4.8 (seguridad): el informe se pinta campo a campo, no con `to_markdown`."""
    at = _app()
    _to_quality(at)
    assert _session(at).screen == "calidad"
    assert not any("# Calidad de" in str(element.value) for element in at.markdown)
    assert not any("## INVEST" in str(element.value) for element in at.markdown)
    _assert_nothing_written(composed)


def test_smoke_review_quality_evolve_opens_new_conversation_with_proposals(
    composed: Container,
) -> None:
    """UI.md §4.8 · T-48: «Evolucionar con esto» abre una evolución con las propuestas."""
    at = _app()
    _to_quality(at)
    session = _session(at)
    review = _stored(session)
    assert session.workspace is not None
    before = {conv.thread_id for conv in session.workspace.conversations}

    at.button(key="quality-evolve").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "iterar", _texts(at)
    assert session.workspace is not None and session.current is not None
    assert session.current not in before
    conv = next(c for c in session.workspace.conversations if c.thread_id == session.current)
    assert conv.request.flow == "evolve" and conv.request.key == "DEMO-3"
    values = session.workspace.graph.get_state(conv.config).values
    for proposal in review.evolve_feedback():
        assert proposal in values["feedback"]
    assert session.quality is None
    _assert_nothing_written(composed)


def test_smoke_qa_user_sees_review_card_disabled_with_af_hint(composed: Container) -> None:
    """UI.md §3 (negativa): QA ve «Revisar la calidad» desactivada con la ayuda del AF."""
    at = _app()
    _login(at, "qa-demo", _password("qa-demo"))
    card = at.button(key="flow-review")
    assert card.disabled is True
    assert card.help == "Disponible para el rol de analista funcional."
    _assert_nothing_written(composed)


def test_smoke_review_quality_external_error_shows_message_and_actions(
    composed: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI.md §4.8 · §7: un `ExternalServiceError` muestra su mensaje, Reintentar y Volver."""

    def failing(*_args: object, **_kwargs: object) -> None:
        raise ExternalServiceError("Proveedores ficticios caídos.", service="llm")

    monkeypatch.setattr(core_quality.QualityReviewer, "review", failing)
    at = _app()
    _to_quality(at)
    session = _session(at)
    assert session.screen == "calidad"
    stored = _stored(session)  # PA-277: el error queda guardado con su mensaje
    assert (stored.state, stored.error_code) == ("error", "quality_failed")
    assert stored.error_message == "Proveedores ficticios caídos."
    errors = [str(error.value) for error in at.error]
    assert any(md_escape("Proveedores ficticios caídos.") in error for error in errors), errors
    assert at.button(key="quality-retry").label == "Reintentar"
    assert at.button(key="quality-home").label == "Volver al inicio"
    assert "quality-download" not in str([d.proto.id for d in _download_buttons(at)])

    at.button(key="quality-home").click().run()
    assert not at.exception, at.exception
    assert _session(at).screen == "inicio"
    _assert_nothing_written(composed)


def test_smoke_review_quality_unexpected_error_hides_internal_message(
    composed: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI.md §7 (seguridad): un error no previsto muestra UNEXPECTED, nunca su mensaje."""

    def failing(*_args: object, **_kwargs: object) -> None:
        raise ValueError("secreto interno")

    monkeypatch.setattr(core_quality.QualityReviewer, "review", failing)
    at = _app()
    _to_quality(at)
    assert _session(at).screen == "calidad"
    errors = [str(error.value) for error in at.error]
    assert any(md_escape(UNEXPECTED) in error for error in errors), errors
    assert "secreto interno" not in _texts(at)
    assert at.button(key="quality-retry") is not None
    assert _stored(_session(at)).error_message == UNEXPECTED  # tampoco se guarda el interno
    _assert_nothing_written(composed)


def test_smoke_review_quality_retry_after_failure_shows_report(
    composed: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI.md §4.8: sin reintento automático; «Reintentar» vuelve a revisar y pinta el informe."""
    original = core_quality.QualityReviewer.review
    calls: list[int] = []

    def flaky(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise ExternalServiceError("Proveedores ficticios caídos.", service="llm")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(core_quality.QualityReviewer, "review", flaky)
    at = _app()
    _to_quality(at)
    failed = _stored(_session(at))
    assert len(calls) == 1 and failed.state == "error"

    at.button(key="quality-retry").click().run()
    assert not at.exception, at.exception
    session = _session(at)
    assert session.screen == "calidad"
    assert len(calls) == 2
    assert _stored(session).state == "done" and _stored(session).id != failed.id
    assert len(_download_buttons(at)) == 1
    _assert_nothing_written(composed)


def test_smoke_review_quality_shows_open_questions(composed: Container) -> None:
    """UI.md §4.8: las preguntas para negocio del informe se pintan escapadas."""
    at = _app()
    _to_quality(at)
    texts = _texts(at)
    assert "Preguntas para negocio" in texts
    assert md_escape("¿Hay un máximo de renovaciones por año? (ficticio)") in texts


def test_smoke_review_quality_receives_unchecked_sources(
    composed: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI.md §4.3 · §4.8 · RF-21: una fuente desmarcada en Mixta 2 no entra en la revisión."""
    original = core_quality.QualityReviewer.review
    received: list[list[str]] = []

    def spy(self: Any, user: Any, key: str, excluded: list[str] | None = None) -> Any:
        received.append(list(excluded or []))
        return original(self, user, key, excluded)

    monkeypatch.setattr(core_quality.QualityReviewer, "review", spy)
    at = _app()
    _to_quality_origin(at)
    boxes = {box.key: box for box in at.checkbox}
    boxes["src-DEMO-3-doc-glosario"].uncheck().run()
    at.button(key="review").click().run()
    assert not at.exception, at.exception
    assert received == [["doc-glosario"]]
    _assert_nothing_written(composed)


# --- PA-277 · Revisiones de calidad guardadas en Streamlit (QualityReviewStore) ----------------


def test_smoke_review_quality_rerun_reads_stored_review_without_calling_llm_again(
    composed: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-277: volver a pintar la pantalla lee el informe guardado; no repite la revisión."""
    original = core_quality.QualityReviewer.review
    calls: list[int] = []

    def counted(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(core_quality.QualityReviewer, "review", counted)
    at = _app()
    _to_quality(at)
    at.run()
    assert not at.exception, at.exception
    assert len(calls) == 1
    assert md_escape("He revisado DEMO-3 con INVEST") in _texts(at)
    _assert_nothing_written(composed)


def test_smoke_sidebar_lists_stored_review_and_reopens_it_in_a_new_session(
    composed: Container,
    quality_store: InMemoryQualityReviewStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PA-277: «Revisiones de calidad» lista «Informe listo» y lo abre tras recargar la app."""
    at = _app()
    _to_quality(at)
    review_id = _stored(_session(at)).id

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no debe volver a revisar")

    monkeypatch.setattr(core_quality.QualityReviewer, "review", unexpected)
    again = _app()  # sesión nueva (recarga o reinicio): el almacén conserva la revisión
    _login(again, "af-demo", _password("af-demo"))
    button = again.button(key=f"quality-{review_id}")
    assert md_escape("Revisar la calidad de DEMO-3") in button.label
    assert "Informe listo" in button.label
    assert "Avisar" not in button.label  # nunca texto del informe en la lista

    button.click().run()
    assert not again.exception, again.exception
    session = _session(again)
    assert session.screen == "calidad" and session.quality == review_id
    assert session.request is not None and session.request.key == "DEMO-3"
    assert md_escape("He revisado DEMO-3 con INVEST") in _texts(again)
    assert len(_download_buttons(again)) == 1
    assert [r.id for r in quality_store.list_for("af-demo")] == [review_id]
    _assert_nothing_written(composed)


def test_smoke_sidebar_shows_failed_review_as_error_and_opens_its_message(
    composed: Container, quality_store: InMemoryQualityReviewStore
) -> None:
    """PA-277: una revisión con error sale como «Error» y al abrirla muestra su mensaje."""
    failed = new_review("00000000-0000-4000-8000-000000000001", "af-demo", "DEMO-3")
    quality_store.create(failed)
    quality_store.fail(failed.id, "quality_failed", "Proveedores ficticios caídos.")
    at = _app()
    _login(at, "af-demo", _password("af-demo"))
    button = at.button(key=f"quality-{failed.id}")
    assert "Error" in button.label

    button.click().run()
    assert not at.exception, at.exception
    errors = [str(error.value) for error in at.error]
    assert any(md_escape("Proveedores ficticios caídos.") in error for error in errors), errors
    assert at.button(key="quality-retry").label == "Reintentar"
    assert _download_buttons(at) == []
    _assert_nothing_written(composed)


def test_smoke_running_review_is_shown_as_in_progress_without_relaunching(
    composed: Container,
    quality_store: InMemoryQualityReviewStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PA-277: una revisión «En marcha» (p. ej. de otra pestaña) no se relanza sola."""
    running = new_review("00000000-0000-4000-8000-000000000002", "af-demo", "DEMO-3")
    quality_store.create(running)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no debe revisar de nuevo sin que la persona lo pida")

    monkeypatch.setattr(core_quality.QualityReviewer, "review", unexpected)
    at = _app()
    _login(at, "af-demo", _password("af-demo"))
    button = at.button(key=f"quality-{running.id}")
    assert "En marcha" in button.label

    button.click().run()
    assert not at.exception, at.exception
    assert "sigue en marcha" in _texts(at)
    assert at.button(key="quality-retry") is not None
    assert quality_store.get(running.id) == running  # no se marca como interrumpida (PA-147)


def test_smoke_reviews_of_another_person_are_not_listed(
    composed: Container, quality_store: InMemoryQualityReviewStore
) -> None:
    """PA-277 (negativa): la lista solo muestra las revisiones de quien ha iniciado sesión."""
    other = new_review("00000000-0000-4000-8000-000000000003", "otra-persona", "DEMO-3")
    quality_store.create(other)
    at = _app()
    _login(at, "af-demo", _password("af-demo"))
    assert f"quality-{other.id}" not in [button.key for button in at.button]
    assert "Revisiones de calidad" not in _texts(at)


def test_smoke_review_quality_rate_limit_is_stored_with_retry_after(
    composed: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-277: un 429 se guarda como `rate_limited` con su `retry_after`, como en la API."""

    def limited(*_args: object, **_kwargs: object) -> None:
        raise RateLimitError("Límite de uso ficticio alcanzado.", service="llm", retry_after=30)

    monkeypatch.setattr(core_quality.QualityReviewer, "review", limited)
    at = _app()
    _to_quality(at)
    stored = _stored(_session(at))
    assert (stored.state, stored.error_code, stored.retry_after) == ("error", "rate_limited", 30)
    _assert_nothing_written(composed)


def test_smoke_quality_store_failure_shows_message_without_calling_llm(
    composed: Container,
    quality_store: InMemoryQualityReviewStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PA-277 · UI.md §7: si no se puede guardar la revisión, mensaje y no se llama al modelo."""

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ExternalServiceError("No se pudo guardar la revisión ficticia.", service="postgres")

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no debe llamar al modelo sin poder guardar")

    monkeypatch.setattr(quality_store, "create", broken)
    monkeypatch.setattr(core_quality.QualityReviewer, "review", unexpected)
    at = _app()
    _to_quality(at)
    assert not at.exception, at.exception
    errors = [str(error.value) for error in at.error]
    assert any(md_escape("No se pudo guardar la revisión ficticia.") in e for e in errors), errors
    assert at.button(key="quality-retry") is not None
