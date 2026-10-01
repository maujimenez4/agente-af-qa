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
from adapters.base import ProjectSummary
from adapters.errors import ExternalServiceError
from app.session import LOGIN_LOCKED, MAX_LOGIN_ATTEMPTS, SessionState, login_locked
from app.text import md_escape
from core.config import ROOT_DIR
from core.container import Container
from core.graph import memory_checkpointer
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.test_management import FakeTestManagement

MAIN = str(ROOT_DIR / "app" / "main.py")
LOGIN_BUTTON = "FormSubmitter:login-Entrar"
EVOLVE_TEXT = "Quiero evolucionar demo-3: renovar desde la app"
COMPOSE_FAILURE = "No se pudo preparar el almacén de conversaciones en PostgreSQL."


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path, publish_mode="simulation", require_actor=True)


@pytest.fixture
def composed(monkeypatch: pytest.MonkeyPatch, container: Container) -> Container:
    """Sustituye la composición de `app/session.py` por los fakes (sin `.env` ni PostgreSQL)."""
    checkpointer = memory_checkpointer()
    monkeypatch.setattr(app_session, "build_config", lambda: None)
    monkeypatch.setattr(app_session, "model_router", lambda _config: None)
    monkeypatch.setattr(app_session, "build_app_container", lambda *_a, **_k: container)
    monkeypatch.setattr(app_session, "shared_checkpointer", lambda _config: checkpointer)
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

    at = _app()

    assert [str(error.value) for error in at.error] == [md_escape(COMPOSE_FAILURE)]
    assert at.button(key="retry_compose") is not None
    assert len(at.text_input) == 0  # sin composición no hay formulario de login
    assert _session(at).workspace is None


def test_smoke_qa_user_sees_tests_card_disabled_until_t28(composed: Container) -> None:
    """UI.md §3 · app/flows.py: QA ve «Preparar pruebas» desactivada (pending_task T-28)."""
    at = _app()
    _login(at, "qa-demo", _password("qa-demo"))
    tests_card = at.button(key="flow-tests")
    assert "Preparar pruebas" in str(tests_card.label)
    assert tests_card.disabled is True
    assert all(at.button(key=f"flow-{flow}").disabled for flow in ("need", "evolve", "review"))
    assert len(at.text_area) == 0  # sin flujo habilitado no hay compositor
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
