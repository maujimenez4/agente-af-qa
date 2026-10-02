"""Prueba cruzada T-35 (RNF-19): el área B prueba la API (`api/`) del área A «con mirada de fuera».

Contra `docs/api/openapi.yaml`, `docs/api/requisitos-parte-2.md` (req. 1-9 y 13-14) y los
principios de CLAUDE.md (aprobación humana, secretos, datos sintéticos). Cubre los huecos que no
fijan `test_api_*.py`: cookies falsificadas o de otra sesión, CSRF fuera de la cabecera, orígenes
raros, CORS, `/docs` en producción, propiedad de conversaciones recién creadas y de las acciones
`edit`/`approve` ajenas, ninguna ruta escribe en Jira salvo `approve`, límites de tamaño, cabeceras
de seguridad en las respuestas de error, logs sin cookie ni token y el SSE (formato, `: ping`,
caducidad, eventos de error).

Solo fakes de `tests/fakes/` y el `TestClient` de FastAPI; datos 100 % ficticios (DEMO-xxx,
`*.example`). Las operaciones largas terminan antes de responder (`run_inline`). Los defectos
confirmados van con `xfail(strict=True)`; el resto fija el comportamiento actual.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from adapters.base import IssueSummary
from api import app as app_module
from api import service
from api.app import API_PREFIX, create_app
from api.errors import UNEXPECTED
from api.runtime import Run, Runtime
from api.security import COOKIE
from tests.fakes.api import api_settings, fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.test_management import FakeTestManagement
from tests.unit.test_api_app import ADMIN, AF, EVOLVE, QA, SECRET_TEXT, Api

ALLOWED = "https://frontal-ficticio.example"
FOREIGN = "https://sitio-ajeno-ficticio.example"
NOT_YOURS = "No existe esa conversación o no es tuya."
SSE_EVENTS = {"progress", "review_ready", "result", "error"}
STORY = "DEMO-3"
CASES = [
    IssueSummary(
        key="DEMO-601", summary="[CP-01] Caso ficticio", issue_type="Subtarea", status="Por hacer"
    ),
]


# --- utilidades --------------------------------------------------------------------------


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path)


@pytest.fixture
def api(rt: Runtime) -> Api:
    a = Api(rt)
    assert a.login().status_code == 200
    return a


@pytest.fixture
def live_rt(tmp_path: Path) -> Runtime:
    runtime = fake_runtime(tmp_path, publish_mode="live")
    _tm(runtime).cases[STORY] = list(CASES)
    return runtime


@pytest.fixture
def fast_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "SSE_POLL_S", 0.02)


def _tracker(rt: Runtime) -> FakeIssueTracker:
    tracker = rt.workspace_factory().container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    return tracker


def _tm(rt: Runtime) -> FakeTestManagement:
    tm = rt.workspace_factory().container.test_management
    assert isinstance(tm, FakeTestManagement)
    return tm


def _nothing_written(rt: Runtime) -> None:
    assert _tracker(rt).writes == []
    assert _tm(rt).publish_calls == 0
    assert _tm(rt).executions == []


def _error(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "retry_after"}, body
    return body["error"]


def _client(rt: Runtime, cookie: str | None = None) -> TestClient:
    client = TestClient(create_app(runtime_instance=rt), base_url="https://testserver")
    if cookie is not None:
        client.headers["Cookie"] = f"{COOKIE}={cookie}"
    return client


def _blocks(text: str) -> list[str]:
    return [b for b in text.split("\n\n") if b]


def _events(text: str) -> list[tuple[str, Any]]:
    """(evento, data JSON) de un texto SSE; se saltan los comentarios."""
    out: list[tuple[str, Any]] = []
    for block in _blocks(text):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        if not lines:
            continue
        fields = dict(line.split(": ", 1) for line in lines)
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def _stream(api: Api, rt: Runtime, cid: str, *actions: tuple[float, Any]) -> Any:
    """Abre el SSE; lanza `actions` (retardo, función) y siempre corta a los 10 s."""
    session = api.session
    timers = [threading.Timer(delay, fn) for delay, fn in actions]
    timers.append(threading.Timer(10.0, lambda: rt.sessions.drop(session.id)))
    for t in timers:
        t.start()
    try:
        return api.get(f"/conversations/{cid}/events")
    finally:
        for t in timers:
            t.cancel()


# --- Req. 1: sesión caducada o falsificada -------------------------------------------------------


@pytest.mark.parametrize(
    "cookie",
    ["", "x", "0" * 43, "cookie-ficticia-falsificada", "a" * 4096, "../../etc", "nulo%00ficticio"],
    ids=["vacia", "corta", "ceros", "inventada", "enorme", "ruta", "nulo"],
)
def test_forged_session_cookie_is_401_in_common_shape(api: Api, rt: Runtime, cookie: str) -> None:
    """Req. 1: una cookie que el servidor no emitió da 401 `unauthenticated`, sin crear sesión."""
    before = set(rt.sessions._sessions)
    response = _client(rt, cookie).get(f"{API_PREFIX}/conversations")
    assert response.status_code == 401
    assert _error(response) == {
        "code": "unauthenticated",
        "message": "Inicia sesión para continuar.",
        "retry_after": None,
    }
    assert "set-cookie" not in response.headers
    assert set(rt.sessions._sessions) == before


def test_csrf_token_used_as_session_cookie_is_401(api: Api, rt: Runtime) -> None:
    """Req. 1: el token anti-CSRF (visible para el frontend) no sirve como identificador."""
    response = _client(rt, api.csrf).get(f"{API_PREFIX}/auth/me")
    assert response.status_code == 401


def test_cookie_in_header_other_than_cookie_is_ignored(api: Api, rt: Runtime) -> None:
    """Req. 1: la sesión solo viaja en la cookie (no en `Authorization` ni en la query)."""
    client = _client(rt)
    for response in (
        client.get(f"{API_PREFIX}/auth/me", headers={"Authorization": f"Bearer {api.cookie}"}),
        client.get(f"{API_PREFIX}/auth/me", params={COOKIE: api.cookie}),
    ):
        assert response.status_code == 401


def test_expired_session_cannot_change_state_even_with_its_csrf(tmp_path: Path) -> None:
    """Req. 1 y 2: con la sesión caducada, cookie + token válidos ya no permiten un POST."""
    rt = fake_runtime(tmp_path)
    now = [0.0]
    rt.sessions._clock = lambda: now[0]
    a = Api(rt)
    a.login()
    now[0] += rt.settings.api_session_idle_minutes * 60 + 1
    response = a.post("/projects/choose", {"project": "DEMO"})
    assert response.status_code == 401
    assert _error(response)["code"] == "unauthenticated"


def test_logout_without_session_is_401(rt: Runtime) -> None:
    """Req. 1: cerrar sesión sin cookie da 401 (no 204 ni 500)."""
    response = Api(rt).post("/auth/logout")
    assert response.status_code == 401
    assert _error(response)["code"] == "unauthenticated"


def test_old_csrf_token_is_rejected_after_login_rotation(api: Api) -> None:
    """Req. 1 y 2: al volver a iniciar sesión, el token anti-CSRF anterior deja de valer."""
    old_csrf = api.csrf
    api.login()
    assert api.csrf != old_csrf
    api_old = api.client.post(
        f"{API_PREFIX}/projects/choose",
        json={"project": "DEMO"},
        headers={"X-CSRF-Token": old_csrf},
    )
    assert api_old.status_code == 403
    assert api.post("/projects/choose", {"project": "DEMO"}).status_code == 200


def test_unauthenticated_request_is_401_before_body_validation(rt: Runtime) -> None:
    """Req. 1 y contrato (401 «Sin sesión o caducada»): sin cookie no se valida ni procesa nada."""
    client = _client(rt)
    for path, body in (
        ("/projects/choose", {"project": "no válido!"}),
        ("/conversations", {"flow": "desconocido"}),
        ("/executions", {"story_key": "sin-formato"}),
    ):
        response = client.post(f"{API_PREFIX}{path}", json=body)
        assert response.status_code == 401, (path, response.status_code)


# --- Req. 2: CSRF y origen -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["", " ", "upper", "trailing-space", "prefix"],
    ids=["vacio", "espacio", "mayusculas", "espacio-final", "prefijo"],
)
def test_csrf_header_variants_are_403(api: Api, variant: str) -> None:
    """Req. 2: solo el token exacto de la sesión vale (comparación estricta)."""
    token = {
        "": "",
        " ": " ",
        "upper": api.csrf.upper() if api.csrf.upper() != api.csrf else api.csrf + "X",
        "trailing-space": api.csrf + " ",
        "prefix": api.csrf[:-1],
    }[variant]
    response = api.client.post(
        f"{API_PREFIX}/projects/choose", json={"project": "DEMO"}, headers={"X-CSRF-Token": token}
    )
    assert response.status_code == 403
    assert _error(response)["code"] == "forbidden"


def test_csrf_token_in_query_or_body_is_not_accepted(api: Api) -> None:
    """Req. 2: el token solo vale en la cabecera `X-CSRF-Token`."""
    in_query = api.client.post(
        f"{API_PREFIX}/projects/choose", json={"project": "DEMO"}, params={"csrf_token": api.csrf}
    )
    in_body = api.client.post(
        f"{API_PREFIX}/projects/choose", json={"project": "DEMO", "csrf_token": api.csrf}
    )
    assert in_query.status_code == in_body.status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "http://testserver",
        "https://testserver.sitio-ajeno-ficticio.example",
        "https://testserver:8443",
        "no-es-una-url",
    ],
    ids=["null", "otro-esquema", "subdominio-ajeno", "otro-puerto", "basura"],
)
def test_unusual_origins_are_403_even_with_valid_csrf(api: Api, rt: Runtime, origin: str) -> None:
    """Req. 2: `Origin` que no es exactamente el mismo origen ni de la lista -> 403, sin efecto."""
    response = api.client.post(
        f"{API_PREFIX}/conversations",
        json=EVOLVE,
        headers={"X-CSRF-Token": api.csrf, "Origin": origin},
    )
    assert response.status_code == 403
    assert _error(response)["message"] == "La petición no viene de un origen permitido."
    assert api.get("/conversations").json() == []


def test_foreign_origin_on_approve_is_403_and_writes_nothing(live_rt: Runtime) -> None:
    """Req. 2 y principio 1: un `approve` desde otro sitio no publica aunque lleve la huella."""
    a = Api(live_rt)
    a.login()
    conv = a.post("/conversations", EVOLVE).json()
    response = a.client.post(
        f"{API_PREFIX}/conversations/{conv['id']}/approve",
        json={"fingerprint": conv["review"]["fingerprint"]},
        headers={"X-CSRF-Token": a.csrf, "Origin": FOREIGN},
    )
    assert response.status_code == 403
    assert a.get(f"/conversations/{conv['id']}").json()["state"] == "in_review"
    _nothing_written(live_rt)


def test_approve_without_csrf_is_403_and_writes_nothing(live_rt: Runtime) -> None:
    """Req. 2 y principio 1: sin token anti-CSRF no se reanuda el grafo ni se publica."""
    a = Api(live_rt)
    a.login()
    conv = a.post("/conversations", EVOLVE).json()
    response = a.post(
        f"/conversations/{conv['id']}/approve",
        {"fingerprint": conv["review"]["fingerprint"]},
        csrf=False,
    )
    assert response.status_code == 403
    assert a.get(f"/conversations/{conv['id']}").json()["state"] == "in_review"
    _nothing_written(live_rt)


def test_iterate_without_csrf_is_403_even_with_blank_feedback(api: Api) -> None:
    """Req. 2: en todo POST el CSRF se comprueba antes que el contenido."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    response = api.post(f"/conversations/{cid}/iterate", {"feedback": "   "}, csrf=False)
    assert response.status_code == 403


def test_iterate_blank_feedback_with_csrf_is_422_in_spanish(api: Api) -> None:
    """Req. 8: con sesión y token, un feedback en blanco da 422 con el mensaje en español."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    response = api.post(f"/conversations/{cid}/iterate", {"feedback": "   "})
    assert response.status_code == 422
    assert _error(response)["message"] == "Escribe qué quieres cambiar de la propuesta."


# --- Req. 3 y 14: CORS y documentación -----------------------------------------------------------


@pytest.mark.parametrize("value", ["*", "https://*.ficticio.example", "frontal-ficticio.example"])
def test_wildcard_or_bare_origins_are_rejected_by_config(value: str) -> None:
    """Req. 3: nunca `*` con credenciales; solo orígenes `http(s)://host[:puerto]`."""
    with pytest.raises(ValidationError):
        api_settings(api_allowed_origins=value)


@pytest.fixture
def cors_client(tmp_path: Path) -> TestClient:
    rt = fake_runtime(tmp_path, settings=api_settings(api_allowed_origins=ALLOWED))
    return _client(rt)


def _preflight(client: TestClient, origin: str, headers: str = "content-type,x-csrf-token") -> Any:
    return client.options(
        f"{API_PREFIX}/projects/choose",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": headers,
        },
    )


def test_cors_preflight_from_allowed_origin_allows_credentials(cors_client: TestClient) -> None:
    """Req. 3: el origen de la lista recibe su propio origen (no `*`) y credenciales."""
    response = _preflight(cors_client, ALLOWED)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_preflight_from_foreign_origin_gets_no_allow_origin(cors_client: TestClient) -> None:
    """Req. 3: un origen fuera de la lista no recibe `Access-Control-Allow-Origin`."""
    response = _preflight(cors_client, FOREIGN)
    assert response.status_code >= 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_rejects_headers_outside_the_list(cors_client: TestClient) -> None:
    """Req. 3: `allow_headers` solo `Content-Type` y `X-CSRF-Token` (no `Authorization`)."""
    response = _preflight(cors_client, ALLOWED, headers="authorization")
    assert response.status_code == 400


def test_cors_simple_get_from_foreign_origin_has_no_allow_origin(cors_client: TestClient) -> None:
    """Req. 3: una lectura desde otro sitio no se le expone al navegador."""
    response = cors_client.get(f"{API_PREFIX}/auth/me", headers={"Origin": FOREIGN})
    assert "access-control-allow-origin" not in response.headers


def test_without_allowed_origins_there_is_no_cors(api: Api) -> None:
    """Req. 3: sin lista, solo el mismo origen: ninguna respuesta lleva cabeceras CORS."""
    response = api.client.get(f"{API_PREFIX}/auth/me", headers={"Origin": FOREIGN})
    assert response.status_code == 200
    assert not [h for h in response.headers if h.startswith("access-control-")]


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json", "/docs", "/openapi.json"])
def test_docs_and_openapi_are_disabled_in_production(tmp_path: Path, path: str) -> None:
    """Req. 14: `/docs` y `/openapi.json` desactivados fuera de desarrollo (404 en forma común)."""
    settings = api_settings(app_env="production")
    client = _client(fake_runtime(tmp_path, settings=settings))
    response = client.get(path)
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


def test_docs_are_available_in_development(rt: Runtime) -> None:
    """Req. 14 (positivo): en desarrollo sí se sirven la documentación y el esquema."""
    client = _client(rt)
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


# --- Req. 5: propiedad entre usuarios ------------------------------------------------------------


def test_list_conversations_only_returns_own(rt: Runtime) -> None:
    """Req. 5: el listado solo trae las conversaciones de la persona."""
    owner, other = Api(rt), Api(rt)
    owner.login()
    other.login(QA)
    cid = owner.post("/conversations", EVOLVE).json()["id"]
    assert [c["thread_id"] for c in owner.get("/conversations").json()] == [cid]
    assert other.get("/conversations").json() == []


def test_admin_cannot_read_or_act_on_others_conversation(rt: Runtime) -> None:
    """Req. 5: el admin tampoco ve conversaciones ajenas (404 idéntico)."""
    owner, admin = Api(rt), Api(rt)
    owner.login()
    admin.login(ADMIN)
    cid = owner.post("/conversations", EVOLVE).json()["id"]
    missing = admin.get(f"/conversations/{uuid4()}")
    for response in (
        admin.get(f"/conversations/{cid}"),
        admin.get(f"/conversations/{cid}/events"),
        admin.post(f"/conversations/{cid}/discard"),
    ):
        assert response.status_code == 404
        assert response.json() == missing.json()


def test_foreign_edit_and_approve_are_404_and_write_nothing(live_rt: Runtime) -> None:
    """Req. 5 y 9: ni editar ni aprobar una conversación ajena, aunque se conozca la huella."""
    owner, other = Api(live_rt), Api(live_rt)
    owner.login()
    other.login(AF)  # otra sesión con el mismo rol...
    other.session.user = other.session.user.model_copy(update={"username": "af-otra-ficticia"})
    conv = owner.post("/conversations", EVOLVE).json()
    cid, review = conv["id"], conv["review"]
    content = review["artifact"]["content"] | {"title": "Título ajeno (ficticio)"}
    missing = other.get(f"/conversations/{uuid4()}").json()
    edited = other.post(
        f"/conversations/{cid}/edit", {"content": content, "fingerprint": review["fingerprint"]}
    )
    approved = other.post(f"/conversations/{cid}/approve", {"fingerprint": review["fingerprint"]})
    assert edited.status_code == approved.status_code == 404
    assert edited.json() == approved.json() == missing
    after = owner.get(f"/conversations/{cid}").json()
    assert after["state"] == "in_review" and after["review"]["version"] == 1
    _nothing_written(live_rt)


def test_conversation_being_created_is_not_visible_to_others(api: Api, rt: Runtime) -> None:
    """Req. 5 y 6: recién creada (sin fila en la lista aún), solo la ve su dueña."""
    cid = str(uuid4())
    rt.runs.add(
        Run(
            thread_id=cid,
            owner="af-demo",
            flow="evolve",
            mode="functional",
            project="DEMO",
            title="Evolucionar DEMO-3 (ficticia)",
            running=True,
            operation="start",
        )
    )
    other = Api(rt)
    other.login(QA)
    missing = other.get(f"/conversations/{uuid4()}")
    for response in (other.get(f"/conversations/{cid}"), other.get(f"/conversations/{cid}/events")):
        assert response.status_code == 404
        assert response.json() == missing.json()
    assert other.session.streams == 0
    mine = api.get(f"/conversations/{cid}")
    assert mine.status_code == 200 and mine.json()["state"] == "generating"


def test_execution_threads_do_not_appear_in_conversation_list(live_rt: Runtime) -> None:
    """Req. 5: un registro de ejecución no se cuela como conversación de la persona."""
    qa = Api(live_rt)
    qa.login(QA)
    created = qa.post("/executions", {"story_key": STORY})
    assert created.status_code == 200, created.text
    listed = [c["thread_id"] for c in qa.get("/conversations").json()]
    assert created.json()["id"] not in listed


# --- IDs con formato inválido --------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/conversations/{bad}",
        "/conversations/{bad}/events",
        "/quality-reviews/{bad}",
        "/executions/{bad}",
    ],
)
@pytest.mark.parametrize(
    "bad",
    [
        str(uuid4()).upper(),
        "1234",
        "00000000-0000-0000-0000-00000000000g",
        "valor-ficticio-<script>",
        "x" * 300,
    ],
    ids=["mayusculas", "corto", "no-hex", "script", "largo"],
)
def test_invalid_ids_are_422_without_echoing_them(api: Api, path: str, bad: str) -> None:
    """Contrato (`pattern` de los IDs) y req. 8: 422 `invalid_request` sin devolver lo enviado."""
    response = api.get(path.format(bad=bad))
    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "invalid_request"
    assert bad not in response.text


@pytest.mark.parametrize("op", ["iterate", "edit", "approve", "discard", "handoff"])
def test_post_with_invalid_conversation_id_changes_nothing(api: Api, rt: Runtime, op: str) -> None:
    """Contrato: un ID con formato inválido en una acción da 422 y no toca nada."""
    response = api.post(f"/conversations/NO-ES-UN-UUID/{op}", {})
    assert response.status_code == 422
    assert _error(response)["code"] == "invalid_request"
    _nothing_written(rt)


# --- Req. 7: tamaño y validación del contenido ---------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body", "ok"),
    [
        ("/start/propose", {"text": "x" * 4000, "project": "DEMO"}, True),
        ("/start/propose", {"text": "x" * 4001, "project": "DEMO"}, False),
        ("/projects/choose", {"project": "D" * 50}, None),
        ("/projects/choose", {"project": "D" * 51}, False),
        ("/conversations", EVOLVE | {"feedback": ["f"] * 30}, True),
        ("/conversations", EVOLVE | {"feedback": ["f"] * 31}, False),
        ("/conversations", EVOLVE | {"feedback": ["f" * 1001]}, False),
        ("/conversations", EVOLVE | {"excluded_sources": ["doc-x"] * 51}, False),
    ],
    ids=[
        "propose-4000",
        "propose-4001",
        "proj-50",
        "proj-51",
        "fb-30",
        "fb-31",
        "fb-1001",
        "excl-51",
    ],
)
def test_field_limits_of_the_contract(api: Api, path: str, body: Any, ok: bool | None) -> None:
    """Contrato (`maxLength`/`maxItems`): en el límite pasa; uno más es 422 sin eco."""
    response = api.post(path, body)
    if ok is False:
        assert response.status_code == 422, response.text
        assert _error(response)["code"] == "invalid_request"
        assert "x" * 4001 not in response.text
    elif ok is True:
        assert response.status_code in (200, 202), response.text
    else:  # válido por formato: puede ser 404 si el proyecto no existe, nunca 422
        assert response.status_code != 422


@pytest.mark.parametrize(("size", "status"), [(4000, 202), (4001, 422)])
def test_iterate_feedback_limit(api: Api, size: int, status: int) -> None:
    """Contrato `IterateIn.feedback` (máx. 4000): el límite exacto pasa, uno más no."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    response = api.post(f"/conversations/{cid}/iterate", {"feedback": "c" * size})
    assert response.status_code == status, response.text


@pytest.mark.parametrize(("size", "status"), [(64, 401), (65, 422)])
def test_login_username_limit(rt: Runtime, size: int, status: int) -> None:
    """Contrato `LoginIn.username` (máx. 64): 401 en el límite, 422 por encima, sin eco."""
    name = "u" * size
    response = Api(rt).login((name, "clave-ficticia"))
    assert response.status_code == status
    assert name not in response.text


def test_edit_with_content_of_other_artifact_type_keeps_review(api: Api, rt: Runtime) -> None:
    """Req. 7: `EditIn.content` se valida con el modelo del artefacto en revisión (HU, no suite)."""
    conv = api.post("/conversations", EVOLVE).json()
    review = conv["review"]
    suite = {
        "story_key": STORY,
        "strategy": "Estrategia ficticia.",
        "cases": [],
    }
    response = api.post(
        f"/conversations/{conv['id']}/edit",
        {"content": suite, "fingerprint": review["fingerprint"]},
    )
    assert response.status_code in (200, 422), response.text
    after = api.get(f"/conversations/{conv['id']}").json()
    assert after["state"] == "in_review"
    assert after["review"]["artifact"]["type"] == review["artifact"]["type"]
    assert after["review"]["artifact"]["content"] == review["artifact"]["content"]
    _nothing_written(rt)


def test_edit_with_stale_fingerprint_does_not_create_a_version(api: Api) -> None:
    """Req. 7 y principio 1: la edición exige la huella del payload mostrado."""
    conv = api.post("/conversations", EVOLVE).json()
    review = conv["review"]
    content = review["artifact"]["content"] | {"title": "Título editado (ficticio)"}
    response = api.post(
        f"/conversations/{conv['id']}/edit", {"content": content, "fingerprint": "0" * 64}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "in_review"
    assert body["review"]["artifact"]["content"]["title"] != "Título editado (ficticio)"
    assert body["review"]["error"]


# --- Req. 9 y principio 1: ninguna ruta escribe en Jira salvo `approve` --------------------------


def test_no_route_other_than_approve_writes_to_jira_in_live_mode(live_rt: Runtime) -> None:
    """Req. 9: en `live`, todas las rutas de lectura, edición y ajustes no escriben en Jira."""
    a, qa = Api(live_rt), Api(live_rt)
    a.login()
    qa.login(QA)
    reads = [
        a.get("/projects"),
        a.get("/projects/DEMO/epics"),
        a.get("/projects/DEMO/search", params={"q": "renovación"}),
        a.get("/epics/DEMO-1/stories"),
        a.get(f"/issues/{STORY}"),
        a.get("/settings"),
        a.get("/conversations"),
        a.get("/auth/me"),
    ]
    assert all(r.status_code == 200 for r in reads), [r.status_code for r in reads]
    writes_ui = [
        a.post("/projects/choose", {"project": "DEMO"}),
        a.post("/start/propose", {"text": "Renovación ficticia DEMO-3", "project": "DEMO"}),
        a.post("/start/sources", {"origin": {"kind": "story", "key": STORY, "project": "DEMO"}}),
        a.put(
            "/settings/models/generate_story",
            {"provider": "ollama", "model": "modelo-ficticio-b"},
        ),
        a.delete("/settings/models/generate_story"),
        a.post("/quality-reviews", {"issue_key": STORY}),
    ]
    assert all(r.status_code in (200, 202) for r in writes_ui), [
        (r.request.url.path, r.status_code) for r in writes_ui
    ]
    conv = a.post("/conversations", EVOLVE).json()
    wrong = a.post(f"/conversations/{conv['id']}/approve", {"fingerprint": "f" * 64})
    assert wrong.status_code == 202 and wrong.json()["state"] == "in_review"
    session = a.session
    sse = _stream(a, live_rt, conv["id"], (0.3, lambda: live_rt.sessions.drop(session.id)))
    assert sse.status_code == 200
    a.login()
    eid = qa.post("/executions", {"story_key": STORY}).json()["id"]
    results = {"results": [{"case_key": "DEMO-601", "status": "paso"}], "environment": "ficticio"}
    assert qa.put(f"/executions/{eid}/results", results).status_code == 200
    wrong_exec = qa.post(f"/executions/{eid}/approve", {"fingerprint": "e" * 64})
    assert wrong_exec.status_code == 200 and wrong_exec.json()["state"] == "in_review"
    assert qa.post(f"/executions/{eid}/discard").json()["state"] == "discarded"
    _nothing_written(live_rt)


# --- Req. 8 y 14: errores y cabeceras ------------------------------------------------------------


def _assert_security_headers(response: Any) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_security_headers_also_on_error_responses(api: Api, rt: Runtime) -> None:
    """Req. 14: las cabeceras de seguridad van también en 401, 403, 404, 405, 413 y 422."""
    responses = [
        _client(rt).get(f"{API_PREFIX}/conversations"),  # 401
        api.post("/projects/choose", {"project": "DEMO"}, csrf=False),  # 403
        api.get("/ruta-ficticia-inexistente"),  # 404
        api.client.patch(f"{API_PREFIX}/settings", headers={"X-CSRF-Token": api.csrf}),  # 405
        api.post("/start/propose", {"text": "x" * 300_000, "project": "DEMO"}),  # 413
        api.post("/projects/choose", {"project": "!"}),  # 422
    ]
    assert [r.status_code for r in responses] == [401, 403, 404, 405, 413, 422]
    for response in responses:
        _assert_security_headers(response)
        assert response.headers["content-type"].startswith("application/json")
        _error(response)


def test_non_json_body_is_422_in_spanish(api: Api) -> None:
    """Req. 8: un cuerpo que no es JSON da 422 en la forma común y en español."""
    response = api.client.post(
        f"{API_PREFIX}/projects/choose",
        content=b"{no es json",
        headers={"X-CSRF-Token": api.csrf, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert _error(response)["message"] == "El cuerpo de la petición no es un JSON válido."


def test_session_cookie_and_csrf_never_logged(
    api: Api, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Req. 13: nunca `Cookie` ni `X-CSRF-Token` en los logs, tampoco en errores."""
    caplog.set_level(logging.DEBUG)
    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.post(f"/conversations/{cid}/iterate", {"feedback": "Cambio ficticio."})
    api.post("/projects/choose", {"project": "!"})
    api.client.post(
        f"{API_PREFIX}/projects/choose", json={"project": "DEMO"}, headers={"X-CSRF-Token": "malo"}
    )
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text
    assert api.cookie not in logs
    assert api.csrf not in logs


# --- Req. 6: SSE ---------------------------------------------------------------------------------


def test_sse_blocks_are_well_formed(api: Api, rt: Runtime, fast_sse: None) -> None:
    """Req. 6: cada bloque es `event: <nombre>` + `data: <JSON en una línea>` + línea vacía."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.post(f"/conversations/{cid}/discard")
    response = _stream(api, rt, cid)  # corte de 10 s aunque el flujo no se cierre
    assert response.status_code == 200
    assert response.text.endswith("\n\n")
    for block in _blocks(response.text):
        lines = block.splitlines()
        if lines[0].startswith(":"):
            continue
        assert len(lines) == 2, block
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        assert lines[0].removeprefix("event: ") in SSE_EVENTS
        json.loads(lines[1].removeprefix("data: "))
    names = [name for name, _ in _events(response.text)]
    assert names.count("result") == 1 and names[-1] == "result"


def test_sse_response_has_security_headers_and_no_cache(
    api: Api, rt: Runtime, fast_sse: None
) -> None:
    """Req. 6 y 14: el flujo lleva `text/event-stream`, `no-store` y las cabeceras de seguridad."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.post(f"/conversations/{cid}/discard")
    response = _stream(api, rt, cid)  # corte de 10 s aunque el flujo no se cierre
    assert response.headers["content-type"].startswith("text/event-stream")
    _assert_security_headers(response)


def test_sse_result_carries_only_the_requested_conversation(rt: Runtime, fast_sse: None) -> None:
    """Req. 6: los eventos de mi flujo solo traen mi conversación, nunca la de otra persona."""
    owner, other = Api(rt), Api(rt)
    owner.login()
    other.login(QA)
    mine = owner.post("/conversations", EVOLVE).json()["id"]
    other_body = {"flow": "tests", "origin": {"kind": "story", "key": STORY, "project": "DEMO"}}
    theirs = other.post("/conversations", other_body).json()["id"]
    owner.post(f"/conversations/{mine}/discard")
    response = _stream(owner, rt, mine)  # corte de 10 s aunque el flujo no se cierre
    assert theirs not in response.text
    finals = [data for name, data in _events(response.text) if name != "progress"]
    assert finals and all(d["id"] == mine for d in finals)


def test_sse_foreign_404_is_identical_to_missing(rt: Runtime) -> None:
    """Req. 5 y 6: el 404 del SSE ajeno es el mismo que el de uno inexistente."""
    owner, other = Api(rt), Api(rt)
    owner.login()
    other.login(QA)
    cid = owner.post("/conversations", EVOLVE).json()["id"]
    foreign = other.get(f"/conversations/{cid}/events")
    missing = other.get(f"/conversations/{uuid4()}/events")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert _error(foreign)["message"] == NOT_YOURS


def test_sse_sends_ping_heartbeat_while_waiting(
    api: Api, rt: Runtime, fast_sse: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req. 6: heartbeat `: ping` mientras no hay cambios (se acorta a 0,1 s en la prueba)."""
    monkeypatch.setattr(app_module, "SSE_HEARTBEAT_S", 0.1)
    cid = api.post("/conversations", EVOLVE).json()["id"]
    session = api.session
    response = _stream(api, rt, cid, (0.5, lambda: rt.sessions.drop(session.id)))
    assert ": ping\n\n" in response.text
    assert session.streams == 0


def test_sse_closes_when_session_expires_by_inactivity(
    api: Api, rt: Runtime, fast_sse: None
) -> None:
    """Req. 6: el flujo se cierra al caducar la sesión por inactividad (no solo al cerrarla)."""
    now = [0.0]
    rt.sessions._clock = lambda: now[0]
    api.login()
    cid = api.post("/conversations", EVOLVE).json()["id"]
    session = api.session
    idle = rt.settings.api_session_idle_minutes * 60

    def expire() -> None:
        now[0] += idle + 1

    response = _stream(api, rt, cid, (0.3, expire))
    names = [name for name, _ in _events(response.text)]
    assert names[-1] == "review_ready" and "result" not in names
    assert session.streams == 0
    assert api.get("/auth/me").status_code == 401


def _flaky_conversation_out(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """La primera lectura (propiedad, antes de abrir) va bien; las siguientes fallan con `exc`."""
    real = service.conversation_out
    calls = [0]

    def flaky(*args: Any) -> Any:
        calls[0] += 1
        if calls[0] == 1:
            return real(*args)
        raise exc

    monkeypatch.setattr(service, "conversation_out", flaky)


def _stream_with_mid_error(
    api: Api, rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, list[tuple[str, Any]], str]:
    cid = api.post("/conversations", EVOLVE).json()["id"]
    run = rt.runs.get(cid)
    assert run is not None
    _flaky_conversation_out(monkeypatch, RuntimeError(SECRET_TEXT))
    response = _stream(api, rt, cid, (0.3, lambda: rt.runs.finish(run)))
    return cid, _events(response.text), response.text


def test_sse_error_event_mid_stream_has_no_internal_details(
    api: Api, rt: Runtime, fast_sse: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req. 6 y 8: un fallo con el flujo abierto da un evento `error` sin trazas y lo cierra."""
    _cid, events, text = _stream_with_mid_error(api, rt, monkeypatch)
    assert events[-1][0] == "error"
    assert SECRET_TEXT not in text and "Traceback" not in text
    assert UNEXPECTED in text
    assert api.session.streams == 0


def test_sse_error_event_data_is_the_full_conversation_as_in_the_contract(
    api: Api, rt: Runtime, fast_sse: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contrato de `/events`: `error` (`data`: la conversación completa, como en `GET`)."""
    cid, events, _text = _stream_with_mid_error(api, rt, monkeypatch)
    name, data = events[-1]
    assert name == "error"
    assert data.get("id") == cid and data.get("state") == "error"


def test_sse_get_has_no_effect_on_the_conversation(api: Api, rt: Runtime, fast_sse: None) -> None:
    """Req. 2 (ningún GET tiene efectos): abrir el SSE no cambia la conversación."""
    cid = api.post("/conversations", EVOLVE).json()["id"]
    api.post(f"/conversations/{cid}/discard")
    before = api.get(f"/conversations/{cid}").json()
    _stream(api, rt, cid)  # corte de 10 s aunque el flujo no se cierre
    after = api.get(f"/conversations/{cid}").json()
    assert after == before


def test_sse_slot_not_reserved_on_404(rt: Runtime) -> None:
    """Req. 6: un 404 no consume plaza: tras muchos intentos ajenos la persona sigue pudiendo."""
    other = Api(rt)
    other.login(QA)
    for _ in range(rt.settings.api_max_streams_per_user + 2):
        assert other.get(f"/conversations/{uuid4()}/events").status_code == 404
    assert other.session.streams == 0


# --- /executions: bordes que no fijan sus pruebas ------------------------------------------------


def test_execution_create_requires_session_before_reading_jira(live_rt: Runtime) -> None:
    """Req. 1 y 9: sin sesión no se lee ni se escribe nada en Jira desde `/executions`."""
    response = _client(live_rt).post(f"{API_PREFIX}/executions", json={"story_key": STORY})
    assert response.status_code == 401
    _nothing_written(live_rt)


def test_execution_approve_from_foreign_origin_is_403_and_records_nothing(
    live_rt: Runtime,
) -> None:
    """Req. 2 y principio 1: aprobar el recibo desde otro sitio no registra en Jira."""
    qa = Api(live_rt)
    qa.login(QA)
    eid = qa.post("/executions", {"story_key": STORY}).json()["id"]
    saved = qa.put(
        f"/executions/{eid}/results",
        {"results": [{"case_key": "DEMO-601", "status": "paso"}], "environment": "ficticio"},
    ).json()
    response = qa.client.post(
        f"{API_PREFIX}/executions/{eid}/approve",
        json={"fingerprint": saved["fingerprint"]},
        headers={"X-CSRF-Token": qa.csrf, "Origin": FOREIGN},
    )
    assert response.status_code == 403
    assert qa.get(f"/executions/{eid}").json()["state"] == "in_review"
    _nothing_written(live_rt)


def test_execution_results_above_200_is_422(live_rt: Runtime) -> None:
    """Contrato `ExecutionResultsIn.results` (máx. 200): uno más es 422 sin tocar el registro."""
    qa = Api(live_rt)
    qa.login(QA)
    eid = qa.post("/executions", {"story_key": STORY}).json()["id"]
    many = [{"case_key": f"DEMO-{700 + i}", "status": "paso"} for i in range(201)]
    response = qa.put(f"/executions/{eid}/results", {"results": many})
    assert response.status_code == 422
    assert qa.get(f"/executions/{eid}").json()["results"] == []
