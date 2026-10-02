"""Contrato de la API para el frontend (T-55, parte 1)."""

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.app import API_PREFIX, create_app
from api.export_openapi import OPENAPI_PATH, openapi_document, render
from tests.fakes import dataset
from tests.fakes.api import fake_runtime

DOC = openapi_document()
OPERATIONS = [
    (path, method, op)
    for path, item in DOC["paths"].items()
    for method, op in item.items()
    if method in {"get", "post", "put", "delete"}
]


def test_published_contract_matches_the_code() -> None:
    """`docs/api/openapi.yaml` se regenera desde `api/`: si no coincide, falta exportarlo."""
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render(), (
        "Contrato desfasado: ejecuta `uv run python -m api.export_openapi`."
    )


def test_every_route_lives_under_the_versioned_prefix() -> None:
    assert all(path.startswith(API_PREFIX + "/") for path, _m, _op in OPERATIONS)
    assert len(OPERATIONS) >= 25


def test_session_is_cookie_plus_csrf_header() -> None:
    schemes = DOC["components"]["securitySchemes"]
    assert schemes["sessionCookie"] == {"type": "apiKey", "in": "cookie", "name": "afqa_session"}
    assert schemes["csrfHeader"]["name"] == "X-CSRF-Token"
    assert DOC["security"] == [{"sessionCookie": [], "csrfHeader": []}]


@pytest.mark.parametrize(("path", "method", "op"), OPERATIONS, ids=lambda v: str(v)[:40])
def test_success_responses_carry_an_example_for_the_mock(
    path: str, method: str, op: dict[str, Any]
) -> None:
    """La API simulada (Prism) responde con estos ejemplos: toda respuesta con cuerpo lleva uno."""
    for code, response in op["responses"].items():
        for media in (response.get("content") or {}).values():
            if code.startswith("2") and code != "204":
                assert "example" in media or "examples" in media, (method, path, code)


@pytest.mark.parametrize(("path", "method", "op"), OPERATIONS, ids=lambda v: str(v)[:40])
def test_error_responses_use_the_common_shape(path: str, method: str, op: dict[str, Any]) -> None:
    for code, response in op["responses"].items():
        if code.startswith(("4", "5")):
            schema = response["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (path, code)


def test_long_operations_answer_202() -> None:
    """Generar, iterar, aprobar y revisar la calidad son asíncronas (decisión del usuario)."""
    long_ops = {
        (f"{API_PREFIX}/conversations", "post"),
        (f"{API_PREFIX}/conversations/{{conversation_id}}/iterate", "post"),
        (f"{API_PREFIX}/conversations/{{conversation_id}}/approve", "post"),
        (f"{API_PREFIX}/quality-reviews", "post"),
        (f"{API_PREFIX}/qa/handoffs/{{handoff_id}}/take", "post"),
    }
    for path, method in long_ops:
        assert "202" in DOC["paths"][path][method]["responses"], path


def test_approve_requires_the_fingerprint() -> None:
    body = DOC["components"]["schemas"]["ApproveIn"]
    assert body["required"] == ["fingerprint"]
    assert body["properties"]["fingerprint"]["minLength"] == 64


def test_qa_handoffs_list_answers_200_for_qa(tmp_path: Path) -> None:
    """T-54 (PA-105): la QA encadenada ya no responde 501; sin entregas, qa-demo recibe `[]`."""
    app = create_app(runtime_instance=fake_runtime(tmp_path))
    client = TestClient(app, base_url="https://testserver")  # la cookie es `Secure`
    login = client.post(
        f"{API_PREFIX}/auth/login",
        json={"username": "qa-demo", "password": dataset.DEMO_USERS["qa-demo"][0]},
    )
    assert login.status_code == 200
    response = client.get(f"{API_PREFIX}/qa/handoffs")
    assert response.status_code == 200
    assert response.json() == []


def test_examples_have_no_real_looking_secrets_or_personal_data() -> None:
    text = OPENAPI_PATH.read_text(encoding="utf-8")
    assert "@" not in text.replace("@example", "")  # ni emails
    for marker in ("Bearer ", 'password": "', "api_key"):
        assert marker not in text


def test_validation_error_never_echoes_the_input() -> None:
    """Seguridad (T-55): un 422 no devuelve lo enviado, p. ej. la contraseña."""
    client = TestClient(create_app())
    secret = "contrasena-ficticia-" + "x" * 300
    response = client.post(
        f"{API_PREFIX}/auth/login", json={"username": "af-demo", "password": secret}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "password" in body["error"]["message"]
    assert secret not in response.text and "contrasena-ficticia" not in response.text


def test_login_has_no_security_and_gets_only_need_the_cookie() -> None:
    assert DOC["paths"][f"{API_PREFIX}/auth/login"]["post"]["security"] == []
    for path, method, op in OPERATIONS:
        if method == "get":
            assert op["security"] == [{"sessionCookie": []}], path
        elif not path.endswith("/auth/login"):
            assert "security" not in op, path  # global: cookie + CSRF


def test_identifiers_fingerprint_and_lists_are_constrained() -> None:
    schemas = DOC["components"]["schemas"]
    assert schemas["ApproveIn"]["properties"]["fingerprint"]["pattern"] == "^[0-9a-f]{64}$"
    params = DOC["paths"][f"{API_PREFIX}/conversations/{{conversation_id}}"]["get"]["parameters"]
    assert params[0]["schema"]["pattern"].startswith("^[0-9a-f]{8}-")
    feedback = schemas["ConversationCreateIn"]["properties"]["feedback"]
    assert feedback["maxItems"] == 30 and feedback["items"]["maxLength"] == 1000  # T-48


def test_events_route_declares_server_sent_events() -> None:
    op = DOC["paths"][f"{API_PREFIX}/conversations/{{conversation_id}}/events"]["get"]
    assert list(op["responses"]["200"]["content"]) == ["text/event-stream"]


@pytest.mark.parametrize(
    ("flow", "origin", "ok"),
    [
        ("need", {"kind": "need", "text": "Necesidad ficticia", "project": "DEMO"}, True),
        ("need", {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}, True),
        ("evolve", {"kind": "story", "key": "DEMO-3", "project": "DEMO"}, True),
        ("tests", {"kind": "story", "key": "DEMO-3", "project": "DEMO"}, True),
        ("evolve", {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}, False),
        ("tests", {"kind": "need", "text": "x", "project": "DEMO"}, False),
        ("tests", {"kind": "story", "key": "DEMO-3", "text": "x", "project": "DEMO"}, False),
    ],
)
def test_flow_must_match_origin_kind(flow: str, origin: dict[str, str], ok: bool) -> None:
    from pydantic import ValidationError

    from api.models import ConversationCreateIn

    if ok:
        ConversationCreateIn(flow=flow, origin=origin)  # type: ignore[arg-type]
    else:
        with pytest.raises(ValidationError):
            ConversationCreateIn(flow=flow, origin=origin)  # type: ignore[arg-type]


def test_frontend_needs_are_in_the_contract() -> None:
    """Revisión de T-55: volver a «Modelo automático», recientes, fecha y autoría."""
    assert "delete" in DOC["paths"][f"{API_PREFIX}/settings/models/{{task}}"]
    search = DOC["paths"][f"{API_PREFIX}/projects/{{project}}/search"]["get"]["parameters"]
    assert next(p for p in search if p["name"] == "q")["required"] is False
    schemas = DOC["components"]["schemas"]
    assert "created_at" in schemas["VersionOut"]["required"]
    assert {"approved_by", "approved_at"} <= set(schemas["PublishOutcome"]["required"])
    assert "failed_ids" in schemas["PublishOutcome"]["properties"]


def test_validation_message_for_model_errors_and_bad_json(tmp_path: Path) -> None:
    """El 422 da un mensaje listo para mostrar también sin campo concreto (revisión de T-55).

    Con sesión y CSRF: sin ellos la API responde 401 o 403 antes de validar el cuerpo (PA-161).
    """
    client = TestClient(
        create_app(runtime_instance=fake_runtime(tmp_path)), base_url="https://testserver"
    )
    login = client.post(
        f"{API_PREFIX}/auth/login",
        json={"username": "af-demo", "password": dataset.DEMO_USERS["af-demo"][0]},
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    response = client.post(
        f"{API_PREFIX}/conversations",
        json={"flow": "tests", "origin": {"kind": "need", "text": "x", "project": "DEMO"}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "El flujo «tests» no admite un origen «need»."
    broken = client.post(
        f"{API_PREFIX}/conversations",
        content=b"{no json",
        headers={"Content-Type": "application/json"},
    )
    assert broken.status_code == 422
    assert broken.json()["error"]["message"] == "El cuerpo de la petición no es un JSON válido."


# --- Segunda ronda (T-55, parte 2): errores comunes y declarados por ruta ---------------------


def _example_code(op: dict[str, Any], status: str) -> str:
    return op["responses"][status]["content"]["application/json"]["example"]["error"]["code"]


@pytest.mark.parametrize(("path", "method", "op"), OPERATIONS, ids=lambda v: str(v)[:40])
def test_every_route_declares_413_500_and_503(path: str, method: str, op: dict[str, Any]) -> None:
    """Req. 7 y 8: cualquier ruta puede dar 413, 500 o 503; el contrato lo declara."""
    assert {"413", "500", "503"} <= set(op["responses"]), (method, path)
    assert _example_code(op, "413") == "payload_too_large"
    assert _example_code(op, "500") == "unexpected"
    assert _example_code(op, "503") == "service_unavailable"


@pytest.mark.parametrize(("path", "method", "op"), OPERATIONS, ids=lambda v: str(v)[:40])
def test_routes_with_session_declare_401(path: str, method: str, op: dict[str, Any]) -> None:
    """Req. 1: toda ruta con sesión declara el 401 `unauthenticated`."""
    if "/auth/" in path:  # sesión: no leen de Jira ni llaman al LLM
        return
    assert _example_code(op, "401") == "unauthenticated", (method, path)


def test_login_declares_origin_403_and_lockout_429() -> None:
    """Req. 2 y 4: el login declara el 403 de origen y el 429 de intentos."""
    op = DOC["paths"][f"{API_PREFIX}/auth/login"]["post"]
    assert "403" in op["responses"]
    assert _example_code(op, "429") == "too_many_attempts"
    assert _example_code(op, "401") == "invalid_credentials"


def test_events_declares_too_many_streams() -> None:
    """Req. 6: `/events` declara el 429 `too_many_streams`."""
    op = DOC["paths"][f"{API_PREFIX}/conversations/{{conversation_id}}/events"]["get"]
    assert _example_code(op, "429") == "too_many_streams"
    assert _example_code(op, "404") == "not_found"


def test_create_conversation_declares_project_404() -> None:
    """Crear: proyecto que no ve la conexión -> 404 declarado."""
    op = DOC["paths"][f"{API_PREFIX}/conversations"]["post"]
    assert "404" in op["responses"]


def test_create_quality_review_does_not_declare_404() -> None:
    """PA-103: la HU inexistente llega como `state=error`, no como 404 de la petición."""
    op = DOC["paths"][f"{API_PREFIX}/quality-reviews"]["post"]
    assert "404" not in op["responses"]
    assert "202" in op["responses"]


def test_quality_review_of_missing_issue_ends_in_error_state(tmp_path: Path) -> None:
    """PA-103: revisar una HU inexistente responde 202 y la revisión queda en `error`."""
    client = TestClient(
        create_app(runtime_instance=fake_runtime(tmp_path)), base_url="https://testserver"
    )
    password = dataset.DEMO_USERS["af-demo"][0]
    login = client.post(
        f"{API_PREFIX}/auth/login", json={"username": "af-demo", "password": password}
    )
    response = client.post(
        f"{API_PREFIX}/quality-reviews",
        json={"issue_key": "DEMO-999"},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "error" and body["error"]["code"] == "not_found"


@pytest.mark.parametrize(("path", "method", "op"), OPERATIONS, ids=lambda v: str(v)[:60])
def test_routes_with_session_declare_rate_limited(path: str, method: str, op: Any) -> None:
    """Cualquier ruta con sesión puede leer de Jira o llamar al LLM: declara 429."""
    if "/auth/" in path:  # sesión: no leen de Jira ni llaman al LLM
        return
    assert "429" in op["responses"], (method, path)


def test_sources_declares_missing_origin_404() -> None:
    assert "404" in DOC["paths"][f"{API_PREFIX}/start/sources"]["post"]["responses"]


HANDOFF_ROUTES = [
    (f"{API_PREFIX}/conversations/{{conversation_id}}/handoff", "post"),
    (f"{API_PREFIX}/qa/handoffs", "get"),
    (f"{API_PREFIX}/qa/handoffs/{{handoff_id}}/take", "post"),
]
HANDOFF_ID = r"^[0-9a-f]{32}$"


@pytest.mark.parametrize(("path", "method"), HANDOFF_ROUTES)
def test_chained_qa_routes_no_longer_declare_501(path: str, method: str) -> None:
    """T-54 (PA-105): la QA encadenada está implementada; ninguna de sus rutas declara 501."""
    responses = DOC["paths"][path][method]["responses"]
    assert "501" not in responses
    assert "provisional" not in str(DOC["paths"][path][method].get("summary", "")).lower()


@pytest.mark.parametrize(
    "path",
    [
        f"{API_PREFIX}/conversations/{{conversation_id}}/handoff",
        f"{API_PREFIX}/qa/handoffs/{{handoff_id}}/take",
    ],
)
def test_handoff_and_take_declare_409_handoff_unavailable(path: str) -> None:
    """T-54: pasar a QA y recoger declaran el 409 `handoff_unavailable` con la forma común."""
    op = DOC["paths"][path]["post"]
    assert _example_code(op, "409") == "handoff_unavailable"


def test_handoff_unavailable_is_a_declared_error_code() -> None:
    """T-54: `handoff_unavailable` forma parte del enumerado `ErrorCode` publicado."""
    error_body = DOC["components"]["schemas"]["ErrorBody"]["properties"]["code"]
    codes = (
        error_body.get("enum")
        or DOC["components"]["schemas"][error_body["$ref"].rsplit("/", 1)[-1]]["enum"]
    )
    assert "handoff_unavailable" in codes


def test_take_handoff_id_is_32_lowercase_hex() -> None:
    """T-54 (límite): el id de entrega en la ruta es `^[0-9a-f]{32}$`, no un UUID con guiones."""
    op = DOC["paths"][f"{API_PREFIX}/qa/handoffs/{{handoff_id}}/take"]["post"]
    param = next(p for p in op["parameters"] if p["name"] == "handoff_id")
    assert param["in"] == "path" and param["required"] is True
    assert param["schema"]["pattern"] == HANDOFF_ID


def test_handoff_out_id_has_the_same_pattern() -> None:
    """T-54: `HandoffOut.id` usa el mismo patrón que la ruta de recoger."""
    schema = DOC["components"]["schemas"]["HandoffOut"]
    assert schema["properties"]["id"]["pattern"] == HANDOFF_ID
    assert "story_key" in schema["required"]  # nullable pero siempre presente


def test_handoff_examples_follow_the_contract() -> None:
    """T-54: los ejemplos (mock Prism) cumplen el patrón del id y la forma de cada respuesta."""
    handoff = DOC["paths"][f"{API_PREFIX}/conversations/{{conversation_id}}/handoff"]["post"]
    one = handoff["responses"]["200"]["content"]["application/json"]["example"]
    assert re.fullmatch(HANDOFF_ID, one["id"])
    listed = DOC["paths"][f"{API_PREFIX}/qa/handoffs"]["get"]
    many = listed["responses"]["200"]["content"]["application/json"]["example"]
    assert many and all(re.fullmatch(HANDOFF_ID, h["id"]) for h in many)
    take = DOC["paths"][f"{API_PREFIX}/qa/handoffs/{{handoff_id}}/take"]["post"]
    conv = take["responses"]["202"]["content"]["application/json"]["example"]
    assert conv["mode"] == "qa" and conv["flow"] == "tests"


def test_list_handoffs_does_not_declare_409() -> None:
    """T-54: listar no recoge nada: no declara el 409 de entrega no disponible."""
    op = DOC["paths"][f"{API_PREFIX}/qa/handoffs"]["get"]
    assert "409" not in op["responses"]


def test_api_never_imports_the_streamlit_ui() -> None:
    """PA-106: la API no depende de `app/` (Streamlit es el plan B y puede retirarse en T-57)."""
    import ast

    api_dir = OPENAPI_PATH.parents[2] / "api"
    for path in api_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            assert not any(n == "app" or n.startswith("app.") for n in names), path.name
