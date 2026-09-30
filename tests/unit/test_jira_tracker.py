"""JiraCloudTracker de lectura (T-11: RF-01, RF-03, RNF-04; SPEC-00 §4, §8, §11).

Sin red: todo el HTTP pasa por `httpx.MockTransport`. Datos 100 % sintéticos del dominio
ficticio de la Biblioteca de Villaficticia; credenciales obviamente de prueba.
"""

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from adapters.base import IssueDetail, IssueLink, IssueSummary, IssueTracker
from adapters.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
)
from adapters.jira.tracker import ISSUE_FIELDS, JIRA_KEY_RE, JiraCloudTracker
from tests.fakes import dataset

BASE_URL = "https://villaficticia.example"
EMAIL = "persona@example.com"
TOKEN = "test-token"
CLOUD_ID = "test-cloud-id"
BODY_MARKER = "MARCADOR-CUERPO-RESPUESTA-FICTICIO"
BASIC_CREDENTIALS = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()

Handler = Callable[[httpx.Request], httpx.Response]


# --- Dobles y utilidades ---------------------------------------------------------------------


class RecordingSleep:
    """Sustituto de `time.sleep` que registra las esperas sin dormir."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


class Recorder:
    """Handler de MockTransport que registra las peticiones y responde en secuencia."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests), len(self.responses)) - 1
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return response


def fail_if_called(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"No debería hacerse ninguna petición HTTP: {request.method} {request.url.path}")


def make_tracker(
    handler: Handler,
    sleep: RecordingSleep | None = None,
    *,
    base_url: str = BASE_URL,
    cloud_id: SecretStr | None = None,
    max_retries: int = 2,
    max_wait_s: float = 30.0,
) -> JiraCloudTracker:
    return JiraCloudTracker(
        base_url,
        SecretStr(EMAIL),
        SecretStr(TOKEN),
        cloud_id=cloud_id,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=max_retries,
        max_wait_s=max_wait_s,
        sleep=sleep or RecordingSleep(),
    )


def error_response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    """Respuesta de error con un marcador en el cuerpo que nunca debe llegar al mensaje."""
    body = {"errorMessages": [f"{BODY_MARKER} {EMAIL} {TOKEN}"], "errors": {}}
    return httpx.Response(status, json=body, headers=headers)


def assert_safe_message(exc: Exception) -> None:
    """El mensaje existe y no contiene token, email, credenciales ni el cuerpo de la respuesta."""
    message = str(exc)
    assert message.strip()
    for forbidden in (TOKEN, EMAIL, BASIC_CREDENTIALS, BODY_MARKER):
        assert forbidden not in message


def adf_paragraph(value: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": value}]}],
    }


DEMO_3_PAYLOAD: dict[str, Any] = {
    "key": "DEMO-3",
    "fields": {
        "summary": "[HU-02] Renovar un préstamo",
        "issuetype": {"name": "Story"},
        "status": {"name": "Por hacer"},
        "description": adf_paragraph("Como persona socia quiero renovar un préstamo."),
        "parent": {"key": "DEMO-1"},
        "subtasks": [
            {
                "key": "DEMO-10",
                "fields": {
                    "summary": "[CP-01] Renovar sin reservas",
                    "issuetype": {"name": "Subtarea"},
                    "status": {"name": "Por hacer"},
                },
            }
        ],
        "issuelinks": [
            {
                "type": {"name": "Relates", "inward": "relates to", "outward": "relates to"},
                "outwardIssue": {"key": "DEMO-2"},
            },
            {
                "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                "inwardIssue": {"key": "DEMO-4"},
            },
        ],
        "comment": {"comments": [{"body": adf_paragraph("Validado con sala (ficticio).")}]},
        "labels": ["prestamo-digital"],
    },
}

EXPECTED_DEMO_3 = IssueDetail(
    key="DEMO-3",
    summary="[HU-02] Renovar un préstamo",
    issue_type="Story",
    status="Por hacer",
    description_text="Como persona socia quiero renovar un préstamo.",
    parent_key="DEMO-1",
    subtasks=[
        IssueSummary(
            key="DEMO-10",
            summary="[CP-01] Renovar sin reservas",
            issue_type="Subtarea",
            status="Por hacer",
        )
    ],
    links=[
        IssueLink(link_type="relates to", key="DEMO-2"),
        IssueLink(link_type="is blocked by", key="DEMO-4"),
    ],
    comments=["Validado con sala (ficticio)."],
    labels=["prestamo-digital"],
)


def ok_issue(payload: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(200, json=payload or DEMO_3_PAYLOAD)


def ok_myself() -> httpx.Response:
    return httpx.Response(200, json={"accountId": "id-ficticio", "displayName": "Persona Demo"})


# --- Constantes y contrato -------------------------------------------------------------------


def test_issue_fields_lists_required_fields() -> None:
    """RF-03: se piden exactamente los campos necesarios para el detalle."""
    assert ISSUE_FIELDS == (
        "summary,issuetype,status,description,parent,subtasks,issuelinks,comment,labels"
    )


@pytest.mark.parametrize("key", ["DEMO-1", "DEMO-123", "AB-9", "PROJ_2-45"])
def test_jira_key_re_matches_valid_keys(key: str) -> None:
    """SPEC-00 §11: claves `^[A-Z][A-Z0-9_]+-\\d+$`."""
    assert JIRA_KEY_RE.match(key)


@pytest.mark.parametrize("key", ["demo-3", "D-1", "DEMO-", "DEMO3", "1DEMO-3", ""])
def test_jira_key_re_rejects_invalid_keys(key: str) -> None:
    """SPEC-00 §11: formatos no válidos de clave de Jira."""
    assert not JIRA_KEY_RE.match(key)


def test_tracker_implements_issue_tracker_protocol() -> None:
    """CA-00-03 / §4: JiraCloudTracker cumple el protocolo IssueTracker."""
    assert isinstance(make_tracker(fail_if_called), IssueTracker)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda t: t.search("project = DEMO"), id="search"),
        pytest.param(lambda t: t.list_epics("DEMO"), id="list_epics"),
        pytest.param(lambda t: t.list_children("DEMO-1"), id="list_children"),
        pytest.param(lambda t: t.create_story(dataset.renewal_story(None), "DEMO-1"), id="create"),
        pytest.param(
            lambda t: t.update_story("DEMO-3", dataset.renewal_story(), "Cambio ficticio"),
            id="update_story",
        ),
        pytest.param(lambda t: t.link("DEMO-3", "DEMO-2", "relates to"), id="link"),
    ],
)
def test_unimplemented_methods_raise_not_implemented_without_http(
    call: Callable[[JiraCloudTracker], object],
) -> None:
    """T-11: search/list_* (T-14) y escrituras (T-27) aún no existen y no tocan la red."""
    with pytest.raises(NotImplementedError):
        call(make_tracker(fail_if_called))


# --- api_root (RF-01, RNF-04) ----------------------------------------------------------------


def test_api_root_is_base_url_when_no_cloud_id() -> None:
    """RF-01: sin cloud_id, la API se sirve desde la URL del sitio."""
    assert make_tracker(fail_if_called).api_root == BASE_URL


def test_api_root_strips_trailing_slash_when_base_url_ends_with_slash() -> None:
    """RF-01: la barra final de la URL del sitio se elimina."""
    tracker = make_tracker(fail_if_called, base_url=f"{BASE_URL}/")
    assert tracker.api_root == BASE_URL


def test_api_root_uses_atlassian_gateway_when_cloud_id() -> None:
    """RNF-04: los tokens con scopes van a api.atlassian.com/ex/jira/<cloudId>."""
    tracker = make_tracker(fail_if_called, cloud_id=SecretStr(CLOUD_ID))
    assert tracker.api_root == f"https://api.atlassian.com/ex/jira/{CLOUD_ID}"


def test_requests_go_to_atlassian_gateway_when_cloud_id() -> None:
    """RNF-04: con cloud_id la petición real se envía a la pasarela de Atlassian."""
    recorder = Recorder(ok_myself())
    make_tracker(recorder, cloud_id=SecretStr(CLOUD_ID)).test_connection()
    url = recorder.requests[0].url
    assert url.host == "api.atlassian.com"
    assert url.path == f"/ex/jira/{CLOUD_ID}/rest/api/3/project/search"


# --- Autenticación y cabeceras (RF-01) --------------------------------------------------------


def test_requests_send_basic_auth_and_json_accept() -> None:
    """RF-01: HTTP Basic con email:token y Accept application/json."""
    recorder = Recorder(ok_myself())
    make_tracker(recorder).test_connection()
    headers = recorder.requests[0].headers
    assert headers["Authorization"] == f"Basic {BASIC_CREDENTIALS}"
    assert "application/json" in headers["Accept"]


def test_get_issue_sends_basic_auth() -> None:
    """RF-01/RF-03: la lectura de incidencias también va autenticada."""
    recorder = Recorder(ok_issue())
    make_tracker(recorder).get_issue("DEMO-3")
    assert recorder.requests[0].headers["Authorization"] == f"Basic {BASIC_CREDENTIALS}"


# --- test_connection (RF-01) ------------------------------------------------------------------


def test_test_connection_returns_none_when_200() -> None:
    """RF-01: GET /rest/api/3/project/search con 200 → la conexión es válida."""
    recorder = Recorder(ok_myself())
    assert make_tracker(recorder).test_connection() is None
    request = recorder.requests[0]
    assert request.method == "GET"
    assert str(request.url) == f"{BASE_URL}/rest/api/3/project/search"


@pytest.mark.parametrize("status", [401, 403])
def test_test_connection_raises_authentication_error_when_401_or_403(status: int) -> None:
    """RF-01: credenciales inválidas o sin permisos → AuthenticationError, sin reintentos."""
    recorder = Recorder(error_response(status))
    sleep = RecordingSleep()
    with pytest.raises(AuthenticationError) as info:
        make_tracker(recorder, sleep).test_connection()
    assert info.value.service == "jira"
    assert_safe_message(info.value)
    assert len(recorder.requests) == 1
    assert sleep.waits == []


def test_test_connection_raises_external_error_after_retries_when_500_persists() -> None:
    """RF-01, §8: 5xx persistente → reintentos con backoff y ExternalServiceError."""
    recorder = Recorder(error_response(500))
    sleep = RecordingSleep()
    with pytest.raises(ExternalServiceError) as info:
        make_tracker(recorder, sleep, max_retries=2).test_connection()
    assert type(info.value) is ExternalServiceError
    assert info.value.service == "jira"
    assert len(recorder.requests) == 3
    assert sleep.waits == [1.0, 2.0]
    assert_safe_message(info.value)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(httpx.ConnectError("conexión rechazada (ficticia)"), id="connect"),
        pytest.param(httpx.ReadTimeout("tiempo agotado (ficticio)"), id="timeout"),
    ],
)
def test_test_connection_raises_external_error_when_transport_fails(error: Exception) -> None:
    """RF-01: fallo de red → ExternalServiceError de «jira» (no AuthenticationError)."""
    recorder = Recorder(error)
    with pytest.raises(ExternalServiceError) as info:
        make_tracker(recorder).test_connection()
    assert not isinstance(info.value, AuthenticationError | NotFoundError | RateLimitError)
    assert info.value.service == "jira"
    assert_safe_message(info.value)


def test_test_connection_succeeds_when_transient_503_then_200() -> None:
    """§8: un 5xx transitorio se reintenta y la conexión termina siendo válida."""
    recorder = Recorder(error_response(503), ok_myself())
    sleep = RecordingSleep()
    make_tracker(recorder, sleep).test_connection()
    assert len(recorder.requests) == 2
    assert sleep.waits == [1.0]


# --- get_issue (RF-03) -----------------------------------------------------------------------


def test_get_issue_requests_issue_endpoint_with_fields() -> None:
    """RF-03: GET /rest/api/3/issue/<clave>?fields=ISSUE_FIELDS."""
    recorder = Recorder(ok_issue())
    make_tracker(recorder).get_issue("DEMO-3")
    request = recorder.requests[0]
    assert request.method == "GET"
    assert request.url.host == "villaficticia.example"
    assert request.url.path == "/rest/api/3/issue/DEMO-3"
    assert request.url.params["fields"] == ISSUE_FIELDS


def test_get_issue_maps_full_payload_to_issue_detail() -> None:
    """RF-03: descripción ADF→texto, épica padre, subtareas, vínculos, comentarios y etiquetas."""
    assert make_tracker(Recorder(ok_issue())).get_issue("DEMO-3") == EXPECTED_DEMO_3


def test_get_issue_maps_link_direction_from_inward_and_outward() -> None:
    """RF-03: outwardIssue → type.outward; inwardIssue → type.inward."""
    payload = json.loads(json.dumps(DEMO_3_PAYLOAD))
    payload["fields"]["issuelinks"] = [
        {
            "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
            "outwardIssue": {"key": "DEMO-7"},
        },
        {
            "type": {"name": "Cloners", "inward": "is cloned by", "outward": "clones"},
            "inwardIssue": {"key": "DEMO-8"},
        },
    ]
    detail = make_tracker(Recorder(ok_issue(payload))).get_issue("DEMO-3")
    assert detail.links == [
        IssueLink(link_type="blocks", key="DEMO-7"),
        IssueLink(link_type="is cloned by", key="DEMO-8"),
    ]


def test_get_issue_converts_rich_adf_description_and_comments() -> None:
    """RF-03: la descripción y cada comentario se convierten de ADF a texto."""
    payload = json.loads(json.dumps(DEMO_3_PAYLOAD))
    payload["fields"]["description"] = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Reglas"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Máximo 2 renovaciones."}],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    payload["fields"]["comment"] = {
        "comments": [
            {"body": adf_paragraph("Primer comentario ficticio.")},
            {"body": adf_paragraph("Segundo comentario ficticio.")},
        ]
    }
    detail = make_tracker(Recorder(ok_issue(payload))).get_issue("DEMO-3")
    assert detail.description_text == "## Reglas\n\n- Máximo 2 renovaciones."
    assert detail.comments == ["Primer comentario ficticio.", "Segundo comentario ficticio."]


def test_get_issue_uses_defaults_when_optional_fields_missing() -> None:
    """RF-03: sin descripción, padre, subtareas, vínculos, comentarios ni etiquetas → defaults."""
    payload = {
        "key": "DEMO-5",
        "fields": {
            "summary": "Incidencia mínima ficticia",
            "issuetype": {"name": "Task"},
            "status": {"name": "Por hacer"},
        },
    }
    detail = make_tracker(Recorder(ok_issue(payload))).get_issue("DEMO-5")
    assert detail == IssueDetail(
        key="DEMO-5",
        summary="Incidencia mínima ficticia",
        issue_type="Task",
        status="Por hacer",
    )


def test_get_issue_uses_defaults_when_optional_fields_null() -> None:
    """RF-03: campos presentes pero nulos → defaults de IssueDetail."""
    payload = {
        "key": "DEMO-6",
        "fields": {
            "summary": "Incidencia con nulos ficticia",
            "issuetype": {"name": "Story"},
            "status": {"name": "En curso"},
            "description": None,
            "parent": None,
            "subtasks": None,
            "issuelinks": None,
            "comment": None,
            "labels": None,
        },
    }
    detail = make_tracker(Recorder(ok_issue(payload))).get_issue("DEMO-6")
    assert detail.description_text == ""
    assert detail.parent_key is None
    assert detail.subtasks == []
    assert detail.links == []
    assert detail.comments == []
    assert detail.labels == []


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("demo-3", id="minusculas"),
        pytest.param("DEMO-3/../x", id="traversal"),
        pytest.param("", id="vacia"),
        pytest.param("DEMO-", id="sin-numero"),
        pytest.param("DEMO-3?fields=*all", id="query"),
        pytest.param("DEMO-3\n", id="salto-final"),
    ],
)
def test_get_issue_raises_not_found_without_request_when_key_invalid(key: str) -> None:
    """SPEC-00 §11: la clave se valida antes de llamar a Jira → NotFoundError sin HTTP."""
    with pytest.raises(NotFoundError) as info:
        make_tracker(fail_if_called).get_issue(key)
    assert info.value.service == "jira"
    assert_safe_message(info.value)


def test_get_issue_raises_not_found_when_404() -> None:
    """RF-03: la incidencia no existe → NotFoundError, sin reintentos."""
    recorder = Recorder(error_response(404))
    sleep = RecordingSleep()
    with pytest.raises(NotFoundError) as info:
        make_tracker(recorder, sleep).get_issue("DEMO-99")
    assert info.value.service == "jira"
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


@pytest.mark.parametrize("status", [401, 403])
def test_get_issue_raises_authentication_error_when_401_or_403(status: int) -> None:
    """RF-01/RF-03: sin permisos o credenciales inválidas → AuthenticationError."""
    recorder = Recorder(error_response(status))
    with pytest.raises(AuthenticationError) as info:
        make_tracker(recorder).get_issue("DEMO-3")
    assert info.value.service == "jira"
    assert len(recorder.requests) == 1
    assert_safe_message(info.value)


# --- Límites de uso y reintentos (§8) ---------------------------------------------------------


def test_get_issue_waits_retry_after_and_retries_when_429() -> None:
    """§8: 429 con Retry-After «2» → espera 2 s y reintenta con éxito."""
    recorder = Recorder(error_response(429, {"Retry-After": "2"}), ok_issue())
    sleep = RecordingSleep()
    detail = make_tracker(recorder, sleep).get_issue("DEMO-3")
    assert detail == EXPECTED_DEMO_3
    assert sleep.waits == [2.0]
    assert len(recorder.requests) == 2


def test_get_issue_raises_rate_limit_when_429_persists() -> None:
    """§8: 429 persistente tras max_retries → RateLimitError con retry_after."""
    recorder = Recorder(error_response(429, {"Retry-After": "2"}))
    sleep = RecordingSleep()
    with pytest.raises(RateLimitError) as info:
        make_tracker(recorder, sleep, max_retries=2).get_issue("DEMO-3")
    assert info.value.retry_after == 2.0
    assert info.value.service == "jira"
    assert len(recorder.requests) == 3
    assert sleep.waits == [2.0, 2.0]
    assert_safe_message(info.value)


def test_get_issue_raises_rate_limit_without_waiting_when_retry_after_exceeds_max_wait() -> None:
    """§8: Retry-After mayor que max_wait_s → RateLimitError inmediato, sin dormir."""
    recorder = Recorder(error_response(429, {"Retry-After": "120"}))
    sleep = RecordingSleep()
    with pytest.raises(RateLimitError) as info:
        make_tracker(recorder, sleep, max_wait_s=30.0).get_issue("DEMO-3")
    assert info.value.retry_after == 120.0
    assert sleep.waits == []
    assert len(recorder.requests) == 1
    assert_safe_message(info.value)


def test_get_issue_does_not_retry_when_max_retries_zero() -> None:
    """§8 (límite): con max_retries=0 solo hay una petición."""
    recorder = Recorder(error_response(429, {"Retry-After": "1"}))
    sleep = RecordingSleep()
    with pytest.raises(RateLimitError):
        make_tracker(recorder, sleep, max_retries=0).get_issue("DEMO-3")
    assert len(recorder.requests) == 1
    assert sleep.waits == []


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_get_issue_retries_with_backoff_then_raises_when_5xx_persists(status: int) -> None:
    """§8: 5xx → backoff 1.0, 2.0… y ExternalServiceError al agotar los reintentos."""
    recorder = Recorder(error_response(status))
    sleep = RecordingSleep()
    with pytest.raises(ExternalServiceError) as info:
        make_tracker(recorder, sleep, max_retries=2).get_issue("DEMO-3")
    assert type(info.value) is ExternalServiceError
    assert info.value.service == "jira"
    assert len(recorder.requests) == 3
    assert sleep.waits == [1.0, 2.0]
    assert_safe_message(info.value)


def test_get_issue_succeeds_when_5xx_then_200() -> None:
    """§8: un 5xx transitorio seguido de 200 devuelve el detalle."""
    recorder = Recorder(error_response(502), ok_issue())
    sleep = RecordingSleep()
    assert make_tracker(recorder, sleep).get_issue("DEMO-3") == EXPECTED_DEMO_3
    assert sleep.waits == [1.0]


# --- Endurecimiento (revisión de seguridad) ---


def _tracker_with(
    handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any
) -> JiraCloudTracker:
    return JiraCloudTracker(
        kwargs.pop("base_url", BASE_URL),
        SecretStr(EMAIL),
        SecretStr(TOKEN),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _s: None,
        **kwargs,
    )


def _never_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError("No debe hacerse ninguna petición")


@pytest.mark.parametrize("url", ["http://villaficticia.example", "ftp://villaficticia.example", ""])
def test_rejects_base_url_without_https(url: str) -> None:
    """Basic auth: sin https las credenciales viajarían sin cifrar."""
    with pytest.raises(AuthenticationError, match="https") as info:
        _tracker_with(_never_called, base_url=url)
    assert TOKEN not in str(info.value)


@pytest.mark.parametrize("cloud_id", ["abc/../x", "abc?x=1", "abc#frag", "a b"])
def test_rejects_malformed_cloud_id(cloud_id: str) -> None:
    """El cloud_id forma parte de la ruta del gateway: solo letras, dígitos y guiones."""
    with pytest.raises(AuthenticationError) as info:
        _tracker_with(_never_called, cloud_id=SecretStr(cloud_id))
    assert cloud_id not in str(info.value)


def test_non_json_body_raises_external_error_without_leaking_body() -> None:
    """Un cuerpo que no es JSON se traduce a ExternalServiceError sin el contenido."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<html>{BODY_MARKER}</html>")

    with pytest.raises(ExternalServiceError) as info:
        _tracker_with(handler).get_issue("DEMO-3")
    assert BODY_MARKER not in str(info.value)
    assert info.value.__cause__ is None


def test_invalid_key_message_is_truncated() -> None:
    """El mensaje de clave inválida no repite entradas arbitrariamente largas."""
    with pytest.raises(NotFoundError) as info:
        _tracker_with(_never_called).get_issue("x" * 500)
    assert len(str(info.value)) < 120
