"""PA-268: la composición real pasa el almacén de entregas a QA al grafo (API y Streamlit).

Sin `handoffs`, la QA encadenada (T-54) falla cerrada en producción aunque las pruebas con
`fake_runtime` pasen; estas pruebas comprueban el montaje real con `monkeypatch`, sin BD ni red.
Datos ficticios.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

import app.session as app_session
import core.config
import core.container
import core.factories
import core.graph
import core.graph.execution
import core.quality
import core.usage
from api.runtime import build_runtime
from core.config import AppConfig, Settings, load_models_config
from core.handoff import Handoff, InMemoryHandoffStore, SqlHandoffStore
from tests.fakes import dataset
from tests.fakes.api import api_settings, fake_runtime
from tests.fakes.container import fake_container
from tests.unit.test_api_app import QA, Api

FAKE_PASSWORD = "contrasena-ficticia-1234"
MODELS_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "models.yaml"


def test_build_handoffs_returns_sql_store_without_connecting() -> None:
    settings = Settings(_env_file=None, postgres_password=FAKE_PASSWORD)  # type: ignore[call-arg]
    models = load_models_config(MODELS_FIXTURE)  # no depende de `config/models.yaml`
    store = core.factories.build_handoffs(AppConfig(settings, models))
    assert isinstance(store, SqlHandoffStore)


def test_build_runtime_passes_the_same_handoff_store_to_the_graph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """API: `build_runtime` deja en `rt.handoffs` el mismo almacén que recibe `build_graph`."""
    store = InMemoryHandoffStore()
    seen: dict[str, Any] = {}
    config = SimpleNamespace(
        settings=api_settings(),
        models=SimpleNamespace(limits=SimpleNamespace(daily_token_warning=1000)),
        task_chain=lambda _task: [],
    )
    base = fake_container(tmp_path, require_actor=True)

    def fake_build_graph(container: Any, **kwargs: Any) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(core.config, "build_config", lambda: config)
    monkeypatch.setattr(core.container, "bootstrap_logging", lambda _c: None)
    monkeypatch.setattr(core.factories, "build_app_container", lambda _c: base)
    monkeypatch.setattr(core.factories, "build_usage_recorder", lambda _c: None)
    monkeypatch.setattr(core.factories, "build_checkpointer", lambda _c: "checkpointer")
    monkeypatch.setattr(core.factories, "build_handoffs", lambda _c: store)
    monkeypatch.setattr(core.factories, "model_router", lambda _c: None)
    monkeypatch.setattr(core.factories, "build_session_container", lambda _c, b, _r, _rec: b)
    monkeypatch.setattr(core.graph, "build_graph", fake_build_graph)
    monkeypatch.setattr(core.graph.execution, "build_execution_graph", lambda *_a, **_k: None)
    monkeypatch.setattr(core.usage.SqlUsageQueries, "from_url", classmethod(lambda _cls, _u: None))
    # PA-272: las revisiones de calidad van a PostgreSQL; aquí, en memoria.
    monkeypatch.setattr(
        core.quality.SqlQualityReviewStore,
        "from_url",
        classmethod(lambda _cls, _u: core.quality.InMemoryQualityReviewStore()),
    )

    rt = build_runtime()
    rt.workspace_factory()

    assert rt.handoffs is store
    assert seen["handoffs"] is store
    assert seen["checkpointer"] == "checkpointer"


def test_streamlit_compose_passes_handoffs_to_build_graph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Streamlit: `compose` pasa `handoffs=` (el almacén compartido del proceso) al grafo."""
    store = InMemoryHandoffStore()
    seen: dict[str, Any] = {}

    def fake_build_graph(container: Any, **kwargs: Any) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(app_session, "build_config", lambda: None)
    monkeypatch.setattr(app_session, "model_router", lambda _c: None)
    monkeypatch.setattr(
        app_session, "build_app_container", lambda *_a, **_k: fake_container(tmp_path)
    )
    monkeypatch.setattr(app_session, "shared_checkpointer", lambda _c: "checkpointer")
    monkeypatch.setattr(app_session, "shared_handoffs", lambda _c: store)
    monkeypatch.setattr(app_session, "shared_quality_reviews", lambda _c: "quality")
    monkeypatch.setattr(app_session, "build_graph", fake_build_graph)

    session = app_session.SessionState()
    app_session.compose(session)

    assert session.compose_error is None
    assert seen["handoffs"] is store
    assert session.quality_store == "quality"  # PA-277: un almacén por proceso


# --- correcciones de security-reviewer -----------------------------------------------------------


def test_take_handoff_of_a_project_not_visible_is_409(tmp_path: Path) -> None:
    """Defensa en profundidad: recoger una entrega de un proyecto que no ve la conexión → 409."""
    rt = fake_runtime(tmp_path)
    assert rt.handoffs is not None
    hidden = Handoff(
        id="ab" * 16,
        artifact_id=uuid4(),
        version=1,
        project_key="OCULTO",
        story_key=None,
        title="HU ficticia de otro proyecto",
        story=dataset.renewal_story(jira_key=None),
        from_user="af-demo",
        from_thread_id=str(uuid4()),
        created_at=datetime.now(UTC),
    )
    rt.handoffs.create(hidden)
    qa = Api(rt)
    assert qa.login(QA).status_code == 200

    response = qa.post(f"/qa/handoffs/{hidden.id}/take")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "handoff_unavailable"
    assert rt.handoffs.get(hidden.id).status == "pending"  # type: ignore[union-attr]


def test_pass_to_qa_checks_permission_and_ownership_before_running_state(tmp_path: Path) -> None:
    """Una conversación ajena en marcha no revela su estado: primero permiso y propiedad."""
    rt = fake_runtime(tmp_path)
    af = Api(rt)
    assert af.login().status_code == 200
    created = af.post(
        "/conversations",
        {"flow": "evolve", "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}},
    ).json()
    run = rt.runs.get(created["id"])
    assert run is not None
    run.running = True  # simula una operación en curso
    qa = Api(rt)
    assert qa.login(QA).status_code == 200

    assert qa.post(f"/conversations/{created['id']}/handoff").status_code == 403
    assert af.post(f"/conversations/{created['id']}/handoff").status_code == 409
