"""T-33 (RF-36/RF-38): pestaña Memoria de Streamlit (`app/views/memoria.py`, botón en `frame.py`).

Se ejecuta `app/main.py` con `streamlit.testing.v1.AppTest` y la composición sustituida por los
fakes (como `tests/unit/test_app_smoke.py`). Las memorias se escriben en `tmp_path` (el
`memory_dir` del contenedor de fakes). Nunca se llama al LLM ni se escribe en Jira.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import app.session as app_session
from adapters.base import Chunk
from app.session import SessionState
from app.text import md_escape
from app.views.memoria import EMPTY, NO_MATCH
from core.config import ROOT_DIR
from core.container import Container
from core.graph import memory_checkpointer
from core.handoff import InMemoryHandoffStore
from core.quality import InMemoryQualityReviewStore
from schemas.common import ArtifactType
from schemas.memory import Memory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore

MAIN = str(ROOT_DIR / "app" / "main.py")
LOGIN_BUTTON = "FormSubmitter:login-Entrar"
BASE_TIME = 1_790_000_000
EMPTY_TEXT = "Aún no hay memorias. Se generan al publicar una HU en Jira (modo real)."
HOSTILE = "<script>alert('ficticio')</script> **negrita** [enlace](http://x)"


def make_memory(key: str, **changes: object) -> Memory:
    values: dict[str, object] = {
        "artifact_type": ArtifactType.USER_STORY,
        "jira_key": key,
        "version": 1,
        "objective": f"Objetivo ficticio de {key}.",
        "scope": "Alcance ficticio de Villaficticia.",
        "business_rules": ["RN-1: regla ficticia."],
        "decisions": [],
        "dependencies": [],
        "changes": [],
        "acceptance_criteria": ["CA-1: criterio ficticio."],
        "references": [key],
    }
    return Memory.model_validate(values | changes)


def write(directory: Path, memory: Memory, mtime: int = BASE_TIME) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{memory.jira_key}.md"
    path.write_text(memory.to_markdown(), encoding="utf-8", newline="\n")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    return tmp_path / "memoria"


@pytest.fixture
def container(memory_dir: Path, llm: FakeLLMProvider) -> Container:
    return fake_container(memory_dir, llm=llm, publish_mode="simulation", require_actor=True)


@pytest.fixture
def composed(monkeypatch: pytest.MonkeyPatch, container: Container) -> Container:
    """Sustituye la composición de `app/session.py` por los fakes (sin `.env` ni PostgreSQL)."""
    checkpointer = memory_checkpointer()
    quality = InMemoryQualityReviewStore()
    monkeypatch.setattr(app_session, "build_config", lambda: None)
    monkeypatch.setattr(app_session, "model_router", lambda _config: None)
    monkeypatch.setattr(app_session, "build_app_container", lambda *_a, **_k: container)
    monkeypatch.setattr(app_session, "shared_checkpointer", lambda _config: checkpointer)
    monkeypatch.setattr(app_session, "shared_handoffs", lambda _c: InMemoryHandoffStore())
    monkeypatch.setattr(app_session, "shared_quality_reviews", lambda _c: quality)
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


def _login(at: AppTest, username: str = "af-demo") -> None:
    at.text_input[0].input(username)
    at.text_input[1].input(dataset.DEMO_USERS[username][0])
    at.button(key=LOGIN_BUTTON).click().run()
    assert not at.exception, at.exception
    assert _session(at).user is not None


def _click(at: AppTest, key: str) -> None:
    at.button(key=key).click().run()
    assert not at.exception, at.exception


def _open_memory_tab(at: AppTest) -> None:
    _click(at, "memory_tab")
    assert _session(at).screen == "memoria"


def _markdown(at: AppTest) -> list[str]:
    return [str(element.value) for element in at.markdown]


def _texts(at: AppTest) -> str:
    parts: list[Any] = [*at.markdown, *at.caption, *at.info, *at.warning, *at.error, *at.subheader]
    return "\n".join(str(element.value) for element in parts)


def _assert_read_only(container: Container, llm: FakeLLMProvider) -> None:
    tracker, testmgmt = container.issue_tracker, container.test_management
    assert isinstance(tracker, FakeIssueTracker) and isinstance(testmgmt, FakeTestManagement)
    assert tracker.writes == []
    assert testmgmt.publish_calls == 0
    assert llm.calls == []


# --- Botón y permisos ----------


@pytest.mark.parametrize("username", ["af-demo", "qa-demo", "admin-demo"])
def test_memory_tab_is_available_to_all_roles(
    composed: Container, llm: FakeLLMProvider, username: str
) -> None:
    """T-33 · los tres roles: botón «Memoria» en la barra lateral que abre la pestaña."""
    at = _app()
    _login(at, username)
    assert "Memoria" in [str(b.label) for b in at.sidebar.button]
    _open_memory_tab(at)
    assert any(str(s.value) == "Memoria" for s in at.subheader)
    _assert_read_only(composed, llm)


def test_memory_tab_without_session_goes_back_to_start(composed: Container) -> None:
    """T-33 · negativa: sin usuario, la pantalla `memoria` no se pinta."""
    at = _app()
    _session(at).screen = "memoria"
    at.run()
    assert not at.exception, at.exception
    assert not any(str(s.value) == "Memoria" for s in at.subheader)


# --- Lista ----------


def test_empty_list_shows_exact_text(composed: Container, llm: FakeLLMProvider) -> None:
    """T-33 · lista vacía (carpeta inexistente): el texto exacto de la UI."""
    at = _app()
    _login(at)
    _open_memory_tab(at)
    assert EMPTY == EMPTY_TEXT
    assert [str(info.value) for info in at.info] == [EMPTY_TEXT]
    _assert_read_only(composed, llm)


def test_empty_directory_shows_exact_text(composed: Container, memory_dir: Path) -> None:
    """T-33 · lista vacía (carpeta existente sin memorias)."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "README.md").write_text("No es una memoria.", encoding="utf-8")
    at = _app()
    _login(at)
    _open_memory_tab(at)
    assert [str(info.value) for info in at.info] == [EMPTY_TEXT]


def test_list_shows_memories_most_recent_first_with_indexed_flag(
    composed: Container, memory_dir: Path, llm: FakeLLMProvider
) -> None:
    """T-33 · lista: una fila por memoria, más recientes primero, «Indexada»/«No indexada»."""
    write(memory_dir, make_memory("DEMO-9001", version=2), BASE_TIME + 10)
    write(memory_dir, make_memory("DEMO-9002"), BASE_TIME)
    store = composed.vector_store
    assert isinstance(store, FakeVectorStore)
    store.upsert(
        [
            Chunk(
                id="memoria-DEMO-9001-0",
                document_id="memoria-DEMO-9001",
                ordinal=0,
                content="Fragmento ficticio.",
                embedding=[1.0, 0.0],
            )
        ]
    )
    at = _app()
    _login(at)
    _open_memory_tab(at)
    rows = [b for b in at.button if str(b.key).startswith("memory-DEMO-")]
    assert [b.key for b in rows] == ["memory-DEMO-9001", "memory-DEMO-9002"]
    first, second = (str(b.label) for b in rows)
    assert md_escape("DEMO-9001") in first and "v2" in first and "Indexada en el RAG" in first
    assert "No indexada" in second
    _assert_read_only(composed, llm)


def test_list_search_without_match_shows_no_match(composed: Container, memory_dir: Path) -> None:
    """T-33 · búsqueda sin coincidencias: «Ninguna memoria coincide con la búsqueda.»."""
    write(memory_dir, make_memory("DEMO-9001"))
    at = _app()
    _login(at)
    _open_memory_tab(at)
    at.text_input(key="memory-q").input("inexistente-xyzzy").run()
    assert not at.exception, at.exception
    assert [str(info.value) for info in at.info] == [NO_MATCH]


def test_list_search_is_case_insensitive(composed: Container, memory_dir: Path) -> None:
    """T-33 · búsqueda `q` sin distinguir mayúsculas (clave)."""
    write(memory_dir, make_memory("DEMO-9001"))
    write(memory_dir, make_memory("DEMO-9002"))
    at = _app()
    _login(at)
    _open_memory_tab(at)
    at.text_input(key="memory-q").input("demo-9002").run()
    assert not at.exception, at.exception
    assert [b.key for b in at.button if str(b.key).startswith("memory-DEMO-")] == [
        "memory-DEMO-9002"
    ]


def test_list_hides_memories_of_projects_not_visible(composed: Container, memory_dir: Path) -> None:
    """T-33 · proyecto no visible: su memoria no aparece en la lista."""
    write(memory_dir, make_memory("OTRO-1"))
    at = _app()
    _login(at)
    _open_memory_tab(at)
    assert not [b for b in at.button if str(b.key).startswith("memory-OTRO-")]
    assert [str(info.value) for info in at.info] == [EMPTY_TEXT]


# --- Detalle ----------


def test_detail_escapes_llm_text_and_offers_download(
    composed: Container, memory_dir: Path, llm: FakeLLMProvider
) -> None:
    """T-33 · detalle: el texto del LLM (`<script>`, `**negrita**`, `[enlace](…)`) se pinta
    escapado, sin HTML, y se ofrece la descarga del `.md`."""
    memory = make_memory(
        "DEMO-9001",
        objective=HOSTILE,
        scope=HOSTILE,
        business_rules=[HOSTILE],
    )
    path = write(memory_dir, memory)
    at = _app()
    _login(at)
    _open_memory_tab(at)
    _click(at, "memory-DEMO-9001")
    assert _session(at).memory == "DEMO-9001"

    markdown = _markdown(at)
    assert md_escape(HOSTILE) in markdown  # objetivo y alcance, campo a campo
    assert f"- {md_escape(HOSTILE)}" in markdown  # la lista de reglas
    for value in markdown:
        assert "<script>" not in value
        assert "**negrita**" not in value
        assert "[enlace](http://x)" not in value
    assert all(not element.allow_html for element in at.markdown)
    assert md_escape(path.read_text(encoding="utf-8")) not in markdown  # nunca el `.md` entero

    downloads = at.get("download_button")
    assert len(downloads) == 1
    assert downloads[0].proto.label == "Descargar .md"
    _assert_read_only(composed, llm)


def test_detail_shows_all_sections_and_empty_ones_as_dash(
    composed: Container, memory_dir: Path
) -> None:
    """T-33 · detalle: todas las secciones; las vacías se muestran como «—»."""
    write(memory_dir, make_memory("DEMO-9001", decisions=[], changes=[]))
    at = _app()
    _login(at)
    _open_memory_tab(at)
    _click(at, "memory-DEMO-9001")
    markdown = _markdown(at)
    for title in (
        "Objetivo",
        "Alcance",
        "Reglas de negocio",
        "Decisiones",
        "Dependencias",
        "Cambios",
        "Criterios de aceptación",
        "Referencias",
    ):
        assert f"**{title}**" in markdown
    assert markdown.count("—") >= 3  # decisiones, dependencias y cambios
    assert any(md_escape("DEMO-9001") in value and value.startswith("####") for value in markdown)


def test_detail_back_button_returns_to_list(composed: Container, memory_dir: Path) -> None:
    """T-33 · detalle → «Volver a la lista»."""
    write(memory_dir, make_memory("DEMO-9001"))
    at = _app()
    _login(at)
    _open_memory_tab(at)
    _click(at, "memory-DEMO-9001")
    _click(at, "memory-back")
    assert _session(at).memory is None
    assert [b.key for b in at.button if str(b.key).startswith("memory-DEMO-")] == [
        "memory-DEMO-9001"
    ]


@pytest.mark.parametrize("key", ["DEMO-404", "OTRO-1", "../DEMO-9001", "no-valida"])
def test_detail_of_missing_hidden_or_invalid_key_shows_same_warning(
    composed: Container, memory_dir: Path, key: str
) -> None:
    """T-33 · detalle: inexistente, proyecto no visible o clave no válida → mismo aviso."""
    write(memory_dir, make_memory("DEMO-9001"))
    write(memory_dir, make_memory("OTRO-1"))
    write(memory_dir.parent, make_memory("DEMO-9001"))
    at = _app()
    _login(at)
    _open_memory_tab(at)
    _session(at).memory = key
    at.run()
    assert not at.exception, at.exception
    assert [str(w.value) for w in at.warning] == ["No existe esa memoria o no la puedes ver."]
    assert not at.get("download_button")


def test_sidebar_memory_button_resets_open_detail(composed: Container, memory_dir: Path) -> None:
    """T-33: pulsar «Memoria» con un detalle abierto vuelve a la lista."""
    write(memory_dir, make_memory("DEMO-9001"))
    at = _app()
    _login(at)
    _open_memory_tab(at)
    _click(at, "memory-DEMO-9001")
    _click(at, "memory_tab")
    assert _session(at).memory is None
    assert _texts(at).count("Descargar") == 0
