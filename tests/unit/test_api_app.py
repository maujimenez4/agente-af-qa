"""API real (T-55, parte 2) sobre los fakes: sesión, CSRF, conversaciones y no escritura en Jira.

Solo fakes de `tests/fakes/` y datos 100 % ficticios. Las operaciones largas se ejecutan en el
mismo hilo (`run_inline`), así que la respuesta ya trae el estado final de la operación.
"""

import asyncio
import gc
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from adapters.base import IssueDetail, IssueSummary, ProjectSummary, User
from adapters.errors import RateLimitError
from api import app as app_module
from api import service
from api.app import API_PREFIX, create_app
from api.errors import UNEXPECTED
from api.runtime import Runtime
from api.security import COOKIE, BodyLimitMiddleware
from api.sessions import ApiSession
from core.approvals import ApprovalError
from core.context.jql import text_search_jql
from tests.fakes import dataset
from tests.fakes.api import api_settings, fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement

AF = ("af-demo", dataset.DEMO_USERS["af-demo"][0])
QA = ("qa-demo", dataset.DEMO_USERS["qa-demo"][0])
ADMIN = ("admin-demo", dataset.DEMO_USERS["admin-demo"][0])
EVOLVE = {"flow": "evolve", "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}}
TESTS = {"flow": "tests", "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}}
NEED = {
    "flow": "need",
    "origin": {"kind": "need", "text": "Avisar del vencimiento (ficticio).", "project": "DEMO"},
}
SECRET_TEXT = "detalle-interno-ficticio-0000"  # texto de excepción que nunca debe salir


class Api:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.client = TestClient(create_app(runtime_instance=rt), base_url="https://testserver")
        self.csrf = ""

    def login(self, who: tuple[str, str] = AF) -> Any:
        response = self.client.post(
            f"{API_PREFIX}/auth/login", json={"username": who[0], "password": who[1]}
        )
        if response.status_code == 200:
            self.csrf = response.json()["csrf_token"]
        return response

    def get(self, path: str, **kw: Any) -> Any:
        return self.client.get(f"{API_PREFIX}{path}", **kw)

    def post(self, path: str, json: Any = None, csrf: bool = True) -> Any:
        headers = {"X-CSRF-Token": self.csrf} if csrf else {}
        return self.client.post(f"{API_PREFIX}{path}", json=json, headers=headers)

    def put(self, path: str, json: Any = None, csrf: bool = True) -> Any:
        headers = {"X-CSRF-Token": self.csrf} if csrf else {}
        return self.client.put(f"{API_PREFIX}{path}", json=json, headers=headers)

    def delete(self, path: str, csrf: bool = True) -> Any:
        headers = {"X-CSRF-Token": self.csrf} if csrf else {}
        return self.client.delete(f"{API_PREFIX}{path}", headers=headers)

    @property
    def cookie(self) -> str:
        value = self.client.cookies.get(COOKIE)
        assert value
        return value

    @property
    def session(self) -> ApiSession[Any]:
        session = self.rt.sessions.get(self.cookie, touch=False)
        assert session is not None
        return session


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path)


@pytest.fixture
def api(rt: Runtime) -> Api:
    a = Api(rt)
    assert a.login().status_code == 200
    return a


def _nothing_written(rt: Runtime) -> None:
    ws_container = rt.workspace_factory().container
    tracker = ws_container.issue_tracker
    testmgmt = ws_container.test_management
    assert isinstance(tracker, FakeIssueTracker) and isinstance(testmgmt, FakeTestManagement)
    assert tracker.writes == []
    assert testmgmt.publish_calls == 0


def test_login_sets_httponly_strict_cookie_and_returns_csrf(rt: Runtime) -> None:
    a = Api(rt)
    response = a.login()
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    for part in ("afqa_session=", "httponly", "secure", "samesite=strict", "path=/api"):
        assert part in cookie
    assert response.json()["user"]["username"] == "af-demo"
    assert "publish_story" in response.json()["user"]["permissions"]


def test_requests_without_session_are_401(rt: Runtime) -> None:
    response = Api(rt).get("/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_wrong_password_is_401_and_then_429(rt: Runtime) -> None:
    a = Api(rt)
    for _ in range(rt.settings.api_login_max_attempts):
        assert a.login(("af-demo", "contrasena-incorrecta")).status_code == 401
    response = a.login()
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"


def test_post_without_csrf_is_403(api: Api) -> None:
    response = api.post("/projects/choose", {"project": "DEMO"}, csrf=False)
    assert response.status_code == 403


def test_post_from_foreign_origin_is_403(api: Api) -> None:
    response = api.client.post(
        f"{API_PREFIX}/projects/choose",
        json={"project": "DEMO"},
        headers={"X-CSRF-Token": api.csrf, "Origin": "https://sitio-ajeno.example"},
    )
    assert response.status_code == 403


def test_evolve_conversation_reaches_review_and_simulated_publish(api: Api, rt: Runtime) -> None:
    created = api.post("/conversations", EVOLVE)
    assert created.status_code == 202, created.text
    conv = created.json()
    assert conv["state"] == "in_review", conv
    review = conv["review"]
    assert review["version"] == 1 and len(review["fingerprint"]) == 64
    assert [s["state"] for s in conv["progress"][:3]] == ["done"] * 3

    listed = api.get("/conversations").json()
    assert [c["thread_id"] for c in listed] == [conv["id"]]

    approved = api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": review["fingerprint"]}
    )
    assert approved.status_code == 202, approved.text
    body = approved.json()
    assert body["state"] == "simulated", body
    assert body["result"]["simulated"] is True
    assert body["result"]["approved_by"] == "af-demo"
    _nothing_written(rt)


def test_iterate_edit_discard_never_write_to_jira(api: Api, rt: Runtime) -> None:
    conv = api.post("/conversations", EVOLVE).json()
    cid = conv["id"]
    iterated = api.post(f"/conversations/{cid}/iterate", {"feedback": "Cambio ficticio."}).json()
    assert iterated["state"] == "in_review" and iterated["review"]["version"] == 2
    content = iterated["review"]["artifact"]["content"] | {"title": "Título editado (ficticio)"}
    edited = api.post(
        f"/conversations/{cid}/edit",
        {"content": content, "fingerprint": iterated["review"]["fingerprint"]},
    ).json()
    assert edited["review"]["version"] == 3, edited
    assert edited["versions"][-1]["edited"] is True
    discarded = api.post(f"/conversations/{cid}/discard").json()
    assert discarded["state"] == "discarded"
    _nothing_written(rt)


def test_other_users_conversation_is_404(rt: Runtime) -> None:
    owner, other = Api(rt), Api(rt)
    owner.login()
    other.login(QA)
    cid = owner.post("/conversations", EVOLVE).json()["id"]
    response = other.get(f"/conversations/{cid}")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "No existe esa conversación o no es tuya."


def test_wrong_fingerprint_keeps_review_with_error(api: Api) -> None:
    conv = api.post("/conversations", EVOLVE).json()
    response = api.post(f"/conversations/{conv['id']}/approve", {"fingerprint": "0" * 64})
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "in_review"
    assert body["review"]["error"]


def test_body_too_large_is_413(api: Api) -> None:
    big = {"text": "x" * 300_000, "project": "DEMO"}
    response = api.post("/start/propose", big)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_settings_only_accept_models_of_the_chain(api: Api) -> None:
    ok = api.client.put(
        f"{API_PREFIX}/settings/models/generate_story",
        json={"provider": "ollama", "model": "modelo-ficticio-b"},
        headers={"X-CSRF-Token": api.csrf},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["override"] == {"provider": "ollama", "model": "modelo-ficticio-b"}
    bad = api.client.put(
        f"{API_PREFIX}/settings/models/generate_story",
        json={"provider": "ollama", "model": "otro-modelo"},
        headers={"X-CSRF-Token": api.csrf},
    )
    assert bad.status_code == 422


def test_security_headers_on_every_response(api: Api) -> None:
    response = api.get("/auth/me")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


# =============================================================================================
# Ampliación (T-55, parte 2): un bloque por criterio de `docs/api/requisitos-parte-2.md`.
# =============================================================================================


@dataclass
class CapturingTracker(FakeIssueTracker):
    """Tracker de los fakes que guarda la JQL recibida y las claves leídas."""

    jqls: list[str] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        self.jqls.append(jql)
        return super().search(jql, limit)

    def get_issue(self, key: str) -> IssueDetail:
        self.fetched.append(key)
        return super().get_issue(key)


@dataclass
class ExplodingProjectsTracker(FakeIssueTracker):
    """Fallo inesperado (no de `adapters/errors.py`) con un texto interno ficticio."""

    def list_projects(self) -> list[ProjectSummary]:
        raise RuntimeError(SECRET_TEXT)


@dataclass
class ExplodingIssueTracker(FakeIssueTracker):
    """Fallo inesperado al leer el origen, ya dentro de la operación en segundo plano."""

    def get_issue(self, key: str) -> IssueDetail:
        raise RuntimeError(SECRET_TEXT)


def _container(rt: Runtime) -> Any:
    return rt.workspace_factory().container


def _with_cookie(rt: Runtime, cookie: str) -> TestClient:
    """Cliente nuevo que solo envía la cookie indicada (p. ej. una ya rotada)."""
    client = TestClient(create_app(runtime_instance=rt), base_url="https://testserver")
    client.headers["Cookie"] = f"{COOKIE}={cookie}"
    return client


def _error(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "retry_after"}, body
    return body["error"]


# --- 1. Sesión --------------------------------------------------------------------------------


def test_insecure_dev_cookie_flag_drops_secure_only_in_development(tmp_path: Path) -> None:
    """Req. 1: sin `Secure` solo con el indicador explícito y APP_ENV=development."""
    settings = api_settings(api_insecure_dev_cookie=True)
    cookie = Api(fake_runtime(tmp_path, settings=settings)).login().headers["set-cookie"]
    parts = [p.strip().lower() for p in cookie.split(";")]
    assert "secure" not in parts
    assert "httponly" in parts and "samesite=strict" in parts and "path=/api" in parts


def test_insecure_dev_cookie_flag_is_ignored_in_production(tmp_path: Path) -> None:
    """Req. 1: en producción la cookie sigue siendo `Secure` aunque esté el indicador."""
    settings = api_settings(app_env="production", api_insecure_dev_cookie=True)
    cookie = Api(fake_runtime(tmp_path, settings=settings)).login().headers["set-cookie"]
    assert "secure" in [p.strip().lower() for p in cookie.split(";")]


def test_cookie_has_no_domain_and_only_an_opaque_id(api: Api) -> None:
    """Req. 1: sin `Domain`; la cookie es un identificador, no lleva el usuario ni el token."""
    response = api.login()
    cookie = response.headers["set-cookie"]
    assert "domain" not in cookie.lower()
    value = api.cookie
    assert "af-demo" not in value and api.csrf not in value and len(value) >= 22


def test_login_again_rotates_and_invalidates_previous_cookie(api: Api, rt: Runtime) -> None:
    """Req. 1: un login nuevo rota el identificador y la cookie anterior deja de valer."""
    old = api.cookie
    assert api.login().status_code == 200
    new = api.cookie
    assert new != old
    assert rt.sessions.get(old) is None
    response = _with_cookie(rt, old).get(f"{API_PREFIX}/auth/me")
    assert response.status_code == 401
    assert api.get("/auth/me").status_code == 200


def test_logout_requires_csrf(api: Api, rt: Runtime) -> None:
    """Req. 1 y 2: `logout` también exige el token anti-CSRF."""
    response = api.post("/auth/logout", csrf=False)
    assert response.status_code == 403
    assert rt.sessions.get(api.cookie) is not None


def test_logout_invalidates_session(api: Api, rt: Runtime) -> None:
    """Req. 1: tras cerrar la sesión, la cookie no vale aunque se reenvíe."""
    old = api.cookie
    response = api.post("/auth/logout")
    assert response.status_code == 204
    assert rt.sessions.get(old) is None
    assert _with_cookie(rt, old).get(f"{API_PREFIX}/auth/me").status_code == 401
    assert api.get("/auth/me").status_code == 401


def test_session_expires_by_inactivity_through_the_api(tmp_path: Path) -> None:
    """Req. 1: con el reloj del almacén adelantado, la sesión caduca por inactividad."""
    rt = fake_runtime(tmp_path)
    now = [0.0]
    rt.sessions._clock = lambda: now[0]
    a = Api(rt)
    a.login()
    now[0] += rt.settings.api_session_idle_minutes * 60 - 1
    assert a.get("/auth/me").status_code == 200
    now[0] += rt.settings.api_session_idle_minutes * 60 + 1
    response = a.get("/auth/me")
    assert response.status_code == 401
    assert _error(response)["code"] == "unauthenticated"


def test_session_expires_by_absolute_time_through_the_api(tmp_path: Path) -> None:
    """Req. 1: aunque haya actividad, la sesión caduca por tiempo absoluto."""
    rt = fake_runtime(tmp_path)
    now = [0.0]
    rt.sessions._clock = lambda: now[0]
    a = Api(rt)
    a.login()
    step = rt.settings.api_session_idle_minutes * 60 - 1
    while now[0] + step <= rt.settings.api_session_max_hours * 3600:
        now[0] += step
        assert a.get("/auth/me").status_code == 200
    now[0] += step
    assert a.get("/auth/me").status_code == 401


def test_auth_me_has_no_side_effects(api: Api, rt: Runtime) -> None:
    """Req. 2: ningún GET tiene efectos: `/auth/me` no rota cookie ni token."""
    cookie, csrf = api.cookie, api.csrf
    first, second = api.get("/auth/me"), api.get("/auth/me")
    assert first.status_code == second.status_code == 200
    assert "set-cookie" not in first.headers and "set-cookie" not in second.headers
    assert first.json() == second.json()
    assert first.json()["csrf_token"] == csrf
    assert api.cookie == cookie and rt.sessions.get(cookie) is not None


# --- 2. CSRF y origen --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/projects/choose", {"project": "DEMO"}),
        ("put", "/settings/models/generate_story", {"provider": "ollama", "model": "x"}),
        ("delete", "/settings/models/generate_story", None),
    ],
)
def test_unsafe_methods_without_csrf_are_403(
    api: Api, method: str, path: str, body: dict[str, str] | None
) -> None:
    """Req. 2: POST, PUT y DELETE sin `X-CSRF-Token` -> 403."""
    call = getattr(api, method)
    response = call(path, body, csrf=False) if body is not None else call(path, csrf=False)
    assert response.status_code == 403
    assert _error(response)["code"] == "forbidden"


def test_csrf_token_of_another_session_is_403(rt: Runtime) -> None:
    """Req. 2: el token está ligado a la sesión: el de otra sesión no vale."""
    mine, other = Api(rt), Api(rt)
    mine.login()
    other.login()
    mine.csrf = other.csrf
    assert mine.post("/projects/choose", {"project": "DEMO"}).status_code == 403
    assert mine.delete("/settings/models/generate_story").status_code == 403


def test_get_without_csrf_is_ok(api: Api) -> None:
    """Req. 2: los GET no necesitan el token (y no tienen efectos)."""
    assert api.get("/projects").status_code == 200
    assert api.get("/conversations").status_code == 200


def test_login_from_foreign_origin_is_403(rt: Runtime) -> None:
    """Req. 2: `Origin` ajeno rechazado también en el login (no crea sesión)."""
    a = Api(rt)
    response = a.client.post(
        f"{API_PREFIX}/auth/login",
        json={"username": AF[0], "password": AF[1]},
        headers={"Origin": "https://sitio-ajeno.example"},
    )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert rt.sessions._sessions == {}


def test_foreign_referer_without_origin_is_403(api: Api) -> None:
    """Req. 2: sin `Origin`, se valida el `Referer`."""
    response = api.client.post(
        f"{API_PREFIX}/projects/choose",
        json={"project": "DEMO"},
        headers={"X-CSRF-Token": api.csrf, "Referer": "https://sitio-ajeno.example/pagina"},
    )
    assert response.status_code == 403


def test_same_origin_is_accepted(api: Api) -> None:
    """Req. 2: el mismo origen pasa (con el token)."""
    response = api.client.post(
        f"{API_PREFIX}/projects/choose",
        json={"project": "DEMO"},
        headers={"X-CSRF-Token": api.csrf, "Origin": "https://testserver"},
    )
    assert response.status_code == 200, response.text


def test_allowed_origin_list_is_accepted_in_login_and_posts(tmp_path: Path) -> None:
    """Req. 2 y 3: un origen de `api_allowed_origins` pasa en el login y en los POST."""
    allowed = "https://frontend.ficticio.example"
    rt = fake_runtime(tmp_path, settings=api_settings(api_allowed_origins=f"{allowed}/"))
    a = Api(rt)
    login = a.client.post(
        f"{API_PREFIX}/auth/login",
        json={"username": AF[0], "password": AF[1]},
        headers={"Origin": allowed},
    )
    assert login.status_code == 200, login.text
    assert login.headers["access-control-allow-origin"] == allowed
    assert login.headers["access-control-allow-credentials"] == "true"
    a.csrf = login.json()["csrf_token"]
    response = a.client.post(
        f"{API_PREFIX}/projects/choose",
        json={"project": "DEMO"},
        headers={"X-CSRF-Token": a.csrf, "Origin": allowed},
    )
    assert response.status_code == 200
    foreign = a.client.post(
        f"{API_PREFIX}/projects/choose",
        json={"project": "DEMO"},
        headers={"X-CSRF-Token": a.csrf, "Origin": "https://otro.ficticio.example"},
    )
    assert foreign.status_code == 403


# --- 3. Login ---------------------------------------------------------------------------------


def test_bad_credentials_same_401_whether_user_exists_or_not(rt: Runtime) -> None:
    """Req. 4: el mismo 401 y mensaje si el usuario existe o no."""
    a = Api(rt)
    existing = a.login(("af-demo", "contrasena-incorrecta-ficticia"))
    missing = a.login(("persona-inexistente", "contrasena-incorrecta-ficticia"))
    assert existing.status_code == missing.status_code == 401
    assert existing.json() == missing.json()
    assert _error(existing)["code"] == "invalid_credentials"
    assert "set-cookie" not in existing.headers


def test_lockout_returns_retry_after_body_and_header(rt: Runtime) -> None:
    """Req. 4: 429 `too_many_attempts` con `retry_after` y cabecera Retry-After."""
    a = Api(rt)
    for _ in range(rt.settings.api_login_max_attempts):
        a.login(("af-demo", "contrasena-incorrecta-ficticia"))
    response = a.login()
    assert response.status_code == 429
    error = _error(response)
    assert error["code"] == "too_many_attempts"
    assert 0 < error["retry_after"] <= rt.settings.api_login_lock_seconds
    assert int(response.headers["retry-after"]) == int(error["retry_after"])
    assert "set-cookie" not in response.headers


def test_lockout_by_ip_even_when_username_changes(rt: Runtime) -> None:
    """Req. 4: límite por IP aunque se cambie de usuario en cada intento."""
    a = Api(rt)
    for n in range(rt.settings.api_login_max_attempts):
        assert a.login((f"persona-ficticia-{n}", "contrasena-ficticia")).status_code == 401
    response = a.login(QA)  # credenciales buenas, otro usuario, misma IP
    assert response.status_code == 429
    assert _error(response)["code"] == "too_many_attempts"


def test_password_and_body_never_logged_nor_returned(
    rt: Runtime, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Req. 4 y 13: la contraseña y el cuerpo no salen en los logs ni en la respuesta."""
    caplog.set_level(logging.DEBUG)
    wrong = "contrasena-ficticia-que-no-debe-salir"
    too_long = "clave-ficticia-larga-" + "z" * 300
    a = Api(rt)
    responses = [
        a.login(("af-demo", wrong)),
        a.login(("persona-inexistente", wrong)),
        a.login(("af-demo", too_long)),  # 422: el mensaje no devuelve lo enviado
        a.login(),
    ]
    assert [r.status_code for r in responses] == [401, 401, 422, 200]
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text
    for secret in (wrong, too_long, AF[1]):
        assert secret not in logs
        assert all(secret not in r.text for r in responses)


# --- 4. Propiedad y permisos -------------------------------------------------------------------


def test_foreign_conversation_404_is_identical_to_missing_one(rt: Runtime) -> None:
    """Req. 5: el 404 de una conversación ajena es idéntico al de una inexistente."""
    owner, other = Api(rt), Api(rt)
    owner.login()
    other.login(QA)
    cid = owner.post("/conversations", EVOLVE).json()["id"]
    foreign = other.get(f"/conversations/{cid}")
    missing = other.get(f"/conversations/{uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    for op, body in (("iterate", {"feedback": "Cambio ficticio."}), ("discard", None)):
        response = other.post(f"/conversations/{cid}/{op}", body)
        assert response.status_code == 404 and response.json() == missing.json()
    assert owner.get(f"/conversations/{cid}").json()["state"] == "in_review"


def test_foreign_quality_review_404_is_identical_to_missing_one(rt: Runtime) -> None:
    """Req. 5: revisión de calidad ajena -> el mismo 404 que una inexistente."""
    owner, other = Api(rt), Api(rt)
    owner.login()
    other.login(QA)
    created = owner.post("/quality-reviews", {"issue_key": "DEMO-3"})
    assert created.status_code == 202, created.text
    rid = created.json()["id"]
    assert owner.get(f"/quality-reviews/{rid}").status_code == 200
    foreign = other.get(f"/quality-reviews/{rid}")
    missing = other.get(f"/quality-reviews/{uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize(
    ("who", "body"),
    [(QA, EVOLVE), (QA, NEED), (AF, TESTS), (ADMIN, NEED), (ADMIN, TESTS)],
    ids=["qa-evolve", "qa-need", "af-tests", "admin-need", "admin-tests"],
)
def test_role_cannot_create_flow_of_other_role(
    rt: Runtime, who: tuple[str, str], body: dict[str, Any]
) -> None:
    """Req. 5: QA no evoluciona HU, el analista no prepara pruebas, el admin no crea nada."""
    a = Api(rt)
    a.login(who)
    response = a.post("/conversations", body)
    assert response.status_code == 403
    assert _error(response)["code"] == "forbidden"
    assert a.get("/conversations").json() == []


def test_approve_requires_publish_story(api: Api, rt: Runtime) -> None:
    """Req. 5: aprobar una HU exige `publish_story` (rol sin él -> 403, nada publicado)."""
    conv = api.post("/conversations", EVOLVE).json()
    api.session.user = User(username="af-demo", role="qa")  # mismo dueño, sin publish_story
    response = api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert response.status_code == 403
    assert api.get(f"/conversations/{conv['id']}").json()["state"] == "in_review"
    _nothing_written(rt)


def test_approve_tests_requires_publish_tests(rt: Runtime) -> None:
    """Req. 5: aprobar una suite exige `publish_tests`."""
    a = Api(rt)
    a.login(QA)
    conv = a.post("/conversations", TESTS).json()
    a.session.user = User(username="qa-demo", role="functional")  # sin publish_tests
    response = a.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert response.status_code == 403
    _nothing_written(rt)


# --- 5. SSE -----------------------------------------------------------------------------------


def _events(text: str) -> list[tuple[str, str]]:
    """(evento, data) de un texto SSE; se ignoran los comentarios `: ping`."""
    out: list[tuple[str, str]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        fields = dict(line.split(": ", 1) for line in lines)
        out.append((fields["event"], fields["data"]))
    return out


@pytest.fixture
def fast_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "SSE_POLL_S", 0.02)


def test_sse_without_session_is_401(rt: Runtime) -> None:
    """Req. 6: el SSE exige la cookie."""
    response = Api(rt).get(f"/conversations/{uuid4()}/events")
    assert response.status_code == 401
    assert _error(response)["code"] == "unauthenticated"


def test_sse_foreign_conversation_is_404_before_opening(rt: Runtime) -> None:
    """Req. 6: propiedad comprobada antes de abrir el flujo (y sin reservar conexión)."""
    owner, other = Api(rt), Api(rt)
    owner.login()
    other.login(QA)
    cid = owner.post("/conversations", EVOLVE).json()["id"]
    response = other.get(f"/conversations/{cid}/events")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert other.session.streams == 0


def test_sse_too_many_streams_is_429(api: Api, rt: Runtime) -> None:
    """Req. 6: límite de flujos abiertos por persona -> 429 `too_many_streams`."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.session.streams = rt.settings.api_max_streams_per_user
    response = api.get(f"/conversations/{cid}/events")
    assert response.status_code == 429
    assert _error(response)["code"] == "too_many_streams"


def test_sse_limit_counts_other_sessions_of_same_person(rt: Runtime) -> None:
    """Req. 6: el cupo es por persona, aunque los flujos sean de otra sesión suya."""
    first, second = Api(rt), Api(rt)
    first.login()
    second.login()
    cid = first.post("/conversations", EVOLVE).json()["id"]
    first.session.streams = rt.settings.api_max_streams_per_user
    response = second.get(f"/conversations/{cid}/events")
    assert response.status_code == 429


def test_sse_discarded_conversation_emits_progress_then_result_and_closes(
    api: Api, fast_sse: None
) -> None:
    """Req. 6: conversación terminada -> `progress` y `result`, y el servidor cierra."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    assert api.post(f"/conversations/{cid}/discard").json()["state"] == "discarded"
    response = api.get(f"/conversations/{cid}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    names = [name for name, _ in events]
    assert names[-1] == "result" and set(names[:-1]) == {"progress"}
    assert '"state": "discarded"' in events[-1][1]
    assert api.session.streams == 0  # la conexión se libera al cerrar


def test_sse_emits_progress_review_ready_and_result_on_discard(
    api: Api, rt: Runtime, fast_sse: None
) -> None:
    """Req. 6: orden `progress` -> `review_ready` -> `result` al descartar con el flujo abierto."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    session = api.session

    def discard() -> None:
        service.resume(rt, session.workspace, session.user, cid, "discard", {"decision": "discard"})

    timer = threading.Timer(0.3, discard)
    safety = threading.Timer(10.0, lambda: rt.sessions.drop(session.id))  # nunca colgarse
    timer.start()
    safety.start()
    try:
        response = api.get(f"/conversations/{cid}/events")
    finally:
        timer.cancel()
        safety.cancel()
    names = [name for name, _ in _events(response.text)]
    assert "review_ready" in names and names[-1] == "result", names
    first_review = names.index("review_ready")
    assert set(names[:first_review]) == {"progress"}
    assert names.count("review_ready") == 1
    assert session.streams == 0


def test_sse_closes_when_session_ends(api: Api, rt: Runtime, fast_sse: None) -> None:
    """Req. 6: el flujo se cierra si la sesión caduca o se cierra."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    session = api.session
    timer = threading.Timer(0.3, lambda: rt.sessions.drop(session.id))
    timer.start()
    try:
        response = api.get(f"/conversations/{cid}/events")
    finally:
        timer.cancel()
    names = [name for name, _ in _events(response.text)]
    assert names[-1] == "review_ready" and "result" not in names


# --- 6. Tamaño del cuerpo ---------------------------------------------------------------------


def _post_chunked(api: Api) -> Any:
    """POST de ~300 KB por trozos (`Transfer-Encoding: chunked`, sin `Content-Length`)."""

    def body() -> Iterator[bytes]:
        yield b'{"text": "' + b"x" * 200_000
        yield b"y" * 100_000 + b'", "project": "DEMO"}'

    response = api.client.post(
        f"{API_PREFIX}/start/propose",
        content=body(),
        headers={"X-CSRF-Token": api.csrf, "Content-Type": "application/json"},
    )
    assert "content-length" not in response.request.headers
    return response


def test_body_too_large_without_content_length_is_rejected(api: Api) -> None:
    """Req. 7: sin `Content-Length`, un cuerpo demasiado grande no llega a procesarse."""
    response = _post_chunked(api)
    assert response.status_code == 413
    _error(response)


def test_body_too_large_without_content_length_is_413(api: Api) -> None:
    """Req. 7: 413 en la forma común también sin `Content-Length` (cuerpo por trozos)."""
    response = _post_chunked(api)
    assert response.status_code == 413
    assert _error(response) == {
        "code": "payload_too_large",
        "message": "La petición es demasiado grande.",
        "retry_after": None,
    }


def test_body_at_limit_is_not_rejected_by_size(tmp_path: Path) -> None:
    """Req. 7 (límite): un cuerpo dentro del límite no da 413."""
    rt = fake_runtime(tmp_path, settings=api_settings(api_max_body_bytes=2048))
    a = Api(rt)
    a.login()
    ok = a.post("/start/propose", {"text": "x" * 1500, "project": "DEMO"})
    assert ok.status_code == 200, ok.text
    too_big = a.post("/start/propose", {"text": "x" * 3000, "project": "DEMO"})
    assert too_big.status_code == 413


def test_non_numeric_content_length_is_413() -> None:
    """Req. 7: un `Content-Length` no numérico se rechaza con 413 sin llamar a la app."""
    called: list[str] = []
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        called.append("app")

    async def too_large(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 413, "headers": []})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    middleware = BodyLimitMiddleware(app, max_bytes=100, on_too_large=too_large)
    scope = {"type": "http", "headers": [(b"content-length", b"abc")]}
    asyncio.run(middleware(scope, receive, send))
    assert called == [] and sent[0]["status"] == 413


# --- 7. Errores -------------------------------------------------------------------------------


def test_unknown_route_is_404_in_common_shape(api: Api) -> None:
    """Req. 8: ruta inexistente -> 404 con la forma común."""
    response = api.get("/ruta-que-no-existe")
    assert response.status_code == 404
    assert _error(response) == {
        "code": "not_found",
        "message": "No existe ese recurso.",
        "retry_after": None,
    }


def test_wrong_method_is_405_in_common_shape(api: Api) -> None:
    """Req. 8: método no permitido -> 405 con la forma común."""
    response = api.delete("/auth/me")
    assert response.status_code == 405
    assert _error(response)["code"] == "method_not_allowed"


def test_llm_rate_limit_leaves_conversation_in_error(tmp_path: Path) -> None:
    """Req. 8: el 429 del LLM al crear deja la conversación en `error` con `rate_limited`."""
    llm = FakeLLMProvider(error=RateLimitError("Límite ficticio del LLM.", "llm", 99_999))
    rt = fake_runtime(tmp_path, llm=llm)
    a = Api(rt)
    a.login()
    created = a.post("/conversations", EVOLVE)
    assert created.status_code == 202, created.text
    conv = created.json()
    assert conv["state"] == "error", conv
    assert conv["error"]["code"] == "rate_limited"
    assert conv["error"]["retry_after"] <= 3600
    assert conv["review"] is None
    _nothing_written(rt)


def test_unexpected_error_in_request_never_exposes_str(tmp_path: Path) -> None:
    """Req. 8: excepción inesperada en la petición -> 500 con el mensaje genérico."""
    rt = fake_runtime(tmp_path, issue_tracker=ExplodingProjectsTracker())
    a = Api(rt)
    a.client = TestClient(
        create_app(runtime_instance=rt),
        base_url="https://testserver",
        raise_server_exceptions=False,
    )
    a.login()
    for response in (a.get("/projects"), a.post("/conversations", NEED)):
        assert response.status_code == 500
        assert _error(response) == {
            "code": "unexpected",
            "message": UNEXPECTED,
            "retry_after": None,
        }
        assert SECRET_TEXT not in response.text


def test_unexpected_error_in_background_operation_never_exposes_str(tmp_path: Path) -> None:
    """Req. 8: excepción inesperada dentro del grafo -> `state=error` con el mensaje genérico."""
    rt = fake_runtime(tmp_path, issue_tracker=ExplodingIssueTracker())
    a = Api(rt)
    a.login()
    created = a.post("/conversations", EVOLVE)
    assert created.status_code == 202
    conv = created.json()
    assert conv["state"] == "error", conv
    assert conv["error"]["message"] == UNEXPECTED
    assert SECRET_TEXT not in created.text
    assert SECRET_TEXT not in a.get(f"/conversations/{conv['id']}").text


def test_validation_422_never_echoes_input(api: Api) -> None:
    """Req. 8: el 422 de validación no devuelve lo enviado."""
    marker = "valor-ficticio-enviado-<script>"
    response = api.post("/projects/choose", {"project": marker})
    assert response.status_code == 422
    assert _error(response)["code"] == "invalid_request"
    assert marker not in response.text


# --- 8. Escritura en Jira ---------------------------------------------------------------------


@pytest.fixture
def live_rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path, publish_mode="live")


def test_edit_iterate_discard_quality_never_write_in_live_mode(live_rt: Runtime) -> None:
    """Req. 9: en `live`, `edit`, `iterate`, `discard` y `quality-reviews` no escriben."""
    a = Api(live_rt)
    a.login()
    assert a.get("/settings").json()["publish_mode"] == "live"
    conv = a.post("/conversations", EVOLVE).json()
    cid = conv["id"]
    iterated = a.post(f"/conversations/{cid}/iterate", {"feedback": "Cambio ficticio."}).json()
    assert iterated["state"] == "in_review"
    content = iterated["review"]["artifact"]["content"] | {"title": "Título editado (ficticio)"}
    edited = a.post(
        f"/conversations/{cid}/edit",
        {"content": content, "fingerprint": iterated["review"]["fingerprint"]},
    )
    assert edited.status_code == 200 and edited.json()["state"] == "in_review"
    review = a.post("/quality-reviews", {"issue_key": "DEMO-3"})
    assert review.status_code == 202 and review.json()["state"] == "done", review.text
    assert a.post(f"/conversations/{cid}/discard").json()["state"] == "discarded"
    _nothing_written(live_rt)


@pytest.mark.parametrize("method", ["put", "post", "delete"])
def test_publish_mode_cannot_be_changed_through_the_api(live_rt: Runtime, method: str) -> None:
    """Req. 9: no hay ruta para cambiar `publish_mode`."""
    a = Api(live_rt)
    a.login()
    for path in ("/settings", "/settings/publish_mode"):
        call = getattr(a, method)
        response = call(path, {"publish_mode": "simulation"}) if method != "delete" else call(path)
        assert response.status_code in (404, 405), (path, response.status_code)
    assert a.get("/settings").json()["publish_mode"] == "live"
    assert _container(live_rt).publish_mode == "live"


def test_approve_in_live_mode_publishes_with_fakes(live_rt: Runtime) -> None:
    """Req. 9: solo `approve` con la huella escribe; en `live` queda `published`."""
    a = Api(live_rt)
    a.login()
    conv = a.post("/conversations", EVOLVE).json()
    approved = a.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert approved.status_code == 202, approved.text
    body = approved.json()
    assert body["state"] == "published", body
    assert body["result"]["simulated"] is False
    tracker = _container(live_rt).issue_tracker
    assert isinstance(tracker, FakeIssueTracker) and tracker.writes


# --- 9. Aprobar -------------------------------------------------------------------------------


def test_approval_ledger_not_offering_version_is_409(
    api: Api, rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approve: el registro de aprobaciones no ofrece la versión -> 409 `approval_rejected`."""
    conv = api.post("/conversations", EVOLVE).json()
    monkeypatch.setattr(_container(rt).approvals, "is_offered", lambda *_a, **_k: False)
    response = api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "approval_rejected"
    _nothing_written(rt)


def test_approval_ledger_error_is_409_with_its_message(
    api: Api, rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approve: un `ApprovalError` del registro (falla cerrado) -> 409 `approval_rejected`."""
    conv = api.post("/conversations", EVOLVE).json()

    def broken(*_a: Any, **_k: Any) -> bool:
        raise ApprovalError("Registro de aprobaciones dañado (ficticio).")

    monkeypatch.setattr(_container(rt).approvals, "is_offered", broken)
    response = api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "approval_rejected"


def test_approval_ledger_unexpected_value_error_is_not_exposed(
    api: Api, rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req. 8: un `ValueError` cualquiera del registro no debe salir tal cual en la respuesta."""
    conv = api.post("/conversations", EVOLVE).json()

    def broken(*_a: Any, **_k: Any) -> bool:
        raise ValueError(SECRET_TEXT)

    monkeypatch.setattr(_container(rt).approvals, "is_offered", broken)
    response = api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert SECRET_TEXT not in response.text


@pytest.mark.parametrize(
    ("op", "body"),
    [
        ("approve", {"fingerprint": "0" * 64}),
        ("iterate", {"feedback": "Cambio ficticio."}),
        ("discard", None),
    ],
)
def test_operation_after_discard_is_409_not_in_review(
    api: Api, rt: Runtime, op: str, body: dict[str, Any] | None
) -> None:
    """Approve/iterate/discard: sobre una conversación que no está en revisión -> 409."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.post(f"/conversations/{cid}/discard")
    response = api.post(f"/conversations/{cid}/{op}", body)
    assert response.status_code == 409
    assert _error(response)["code"] == "not_in_review"
    _nothing_written(rt)


def test_edit_after_discard_is_409_not_in_review(api: Api) -> None:
    """Edit: sobre una conversación descartada -> 409 `not_in_review`."""
    conv = api.post("/conversations", EVOLVE).json()
    api.post(f"/conversations/{conv['id']}/discard")
    response = api.post(
        f"/conversations/{conv['id']}/edit",
        {"content": conv["review"]["artifact"]["content"], "fingerprint": "0" * 64},
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "not_in_review"


def test_operation_while_running_is_409_not_in_review(api: Api, rt: Runtime) -> None:
    """Approve: con otra operación en curso sobre la conversación -> 409 `not_in_review`."""
    conv = api.post("/conversations", EVOLVE).json()
    run = rt.runs.get(conv["id"])
    assert run is not None
    run.running = True
    response = api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert response.status_code == 409
    assert _error(response)["code"] == "not_in_review"
    _nothing_written(rt)


@pytest.mark.parametrize("fingerprint", ["corta", "G" * 64, "0" * 65])
def test_approve_with_malformed_fingerprint_is_422(api: Api, fingerprint: str) -> None:
    """Approve (límite): la huella debe ser 64 hexadecimales."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    response = api.post(f"/conversations/{cid}/approve", {"fingerprint": fingerprint})
    assert response.status_code == 422


# --- 10. Flujo QA -----------------------------------------------------------------------------


def test_tests_flow_with_qa_reaches_review_with_suite(rt: Runtime) -> None:
    """Flujo QA: `tests` con qa-demo sobre DEMO-3 llega a `in_review` con una suite."""
    a = Api(rt)
    a.login(QA)
    created = a.post("/conversations", TESTS)
    assert created.status_code == 202, created.text
    conv = created.json()
    assert conv["state"] == "in_review", conv
    assert conv["mode"] == "qa" and conv["flow"] == "tests"
    artifact = conv["review"]["artifact"]
    assert artifact["type"] == "test_suite"
    assert artifact["content"]["story_jira_key"] == "DEMO-3"
    assert artifact["content"]["cases"]
    approved = a.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    ).json()
    assert approved["state"] == "simulated", approved
    _nothing_written(rt)


# --- 11. Búsqueda -----------------------------------------------------------------------------


@pytest.fixture
def tracker_api(tmp_path: Path) -> tuple[Api, CapturingTracker]:
    tracker = CapturingTracker()
    a = Api(fake_runtime(tmp_path, issue_tracker=tracker))
    a.login()
    return a, tracker


def test_search_text_is_escaped_in_jql(tracker_api: tuple[Api, CapturingTracker]) -> None:
    """Req. 11: `q` con comillas y operadores JQL nunca llega sin escapar al tracker."""
    a, tracker = tracker_api
    q = 'renovar" OR project = OTRO OR text ~ "x'
    response = a.get("/projects/DEMO/search", params={"q": q})
    assert response.status_code == 200
    assert tracker.jqls == [text_search_jql("DEMO", q)]
    jql = tracker.jqls[0]
    assert jql.startswith('project = "DEMO" AND text ~ "')
    assert 'renovar" OR' not in jql and '\\"' in jql


def test_search_without_q_uses_recent_issues(tracker_api: tuple[Api, CapturingTracker]) -> None:
    """Req. 11: sin `q`, las recientes del proyecto (sin texto libre en la JQL)."""
    a, tracker = tracker_api
    response = a.get("/projects/DEMO/search")
    assert response.status_code == 200
    assert tracker.jqls == ['project = "DEMO" ORDER BY updated DESC']
    assert {i["key"] for i in response.json()} >= {"DEMO-2", "DEMO-3"}


def test_search_key_of_other_project_returns_empty(
    tracker_api: tuple[Api, CapturingTracker],
) -> None:
    """Req. 11: una clave de otro proyecto devuelve [] sin consultar el tracker."""
    a, tracker = tracker_api
    response = a.get("/projects/DEMO/search", params={"q": "OTRO-1"})
    assert response.status_code == 200 and response.json() == []
    assert tracker.fetched == [] and tracker.jqls == []


def test_search_key_of_same_project_is_found(tracker_api: tuple[Api, CapturingTracker]) -> None:
    """Req. 11: una clave del proyecto (también en minúsculas) se resuelve sin JQL."""
    a, tracker = tracker_api
    response = a.get("/projects/DEMO/search", params={"q": "demo-3"})
    assert [i["key"] for i in response.json()] == ["DEMO-3"]
    assert tracker.jqls == []


def test_search_invalid_project_is_rejected(tracker_api: tuple[Api, CapturingTracker]) -> None:
    """Req. 11: la clave de proyecto de la ruta se valida (no se interpola texto libre)."""
    a, tracker = tracker_api
    response = a.get('/projects/DEMO"x/search')
    assert response.status_code in (404, 422)
    assert tracker.jqls == []


def test_propose_never_interpolates_text_in_jql(
    tracker_api: tuple[Api, CapturingTracker],
) -> None:
    """Req. 11: `propose` pasa por `keywords`/`any_keyword_jql`: el texto no rompe la JQL."""
    a, tracker = tracker_api
    text = 'préstamo" OR project = OTRO OR summary ~ "renovar'
    response = a.post("/start/propose", {"text": text, "project": "DEMO"})
    assert response.status_code == 200, response.text
    for jql in tracker.jqls:
        assert jql.startswith('project = "DEMO"'), jql
        assert '" OR project = OTRO' not in jql


# --- 12. Selector de modelo -------------------------------------------------------------------


def test_model_override_unknown_task_is_404(api: Api) -> None:
    """Req. 12: tarea inexistente -> 404 en PUT y DELETE."""
    choice = {"provider": "ollama", "model": "modelo-ficticio-a"}
    put = api.put("/settings/models/tarea_inexistente", choice)
    delete = api.delete("/settings/models/tarea_inexistente")
    assert put.status_code == delete.status_code == 404
    assert _error(put)["code"] == "not_found"


def test_model_override_provider_not_in_chain_is_422(api: Api) -> None:
    """Req. 12: un modelo de la cadena con otro proveedor no es un par válido."""
    response = api.put(
        "/settings/models/generate_story", {"provider": "groq", "model": "modelo-ficticio-a"}
    )
    assert response.status_code == 422
    tasks = {t["task"]: t for t in api.get("/settings").json()["tasks"]}
    assert tasks["generate_story"]["override"] is None


def test_model_override_delete_clears_it(api: Api) -> None:
    """Req. 12: DELETE vuelve a «Modelo automático»."""
    choice = {"provider": "ollama", "model": "modelo-ficticio-b"}
    assert api.put("/settings/models/generate_story", choice).json()["override"] == choice
    cleared = api.delete("/settings/models/generate_story")
    assert cleared.status_code == 200
    assert cleared.json()["override"] is None
    tasks = {t["task"]: t for t in api.get("/settings").json()["tasks"]}
    assert tasks["generate_story"]["override"] is None
    assert api.session.workspace.overrides == {}


def test_model_override_is_per_session(rt: Runtime) -> None:
    """Req. 12 / RF-42: el cambio de modelo es de la sesión; otra sesión no lo ve."""
    first, second = Api(rt), Api(rt)
    first.login()
    second.login()
    choice = {"provider": "ollama", "model": "modelo-ficticio-b"}
    assert first.put("/settings/models/generate_story", choice).status_code == 200
    tasks = {t["task"]: t for t in second.get("/settings").json()["tasks"]}
    assert tasks["generate_story"]["override"] is None
    mine = {t["task"]: t for t in first.get("/settings").json()["tasks"]}
    assert mine["generate_story"]["override"] == choice


# --- 13. Crear conversación -------------------------------------------------------------------

OTHER_PROJECT_NEED = {
    "flow": "need",
    "origin": {"kind": "need", "text": "Necesidad ficticia.", "project": "OTRO"},
}
OTHER_PROJECT_STORY = {
    "flow": "evolve",
    "origin": {"kind": "story", "key": "OTRO-3", "project": "OTRO"},
}


@pytest.mark.parametrize("body", [OTHER_PROJECT_NEED, OTHER_PROJECT_STORY], ids=["need", "evolve"])
def test_create_conversation_in_invisible_project_is_404(api: Api, body: dict[str, Any]) -> None:
    """Req. 11 / crear: proyecto que no ve la conexión -> 404, sin conversación creada."""
    response = api.post("/conversations", body)
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"
    assert api.get("/conversations").json() == []


@pytest.mark.parametrize("text", [None, "", "   "])
def test_create_need_without_text_is_422(api: Api, text: str | None) -> None:
    """Crear: `need` sin texto -> 422 con el mensaje para la persona."""
    body = {"flow": "need", "origin": {"kind": "need", "text": text, "project": "DEMO"}}
    response = api.post("/conversations", body)
    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "invalid_request"
    assert error["message"] == service.NEED_TEXT_REQUIRED


def test_create_flow_origin_mismatch_is_422(api: Api) -> None:
    """Crear: `tests` no admite un origen `need`."""
    body = {"flow": "tests", "origin": {"kind": "need", "text": "Ficticio.", "project": "DEMO"}}
    response = api.post("/conversations", body)
    assert response.status_code == 422
    assert "no admite" in _error(response)["message"]


# --- 14. QA encadenada (T-54, PA-105) --------------------------------------------------------

HANDOFF_HEX = "0123456789abcdef" * 2  # id de entrega bien formado (32 hex), inexistente


def test_chained_qa_routes_answer_with_session(api: Api, rt: Runtime) -> None:
    """Req. 10 (T-54): con sesión ya no hay 501; la entrega inexistente responde 409/403/404."""
    handoff = api.post(f"/conversations/{uuid4()}/handoff")
    assert handoff.status_code == 404  # conversación inexistente
    qa = Api(rt)
    qa.login(QA)
    listed = qa.get("/qa/handoffs")
    taken = qa.post(f"/qa/handoffs/{HANDOFF_HEX}/take")
    assert listed.status_code == 200 and listed.json() == []
    assert taken.status_code == 409 and _error(taken)["code"] == "handoff_unavailable"
    for response in (handoff, listed, taken):
        assert response.status_code != 501


def test_chained_qa_routes_are_401_without_session(rt: Runtime) -> None:
    """Req. 1 y 10: sin sesión -> 401 (con un id de entrega válido de 32 hex)."""
    a = Api(rt)
    responses = [
        a.post(f"/conversations/{uuid4()}/handoff", csrf=False),
        a.get("/qa/handoffs"),
        a.post(f"/qa/handoffs/{HANDOFF_HEX}/take", csrf=False),
    ]
    assert [r.status_code for r in responses] == [401, 401, 401]
    assert {_error(r)["code"] for r in responses} == {"unauthenticated"}


def test_chained_qa_post_routes_require_csrf(api: Api, rt: Runtime) -> None:
    """Req. 2 y 10: los POST de QA encadenada exigen el token anti-CSRF."""
    assert api.post(f"/conversations/{uuid4()}/handoff", csrf=False).status_code == 403
    qa = Api(rt)
    qa.login(QA)
    assert qa.post(f"/qa/handoffs/{HANDOFF_HEX}/take", csrf=False).status_code == 403
    assert api.post(f"/qa/handoffs/{HANDOFF_HEX}/take", csrf=False).status_code == 403


# =============================================================================================
# Segunda ronda (T-55, parte 2): rutas sin prueba, SSE con desconexión, tope de revisiones de
# calidad, Retry-After, manejador genérico y cookie al cerrar sesión.
# =============================================================================================

# --- Rutas de Jira y arranque guiado ----------------------------------------------------------


def test_list_epics_of_project(api: Api) -> None:
    """RF-01 / UI «Elegir en Jira»: épicas del proyecto."""
    response = api.get("/projects/DEMO/epics")
    assert response.status_code == 200
    assert [i["key"] for i in response.json()] == ["DEMO-1"]
    assert api.get("/projects/OTRO/epics").json() == []


def test_list_stories_of_epic(api: Api) -> None:
    """RF-01: HU de una épica (clave también en minúsculas)."""
    for key in ("DEMO-1", "demo-1"):
        response = api.get(f"/epics/{key}/stories")
        assert response.status_code == 200
        assert {i["key"] for i in response.json()} == set(dataset.STORY_KEYS)


def test_issue_card_counts_distinct_criteria_and_rules(tmp_path: Path) -> None:
    """Ficha de incidencia: CA y RN distintos contados de la descripción, sin IA."""
    tracker = FakeIssueTracker()
    tracker.issues[
        "DEMO-4"
    ].description_text = (
        "CA-01 consultar. CA-02 filtrar. Repite CA-01. RN-01 doce meses. Texto CA-x sin número."
    )
    a = Api(fake_runtime(tmp_path, issue_tracker=tracker))
    a.login()
    response = a.get("/issues/demo-4")
    assert response.status_code == 200
    card = response.json()
    assert card["key"] == "DEMO-4" and card["project"] == "DEMO" and card["epic_key"] == "DEMO-1"
    assert (card["criteria_count"], card["rules_count"]) == (2, 1)


def test_issue_card_without_criteria_counts_zero(api: Api) -> None:
    """Ficha (límite): sin CA ni RN en la descripción, ceros."""
    card = api.get("/issues/DEMO-3").json()
    assert (card["criteria_count"], card["rules_count"]) == (0, 0)


def test_issue_card_missing_issue_is_404(api: Api) -> None:
    """Ficha (error): incidencia inexistente -> 404 con la forma común."""
    response = api.get("/issues/DEMO-999")
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


def test_sources_marks_origin_row_as_required(api: Api) -> None:
    """T-51: la fila de la incidencia de origen es `required`; el resto se puede desmarcar."""
    body = {"origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}}
    rows = api.post("/start/sources", body).json()["sources"]
    required = [r for r in rows if r["required"]]
    assert [r["ref"] for r in required] == ["DEMO-3"]
    assert {"DEMO-2", "doc-reglamento"} <= {r["ref"] for r in rows}


def test_sources_excluded_rows_are_left_out(api: Api) -> None:
    """T-51: las fuentes excluidas no aparecen en la vista previa."""
    body = {
        "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"},
        "excluded_sources": ["DEMO-2", "doc-glosario"],
    }
    refs = {r["ref"] for r in api.post("/start/sources", body).json()["sources"]}
    assert "DEMO-3" in refs and "DEMO-2" not in refs and "doc-glosario" not in refs


def test_sources_excluding_origin_is_422(api: Api) -> None:
    """T-51 (error): excluir la incidencia de origen -> 422 con el mensaje para la persona."""
    body = {
        "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"},
        "excluded_sources": ["DEMO-3"],
    }
    response = api.post("/start/sources", body)
    assert response.status_code == 422
    assert "DEMO-3" in _error(response)["message"]


def test_sources_need_without_text_is_422(api: Api) -> None:
    """T-51 (error): una necesidad sin texto no tiene vista previa."""
    body = {"origin": {"kind": "need", "text": "  ", "project": "DEMO"}}
    response = api.post("/start/sources", body)
    assert response.status_code == 422
    assert _error(response)["message"] == service.NEED_TEXT_REQUIRED


# --- SSE: la plaza se libera aunque el cliente se vaya ----------------------------------------


def test_sse_slots_are_released_after_each_stream(api: Api, rt: Runtime, fast_sse: None) -> None:
    """Req. 6: abrir y cerrar más flujos que el límite seguidos no da 429."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.post(f"/conversations/{cid}/discard")
    for _ in range(rt.settings.api_max_streams_per_user + 1):
        with api.client.stream("GET", f"{API_PREFIX}/conversations/{cid}/events") as response:
            assert response.status_code == 200
        assert api.session.streams == 0


def _events_scope(cookie: str, cid: str, spec_version: str) -> dict[str, Any]:
    path = f"{API_PREFIX}/conversations/{cid}/events"
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"cookie", f"{COOKIE}={cookie}".encode())],
        "client": ("testclient", 50000),
        "server": ("testserver", 443),
    }


def _call_events(
    rt: Runtime, cookie: str, cid: str, spec: str, client_gone: str
) -> tuple[list[int], int]:
    """Llama a la app ASGI con un cliente que se va antes de leer (`disconnect` u `OSError`).

    Devuelve los estados enviados y las plazas SSE ocupadas justo al terminar la petición,
    medidas dentro del bucle de eventos (como en uvicorn, que no lo cierra).
    """
    app = create_app(runtime_instance=rt)
    first = True

    async def receive() -> dict[str, Any]:
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": b"", "more_body": False}
        if client_gone == "disconnect":
            return {"type": "http.disconnect"}
        await asyncio.sleep(60)
        return {"type": "http.disconnect"}

    statuses: list[int] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])
        elif client_gone == "oserror":
            raise OSError("conexión cerrada por el cliente (ficticio)")

    session = rt.sessions.get(cookie, touch=False)
    assert session is not None

    async def main() -> int:
        await asyncio.wait_for(app(_events_scope(cookie, cid, spec), receive, send), 10)
        return session.streams

    streams = asyncio.run(main())
    return statuses, streams


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
def test_sse_slot_released_when_client_disconnects_before_reading(
    api: Api, rt: Runtime, fast_sse: None, spec: str
) -> None:
    """Req. 6: si el cliente se desconecta antes de leer, la plaza se libera (en revisión)."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    statuses, streams = _call_events(rt, api.cookie, cid, spec, "disconnect")
    assert statuses == [200] and streams == 0


def test_sse_slot_released_when_send_fails_without_gc(
    api: Api, rt: Runtime, fast_sse: None
) -> None:
    """Req. 6: la plaza se libera al terminar la petición, sin depender del recolector."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    gc.collect()
    gc.disable()
    try:
        statuses, streams = _call_events(rt, api.cookie, cid, "2.4", "oserror")
        assert statuses == [200]
        assert streams == 0
    finally:
        gc.enable()


def test_sse_slot_eventually_released_when_send_fails(
    api: Api, rt: Runtime, fast_sse: None
) -> None:
    """Req. 6: con `OSError` al enviar, la plaza termina liberándose (finalizador del flujo)."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    _call_events(rt, api.cookie, cid, "2.4", "oserror")
    gc.collect()
    assert api.session.streams == 0


# --- Revisiones de calidad: tope por persona --------------------------------------------------


def test_quality_reviews_keep_only_latest_per_person(rt: Runtime) -> None:
    """PA-103: más de MAX_QUALITY_JOBS de una persona -> solo sus más recientes; las de otra no."""
    rt.auth.users["af-ficticia-2"] = (  # type: ignore[attr-defined]
        "demo-password-af2",
        User(username="af-ficticia-2", role="functional"),
    )
    other, mine = Api(rt), Api(rt)
    other.login(("af-ficticia-2", "demo-password-af2"))
    mine.login()
    other_ids = [other.post("/quality-reviews", {"issue_key": "DEMO-3"}).json()["id"]]
    limit = app_module.MAX_QUALITY_JOBS
    my_ids = [
        mine.post("/quality-reviews", {"issue_key": "DEMO-3"}).json()["id"]
        for _ in range(limit + 5)
    ]
    other_ids.append(other.post("/quality-reviews", {"issue_key": "DEMO-2"}).json()["id"])
    rows = rt.quality.rows  # type: ignore[attr-defined]  # InMemoryQualityReviewStore
    kept = [rid for rid, r in rows.items() if r.username == "af-demo"]
    assert kept == my_ids[-limit:]
    assert [rid for rid, r in rows.items() if r.username == "af-ficticia-2"] == other_ids
    assert mine.get(f"/quality-reviews/{my_ids[0]}").status_code == 404
    assert mine.get(f"/quality-reviews/{my_ids[-1]}").status_code == 200
    assert other.get(f"/quality-reviews/{other_ids[0]}").status_code == 200


# --- Retry-After, manejador genérico y logout -------------------------------------------------


@pytest.mark.parametrize(("wait", "header"), [(0.4, "1"), (1.0, "1"), (30.2, "31")])
def test_retry_after_header_is_rounded_up(
    rt: Runtime, monkeypatch: pytest.MonkeyPatch, wait: float, header: str
) -> None:
    """Req. 4 y 8: la cabecera Retry-After se redondea hacia arriba (nunca «0»)."""
    monkeypatch.setattr(rt.limiter, "retry_after", lambda *_k: wait)
    response = Api(rt).login()
    assert response.status_code == 429
    assert response.headers["retry-after"] == header
    assert _error(response)["retry_after"] == wait


def test_unexpected_error_is_500_without_reraising(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Req. 8 y 13: el 500 genérico no relanza la excepción ni registra su texto."""
    rt = fake_runtime(tmp_path, issue_tracker=ExplodingProjectsTracker())
    a = Api(rt)  # TestClient con raise_server_exceptions=True: fallaría si se relanzara
    a.login()
    response = a.get("/projects")
    assert response.status_code == 500
    assert _error(response)["message"] == UNEXPECTED
    assert response.headers["x-content-type-options"] == "nosniff"
    captured = capsys.readouterr()
    assert SECRET_TEXT not in captured.out + captured.err
    assert "RuntimeError" in captured.out + captured.err


def test_logout_expires_cookie_with_same_attributes(api: Api) -> None:
    """Req. 1: al cerrar sesión la cookie se borra con Secure, HttpOnly, SameSite y Path."""
    response = api.post("/auth/logout")
    assert response.status_code == 204
    parts = [p.strip().lower() for p in response.headers["set-cookie"].split(";")]
    assert parts[0].startswith(f"{COOKIE}=")
    for attribute in ("secure", "httponly", "samesite=strict", "path=/api", "max-age=0"):
        assert attribute in parts, parts


# --- PA-305 y PA-307 (comentario del PR de T-56) ---------------------------------------------


def test_usage_today_sums_only_todays_calls(api: Api, rt: Runtime) -> None:
    """PA-305: el anillo del carril recibe los tokens de hoy y el umbral de aviso."""
    from datetime import UTC, datetime, timedelta

    from adapters.base import TaskType
    from adapters.llm.usage import UsageRecord
    from core.usage import InMemoryUsageQueries

    now = datetime.now(UTC)
    records = [
        UsageRecord(TaskType.GENERATE_STORY, "ollama", "modelo-ficticio-a", 100, 50, 10, at=now),
        UsageRecord(
            TaskType.GENERATE_STORY,
            "ollama",
            "modelo-ficticio-a",
            900,
            900,
            10,
            at=now - timedelta(days=2),
        ),
    ]
    rt.usage = InMemoryUsageQueries(lambda: records)
    rt.token_warning = 1000
    body = api.get("/settings/usage").json()
    assert body == {"tokens_today": 150, "warning_threshold": 1000, "scope": "global"}


def test_usage_today_without_registry_is_503(api: Api, rt: Runtime) -> None:
    rt.usage = None
    response = api.get("/settings/usage")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_sse_progress_event_is_a_full_progress_step(api: Api) -> None:
    """PA-307: `data` de `progress` es un `ProgressStep` completo (con `label`)."""
    import json

    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.post(f"/conversations/{cid}/discard")
    with api.client.stream("GET", f"{API_PREFIX}/conversations/{cid}/events") as resp:
        lines = list(resp.iter_lines())
    progress = [
        json.loads(lines[i + 1].removeprefix("data: "))
        for i, line in enumerate(lines)
        if line == "event: progress"
    ]
    assert progress
    assert all(set(p) == {"node", "label", "state"} and p["label"] for p in progress)


def test_usage_today_requires_session(rt: Runtime) -> None:
    assert Api(rt).get("/settings/usage").status_code == 401


def test_usage_today_database_error_is_503(api: Api, rt: Runtime) -> None:
    from sqlalchemy.exc import OperationalError

    class Broken:
        def calls(self, *_a: object, **_k: object) -> list[object]:
            raise OperationalError("SELECT", {}, Exception("detalle-interno-ficticio"))

    rt.usage = Broken()  # type: ignore[assignment]
    response = api.get("/settings/usage")
    assert response.status_code == 503
    assert "detalle-interno-ficticio" not in response.text


# --- PA-102 y PA-104 (para el frontend) --------------------------------------------------------


def test_sources_include_the_context_budget(api: Api) -> None:
    """PA-102: la vista previa trae el presupuesto de tokens (usado frente a disponible)."""
    body = {"origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}}
    budget = api.post("/start/sources", body).json()["budget"]
    assert set(budget) == {"used", "limit", "dropped_sources", "truncated_sources"}
    assert 0 < budget["used"] <= budget["limit"]


def test_issue_card_counts_test_cases_in_jira(tmp_path: Path) -> None:
    """PA-104: la ficha indica cuántas subtareas CP tiene la HU en Jira."""
    from adapters.base import IssueSummary
    from tests.fakes.test_management import FakeTestManagement

    testmgmt = FakeTestManagement()
    testmgmt.cases["DEMO-3"] = [
        IssueSummary(key="DEMO-901", summary="[CP-01] Ficticio", issue_type="Subtarea", status="x")
    ]
    a = Api(fake_runtime(tmp_path, test_management=testmgmt))
    a.login()
    card = a.get("/issues/DEMO-3").json()
    assert card["test_cases"] == 1
    assert card["published_by_agent"] is None  # sin almacén de versiones en los fakes


def test_issue_card_test_cases_is_null_when_jira_fails(tmp_path: Path) -> None:
    """PA-104 (error): si la consulta de casos falla, `test_cases` es null y la ficha sale igual."""
    from adapters.errors import ExternalServiceError
    from tests.fakes.test_management import FakeTestManagement

    class Failing(FakeTestManagement):
        def list_cases(self, story_key: str) -> list:  # type: ignore[override]
            raise ExternalServiceError("Jira no responde (ficticio).", service="jira")

    a = Api(fake_runtime(tmp_path, test_management=Failing()))
    a.login()
    response = a.get("/issues/DEMO-3")
    assert response.status_code == 200
    assert response.json()["test_cases"] is None


def test_issue_card_published_by_agent_comes_from_the_version_store(tmp_path: Path) -> None:
    """PA-104: «Publicada por el agente» sale del almacén de versiones (tabla `artifacts`)."""

    class Versions:
        def save(self, artifact: object) -> None: ...
        def update_status(self, *_a: object, **_k: object) -> None: ...
        def published_by_agent(self, jira_key: str) -> bool:
            return jira_key == "DEMO-3"

    a = Api(fake_runtime(tmp_path, versions=Versions()))
    a.login()
    assert a.get("/issues/DEMO-3").json()["published_by_agent"] is True
    assert a.get("/issues/DEMO-4").json()["published_by_agent"] is False


def test_issue_card_published_by_agent_is_null_when_the_store_fails(tmp_path: Path) -> None:
    """PA-104 (error): si el almacén de versiones falla, `published_by_agent` es null."""
    from adapters.errors import ExternalServiceError

    class Broken:
        def save(self, artifact: object) -> None: ...
        def update_status(self, *_a: object, **_k: object) -> None: ...
        def published_by_agent(self, jira_key: str) -> bool:
            raise ExternalServiceError("Base de datos ficticia caída.", service="postgres")

    a = Api(fake_runtime(tmp_path, versions=Broken()))
    a.login()
    response = a.get("/issues/DEMO-3")
    assert response.status_code == 200
    assert response.json()["published_by_agent"] is None


def test_settings_without_jira_site_has_no_browse_url(api: Api) -> None:
    """PA-318: sin sitio de Jira configurado, `jira_browse_url` es `null`."""
    response = api.client.get(f"{API_PREFIX}/settings")
    assert response.status_code == 200, response.text
    assert response.json()["jira_browse_url"] is None


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (
            "https://villaficticia-ejemplo.atlassian.net",
            "https://villaficticia-ejemplo.atlassian.net/browse/",
        ),
        (
            "https://villaficticia-ejemplo.atlassian.net/",
            "https://villaficticia-ejemplo.atlassian.net/browse/",
        ),
        (None, None),
        ("", None),
        ("http://villaficticia-ejemplo.atlassian.net", None),
        ("javascript:alert(1)", None),
        ("https://usuario:clave@villaficticia-ejemplo.atlassian.net", None),
        ("https://villaficticia-ejemplo.atlassian.net/otra/ruta", None),
        ("https://villaficticia-ejemplo.atlassian.net/?q=1", None),
    ],
)
def test_jira_browse_url_only_accepts_a_plain_https_site(
    base_url: str | None, expected: str | None
) -> None:
    """PA-318: solo `https://<sitio>`; otro esquema, credenciales, ruta o consulta → `None`."""
    assert app_module.jira_browse_url(base_url) == expected
