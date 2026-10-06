"""Pruebas del servidor MCP de solo lectura (T-59, fases 1 y 2; principio 1 de CLAUDE.md).

Cubren las seis herramientas (`buscar_historias`, `ver_incidencia`, `revisar_calidad`,
`fuentes_de_contexto`, `proponer_inicio` y `mis_conversaciones`) con el cliente en memoria del
SDK, los permisos por rol, los errores en español sin trazas, que nada escribe en Jira (espías y
`ReadOnlyProxy`), los logs sin contenido, que stdout solo lleva el protocolo en un subproceso
real por stdio, el arranque sin `MCP_USER` y la validación de `MCP_ROLE` en `Settings`.
Todos los datos son sintéticos (`tests/fakes/dataset.py`).
"""

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.types import CallToolResult, ListToolsResult
from pydantic import ValidationError
from structlog.testing import capture_logs

from adapters.base import IssueDetail, IssueSummary, User
from adapters.errors import PublishError
from api.errors import UNEXPECTED
from core.config import Settings
from core.container import Container
from core.conversations import ConversationSummary, InMemoryConversationStore, new_summary
from mcp_server.__main__ import NO_USER
from mcp_server.server import (
    CONVERSATION_READ_METHODS,
    LAST_PROJECT_READ_METHODS,
    MAX_CONVERSATIONS,
    MAX_PROPOSE_CHARS,
    MAX_RESULTS,
    READ_METHODS,
    READ_ONLY_MESSAGE,
    TEXT_TOO_LONG,
    VECTOR_READ_METHODS,
    WRITE_METHODS,
    ReadOnlyProxy,
    build_server,
    read_only_container,
)
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.test_management import FakeTestManagement

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONAL = User(username="af-ficticio", role="functional")
QA = User(username="qa-ficticio", role="qa")
ADMIN = User(username="x", role="admin")
NO_ROLE = User.model_construct(username="sin-rol-ficticio", role="invitado")
PERMISSION_MESSAGE = "No tienes permiso para realizar esta acción."
TOOL_NAMES = {
    "buscar_historias",
    "ver_incidencia",
    "revisar_calidad",
    "fuentes_de_contexto",
    "proponer_inicio",
    "mis_conversaciones",
}
OTHER_USER = "otra-persona-ficticia"
# Marca reconocible del texto libre: nunca debe aparecer en los logs.
PRIVATE_MARKER = "frasemarcadoraficticia"
INTERNAL_DETAIL = "detalle interno /ruta/oculta"
SUBTASK_KEY = "DEMO-5"
COUNTED_KEY = "DEMO-6"
PROCESS_TIMEOUT = 30.0


# --- Dobles de prueba ----------------------------------------------------------------------


class SpyIssueTracker(FakeIssueTracker):
    """FakeIssueTracker que registra el nombre de cada método público al que se accede."""

    def __init__(self) -> None:
        super().__init__()
        self.accessed: list[str] = []
        self.search_limits: list[int] = []

    def __getattribute__(self, name: str) -> Any:
        value = object.__getattribute__(self, name)
        if not name.startswith("_") and callable(value):
            object.__getattribute__(self, "accessed").append(name)
        return value

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        self.search_limits.append(limit)
        return super().search(jql, limit)


class SpyTestManagement(FakeTestManagement):
    """FakeTestManagement que registra el nombre de cada método público al que se accede."""

    __test__ = False

    def __init__(self) -> None:
        super().__init__()
        self.accessed: list[str] = []

    def __getattribute__(self, name: str) -> Any:
        value = object.__getattribute__(self, name)
        if not name.startswith("_") and callable(value):
            object.__getattribute__(self, "accessed").append(name)
        return value


class BrokenIssueTracker(FakeIssueTracker):
    """Tracker cuyas lecturas fallan con un detalle interno que nunca debe llegar al cliente."""

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        raise RuntimeError(INTERNAL_DETAIL)

    def get_issue(self, key: str) -> IssueDetail:
        raise RuntimeError(INTERNAL_DETAIL)


class SpyConversationStore(InMemoryConversationStore):
    """Almacén en memoria que registra los límites de `list_for` y cualquier escritura."""

    def __init__(self) -> None:
        super().__init__()
        self.list_limits: list[int] = []
        self.write_calls: list[str] = []

    def start(self, summary: ConversationSummary) -> None:
        self.write_calls.append("start")
        super().start(summary)

    def update(self, thread_id: str, **changes: Any) -> None:
        self.write_calls.append("update")
        super().update(thread_id, **changes)

    def list_for(self, username: str, limit: int = 50) -> list[ConversationSummary]:
        self.list_limits.append(limit)
        return super().list_for(username, limit)


class BrokenConversationStore(InMemoryConversationStore):
    """Almacén cuya lectura falla con un detalle interno que nunca debe llegar al cliente."""

    def list_for(self, username: str, limit: int = 50) -> list[ConversationSummary]:
        raise RuntimeError(INTERNAL_DETAIL)


# --- Utilidades ----------------------------------------------------------------------------


def _container(tmp_path: Path, **overrides: object) -> Container:
    return fake_container(tmp_path / "memoria", publish_mode="simulation", **overrides)


def _call(container: Container, user: User, tool: str, args: dict[str, Any]) -> CallToolResult:
    server = build_server(container, user)

    async def run() -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(tool, args)

    return anyio.run(run)


def _list_tools(container: Container, user: User) -> ListToolsResult:
    server = build_server(container, user)

    async def run() -> ListToolsResult:
        async with Client(server) as client:
            return await client.list_tools()

    return anyio.run(run)


def _text(result: CallToolResult) -> str:
    first = result.content[0]
    assert first.type == "text"
    return first.text


def _keys(result: CallToolResult) -> list[str]:
    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    return [item["key"] for item in result.structured_content["results"]]


def _subtask() -> IssueDetail:
    return IssueDetail(
        key=SUBTASK_KEY,
        summary="[CP-01] Renovar un préstamo con reservas (caso ficticio)",
        issue_type="Subtarea",
        status="Por hacer",
        parent_key="DEMO-3",
        description_text="Caso de prueba ficticio para renovar un préstamo.",
    )


def _conversation(
    thread_id: str,
    username: str,
    origin_key: str | None,
    minutes_ago: int,
    mode: str = "functional",
    origin_kind: str = "story",
) -> ConversationSummary:
    """Fila ficticia del índice, con `updated_at` controlado para comprobar el orden."""
    summary = new_summary(
        thread_id=thread_id,
        username=username,
        project=dataset.PROJECT_KEY,
        mode=mode,
        origin_kind=origin_kind,
        origin_key=origin_key,
    )
    moment = datetime(2026, 1, 15, 12, 0, tzinfo=UTC) - timedelta(minutes=minutes_ago)
    return summary.model_copy(
        update={
            "created_at": moment - timedelta(hours=1),
            "updated_at": moment,
            "artifact_id": f"artefacto-ficticio-{thread_id}",
            "version": 2,
            "status": "in_review",
        }
    )


def _seeded_store(store: InMemoryConversationStore) -> InMemoryConversationStore:
    """Tres conversaciones del usuario functional y una de otra persona (la más reciente)."""
    for row in (
        _conversation("hilo-ficticio-1", FUNCTIONAL.username, "DEMO-2", minutes_ago=30),
        _conversation("hilo-ficticio-2", FUNCTIONAL.username, "DEMO-3", minutes_ago=5),
        _conversation(
            "hilo-ficticio-3", FUNCTIONAL.username, None, minutes_ago=60, origin_kind="need"
        ),
        _conversation("hilo-ficticio-4", OTHER_USER, "DEMO-4", minutes_ago=1),
    ):
        store.rows[row.thread_id] = row
    return store


def _options(result: CallToolResult) -> list[tuple[str, str]]:
    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    return [(o["kind"], o["label"]) for o in result.structured_content["options"]]


def _without_mark(data: dict[str, Any]) -> dict[str, Any]:
    """El resultado sin `aviso` ni `campos_no_confiables` (PA-249): lo que ya devolvía."""
    return {k: v for k, v in data.items() if k not in {"aviso", "campos_no_confiables"}}


def _logged(events: list[dict[str, Any]]) -> str:
    return json.dumps(events, ensure_ascii=False, default=str)


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return _container(tmp_path)


@pytest.fixture
def subtask_container(tmp_path: Path) -> Container:
    tracker = FakeIssueTracker()
    tracker.issues[SUBTASK_KEY] = _subtask()
    return _container(tmp_path, issue_tracker=tracker)


# --- 1. Lista de herramientas --------------------------------------------------------------


def test_list_tools_returns_exactly_six_read_only_tools(container: Container) -> None:
    """T-59 caso 1 (fase 2): exactamente las seis herramientas, todas con `read_only_hint=True`."""
    tools = _list_tools(container, FUNCTIONAL).tools

    assert {tool.name for tool in tools} == TOOL_NAMES
    assert len(tools) == len(TOOL_NAMES)
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


def test_list_tools_quality_description_warns_it_takes_minutes(container: Container) -> None:
    """T-59 caso 1: la descripción de `revisar_calidad` avisa de que tarda minutos."""
    tools = {tool.name: tool for tool in _list_tools(container, FUNCTIONAL).tools}

    description = (tools["revisar_calidad"].description or "").lower()
    assert "minutos" in description
    assert "tarda" in description


# --- 2. buscar_historias -------------------------------------------------------------------


def test_search_returns_recent_issues_without_text(container: Container) -> None:
    """T-59 caso 2: sin texto devuelve las recientes del proyecto (épica y HU)."""
    result = _call(container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO"})

    assert set(_keys(result)) == {dataset.EPIC_KEY, *dataset.STORY_KEYS}
    assert result.structured_content is not None
    assert result.structured_content["project"] == "DEMO"
    item = result.structured_content["results"][0]
    assert set(item) == {"key", "summary", "issue_type", "status"}


def test_search_normalizes_lowercase_project(container: Container) -> None:
    """T-59 caso 2: la clave del proyecto en minúsculas se normaliza."""
    result = _call(container, FUNCTIONAL, "buscar_historias", {"proyecto": " demo "})

    assert result.structured_content is not None
    assert result.structured_content["project"] == "DEMO"
    assert dataset.STORY_KEYS[0] in _keys(result)


def test_search_filters_by_text(container: Container) -> None:
    """T-59 caso 2: con texto devuelve solo las incidencias que lo contienen."""
    result = _call(
        container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO", "texto": "renovar"}
    )

    # La épica ficticia también menciona «renovar» en su descripción.
    assert set(_keys(result)) == {dataset.EPIC_KEY, "DEMO-3"}


def test_search_text_without_matches_returns_empty_list(container: Container) -> None:
    """T-59 caso 2 (límite): un texto sin coincidencias da una lista vacía, sin error."""
    result = _call(
        container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO", "texto": "zzqxficticio"}
    )

    assert _keys(result) == []


@pytest.mark.parametrize("text", ["DEMO-2", "demo-2", "  Demo-2  "])
def test_search_exact_key_returns_that_issue(container: Container, text: str) -> None:
    """T-59 caso 2: una clave exacta del proyecto (también en minúsculas) devuelve esa HU."""
    result = _call(container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO", "texto": text})

    assert _keys(result) == ["DEMO-2"]
    assert result.structured_content is not None
    assert result.structured_content["results"][0]["summary"] == dataset.STORIES["DEMO-2"].summary


def test_search_exact_key_not_found_returns_empty_list(container: Container) -> None:
    """T-59 caso 2 (límite): una clave del proyecto que no existe da una lista vacía."""
    result = _call(
        container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO", "texto": "DEMO-999"}
    )

    assert _keys(result) == []


def test_search_key_of_other_project_returns_empty_list(tmp_path: Path) -> None:
    """T-59 caso 2 (negativo): una clave de otro proyecto da una lista vacía y no se consulta."""
    tracker = SpyIssueTracker()
    container = _container(tmp_path, issue_tracker=tracker)

    result = _call(
        container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO", "texto": "OTRO-2"}
    )

    assert _keys(result) == []
    assert "get_issue" not in tracker.accessed
    assert "search" not in tracker.accessed


@pytest.mark.parametrize("project", ["DEMO-1", "de mo", "", "1DEMO", 'DEMO" OR 1=1'])
def test_search_invalid_project_returns_spanish_error(container: Container, project: str) -> None:
    """T-59 caso 2 (error): un proyecto inválido da `is_error` con mensaje en español."""
    result = _call(container, FUNCTIONAL, "buscar_historias", {"proyecto": project})

    assert result.is_error is True
    assert "no es una clave de proyecto válida" in _text(result)
    assert "Traceback" not in _text(result)


def test_search_excludes_subtasks_without_text(subtask_container: Container) -> None:
    """T-59 caso 2: las recientes no incluyen subtareas (casos de prueba)."""
    result = _call(subtask_container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO"})

    assert SUBTASK_KEY not in _keys(result)
    assert "DEMO-3" in _keys(result)


def test_search_excludes_subtasks_with_text(subtask_container: Container) -> None:
    """T-59 caso 2: la búsqueda por texto tampoco devuelve subtareas."""
    result = _call(
        subtask_container,
        FUNCTIONAL,
        "buscar_historias",
        {"proyecto": "DEMO", "texto": "renovar"},
    )

    assert SUBTASK_KEY not in _keys(result)
    assert "DEMO-3" in _keys(result)


def test_search_excludes_subtask_by_exact_key(subtask_container: Container) -> None:
    """T-59 caso 2: buscar la clave exacta de una subtarea no la devuelve."""
    result = _call(
        subtask_container,
        FUNCTIONAL,
        "buscar_historias",
        {"proyecto": "DEMO", "texto": SUBTASK_KEY},
    )

    assert _keys(result) == []


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(-5, 1), (0, 1), (1, 1), (10, 10), (MAX_RESULTS, MAX_RESULTS), (999, MAX_RESULTS)],
)
def test_search_limit_is_clamped(tmp_path: Path, limit: int, expected: int) -> None:
    """T-59 caso 2 (límite): `limite` se acota a 1..50 antes de consultar Jira."""
    tracker = SpyIssueTracker()
    container = _container(tmp_path, issue_tracker=tracker)

    result = _call(container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO", "limite": limit})

    assert not result.is_error
    assert tracker.search_limits == [expected]
    assert len(_keys(result)) <= expected


def test_search_limit_one_returns_single_result(container: Container) -> None:
    """T-59 caso 2 (límite): con `limite=1` llega un único resultado."""
    result = _call(container, FUNCTIONAL, "buscar_historias", {"proyecto": "DEMO", "limite": 1})

    assert len(_keys(result)) == 1


# --- 3. ver_incidencia ---------------------------------------------------------------------


def test_view_issue_returns_all_fields(container: Container) -> None:
    """T-59 caso 3: la ficha trae clave, proyecto, resumen, tipo, estado, épica y conteos."""
    result = _call(container, FUNCTIONAL, "ver_incidencia", {"clave": "demo-3"})

    assert not result.is_error, _text(result)
    data = result.structured_content
    assert data is not None
    story = dataset.STORIES["DEMO-3"]
    # PA-249: el aviso y la lista de campos no confiables van delante; el resto no cambia.
    assert list(data)[:2] == ["aviso", "campos_no_confiables"]
    assert data["campos_no_confiables"] == ["summary", "description"]
    assert _without_mark(data) == {
        "key": "DEMO-3",
        "project": "DEMO",
        "summary": story.summary,
        "issue_type": "Story",
        "status": story.status,
        "epic_key": dataset.EPIC_KEY,
        "description": story.description_text,
        "criteria_count": 0,
        "rules_count": 0,
    }
    assert json.loads(_text(result)) == data


def test_view_issue_counts_distinct_criteria_and_rules(tmp_path: Path) -> None:
    """T-59 caso 3: `criteria_count` y `rules_count` cuentan IDs distintos de CA y RN."""
    tracker = FakeIssueTracker()
    tracker.issues[COUNTED_KEY] = IssueDetail(
        key=COUNTED_KEY,
        summary="[HU-04] Avisar del vencimiento (ficticia)",
        issue_type="Story",
        status="Por hacer",
        description_text=(
            "CA-01: aviso 2 días antes. CA-02: aviso el mismo día. CA-01 se repite. "
            "RN-01: solo por correo ficticio."
        ),
    )
    container = _container(tmp_path, issue_tracker=tracker)

    result = _call(container, FUNCTIONAL, "ver_incidencia", {"clave": COUNTED_KEY})

    assert result.structured_content is not None
    assert result.structured_content["criteria_count"] == 2
    assert result.structured_content["rules_count"] == 1
    assert result.structured_content["epic_key"] is None


def test_view_issue_epic_has_no_epic_key(container: Container) -> None:
    """T-59 caso 3 (límite): la épica no tiene épica padre."""
    result = _call(container, FUNCTIONAL, "ver_incidencia", {"clave": dataset.EPIC_KEY})

    assert result.structured_content is not None
    assert result.structured_content["issue_type"] == "Epic"
    assert result.structured_content["epic_key"] is None


@pytest.mark.parametrize("key", ["zz", "DEMO", "DEMO-", "-3", "DEMO 3", ""])
def test_view_issue_invalid_key_returns_spanish_error(container: Container, key: str) -> None:
    """T-59 caso 3 (error): una clave inválida da `is_error` con mensaje en español."""
    result = _call(container, FUNCTIONAL, "ver_incidencia", {"clave": key})

    assert result.is_error is True
    assert "no es una clave de Jira válida" in _text(result)
    assert result.structured_content is None


def test_view_issue_missing_key_returns_spanish_error(container: Container) -> None:
    """T-59 caso 3 (error): una incidencia inexistente da `is_error` con mensaje en español."""
    result = _call(container, FUNCTIONAL, "ver_incidencia", {"clave": "DEMO-999"})

    assert result.is_error is True
    assert _text(result) == "La incidencia DEMO-999 no existe."


# --- 4. revisar_calidad --------------------------------------------------------------------


def test_review_quality_returns_report_for_functional(container: Container) -> None:
    """T-59 caso 4: con rol functional devuelve INVEST (6 letras), hallazgos, fuentes y modelo."""
    result = _call(container, FUNCTIONAL, "revisar_calidad", {"clave": "DEMO-3"})

    assert not result.is_error, _text(result)
    data = result.structured_content
    assert data is not None
    assert data["key"] == "DEMO-3"
    assert [item["letter"] for item in data["invest"]] == list("INVEST")
    assert all(item["verdict"] and item["reason"] for item in data["invest"])
    assert data["findings"]
    assert all({"kind", "target_id", "explanation", "proposal"} <= set(f) for f in data["findings"])
    assert data["sources"]
    assert all(source["ref"] for source in data["sources"])
    assert data["model"] == "fake/fake-model"
    assert data["prompt_version"]
    assert isinstance(data["open_questions"], list)


def test_review_quality_missing_key_returns_spanish_error(container: Container) -> None:
    """T-59 caso 4 (error): revisar una incidencia inexistente da un error en español."""
    result = _call(container, FUNCTIONAL, "revisar_calidad", {"clave": "DEMO-999"})

    assert result.is_error is True
    assert "DEMO-999" in _text(result)
    assert "Traceback" not in _text(result)


def test_review_quality_invalid_key_returns_spanish_error(container: Container) -> None:
    """T-59 caso 4 (error): una clave inválida da un error en español."""
    result = _call(container, FUNCTIONAL, "revisar_calidad", {"clave": "no-es-clave"})

    assert result.is_error is True
    assert "no es una clave de Jira válida" in _text(result)


# --- 5. Permisos por rol -------------------------------------------------------------------


def test_qa_cannot_review_quality(container: Container) -> None:
    """T-59 caso 5 y PA-249: el rol qa no puede revisar la calidad (permiso de generar HU): la
    herramienta ni se le ofrece y llamarla da error sin resultado."""
    result = _call(container, QA, "revisar_calidad", {"clave": "DEMO-3"})

    assert "revisar_calidad" not in {tool.name for tool in _list_tools(container, QA).tools}
    assert result.is_error is True
    assert result.structured_content is None


def test_qa_can_search_and_view(container: Container) -> None:
    """T-59 caso 5: el rol qa sí puede buscar y ver incidencias."""
    search = _call(container, QA, "buscar_historias", {"proyecto": "DEMO"})
    view = _call(container, QA, "ver_incidencia", {"clave": "DEMO-2"})

    assert not search.is_error
    assert "DEMO-2" in _keys(search)
    assert not view.is_error
    assert view.structured_content is not None
    assert view.structured_content["key"] == "DEMO-2"


def test_admin_cannot_review_quality(container: Container) -> None:
    """T-59 caso 5 y PA-249: admin no tiene GENERATE_STORY: no se le ofrece revisar la calidad."""
    result = _call(container, ADMIN, "revisar_calidad", {"clave": "DEMO-3"})

    assert "revisar_calidad" not in {tool.name for tool in _list_tools(container, ADMIN).tools}
    assert result.is_error is True
    assert result.structured_content is None


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("buscar_historias", {"proyecto": "DEMO"}),
        ("ver_incidencia", {"clave": "DEMO-2"}),
        ("fuentes_de_contexto", {"clave": "DEMO-3"}),
        ("proponer_inicio", {"texto": "demo-3", "proyecto": "DEMO"}),
    ],
)
def test_unknown_role_is_denied_every_tool(
    container: Container, tool: str, args: dict[str, Any]
) -> None:
    """T-59 caso 5 (negativo): un rol sin permisos no puede usar ninguna herramienta
    (`revisar_calidad` ni se le ofrece: PA-249, `test_unknown_role_is_not_offered_review`)."""
    result = _call(container, NO_ROLE, tool, args)

    assert result.is_error is True
    assert _text(result) == PERMISSION_MESSAGE
    assert result.structured_content is None


def test_unknown_role_is_not_offered_review(container: Container) -> None:
    """PA-249: sin el permiso de revisar no se ofrece `revisar_calidad`; llamarla da error."""
    result = _call(container, NO_ROLE, "revisar_calidad", {"clave": "DEMO-3"})

    assert "revisar_calidad" not in {t.name for t in _list_tools(container, NO_ROLE).tools}
    assert result.is_error is True
    assert result.structured_content is None


def test_permission_checked_before_reading_jira(tmp_path: Path) -> None:
    """T-59 caso 5: sin permiso no se llega a consultar Jira."""
    tracker = SpyIssueTracker()
    container = _container(tmp_path, issue_tracker=tracker)

    _call(container, NO_ROLE, "buscar_historias", {"proyecto": "DEMO"})
    _call(container, NO_ROLE, "ver_incidencia", {"clave": "DEMO-2"})
    _call(container, QA, "revisar_calidad", {"clave": "DEMO-3"})
    _call(container, NO_ROLE, "fuentes_de_contexto", {"clave": "DEMO-3"})
    _call(container, ADMIN, "proponer_inicio", {"texto": "demo-3 renovar", "proyecto": "DEMO"})

    assert "search" not in tracker.accessed
    assert "get_issue" not in tracker.accessed


# --- 6. Errores sin trazas -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("buscar_historias", {"proyecto": "DEMO"}),
        ("buscar_historias", {"proyecto": "DEMO", "texto": "renovar"}),
        ("buscar_historias", {"proyecto": "DEMO", "texto": "DEMO-2"}),
        ("ver_incidencia", {"clave": "DEMO-2"}),
        ("revisar_calidad", {"clave": "DEMO-3"}),
        ("fuentes_de_contexto", {"clave": "DEMO-3"}),
        ("proponer_inicio", {"texto": "quiero evolucionar demo-3", "proyecto": "DEMO"}),
        ("proponer_inicio", {"texto": "renovar", "proyecto": "DEMO"}),
    ],
)
def test_unexpected_error_returns_generic_message(
    tmp_path: Path, tool: str, args: dict[str, Any]
) -> None:
    """T-59 caso 6: un fallo interno da el mensaje genérico, sin el detalle ni la traza."""
    container = _container(tmp_path, issue_tracker=BrokenIssueTracker())

    result = _call(container, FUNCTIONAL, tool, args)

    assert result.is_error is True
    text = _text(result)
    assert text == UNEXPECTED
    assert INTERNAL_DETAIL not in text
    assert "/ruta/oculta" not in text
    assert "Traceback" not in text
    assert "RuntimeError" not in text
    assert result.structured_content is None


# --- 7. Ninguna herramienta escribe --------------------------------------------------------


def test_no_tool_calls_write_methods(tmp_path: Path) -> None:
    """T-59 caso 7: tras usar las tres herramientas, no se accede a ningún método de escritura."""
    tracker = SpyIssueTracker()
    tests = SpyTestManagement()
    container = _container(tmp_path, issue_tracker=tracker, test_management=tests)
    calls: list[tuple[str, dict[str, Any]]] = [
        ("buscar_historias", {"proyecto": "DEMO"}),
        ("buscar_historias", {"proyecto": "DEMO", "texto": "renovar"}),
        ("buscar_historias", {"proyecto": "DEMO", "texto": "DEMO-2"}),
        ("ver_incidencia", {"clave": "DEMO-3"}),
        ("revisar_calidad", {"clave": "DEMO-3"}),
    ]

    for tool, args in calls:
        result = _call(container, FUNCTIONAL, tool, args)
        assert not result.is_error, (tool, _text(result))

    assert tracker.accessed, "el espía debe registrar las lecturas"
    assert not WRITE_METHODS & set(tracker.accessed)
    assert not WRITE_METHODS & set(tests.accessed)
    assert tracker.writes == []
    assert tests.publish_calls == 0
    assert tests.executions == []


def test_write_methods_constant_lists_every_write() -> None:
    """T-59 caso 7: `WRITE_METHODS` incluye las cinco escrituras de Jira."""
    assert {
        "create_story",
        "update_story",
        "link",
        "publish_suite",
        "record_execution",
    } == WRITE_METHODS


@pytest.mark.parametrize("method", sorted(WRITE_METHODS))
def test_read_only_proxy_blocks_write_methods(method: str) -> None:
    """T-59 caso 7: `ReadOnlyProxy` lanza `PublishError` al acceder a una escritura."""
    tracker = FakeIssueTracker()
    tests = FakeTestManagement()
    for inner in (tracker, tests):
        proxy = ReadOnlyProxy(inner)
        with pytest.raises(PublishError) as raised:
            getattr(proxy, method)
        assert str(raised.value) == READ_ONLY_MESSAGE
    assert tracker.writes == []
    assert tests.publish_calls == 0


def test_read_only_proxy_delegates_reads() -> None:
    """T-59 caso 7: `ReadOnlyProxy` delega las lecturas en el objeto envuelto."""
    tracker = ReadOnlyProxy(FakeIssueTracker())
    tests = ReadOnlyProxy(FakeTestManagement())

    assert tracker.get_issue("DEMO-2").key == "DEMO-2"
    assert {i.key for i in tracker.search('project = "DEMO"')} >= set(dataset.STORY_KEYS)
    assert tracker.list_projects()[0].key == dataset.PROJECT_KEY
    assert tests.list_cases("DEMO-3") == []


def _protocol_methods(protocol: type) -> set[str]:
    return {
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    }


def test_read_and_write_lists_cover_every_jira_protocol_method() -> None:
    """Lista blanca: lecturas + escrituras son exactamente los métodos de los Protocol de Jira.

    Si se añade un método a `IssueTracker` o `TestManagement`, esta prueba obliga a decidir si
    es de lectura; mientras tanto, el proxy lo bloquea.
    """
    from adapters.base import IssueTracker, TestManagement

    protocol = _protocol_methods(IssueTracker) | _protocol_methods(TestManagement)
    assert set(READ_METHODS) | set(WRITE_METHODS) == protocol
    assert not set(READ_METHODS) & set(WRITE_METHODS)


@pytest.mark.parametrize("name", ["_inner", "_send", "_http", "delete_issue", "transition"])
def test_read_only_proxy_blocks_any_other_attribute(name: str) -> None:
    """Privados, métodos futuros o desconocidos: bloqueados y ausentes para `hasattr`."""
    proxy = ReadOnlyProxy(FakeIssueTracker())

    with pytest.raises(PublishError, match="solo lectura"):
        getattr(proxy, name)
    assert not hasattr(proxy, name)


def test_read_only_proxy_has_no_instance_dict() -> None:
    """Sin `__dict__`: `vars()` no expone el adaptador envuelto."""
    proxy = ReadOnlyProxy(FakeIssueTracker())

    assert not hasattr(proxy, "__dict__")
    with pytest.raises(TypeError):
        vars(proxy)


def test_read_only_proxy_rejects_attribute_assignment() -> None:
    proxy = ReadOnlyProxy(FakeIssueTracker())

    with pytest.raises(PublishError, match="solo lectura"):
        proxy.search = lambda *args, **kwargs: []  # type: ignore[method-assign]


def _store_methods(protocol: type) -> set[str]:
    return {n for n, v in vars(protocol).items() if callable(v) and not n.startswith("_")}


@pytest.mark.parametrize(
    ("field", "allowed", "blocked"),
    [
        ("vector_store", VECTOR_READ_METHODS, ("upsert", "delete_by_document", "replace_document")),
        ("conversations", CONVERSATION_READ_METHODS, ("start", "update")),
        ("last_projects", LAST_PROJECT_READ_METHODS, ("set",)),
    ],
)
def test_read_only_container_wraps_agent_stores(
    container: Container, field: str, allowed: frozenset[str], blocked: tuple[str, ...]
) -> None:
    """RAG, conversaciones y último proyecto: solo sus lecturas; las escrituras, bloqueadas."""
    safe = read_only_container(container)
    proxy = getattr(safe, field)

    assert isinstance(proxy, ReadOnlyProxy)
    assert getattr(container, field) is not proxy
    for name in allowed:
        assert callable(getattr(proxy, name))
    for name in blocked:
        with pytest.raises(PublishError, match="solo lectura"):
            getattr(proxy, name)


def test_store_read_lists_are_reads_of_their_protocols() -> None:
    """Las listas blancas solo contienen métodos de lectura que existen en cada Protocol."""
    from adapters.base import VectorStore
    from core.conversations import ConversationStore
    from core.projects import LastProjectStore

    assert (
        _store_methods(VectorStore)
        - {
            "upsert",
            "delete_by_document",
            "replace_document",
        }
        == VECTOR_READ_METHODS
    )
    assert _store_methods(ConversationStore) - {"start", "update"} == CONVERSATION_READ_METHODS
    assert _store_methods(LastProjectStore) - {"set"} == LAST_PROJECT_READ_METHODS


def test_read_only_container_wraps_jira_only(container: Container) -> None:
    """T-59 caso 7: `read_only_container` envuelve Jira y deja intacto el contenedor original."""
    original_tracker = container.issue_tracker
    original_tests = container.test_management

    safe = read_only_container(container)

    assert isinstance(safe.issue_tracker, ReadOnlyProxy)
    assert isinstance(safe.test_management, ReadOnlyProxy)
    assert container.issue_tracker is original_tracker
    assert container.test_management is original_tests
    assert safe.llm is container.llm
    with pytest.raises(PublishError):
        _ = safe.issue_tracker.create_story
    with pytest.raises(PublishError):
        _ = safe.test_management.publish_suite


# --- 7b. Fase 2: fuentes_de_contexto ---------------------------------------------------------


def test_context_sources_origin_story_is_required_jira_source(container: Container) -> None:
    """T-59 fase 2: la HU de origen sale la primera, de tipo jira y con `required=True`."""
    result = _call(container, FUNCTIONAL, "fuentes_de_contexto", {"clave": "DEMO-3"})

    assert not result.is_error, _text(result)
    data = result.structured_content
    assert data is not None
    assert data["key"] == "DEMO-3"
    origin = [s for s in data["sources"] if s["ref"] == "DEMO-3"]
    assert len(origin) == 1
    assert origin[0]["kind"] == "jira"
    assert origin[0]["required"] is True
    assert origin[0]["title"] == dataset.STORIES["DEMO-3"].summary
    assert all(s["required"] is False for s in data["sources"] if s["ref"] != "DEMO-3")
    for source in data["sources"]:
        assert set(source) == {"ref", "kind", "title", "category", "required"}
        assert source["kind"] in {"jira", "rag", "memory"}
    assert json.loads(_text(result)) == data


def test_context_sources_includes_epic_and_rag_documents(container: Container) -> None:
    """T-59 fase 2: además de la HU, entran su épica y los documentos del RAG ficticio."""
    result = _call(container, FUNCTIONAL, "fuentes_de_contexto", {"clave": "DEMO-3"})

    assert result.structured_content is not None
    refs = {s["ref"]: s["kind"] for s in result.structured_content["sources"]}
    assert refs[dataset.EPIC_KEY] == "jira"
    assert {ref for ref, kind in refs.items() if kind == "rag"} == set(dataset.DOCUMENTS)


def test_context_sources_budget_used_within_limit(container: Container) -> None:
    """T-59 fase 2: el presupuesto trae `used <= limit` y los contadores no son negativos."""
    result = _call(container, FUNCTIONAL, "fuentes_de_contexto", {"clave": "DEMO-3"})

    assert result.structured_content is not None
    budget = result.structured_content["budget"]
    assert set(budget) == {"used", "limit", "dropped_sources", "truncated_sources"}
    assert 0 < budget["used"] <= budget["limit"]
    assert budget["dropped_sources"] >= 0
    assert budget["truncated_sources"] >= 0


@pytest.mark.parametrize("key", ["demo-3", "  Demo-3  "])
def test_context_sources_normalizes_lowercase_key(container: Container, key: str) -> None:
    """T-59 fase 2: la clave en minúsculas o con espacios se normaliza a `DEMO-3`."""
    result = _call(container, FUNCTIONAL, "fuentes_de_contexto", {"clave": key})

    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    assert result.structured_content["key"] == "DEMO-3"
    required = [s["ref"] for s in result.structured_content["sources"] if s["required"]]
    assert required == ["DEMO-3"]


def test_context_sources_qa_can_view(container: Container) -> None:
    """T-59 fase 2: el rol qa tiene VIEW_CONTEXT y puede ver las fuentes."""
    result = _call(container, QA, "fuentes_de_contexto", {"clave": "DEMO-2"})

    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    assert result.structured_content["key"] == "DEMO-2"


@pytest.mark.parametrize("key", ["zz", "DEMO", "DEMO-", "-3", "DEMO 3", ""])
def test_context_sources_invalid_key_returns_spanish_error(container: Container, key: str) -> None:
    """T-59 fase 2 (error): una clave inválida da `is_error` con mensaje en español."""
    result = _call(container, FUNCTIONAL, "fuentes_de_contexto", {"clave": key})

    assert result.is_error is True
    assert "no es una clave de Jira válida" in _text(result)
    assert "Traceback" not in _text(result)
    assert result.structured_content is None


def test_context_sources_missing_key_returns_spanish_error(container: Container) -> None:
    """T-59 fase 2 (error): una incidencia inexistente da `is_error` con mensaje en español."""
    result = _call(container, FUNCTIONAL, "fuentes_de_contexto", {"clave": "demo-999"})

    assert result.is_error is True
    assert _text(result) == "La incidencia DEMO-999 no existe."
    assert result.structured_content is None


def test_context_sources_without_view_context_is_denied(tmp_path: Path) -> None:
    """T-59 fase 2 (negativo): un rol sin VIEW_CONTEXT recibe «permiso denegado» sin leer Jira."""
    tracker = SpyIssueTracker()
    container = _container(tmp_path, issue_tracker=tracker)

    result = _call(container, NO_ROLE, "fuentes_de_contexto", {"clave": "DEMO-3"})

    assert result.is_error is True
    assert _text(result) == PERMISSION_MESSAGE
    assert "get_issue" not in tracker.accessed


# --- 7c. Fase 2: proponer_inicio -------------------------------------------------------------


def test_propose_lowercase_key_offers_evolve_for_functional(container: Container) -> None:
    """T-59 fase 2: functional, «demo-3» en el texto → reconoce la HU y ofrece evolucionarla."""
    result = _call(
        container,
        FUNCTIONAL,
        "proponer_inicio",
        {"texto": "quiero cambiar demo-3 por favor", "proyecto": "DEMO"},
    )

    assert _options(result) == [("evolve", "Evolucionar DEMO-3")]
    data = result.structured_content
    assert data is not None
    assert [r["key"] for r in data["recognized"]] == ["DEMO-3"]
    assert data["similar"] == []
    assert data["project"] == "DEMO"
    assert data["project_changed"] is False
    assert data["options"][0]["origin"] == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}


def test_propose_lowercase_key_offers_tests_for_qa(container: Container) -> None:
    """T-59 fase 2: qa, «demo-3» en el texto → reconoce la HU y ofrece preparar sus pruebas."""
    result = _call(
        container, QA, "proponer_inicio", {"texto": "pruebas de demo-3", "proyecto": "demo"}
    )

    assert _options(result) == [("tests", "Preparar pruebas de DEMO-3")]
    assert result.structured_content is not None
    assert [r["key"] for r in result.structured_content["recognized"]] == ["DEMO-3"]


def test_propose_epic_key_offers_new_story_for_functional(container: Container) -> None:
    """T-59 fase 2 · PA-285: functional, clave de la épica → «HU nueva en la épica DEMO-1»."""
    result = _call(
        container, FUNCTIONAL, "proponer_inicio", {"texto": "demo-1", "proyecto": "DEMO"}
    )

    assert _options(result) == [("new_story_in_epic", "HU nueva en la épica DEMO-1")]


def test_propose_epic_key_gives_no_option_for_qa(container: Container) -> None:
    """T-59 fase 2 (límite): qa parte siempre de una HU; con la épica no hay opción."""
    result = _call(container, QA, "proponer_inicio", {"texto": "demo-1", "proyecto": "DEMO"})

    assert _options(result) == []
    assert result.structured_content is not None
    assert [r["key"] for r in result.structured_content["recognized"]] == [dataset.EPIC_KEY]


def test_propose_text_without_keys_offers_similar_and_new_need(container: Container) -> None:
    """T-59 fase 2: functional, texto sin claves → HU parecidas y la opción de necesidad nueva."""
    result = _call(
        container, FUNCTIONAL, "proponer_inicio", {"texto": "renovar", "proyecto": "DEMO"}
    )

    options = _options(result)
    data = result.structured_content
    assert data is not None
    assert data["recognized"] == []
    similar = [s["key"] for s in data["similar"]]
    assert "DEMO-3" in similar
    assert dataset.EPIC_KEY not in similar  # solo HU, nunca épicas
    assert ("evolve", "Evolucionar DEMO-3") in options
    assert options[-1] == ("new_need", "Crear HU nueva")
    assert data["options"][-1]["origin"] == {"kind": "need", "text": "renovar", "project": "DEMO"}


def test_propose_text_without_keys_offers_similar_tests_for_qa(container: Container) -> None:
    """T-59 fase 2: qa, texto sin claves → pruebas de HU parecidas y nunca necesidad nueva."""
    result = _call(container, QA, "proponer_inicio", {"texto": "renovar", "proyecto": "DEMO"})

    options = _options(result)
    assert ("tests", "Preparar pruebas de DEMO-3") in options
    assert all(kind == "tests" for kind, _ in options)


def test_propose_text_without_matches_offers_only_new_need(container: Container) -> None:
    """T-59 fase 2 (límite): functional, sin claves ni parecidas → solo «Crear HU nueva»."""
    result = _call(
        container, FUNCTIONAL, "proponer_inicio", {"texto": "zzqx ficticio", "proyecto": "DEMO"}
    )

    assert _options(result) == [("new_need", "Crear HU nueva")]
    assert result.structured_content is not None
    assert result.structured_content["similar"] == []


def test_propose_text_without_matches_gives_no_option_for_qa(container: Container) -> None:
    """T-59 fase 2 (límite): qa, sin claves ni parecidas → ninguna opción."""
    result = _call(container, QA, "proponer_inicio", {"texto": "zzqx ficticio", "proyecto": "DEMO"})

    assert _options(result) == []


def test_propose_missing_key_is_not_recognized(container: Container) -> None:
    """T-59 fase 2 (límite): una clave que no existe no se reconoce; queda la necesidad nueva."""
    result = _call(
        container, FUNCTIONAL, "proponer_inicio", {"texto": "demo-999", "proyecto": "DEMO"}
    )

    assert _options(result) == [("new_need", "Crear HU nueva")]
    assert result.structured_content is not None
    assert result.structured_content["recognized"] == []


def test_propose_empty_text_gives_no_option(container: Container) -> None:
    """T-59 fase 2 (límite): un texto vacío no da opciones ni consulta HU parecidas."""
    result = _call(container, FUNCTIONAL, "proponer_inicio", {"texto": "", "proyecto": "DEMO"})

    assert _options(result) == []


def test_propose_text_over_limit_returns_too_long(tmp_path: Path) -> None:
    """T-59 fase 2 (error): 4001 caracteres → `is_error` con TEXT_TOO_LONG, sin leer Jira."""
    tracker = SpyIssueTracker()
    container = _container(tmp_path, issue_tracker=tracker)
    text = "x" * (MAX_PROPOSE_CHARS + 1)

    result = _call(container, FUNCTIONAL, "proponer_inicio", {"texto": text, "proyecto": "DEMO"})

    assert MAX_PROPOSE_CHARS == 4000
    assert result.is_error is True
    assert _text(result) == TEXT_TOO_LONG
    assert "4000" in _text(result)
    assert result.structured_content is None
    assert "get_issue" not in tracker.accessed
    assert "search" not in tracker.accessed


def test_propose_text_at_limit_is_accepted(container: Container) -> None:
    """T-59 fase 2 (límite): exactamente 4000 caracteres se aceptan."""
    text = ("demo-3 " + "x" * MAX_PROPOSE_CHARS)[:MAX_PROPOSE_CHARS]
    assert len(text) == MAX_PROPOSE_CHARS

    result = _call(container, FUNCTIONAL, "proponer_inicio", {"texto": text, "proyecto": "DEMO"})

    assert _options(result) == [("evolve", "Evolucionar DEMO-3")]


def test_propose_admin_is_denied(container: Container) -> None:
    """T-59 fase 2 (negativo): admin no tiene GENERATE_STORY → permiso denegado."""
    result = _call(container, ADMIN, "proponer_inicio", {"texto": "demo-3", "proyecto": "DEMO"})

    assert result.is_error is True
    assert _text(result) == PERMISSION_MESSAGE
    assert result.structured_content is None


def test_propose_permission_checked_before_length(container: Container) -> None:
    """T-59 fase 2 (negativo): sin permiso, un texto demasiado largo da «permiso denegado»."""
    text = "x" * (MAX_PROPOSE_CHARS + 1)

    result = _call(container, ADMIN, "proponer_inicio", {"texto": text, "proyecto": "DEMO"})

    assert _text(result) == PERMISSION_MESSAGE


@pytest.mark.parametrize("project", ["DEMO-1", "de mo", "", "1DEMO", 'DEMO" OR 1=1'])
def test_propose_invalid_project_returns_spanish_error(container: Container, project: str) -> None:
    """T-59 fase 2 (error): un proyecto inválido da `is_error` con mensaje en español."""
    result = _call(
        container, FUNCTIONAL, "proponer_inicio", {"texto": "renovar", "proyecto": project}
    )

    assert result.is_error is True
    assert "no es una clave de proyecto válida" in _text(result)
    assert "Traceback" not in _text(result)


# --- 7d. Fase 2: mis_conversaciones ----------------------------------------------------------


def test_my_conversations_returns_only_own_most_recent_first(tmp_path: Path) -> None:
    """T-59 fase 2: solo las conversaciones del usuario configurado, más recientes primero."""
    container = _container(tmp_path, conversations=_seeded_store(InMemoryConversationStore()))

    result = _call(container, FUNCTIONAL, "mis_conversaciones", {})

    assert not result.is_error, _text(result)
    data = result.structured_content
    assert data is not None
    assert "user" not in data  # ni el nombre del usuario configurado en la salida
    assert [c["origin_key"] for c in data["conversations"]] == ["DEMO-3", "DEMO-2", None]
    assert "DEMO-4" not in _text(result)  # la de otra persona
    first = data["conversations"][0]
    assert first == {
        "title": "Evolucionar DEMO-3",
        "project": "DEMO",
        "mode": "functional",
        "origin_kind": "story",
        "origin_key": "DEMO-3",
        "status": "in_review",
        "version": 2,
        "created_at": first["created_at"],
        "updated_at": first["updated_at"],
    }
    updated = [datetime.fromisoformat(c["updated_at"]) for c in data["conversations"]]
    assert updated == sorted(updated, reverse=True)


def test_my_conversations_hides_resume_identifiers(tmp_path: Path) -> None:
    """T-59 fase 2: ninguna fila lleva `thread_id`, `artifact_id` ni `username`."""
    container = _container(tmp_path, conversations=_seeded_store(InMemoryConversationStore()))

    result = _call(container, FUNCTIONAL, "mis_conversaciones", {"limite": 10})

    assert result.structured_content is not None
    rows = result.structured_content["conversations"]
    assert rows
    for row in rows:
        assert not {"thread_id", "artifact_id", "username"} & set(row)
    text = _text(result)
    assert "hilo-ficticio" not in text
    assert "artefacto-ficticio" not in text


def test_my_conversations_other_user_sees_only_theirs(tmp_path: Path) -> None:
    """T-59 fase 2 (negativo): la otra persona solo ve la suya."""
    container = _container(tmp_path, conversations=_seeded_store(InMemoryConversationStore()))
    other = User(username=OTHER_USER, role="qa")

    result = _call(container, other, "mis_conversaciones", {})

    assert result.structured_content is not None
    assert [c["origin_key"] for c in result.structured_content["conversations"]] == ["DEMO-4"]


def test_my_conversations_empty_when_none(container: Container) -> None:
    """T-59 fase 2 (límite): sin conversaciones, lista vacía y sin error."""
    result = _call(container, FUNCTIONAL, "mis_conversaciones", {})

    assert not result.is_error, _text(result)
    assert result.structured_content == {"conversations": []}


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(-3, 1), (0, 1), (1, 1), (20, 20), (MAX_CONVERSATIONS, MAX_CONVERSATIONS), (999, 100)],
)
def test_my_conversations_limit_is_clamped(tmp_path: Path, limit: int, expected: int) -> None:
    """T-59 fase 2 (límite): `limite` se acota a 1..100 antes de leer el índice."""
    store = SpyConversationStore()
    container = _container(tmp_path, conversations=store)

    result = _call(container, FUNCTIONAL, "mis_conversaciones", {"limite": limit})

    assert not result.is_error, _text(result)
    assert store.list_limits == [expected]


def test_my_conversations_default_limit_is_twenty(tmp_path: Path) -> None:
    """T-59 fase 2: sin `limite`, se piden 20."""
    store = SpyConversationStore()
    container = _container(tmp_path, conversations=store)

    _call(container, FUNCTIONAL, "mis_conversaciones", {})

    assert store.list_limits == [20]


def test_my_conversations_limit_one_returns_most_recent(tmp_path: Path) -> None:
    """T-59 fase 2 (límite): con `limite=0` (acotado a 1) llega solo la más reciente propia."""
    container = _container(tmp_path, conversations=_seeded_store(InMemoryConversationStore()))

    result = _call(container, FUNCTIONAL, "mis_conversaciones", {"limite": 0})

    assert result.structured_content is not None
    assert [c["origin_key"] for c in result.structured_content["conversations"]] == ["DEMO-3"]


def test_my_conversations_unexpected_error_returns_generic_message(tmp_path: Path) -> None:
    """T-59 fase 2 (error): un fallo del índice da UNEXPECTED, sin detalle ni traza."""
    container = _container(tmp_path, conversations=BrokenConversationStore())

    result = _call(container, FUNCTIONAL, "mis_conversaciones", {})

    assert result.is_error is True
    assert _text(result) == UNEXPECTED
    assert INTERNAL_DETAIL not in _text(result)
    assert "Traceback" not in _text(result)
    assert result.structured_content is None


# --- 7e. Fase 2: solo lectura y logs sin contenido -------------------------------------------


def test_phase_two_tools_call_no_write_methods(tmp_path: Path) -> None:
    """T-59 fase 2: las tres herramientas nuevas no escriben en Jira ni en el índice."""
    tracker = SpyIssueTracker()
    tests = SpyTestManagement()
    store = _seeded_store(SpyConversationStore())
    container = _container(
        tmp_path, issue_tracker=tracker, test_management=tests, conversations=store
    )
    calls: list[tuple[User, str, dict[str, Any]]] = [
        (FUNCTIONAL, "fuentes_de_contexto", {"clave": "DEMO-3"}),
        (FUNCTIONAL, "proponer_inicio", {"texto": "evolucionar demo-3", "proyecto": "DEMO"}),
        (FUNCTIONAL, "proponer_inicio", {"texto": "renovar", "proyecto": "DEMO"}),
        (QA, "proponer_inicio", {"texto": "pruebas de demo-2", "proyecto": "DEMO"}),
        (FUNCTIONAL, "mis_conversaciones", {"limite": 5}),
    ]

    for user, tool, args in calls:
        result = _call(container, user, tool, args)
        assert not result.is_error, (tool, _text(result))

    assert tracker.accessed, "el espía debe registrar las lecturas"
    assert not WRITE_METHODS & set(tracker.accessed)
    assert not WRITE_METHODS & set(tests.accessed)
    assert set(tracker.accessed) <= READ_METHODS
    assert tracker.writes == []
    assert tests.publish_calls == 0
    assert tests.executions == []
    assert store.write_calls == []  # proponer_inicio no crea ninguna conversación
    assert len(store.rows) == 4


@pytest.mark.parametrize(
    ("user", "tool", "args"),
    [
        (FUNCTIONAL, "fuentes_de_contexto", {"clave": "DEMO-3"}),
        (FUNCTIONAL, "proponer_inicio", {"texto": f"{PRIVATE_MARKER} demo-3", "proyecto": "DEMO"}),
        (QA, "proponer_inicio", {"texto": f"{PRIVATE_MARKER} renovar", "proyecto": "DEMO"}),
        (FUNCTIONAL, "mis_conversaciones", {}),
    ],
)
def test_phase_two_logs_carry_no_content(
    tmp_path: Path, user: User, tool: str, args: dict[str, Any]
) -> None:
    """T-59 fase 2: el log lleva usuario, acción y duración, nunca el texto ni los datos."""
    container = _container(tmp_path, conversations=_seeded_store(InMemoryConversationStore()))

    with capture_logs() as events:
        result = _call(container, user, tool, args)

    assert not result.is_error, _text(result)
    mine = [e for e in events if e.get("action") == tool]
    assert len(mine) == 1
    assert mine[0]["event"] == "herramienta mcp"
    assert mine[0]["user"] == user.username
    assert isinstance(mine[0]["duration_ms"], int)
    logged = _logged(events)
    assert PRIVATE_MARKER not in logged
    assert "renovar" not in logged
    for story in dataset.STORIES.values():
        assert story.summary not in logged
    assert "hilo-ficticio" not in logged
    assert "Evolucionar DEMO" not in logged


@pytest.mark.parametrize(
    ("user", "tool", "args"),
    [
        (FUNCTIONAL, "proponer_inicio", {"texto": PRIVATE_MARKER * 200, "proyecto": "DEMO"}),
        (FUNCTIONAL, "proponer_inicio", {"texto": PRIVATE_MARKER, "proyecto": "no valido"}),
        (ADMIN, "proponer_inicio", {"texto": PRIVATE_MARKER, "proyecto": "DEMO"}),
        (FUNCTIONAL, "fuentes_de_contexto", {"clave": PRIVATE_MARKER}),
    ],
)
def test_phase_two_error_logs_carry_no_content(
    container: Container, user: User, tool: str, args: dict[str, Any]
) -> None:
    """T-59 fase 2: el log de un fallo lleva código y tipo de error, nunca el texto enviado."""
    with capture_logs() as events:
        result = _call(container, user, tool, args)

    assert result.is_error is True
    mine = [e for e in events if e.get("action") == tool]
    assert len(mine) == 1
    assert mine[0]["event"] == "herramienta mcp fallida"
    assert mine[0]["code"]
    assert mine[0]["error_type"]
    assert PRIVATE_MARKER not in _logged(events)


def test_unexpected_error_log_has_no_internal_detail(tmp_path: Path) -> None:
    """T-59 fase 2: un fallo inesperado registra `unexpected` y el tipo, nunca su detalle."""
    container = _container(tmp_path, conversations=BrokenConversationStore())

    with capture_logs() as events:
        _call(container, FUNCTIONAL, "mis_conversaciones", {})

    mine = [e for e in events if e.get("action") == "mis_conversaciones"]
    assert len(mine) == 1
    assert mine[0]["code"] == "unexpected"
    assert mine[0]["error_type"] == "RuntimeError"
    assert INTERNAL_DETAIL not in _logged(events)


# --- 8. stdout solo lleva el protocolo ------------------------------------------------------

STDIO_SCRIPT = """
import sys
from pathlib import Path

from adapters.base import User
from core.logging import configure_logging
from mcp_server.server import build_server
from tests.fakes.container import fake_container

configure_logging(stream=sys.stderr)
container = fake_container(Path(sys.argv[1]), publish_mode="simulation")
build_server(container, User(username="af-ficticio", role="functional")).run("stdio")
"""


# Entorno mínimo para los subprocesos: no se hereda `os.environ` (podría llevar credenciales).
_INHERITED = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
)


def _subprocess_env(**extra: str) -> dict[str, str]:
    env = {name: os.environ[name] for name in _INHERITED if name in os.environ}
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _pump(stream: Any, sink: list[str], lines: "queue.Queue[str] | None") -> None:
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", errors="replace")
        sink.append(line)
        if lines is not None:
            lines.put(line)


def _wait_for_id(lines: "queue.Queue[str]", request_id: int) -> dict[str, Any]:
    while True:
        line = lines.get(timeout=PROCESS_TIMEOUT).strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("id") == request_id:
            return message


def _send(process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
    process.stdin.flush()


def _protocol_version() -> str:
    from mcp import types

    version = getattr(types, "LATEST_PROTOCOL_VERSION", None)
    assert isinstance(version, str)
    return version


@pytest.fixture
def stdio_process(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[bytes], list[str], list[str]]]:
    """Servidor MCP real por stdio en un subproceso propio; se cierra siempre al terminar."""
    process = subprocess.Popen(  # noqa: S603 - script fijo de la propia prueba
        [sys.executable, "-c", STDIO_SCRIPT, str(tmp_path / "memoria")],
        cwd=ROOT,
        env=_subprocess_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    try:
        yield process, stdout_lines, stderr_lines
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=PROCESS_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()  # solo el proceso que lanza esta prueba
            process.wait(timeout=PROCESS_TIMEOUT)


def test_stdio_stdout_carries_only_protocol(
    stdio_process: tuple[subprocess.Popen[bytes], list[str], list[str]],
) -> None:
    """T-59 caso 8: por stdio, stdout solo lleva JSON-RPC y los logs van a stderr."""
    process, stdout_lines, stderr_lines = stdio_process
    incoming: queue.Queue[str] = queue.Queue()
    readers = [
        threading.Thread(target=_pump, args=(process.stdout, stdout_lines, incoming), daemon=True),
        threading.Thread(target=_pump, args=(process.stderr, stderr_lines, None), daemon=True),
    ]
    for reader in readers:
        reader.start()

    _send(
        process,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _protocol_version(),
                "capabilities": {},
                "clientInfo": {"name": "cliente-ficticio", "version": "0.0.1"},
            },
        },
    )
    initialized = _wait_for_id(incoming, 1)
    assert "result" in initialized, initialized
    _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    _send(
        process,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "buscar_historias", "arguments": {"proyecto": "DEMO"}},
        },
    )
    response = _wait_for_id(incoming, 2)

    assert process.stdin is not None
    process.stdin.close()
    process.wait(timeout=PROCESS_TIMEOUT)
    for reader in readers:
        reader.join(timeout=PROCESS_TIMEOUT)

    result = response["result"]
    assert result.get("isError") in (None, False)
    keys = [item["key"] for item in result["structuredContent"]["results"]]
    assert set(dataset.STORY_KEYS) <= set(keys)
    non_empty = [line for line in stdout_lines if line.strip()]
    assert len(non_empty) >= 2
    for line in non_empty:
        assert json.loads(line)["jsonrpc"] == "2.0", line
    stdout_text = "".join(stdout_lines)
    stderr_text = "".join(stderr_lines)
    assert "herramienta mcp" in stderr_text
    assert "herramienta mcp" not in stdout_text
    # Logs sin contenido: ni los resúmenes de Jira devueltos aparecen en stderr.
    summaries = [item["summary"] for item in result["structuredContent"]["results"]]
    assert summaries
    for summary in summaries:
        assert summary not in stderr_text


# --- 9. main() sin MCP_USER -----------------------------------------------------------------


def test_main_without_user_exits_with_code_two(tmp_path: Path) -> None:
    """T-59 caso 9: sin `MCP_USER`, `python -m mcp_server` sale con 2, stdout vacío y aviso."""
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_server"],
        # `Settings` lee el `.env` del repositorio por ruta absoluta; las variables MCP_* del
        # entorno tienen prioridad, así que el resultado no depende de ese archivo.
        cwd=tmp_path,
        env=_subprocess_env(MCP_USER=""),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=PROCESS_TIMEOUT,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert NO_USER in completed.stderr.decode("utf-8")


def test_main_with_invalid_role_exits_without_trace_or_values(tmp_path: Path) -> None:
    """T-59: un `MCP_ROLE` no válido da un aviso en español con el nombre, sin traza ni valor."""
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_server"],
        # `Settings` lee el `.env` del repositorio por ruta absoluta; las variables MCP_* del
        # entorno tienen prioridad, así que el resultado no depende de ese archivo.
        cwd=tmp_path,
        env=_subprocess_env(MCP_USER="af-ficticio", MCP_ROLE="admin"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=PROCESS_TIMEOUT,
        check=False,
    )

    stderr = completed.stderr.decode("utf-8")
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert "MCP_ROLE" in stderr
    assert "Traceback" not in stderr
    assert "input_value" not in stderr
    assert "admin" not in stderr


# --- 10. Settings: MCP_ROLE ----------------------------------------------------------------


@pytest.fixture
def mcp_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    clean_env.delenv("MCP_USER", raising=False)
    clean_env.delenv("MCP_ROLE", raising=False)
    return clean_env


@pytest.mark.usefixtures("mcp_env")
def test_settings_mcp_defaults() -> None:
    """T-59 caso 10: sin configurar, no hay usuario y el rol es functional."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.mcp_user is None
    assert settings.mcp_role == "functional"


@pytest.mark.usefixtures("mcp_env")
@pytest.mark.parametrize("role", ["functional", "qa"])
def test_settings_accepts_working_roles(role: str) -> None:
    """T-59 caso 10: `mcp_role` acepta functional y qa."""
    settings = Settings(_env_file=None, mcp_user="af-ficticio", mcp_role=role)  # type: ignore[call-arg]

    assert settings.mcp_role == role
    assert settings.mcp_user == "af-ficticio"


@pytest.mark.usefixtures("mcp_env")
@pytest.mark.parametrize("role", ["admin", "invitado", ""])
def test_settings_rejects_other_roles(role: str) -> None:
    """T-59 caso 10 (negativo): `mcp_role` rechaza admin y cualquier otro rol."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, mcp_role=role)  # type: ignore[call-arg]


@pytest.mark.usefixtures("mcp_env")
def test_settings_reads_role_from_environment(mcp_env: pytest.MonkeyPatch) -> None:
    """T-59 caso 10: `MCP_USER` y `MCP_ROLE` se leen del entorno."""
    mcp_env.setenv("MCP_USER", "qa-ficticio")
    mcp_env.setenv("MCP_ROLE", "qa")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.mcp_user == "qa-ficticio"
    assert settings.mcp_role == "qa"
