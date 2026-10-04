"""T-33 (RF-36/RF-38): `GET /api/v1/memories` y `GET /api/v1/memories/{key}` (`api/memories.py`).

Sobre `fake_runtime`: el `memory_dir` del contenedor está en `tmp_path`. Solo fakes de
`tests/fakes/`, sin red, sin `.env`, sin Jira ni LLM reales; datos 100 % ficticios.
"""

import os
from pathlib import Path
from typing import Any

import pytest

from adapters.base import Chunk, ProjectSummary
from api.memories import NOT_FOUND_MESSAGE
from api.runtime import Runtime
from core.container import Container
from schemas.common import ArtifactType
from schemas.memory import Memory
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore
from tests.unit.test_api_app import ADMIN, AF, QA, Api

BASE_TIME = 1_790_000_000
NOT_FOUND = {"error": {"code": "not_found", "message": NOT_FOUND_MESSAGE, "retry_after": None}}


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


def index(container: Container, key: str) -> None:
    store = container.vector_store
    assert isinstance(store, FakeVectorStore)
    store.upsert(
        [
            Chunk(
                id=f"memoria-{key}-0",
                document_id=f"memoria-{key}",
                ordinal=0,
                content="Fragmento ficticio de memoria.",
                embedding=[1.0, 0.0],
                metadata={"category": "memoria"},
            )
        ]
    )


@pytest.fixture
def llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def tracker() -> FakeIssueTracker:
    return FakeIssueTracker()


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    return tmp_path / "memoria"


@pytest.fixture
def rt(memory_dir: Path, llm: FakeLLMProvider, tracker: FakeIssueTracker) -> Runtime:
    return fake_runtime(memory_dir, llm=llm, issue_tracker=tracker)


@pytest.fixture
def api(rt: Runtime) -> Api:
    a = Api(rt)
    assert a.login().status_code == 200
    return a


def _container(rt: Runtime) -> Container:
    return rt.workspace_factory().container


def _memory_dir(rt: Runtime) -> Path:
    return _container(rt).memory_dir


def _assert_read_only(rt: Runtime, llm: FakeLLMProvider) -> None:
    container = _container(rt)
    tracker, testmgmt = container.issue_tracker, container.test_management
    assert isinstance(tracker, FakeIssueTracker) and isinstance(testmgmt, FakeTestManagement)
    assert tracker.writes == []
    assert testmgmt.publish_calls == 0
    assert llm.calls == []


def _two_projects(monkeypatch: pytest.MonkeyPatch, tracker: FakeIssueTracker) -> None:
    projects = [*tracker.list_projects(), ProjectSummary(key="OTRO", name="Proyecto ficticio")]
    monkeypatch.setattr(tracker, "list_projects", lambda: projects)


# --- Composición ----------


def test_fake_runtime_memory_dir_is_in_tmp_path(rt: Runtime, memory_dir: Path) -> None:
    """T-33: el contenedor de la API lee las memorias de `tmp_path`, no de `data/memory/`."""
    assert _memory_dir(rt) == memory_dir


# --- Lista ----------


def test_list_memories_returns_summaries(rt: Runtime, api: Api, llm: FakeLLMProvider) -> None:
    """T-33 · lista: `MemorySummary` con clave, proyecto, título, versión, fecha e indexada."""
    write(_memory_dir(rt), make_memory("DEMO-9001", version=2))
    response = api.get("/memories")
    assert response.status_code == 200
    (row,) = response.json()
    assert set(row) == {"key", "project", "title", "version", "updated_at", "indexed"}
    assert row["key"] == "DEMO-9001"
    assert row["project"] == "DEMO"
    assert row["title"] == "Objetivo ficticio de DEMO-9001."
    assert row["version"] == 2
    assert row["indexed"] is False
    assert row["updated_at"].startswith("2026-")
    _assert_read_only(rt, llm)


def test_list_memories_empty_directory_returns_empty_list(
    rt: Runtime, api: Api, llm: FakeLLMProvider
) -> None:
    """T-33 · lista vacía: carpeta sin memorias → `[]`."""
    _memory_dir(rt).mkdir(parents=True, exist_ok=True)
    response = api.get("/memories")
    assert response.status_code == 200 and response.json() == []
    _assert_read_only(rt, llm)


def test_list_memories_missing_directory_returns_empty_list(rt: Runtime, api: Api) -> None:
    """T-33 · lista vacía: la carpeta de memorias no existe → `[]` (no 500)."""
    missing = _memory_dir(rt)
    if missing.exists():
        for child in missing.iterdir():
            assert child.suffix != ".md"
    response = api.get("/memories")
    assert response.status_code == 200 and response.json() == []


def test_list_memories_indexed_flag_follows_vector_store(rt: Runtime, api: Api) -> None:
    """T-33 · indexada: true con un Chunk `memoria-DEMO-9001` en el vector store; si no, false."""
    write(_memory_dir(rt), make_memory("DEMO-9001"), BASE_TIME + 1)
    write(_memory_dir(rt), make_memory("DEMO-9002"), BASE_TIME)
    index(_container(rt), "DEMO-9001")
    rows = api.get("/memories").json()
    assert {row["key"]: row["indexed"] for row in rows} == {
        "DEMO-9001": True,
        "DEMO-9002": False,
    }
    detail = api.get("/memories/DEMO-9001").json()
    assert detail["indexed"] is True
    assert api.get("/memories/DEMO-9002").json()["indexed"] is False


def test_list_memories_most_recent_first(rt: Runtime, api: Api) -> None:
    """T-33 · orden: más recientes primero (mtime fijado con `os.utime`)."""
    write(_memory_dir(rt), make_memory("DEMO-1"), BASE_TIME + 10)
    write(_memory_dir(rt), make_memory("DEMO-2"), BASE_TIME + 30)
    write(_memory_dir(rt), make_memory("DEMO-3"), BASE_TIME + 20)
    assert [row["key"] for row in api.get("/memories").json()] == ["DEMO-2", "DEMO-3", "DEMO-1"]


def test_list_memories_limit(rt: Runtime, api: Api) -> None:
    """T-33 · `limit`: las N más recientes."""
    for number in range(1, 5):
        write(_memory_dir(rt), make_memory(f"DEMO-{number}"), BASE_TIME + number)
    rows = api.get("/memories", params={"limit": 2}).json()
    assert [row["key"] for row in rows] == ["DEMO-4", "DEMO-3"]


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"limit": "muchas"}, {"q": "x" * 101}, {"project": "1ABC"}],
)
def test_list_memories_rejects_invalid_query_params(
    rt: Runtime, api: Api, params: dict[str, Any]
) -> None:
    """T-33 · negativa / límite: `limit` fuera de 1..200, `q` > 100 o `project` no válido."""
    response = api.get("/memories", params=params)
    assert response.status_code in (400, 422), response.text
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("params", [{"limit": 1}, {"limit": 200}, {"q": "x" * 100}])
def test_list_memories_accepts_boundary_query_params(
    rt: Runtime, api: Api, params: dict[str, Any]
) -> None:
    """T-33 · límite: `limit` 1 y 200 y `q` de 100 caracteres son válidos."""
    assert api.get("/memories", params=params).status_code == 200


def test_list_memories_query_case_insensitive_in_key_and_text(rt: Runtime, api: Api) -> None:
    """T-33 · búsqueda `q`: sin distinguir mayúsculas, en la clave y en el texto."""
    write(_memory_dir(rt), make_memory("DEMO-9001"))
    write(_memory_dir(rt), make_memory("DEMO-9002", scope="Cola de RESERVAS ficticias."))
    by_key = api.get("/memories", params={"q": "demo-9001"}).json()
    assert [row["key"] for row in by_key] == ["DEMO-9001"]
    by_text = api.get("/memories", params={"q": "reservas"}).json()
    assert [row["key"] for row in by_text] == ["DEMO-9002"]
    assert api.get("/memories", params={"q": "inexistente-xyzzy"}).json() == []


def test_list_memories_hides_projects_not_visible(rt: Runtime, api: Api) -> None:
    """T-33 · proyecto no visible: sus memorias no aparecen, ni filtrando por él."""
    write(_memory_dir(rt), make_memory("DEMO-1"))
    write(_memory_dir(rt), make_memory("OTRO-1"))
    assert [row["key"] for row in api.get("/memories").json()] == ["DEMO-1"]
    assert api.get("/memories", params={"project": "OTRO"}).json() == []
    assert api.get("/memories", params={"q": "otro-1"}).json() == []


def test_list_memories_filters_by_project(
    monkeypatch: pytest.MonkeyPatch, rt: Runtime, api: Api, tracker: FakeIssueTracker
) -> None:
    """T-33 · filtro `project` (también en minúsculas) con dos proyectos visibles."""
    _two_projects(monkeypatch, tracker)
    write(_memory_dir(rt), make_memory("DEMO-1"), BASE_TIME + 1)
    write(_memory_dir(rt), make_memory("OTRO-1"), BASE_TIME)
    assert [row["key"] for row in api.get("/memories").json()] == ["DEMO-1", "OTRO-1"]
    assert [r["key"] for r in api.get("/memories", params={"project": "OTRO"}).json()] == ["OTRO-1"]
    assert [r["key"] for r in api.get("/memories", params={"project": "demo"}).json()] == ["DEMO-1"]


# --- Detalle ----------


def test_get_memory_returns_summary_memory_and_markdown(
    rt: Runtime, api: Api, llm: FakeLLMProvider
) -> None:
    """T-33 · detalle: `MemoryOut` = resumen + `memory` estructurada + `markdown` del archivo."""
    memory = make_memory("DEMO-9001", version=3, decisions=["Decisión\ncon salto ficticio."])
    path = write(_memory_dir(rt), memory)
    response = api.get("/memories/DEMO-9001")
    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "DEMO-9001" and body["project"] == "DEMO" and body["version"] == 3
    assert body["title"] == "Objetivo ficticio de DEMO-9001."
    assert Memory.model_validate(body["memory"]) == memory
    assert body["markdown"] == path.read_text(encoding="utf-8")
    _assert_read_only(rt, llm)


def test_get_memory_accepts_lowercase_key(rt: Runtime, api: Api) -> None:
    """T-33: la clave en minúsculas encuentra la memoria."""
    write(_memory_dir(rt), make_memory("DEMO-9001"))
    response = api.get("/memories/demo-9001")
    assert response.status_code == 200 and response.json()["key"] == "DEMO-9001"


@pytest.mark.parametrize(
    "path",
    [
        "/memories/DEMO-404",  # inexistente
        "/memories/OTRO-1",  # existe, proyecto no visible
        "/memories/no-valida",  # clave no válida
        "/memories/DEMO-1.md",
        "/memories/..%2FDEMO-5",  # existe fuera de memory_dir
        "/memories/..%2F..%2Ffuera%2FDEMO-5",
        "/memories/DEMO-1%2F..%2F..%2FDEMO-5",
        "/memories/..%5CDEMO-5",
        "/memories/DEMO-1/../DEMO-5",
        "/memories/%2E%2E%2FDEMO-5",
        "/memories/DEMO-1%00",
        "/memories/DEMO-2",  # cabecera con otra clave
    ],
)
def test_get_memory_same_404_for_missing_hidden_invalid_or_traversal(
    rt: Runtime, api: Api, llm: FakeLLMProvider, path: str
) -> None:
    """T-33 · 404 idéntico (mismo código y mismo cuerpo) para inexistente, proyecto no visible,
    clave no válida y `../`, aunque el archivo exista en otro sitio."""
    memory_dir = _memory_dir(rt)
    write(memory_dir, make_memory("DEMO-1"))
    write(memory_dir, make_memory("OTRO-1"))
    (memory_dir / "DEMO-2.md").write_text(make_memory("DEMO-1").to_markdown(), encoding="utf-8")
    write(memory_dir.parent, make_memory("DEMO-5"))  # fuera de memory_dir
    write(memory_dir.parent / "fuera", make_memory("DEMO-5"))
    response = api.get(path)
    assert response.status_code == 404, response.text
    assert response.json() == NOT_FOUND
    _assert_read_only(rt, llm)


def test_get_memory_404_bodies_are_identical(rt: Runtime, api: Api) -> None:
    """T-33 · 404 idéntico: inexistente y proyecto no visible no se distinguen por el cuerpo."""
    write(_memory_dir(rt), make_memory("OTRO-1"))
    missing = api.get("/memories/DEMO-404")
    hidden = api.get("/memories/OTRO-1")
    invalid = api.get("/memories/..%2F..%2Fx")
    assert missing.status_code == hidden.status_code == invalid.status_code == 404
    assert missing.content == hidden.content == invalid.content


def test_get_memory_of_other_project_visible_when_connection_sees_it(
    monkeypatch: pytest.MonkeyPatch, rt: Runtime, api: Api, tracker: FakeIssueTracker
) -> None:
    """T-33: la misma memoria `OTRO-1` es visible si la conexión de Jira ve el proyecto."""
    write(_memory_dir(rt), make_memory("OTRO-1"))
    assert api.get("/memories/OTRO-1").status_code == 404
    _two_projects(monkeypatch, tracker)
    assert api.get("/memories/OTRO-1").status_code == 200


# --- Roles y sesión ----------


@pytest.mark.parametrize("who", [AF, QA, ADMIN], ids=["functional", "qa", "admin"])
def test_all_roles_can_read_memories(
    rt: Runtime, llm: FakeLLMProvider, who: tuple[str, str]
) -> None:
    """T-33 · los tres roles tienen `VIEW_MEMORY`: lista y detalle con 200."""
    write(_memory_dir(rt), make_memory("DEMO-9001"))
    client = Api(rt)
    login = client.login(who)
    assert login.status_code == 200
    assert "view_memory" in login.json()["user"]["permissions"]
    listed = client.get("/memories")
    assert listed.status_code == 200 and [r["key"] for r in listed.json()] == ["DEMO-9001"]
    assert client.get("/memories/DEMO-9001").status_code == 200
    _assert_read_only(rt, llm)


def test_memories_require_session(rt: Runtime) -> None:
    """T-33 · negativa: sin sesión, 401 en lista y detalle."""
    write(_memory_dir(rt), make_memory("DEMO-9001"))
    anonymous = Api(rt)
    assert anonymous.get("/memories").status_code == 401
    assert anonymous.get("/memories/DEMO-9001").status_code == 401


def test_memories_forbidden_without_view_memory_permission(
    monkeypatch: pytest.MonkeyPatch, rt: Runtime
) -> None:
    """T-33 · negativa: un rol sin `VIEW_MEMORY` recibe 403 (no ve ni si existe)."""
    from core import permissions

    write(_memory_dir(rt), make_memory("DEMO-9001"))
    stripped = {
        role: frozenset(p for p in perms if p is not permissions.Permission.VIEW_MEMORY)
        for role, perms in permissions.ROLE_PERMISSIONS.items()
    }
    client = Api(rt)
    assert client.login(AF).status_code == 200
    monkeypatch.setattr(permissions, "ROLE_PERMISSIONS", stripped)
    assert client.get("/memories").status_code == 403
    assert client.get("/memories/DEMO-9001").status_code == 403


def test_demo_users_are_fictitious() -> None:
    """Higiene: los usuarios que inician sesión son los ficticios del dataset."""
    assert {AF[0], QA[0], ADMIN[0]} <= set(dataset.DEMO_USERS)
