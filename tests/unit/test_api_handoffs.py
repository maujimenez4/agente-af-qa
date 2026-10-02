"""QA encadenada por la API (T-54 · PA-105, PA-268 · RF-14, RF-22, D-01).

Rutas `POST /conversations/{id}/handoff`, `GET /qa/handoffs` y `POST /qa/handoffs/{id}/take`
sobre `fake_runtime` (entregas en `InMemoryHandoffStore`). Solo fakes de `tests/fakes/`, sin red,
sin `.env`, sin Jira ni LLM reales; datos 100 % ficticios. Las operaciones largas se ejecutan en
el mismo hilo (`run_inline`): la respuesta ya trae el estado final.
"""

import secrets
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from adapters.base import User
from api.app import API_PREFIX, create_app
from api.runtime import Runtime
from api.security import COOKIE
from api.sessions import ApiSession
from core.graph.nodes import UNPUBLISHED_STORY
from core.handoff import InMemoryHandoffStore
from core.qa.writer import UNPUBLISHED_STORY_KEY
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.test_management import FakeTestManagement

AF = ("af-demo", dataset.DEMO_USERS["af-demo"][0])
QA = ("qa-demo", dataset.DEMO_USERS["qa-demo"][0])
OTHER_QA = User(username="qa-ficticio-dos", role="qa")
EVOLVE = {"flow": "evolve", "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}}
HEX32 = "0123456789abcdef" * 2  # bien formado, inexistente


class Api:
    def __init__(self, rt: Runtime, who: tuple[str, str] | None = None) -> None:
        self.rt = rt
        self.client = TestClient(create_app(runtime_instance=rt), base_url="https://testserver")
        self.csrf = ""
        if who is not None:
            response = self.login(who)
            assert response.status_code == 200, response.text

    def login(self, who: tuple[str, str]) -> Any:
        response = self.client.post(
            f"{API_PREFIX}/auth/login", json={"username": who[0], "password": who[1]}
        )
        if response.status_code == 200:
            self.csrf = response.json()["csrf_token"]
        return response

    def get(self, path: str) -> Any:
        return self.client.get(f"{API_PREFIX}{path}")

    def post(self, path: str, json: Any = None, csrf: bool = True) -> Any:
        headers = {"X-CSRF-Token": self.csrf} if csrf else {}
        return self.client.post(f"{API_PREFIX}{path}", json=json, headers=headers)

    @property
    def session(self) -> ApiSession[Any]:
        cookie = self.client.cookies.get(COOKIE)
        assert cookie
        session = self.rt.sessions.get(cookie, touch=False)
        assert session is not None
        return session


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def _fakes(rt: Runtime) -> tuple[FakeIssueTracker, FakeTestManagement]:
    container = rt.workspace_factory().container
    tracker, testmgmt = container.issue_tracker, container.test_management
    assert isinstance(tracker, FakeIssueTracker) and isinstance(testmgmt, FakeTestManagement)
    return tracker, testmgmt


def _store(rt: Runtime) -> InMemoryHandoffStore:
    assert isinstance(rt.handoffs, InMemoryHandoffStore)
    return rt.handoffs


def _approved_story(af: Api) -> str:
    """af-demo crea la evolución de DEMO-3 y la aprueba; devuelve la conversación."""
    conv = af.post("/conversations", EVOLVE).json()
    assert conv["state"] == "in_review", conv
    approved = af.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert approved.status_code == 202, approved.text
    assert approved.json()["state"] in ("simulated", "published"), approved.json()
    return str(conv["id"])


def _handed_off(rt: Runtime) -> tuple[Api, str, dict[str, Any]]:
    af = Api(rt, AF)
    cid = _approved_story(af)
    response = af.post(f"/conversations/{cid}/handoff")
    assert response.status_code == 200, response.text
    return af, cid, response.json()


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path)


@pytest.fixture
def live_rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path, publish_mode="live")


# --- Flujo completo ----------------------------------------------------------------------------


def test_full_chained_flow_in_simulation_never_writes_to_jira(rt: Runtime) -> None:
    """T-54 req. 10 (PA-105): AF aprueba en simulación y pasa a QA; QA lista, recoge (202, suite
    en revisión) y, al aprobar la suite sin clave, se queda en revisión con error y sin escribir.
    """
    _af, _cid, handoff = _handed_off(rt)
    assert handoff["story_key"] is None  # aprobada en simulación: sin clave
    assert handoff["project"] == "DEMO" and handoff["from_user"] == "af-demo"
    assert handoff["version"] >= 1 and len(handoff["id"]) == 32

    qa = Api(rt, QA)
    listed = qa.get("/qa/handoffs")
    assert listed.status_code == 200
    assert [h["id"] for h in listed.json()] == [handoff["id"]]

    taken = qa.post(f"/qa/handoffs/{handoff['id']}/take")
    assert taken.status_code == 202, taken.text
    conv = taken.json()
    assert conv["mode"] == "qa" and conv["flow"] == "tests" and conv["project"] == "DEMO"
    assert conv["state"] == "in_review", conv
    artifact = conv["review"]["artifact"]
    assert artifact["type"] == "test_suite" and artifact["content"]["cases"]
    assert artifact["content"]["story_jira_key"] == UNPUBLISHED_STORY_KEY

    assert qa.get("/qa/handoffs").json() == []  # ya recogida: sale de la lista

    approved = qa.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert approved.status_code == 202, approved.text
    body = approved.json()
    assert body["state"] == "in_review", body
    assert body["review"]["error"]
    tracker, testmgmt = _fakes(rt)
    assert tracker.writes == [] and testmgmt.publish_calls == 0


def test_unpublished_suite_approval_error_explains_the_missing_key(rt: Runtime) -> None:
    """T-54: el error de revisión al aprobar sin clave es el mensaje en español de la HU sin
    publicar."""
    _af, _cid, handoff = _handed_off(rt)
    qa = Api(rt, QA)
    conv = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()
    body = qa.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    ).json()
    error = body["review"]["error"]
    text = error if isinstance(error, str) else str(error)
    assert "no está publicada en Jira" in text or UNPUBLISHED_STORY in text, error


def test_live_published_story_handoff_has_key_and_qa_can_publish(live_rt: Runtime) -> None:
    """T-54 (live): con la HU publicada la entrega lleva `story_key` y QA publica la suite en el
    fake (una sola llamada a `publish`)."""
    _af, _cid, handoff = _handed_off(live_rt)
    assert handoff["story_key"] == "DEMO-3"

    qa = Api(live_rt, QA)
    conv = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()
    assert conv["state"] == "in_review", conv
    assert conv["review"]["artifact"]["content"]["story_jira_key"] == "DEMO-3"
    approved = qa.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert approved.status_code == 202, approved.text
    assert approved.json()["state"] == "published", approved.json()
    _tracker, testmgmt = _fakes(live_rt)
    assert testmgmt.publish_calls == 1


def test_qa_conversation_is_listed_only_for_qa_person(rt: Runtime) -> None:
    """T-54 / T-52: la conversación de QA aparece en `GET /conversations` de qa-demo y no en la
    de af-demo."""
    af, cid, handoff = _handed_off(rt)
    qa = Api(rt, QA)
    qa_cid = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()["id"]

    qa_ids = [c["thread_id"] for c in qa.get("/conversations").json()]
    af_ids = [c["thread_id"] for c in af.get("/conversations").json()]
    assert qa_cid in qa_ids and cid not in qa_ids
    assert qa_cid not in af_ids and cid in af_ids
    assert af.get(f"/conversations/{qa_cid}").status_code == 404


# --- Pasar a QA ----------------------------------------------------------------------------------


def test_handoff_before_approval_is_409_handoff_unavailable(rt: Runtime) -> None:
    """T-54 req. 10: solo se pasa a QA una HU aprobada o publicada (en revisión -> 409)."""
    af = Api(rt, AF)
    cid = af.post("/conversations", EVOLVE).json()["id"]
    response = af.post(f"/conversations/{cid}/handoff")
    assert response.status_code == 409
    assert _code(response) == "handoff_unavailable"
    assert _store(rt).rows == {}


def test_handoff_after_discard_is_409_handoff_unavailable(rt: Runtime) -> None:
    """T-54 req. 10 (negativa): una HU descartada no se pasa a QA."""
    af = Api(rt, AF)
    cid = af.post("/conversations", EVOLVE).json()["id"]
    af.post(f"/conversations/{cid}/discard")
    response = af.post(f"/conversations/{cid}/handoff")
    assert response.status_code == 409
    assert _code(response) == "handoff_unavailable"


def test_handoff_while_running_is_409_not_in_review(rt: Runtime) -> None:
    """PA-105: con una operación en curso sobre la conversación -> 409 `not_in_review`."""
    af = Api(rt, AF)
    cid = _approved_story(af)
    run = rt.runs.get(cid)
    assert run is not None
    run.running = True
    response = af.post(f"/conversations/{cid}/handoff")
    assert response.status_code == 409
    assert _code(response) == "not_in_review"
    assert _store(rt).rows == {}


def test_handoff_of_foreign_conversation_is_404(rt: Runtime) -> None:
    """Req. 3: pasar a QA la conversación de otra persona -> 404 igual que una inexistente."""
    af = Api(rt, AF)
    cid = _approved_story(af)
    intruder = Api(rt, AF)
    intruder.session.user = User(username="af-ficticio-ajeno", role="functional")
    foreign = intruder.post(f"/conversations/{cid}/handoff")
    missing = intruder.post(f"/conversations/{uuid4()}/handoff")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert _store(rt).rows == {}


def test_handoff_with_malformed_conversation_id_is_422(rt: Runtime) -> None:
    """Contrato: el id de conversación sigue su patrón (UUID)."""
    af = Api(rt, AF)
    assert af.post("/conversations/no-es-un-uuid/handoff").status_code == 422


def test_handoff_twice_is_idempotent(rt: Runtime) -> None:
    """T-54: pasar a QA dos veces la misma versión devuelve la misma entrega."""
    af, cid, first = _handed_off(rt)
    second = af.post(f"/conversations/{cid}/handoff")
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert len(_store(rt).rows) == 1


def test_qa_cannot_hand_off_is_403(rt: Runtime) -> None:
    """D-01: qa-demo no tiene `generate_story`: no puede pasar a QA."""
    qa = Api(rt, QA)
    response = qa.post(f"/conversations/{uuid4()}/handoff")
    assert response.status_code == 403
    assert _code(response) == "forbidden"


def test_qa_cannot_hand_off_own_qa_conversation(rt: Runtime) -> None:
    """D-01 (negativa): ni siquiera sobre una conversación propia de QA."""
    _af, _cid, handoff = _handed_off(rt)
    qa = Api(rt, QA)
    qa_cid = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()["id"]
    response = qa.post(f"/conversations/{qa_cid}/handoff")
    assert response.status_code == 403


# --- Listar y recoger ----------------------------------------------------------------------------


def test_functional_cannot_list_or_take_handoffs_is_403(rt: Runtime) -> None:
    """D-01: af-demo no tiene `generate_tests`: ni lista ni recoge."""
    af, _cid, handoff = _handed_off(rt)
    listed = af.get("/qa/handoffs")
    taken = af.post(f"/qa/handoffs/{handoff['id']}/take")
    assert listed.status_code == taken.status_code == 403
    assert _code(listed) == _code(taken) == "forbidden"
    assert _store(rt).rows[handoff["id"]].status == "pending"


def test_list_is_empty_without_handoffs(rt: Runtime) -> None:
    """T-54 (límite): sin entregas la lista está vacía."""
    assert Api(rt, QA).get("/qa/handoffs").json() == []


def test_list_only_includes_visible_projects(rt: Runtime) -> None:
    """T-54: solo las entregas de proyectos que devuelve `list_projects`."""
    _af, _cid, handoff = _handed_off(rt)
    store = _store(rt)
    hidden = store.rows[handoff["id"]].model_copy(
        update={"id": secrets.token_hex(16), "artifact_id": uuid4(), "project_key": "OCULTO"}
    )
    store.rows[hidden.id] = hidden
    listed = Api(rt, QA).get("/qa/handoffs").json()
    assert [h["id"] for h in listed] == [handoff["id"]]
    assert all(h["project"] == "DEMO" for h in listed)


def test_take_twice_by_same_person_is_409_and_one_conversation(rt: Runtime) -> None:
    """T-54: una entrega se recoge una sola vez; el segundo intento -> 409 y ninguna
    conversación nueva."""
    _af, _cid, handoff = _handed_off(rt)
    qa = Api(rt, QA)
    first = qa.post(f"/qa/handoffs/{handoff['id']}/take")
    second = qa.post(f"/qa/handoffs/{handoff['id']}/take")
    assert first.status_code == 202
    assert second.status_code == 409 and _code(second) == "handoff_unavailable"
    assert [c["thread_id"] for c in qa.get("/conversations").json()] == [first.json()["id"]]


def test_take_by_two_people_only_first_wins(rt: Runtime) -> None:
    """T-54 / D-01: si otra persona de QA ya la recogió -> 409; solo existe una conversación."""
    _af, _cid, handoff = _handed_off(rt)
    qa = Api(rt, QA)
    other = Api(rt, QA)
    other.session.user = OTHER_QA
    first = qa.post(f"/qa/handoffs/{handoff['id']}/take")
    second = other.post(f"/qa/handoffs/{handoff['id']}/take")
    assert first.status_code == 202
    assert second.status_code == 409 and _code(second) == "handoff_unavailable"
    assert other.get("/conversations").json() == []
    assert len(qa.get("/conversations").json()) == 1
    row = _store(rt).rows[handoff["id"]]
    assert row.taken_by == "qa-demo" and row.qa_thread_id == first.json()["id"]


def test_take_unknown_well_formed_id_is_409(rt: Runtime) -> None:
    """T-54: id bien formado que no existe -> 409 `handoff_unavailable` (no revela si existe)."""
    qa = Api(rt, QA)
    response = qa.post(f"/qa/handoffs/{HEX32}/take")
    assert response.status_code == 409
    assert _code(response) == "handoff_unavailable"
    assert qa.get("/conversations").json() == []


@pytest.mark.parametrize(
    "handoff_id",
    [
        str(uuid4()),  # UUID con guiones
        "A" * 32,  # mayúsculas
        "0" * 31,  # corto
        "0" * 33,  # largo
        "g" * 32,  # no hexadecimal
    ],
)
def test_take_malformed_id_is_422(rt: Runtime, handoff_id: str) -> None:
    """Contrato (límite): `handoff_id` debe cumplir `^[0-9a-f]{32}$`."""
    qa = Api(rt, QA)
    response = qa.post(f"/qa/handoffs/{handoff_id}/take")
    assert response.status_code == 422
    assert _code(response) == "invalid_request"


# --- Sin almacén de entregas ---------------------------------------------------------------------


def test_routes_without_handoff_store_are_503(rt: Runtime) -> None:
    """PA-268: sin `rt.handoffs` las tres rutas responden 503 `service_unavailable`."""
    af = Api(rt, AF)
    cid = _approved_story(af)
    rt.handoffs = None
    qa = Api(rt, QA)
    responses = [
        af.post(f"/conversations/{cid}/handoff"),
        qa.get("/qa/handoffs"),
        qa.post(f"/qa/handoffs/{HEX32}/take"),
    ]
    assert [r.status_code for r in responses] == [503, 503, 503]
    assert {_code(r) for r in responses} == {"service_unavailable"}
