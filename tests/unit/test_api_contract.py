"""Contrato de la API para el frontend (T-55, parte 1)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.app import API_PREFIX, create_app
from api.export_openapi import OPENAPI_PATH, openapi_document, render

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


def test_part_one_routes_answer_501_with_the_common_error() -> None:
    client = TestClient(create_app())
    response = client.get(f"{API_PREFIX}/projects")
    assert response.status_code == 501
    assert response.json() == {
        "error": {
            "code": "not_implemented",
            "message": "Disponible en la parte 2 de T-55 (API real).",
            "retry_after": None,
        }
    }


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


def test_validation_message_for_model_errors_and_bad_json() -> None:
    """El 422 da un mensaje listo para mostrar también sin campo concreto (revisión de T-55)."""
    client = TestClient(create_app())
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
