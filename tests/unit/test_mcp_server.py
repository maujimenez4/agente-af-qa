"""Pruebas del servidor MCP de solo lectura (T-59, fase 1; principio 1 de CLAUDE.md).

Cubren las tres herramientas (`buscar_historias`, `ver_incidencia`, `revisar_calidad`) con el
cliente en memoria del SDK, los permisos por rol, los errores en español sin trazas, que nada
escribe en Jira (espías y `ReadOnlyProxy`), que stdout solo lleva el protocolo en un subproceso
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
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.types import CallToolResult, ListToolsResult
from pydantic import ValidationError

from adapters.base import IssueDetail, IssueSummary, User
from adapters.errors import PublishError
from api.errors import UNEXPECTED
from core.config import Settings
from core.container import Container
from mcp_server.__main__ import NO_USER
from mcp_server.server import (
    MAX_RESULTS,
    READ_METHODS,
    READ_ONLY_MESSAGE,
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
TOOL_NAMES = {"buscar_historias", "ver_incidencia", "revisar_calidad"}
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


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return _container(tmp_path)


@pytest.fixture
def subtask_container(tmp_path: Path) -> Container:
    tracker = FakeIssueTracker()
    tracker.issues[SUBTASK_KEY] = _subtask()
    return _container(tmp_path, issue_tracker=tracker)


# --- 1. Lista de herramientas --------------------------------------------------------------


def test_list_tools_returns_exactly_three_read_only_tools(container: Container) -> None:
    """T-59 caso 1: exactamente las tres herramientas, todas con `read_only_hint=True`."""
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
    assert data == {
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
    """T-59 caso 5: el rol qa no puede revisar la calidad (permiso de generar HU)."""
    result = _call(container, QA, "revisar_calidad", {"clave": "DEMO-3"})

    assert result.is_error is True
    assert _text(result) == PERMISSION_MESSAGE


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
    """T-59 caso 5: admin no tiene GENERATE_STORY, así que no puede revisar la calidad."""
    result = _call(container, ADMIN, "revisar_calidad", {"clave": "DEMO-3"})

    assert result.is_error is True
    assert _text(result) == PERMISSION_MESSAGE


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("buscar_historias", {"proyecto": "DEMO"}),
        ("ver_incidencia", {"clave": "DEMO-2"}),
        ("revisar_calidad", {"clave": "DEMO-3"}),
    ],
)
def test_unknown_role_is_denied_every_tool(
    container: Container, tool: str, args: dict[str, Any]
) -> None:
    """T-59 caso 5 (negativo): un rol sin permisos no puede usar ninguna herramienta."""
    result = _call(container, NO_ROLE, tool, args)

    assert result.is_error is True
    assert _text(result) == PERMISSION_MESSAGE
    assert result.structured_content is None


def test_permission_checked_before_reading_jira(tmp_path: Path) -> None:
    """T-59 caso 5: sin permiso no se llega a consultar Jira."""
    tracker = SpyIssueTracker()
    container = _container(tmp_path, issue_tracker=tracker)

    _call(container, NO_ROLE, "buscar_historias", {"proyecto": "DEMO"})
    _call(container, NO_ROLE, "ver_incidencia", {"clave": "DEMO-2"})
    _call(container, QA, "revisar_calidad", {"clave": "DEMO-3"})

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
