"""JiraCloudTracker de lectura (T-11: RF-01, RF-03, RNF-04; T-14: RF-02; SPEC-00 §4, §8, §11).

Sin red: todo el HTTP pasa por `httpx.MockTransport`. Datos 100 % sintéticos del dominio
ficticio de la Biblioteca de Villaficticia; credenciales obviamente de prueba.
"""

import base64
import inspect
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
from adapters.jira import tracker as tracker_module
from adapters.jira.tracker import (
    ISSUE_FIELDS,
    JIRA_KEY_RE,
    MAX_RESULTS,
    PAGE_SIZE,
    SEARCH_FIELDS,
    JiraCloudTracker,
)

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


# Las escrituras (T-27) se prueban en tests/unit/test_jira_write.py.


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


# --- Contrato del protocolo tras T-14 ---------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "test_connection",
        "search",
        "get_issue",
        "list_epics",
        "list_children",
        "create_story",
        "update_story",
        "link",
    ],
)
def test_tracker_method_signature_matches_protocol(name: str) -> None:
    """§4: cada método de JiraCloudTracker tiene la misma firma que IssueTracker."""
    expected = inspect.signature(getattr(IssueTracker, name))
    assert inspect.signature(getattr(JiraCloudTracker, name)) == expected


# --- search (T-14, RF-02) --------------------------------------------------------------------

SEARCH_PATH = "/rest/api/3/search/jql"
JQL_MARKER = "MARCADOR-JQL-FICTICIA"


def fake_issue(number: int) -> dict[str, Any]:
    return {
        "id": str(10000 + number),
        "key": f"DEMO-{number}",
        "fields": {
            "summary": f"[HU-{number:02d}] Historia ficticia {number}",
            "issuetype": {"name": "Story"},
            "status": {"name": "Por hacer"},
        },
    }


def issues_range(start: int, count: int) -> list[dict[str, Any]]:
    return [fake_issue(n) for n in range(start, start + count)]


def search_page(
    issues: list[dict[str, Any]], token: str | None = None, is_last: bool | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"issues": issues}
    if token is not None:
        body["nextPageToken"] = token
    if is_last is not None:
        body["isLast"] = is_last
    return httpx.Response(200, json=body)


def keys(results: list[IssueSummary]) -> list[str]:
    return [issue.key for issue in results]


def test_search_returns_single_page_when_is_last() -> None:
    """RF-02: una página con isLast=true → una sola petición y todos los resultados."""
    recorder = Recorder(search_page(issues_range(1, 3), is_last=True))
    results = make_tracker(recorder).search("project = DEMO")
    assert keys(results) == ["DEMO-1", "DEMO-2", "DEMO-3"]
    assert len(recorder.requests) == 1


def test_search_requests_search_jql_endpoint_with_params() -> None:
    """RF-02: GET /rest/api/3/search/jql con jql, maxResults y fields=SEARCH_FIELDS."""
    recorder = Recorder(search_page([], is_last=True))
    make_tracker(recorder).search("project = DEMO ORDER BY key", limit=20)
    request = recorder.requests[0]
    assert request.method == "GET"
    assert request.url.path == SEARCH_PATH
    assert request.url.params["jql"] == "project = DEMO ORDER BY key"
    assert request.url.params["maxResults"] == "20"
    assert request.url.params["fields"] == SEARCH_FIELDS
    assert "nextPageToken" not in request.url.params
    assert request.headers["Authorization"] == f"Basic {BASIC_CREDENTIALS}"


def test_search_fields_are_summary_type_and_status() -> None:
    """RF-02: la búsqueda solo pide los campos de IssueSummary."""
    assert SEARCH_FIELDS == "summary,issuetype,status"


def test_search_uses_default_limit_of_50() -> None:
    """RF-02, §4: sin `limit` explícito se piden 50 resultados."""
    recorder = Recorder(search_page([], is_last=True))
    make_tracker(recorder).search("project = DEMO")
    assert recorder.requests[0].url.params["maxResults"] == "50"


def test_search_follows_next_page_token_across_three_pages() -> None:
    """RF-02: se encadena nextPageToken y maxResults se ajusta a lo que falta."""
    assert PAGE_SIZE == 100
    recorder = Recorder(
        search_page(issues_range(1, 100), token="token-ficticio-1", is_last=False),
        search_page(issues_range(101, 100), token="token-ficticio-2", is_last=False),
        search_page(issues_range(201, 50), token="token-ficticio-3", is_last=False),
    )
    results = make_tracker(recorder).search("project = DEMO", limit=250)
    assert keys(results) == [f"DEMO-{n}" for n in range(1, 251)]
    assert len(recorder.requests) == 3
    first, second, third = (r.url.params for r in recorder.requests)
    assert "nextPageToken" not in first
    assert second["nextPageToken"] == "token-ficticio-1"
    assert third["nextPageToken"] == "token-ficticio-2"
    assert [p["maxResults"] for p in (first, second, third)] == ["100", "100", "50"]
    assert all(p["jql"] == "project = DEMO" for p in (first, second, third))
    assert all(p["fields"] == SEARCH_FIELDS for p in (first, second, third))


def test_search_follows_token_when_is_last_absent() -> None:
    """RF-02: sin isLast, un nextPageToken presente significa que hay más páginas."""
    recorder = Recorder(
        search_page(issues_range(1, 2), token="token-ficticio-1"),
        search_page(issues_range(3, 1)),
    )
    results = make_tracker(recorder).search("project = DEMO", limit=10)
    assert keys(results) == ["DEMO-1", "DEMO-2", "DEMO-3"]
    assert len(recorder.requests) == 2


def test_search_truncates_when_page_exceeds_limit() -> None:
    """RF-02 (límite): si Jira devuelve más de lo pedido, se corta en `limit` y no sigue."""
    recorder = Recorder(search_page(issues_range(1, 5), token="token-ficticio-1"))
    results = make_tracker(recorder).search("project = DEMO", limit=3)
    assert keys(results) == ["DEMO-1", "DEMO-2", "DEMO-3"]
    assert len(recorder.requests) == 1


def test_search_truncates_mid_second_page_when_limit_reached() -> None:
    """RF-02 (límite): limit=150 → 100 de la 1.ª página y 50 de la 2.ª, sin 3.ª petición."""
    recorder = Recorder(
        search_page(issues_range(1, 100), token="token-ficticio-1"),
        search_page(issues_range(101, 100), token="token-ficticio-2"),
    )
    results = make_tracker(recorder).search("project = DEMO", limit=150)
    assert keys(results) == [f"DEMO-{n}" for n in range(1, 151)]
    assert len(recorder.requests) == 2
    assert recorder.requests[1].url.params["maxResults"] == "50"


def test_search_stops_when_limit_equals_page_size() -> None:
    """RF-02 (límite): limit == PAGE_SIZE y página llena con token → no pide otra página."""
    recorder = Recorder(search_page(issues_range(1, PAGE_SIZE), token="token-ficticio-1"))
    results = make_tracker(recorder).search("project = DEMO", limit=PAGE_SIZE)
    assert len(results) == PAGE_SIZE
    assert len(recorder.requests) == 1


def test_search_stops_when_is_last_true_even_with_token() -> None:
    """RF-02: isLast=true detiene la paginación aunque venga un token."""
    recorder = Recorder(search_page(issues_range(1, 2), token="token-ficticio-1", is_last=True))
    results = make_tracker(recorder).search("project = DEMO", limit=10)
    assert keys(results) == ["DEMO-1", "DEMO-2"]
    assert len(recorder.requests) == 1


def test_search_stops_when_no_token_even_if_is_last_false() -> None:
    """RF-02: sin nextPageToken no hay forma de seguir → se detiene."""
    recorder = Recorder(search_page(issues_range(1, 2), is_last=False))
    results = make_tracker(recorder).search("project = DEMO", limit=10)
    assert keys(results) == ["DEMO-1", "DEMO-2"]
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"issues": [], "nextPageToken": "token-ficticio-1"}, id="vacia-con-token"),
        pytest.param({"issues": [], "isLast": True}, id="vacia-ultima"),
        pytest.param({"nextPageToken": "token-ficticio-1"}, id="sin-issues"),
        pytest.param({"issues": None, "nextPageToken": "token-ficticio-1"}, id="issues-null"),
        pytest.param({}, id="cuerpo-vacio"),
    ],
)
def test_search_stops_and_returns_empty_when_page_empty(body: dict[str, Any]) -> None:
    """RF-02: una página sin incidencias detiene la paginación (evita bucles)."""
    recorder = Recorder(httpx.Response(200, json=body))
    assert make_tracker(recorder).search("project = DEMO", limit=10) == []
    assert len(recorder.requests) == 1


def test_search_stops_when_later_page_empty() -> None:
    """RF-02: una 2.ª página vacía con token no provoca una 3.ª petición."""
    recorder = Recorder(
        search_page(issues_range(1, 2), token="token-ficticio-1"),
        search_page([], token="token-ficticio-2"),
        search_page(issues_range(3, 2)),
    )
    results = make_tracker(recorder).search("project = DEMO", limit=10)
    assert keys(results) == ["DEMO-1", "DEMO-2"]
    assert len(recorder.requests) == 2


@pytest.mark.parametrize("limit", [0, -1, -50])
def test_search_returns_empty_without_request_when_limit_not_positive(limit: int) -> None:
    """RF-02 (límite): limit <= 0 → [] sin llamar a Jira."""
    assert make_tracker(fail_if_called).search("project = DEMO", limit=limit) == []


def test_search_caps_results_at_max_results_when_limit_larger() -> None:
    """RF-02 (límite): nunca se devuelven más de MAX_RESULTS aunque haya más páginas."""
    assert MAX_RESULTS == 1000
    requests: list[httpx.Request] = []

    def endless(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        start = len(requests) * 1000
        size = int(request.url.params["maxResults"])
        return search_page(issues_range(start, size), token=f"token-ficticio-{len(requests)}")

    results = make_tracker(endless).search("project = DEMO", limit=5000)
    assert len(results) == MAX_RESULTS
    assert len(requests) == MAX_RESULTS // PAGE_SIZE
    assert all(r.url.params["maxResults"] == str(PAGE_SIZE) for r in requests)


def test_search_honours_patched_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-02: PAGE_SIZE se lee en cada llamada (lo usa la prueba de integración)."""
    monkeypatch.setattr(tracker_module, "PAGE_SIZE", 2)
    recorder = Recorder(
        search_page(issues_range(1, 2), token="token-ficticio-1"),
        search_page(issues_range(3, 2), token="token-ficticio-2"),
        search_page(issues_range(5, 1)),
    )
    results = make_tracker(recorder).search("project = DEMO", limit=5)
    assert keys(results) == [f"DEMO-{n}" for n in range(1, 6)]
    assert [r.url.params["maxResults"] for r in recorder.requests] == ["2", "2", "1"]


@pytest.mark.parametrize("jql", ["", "   ", "\n\t"])
def test_search_raises_value_error_without_request_when_jql_empty(jql: str) -> None:
    """RF-02 (error): JQL vacía o solo espacios → ValueError sin llamar a Jira."""
    with pytest.raises(ValueError):
        make_tracker(fail_if_called).search(jql)


def test_search_maps_issues_to_issue_summary() -> None:
    """RF-02: cada incidencia se mapea a IssueSummary (key, summary, issue_type, status)."""
    payload = {
        "key": "DEMO-3",
        "fields": {
            "summary": "[HU-02] Renovar un préstamo",
            "issuetype": {"name": "Historia"},
            "status": {"name": "En curso"},
        },
    }
    results = make_tracker(Recorder(search_page([payload]))).search("project = DEMO")
    assert results == [
        IssueSummary(
            key="DEMO-3",
            summary="[HU-02] Renovar un préstamo",
            issue_type="Historia",
            status="En curso",
        )
    ]


def test_search_maps_missing_fields_to_empty_strings() -> None:
    """RF-02: campos ausentes o nulos → cadenas vacías, sin excepción."""
    payload = {"key": "DEMO-9", "fields": {"summary": None, "issuetype": None}}
    results = make_tracker(Recorder(search_page([payload]))).search("project = DEMO")
    assert results == [IssueSummary(key="DEMO-9", summary="", issue_type="", status="")]


def test_search_raises_external_error_without_jql_when_400() -> None:
    """RF-02 (error): 400 → ExternalServiceError «La consulta JQL no es válida», sin la JQL."""
    recorder = Recorder(error_response(400))
    sleep = RecordingSleep()
    with pytest.raises(ExternalServiceError) as info:
        make_tracker(recorder, sleep).search(f"summary ~ {JQL_MARKER} AND (")
    assert type(info.value) is ExternalServiceError
    assert info.value.service == "jira"
    message = str(info.value)
    assert "La consulta JQL no es válida" in message
    assert JQL_MARKER not in message
    assert_safe_message(info.value)
    assert len(recorder.requests) == 1
    assert sleep.waits == []


def test_get_issue_keeps_generic_error_when_400() -> None:
    """§8: el mensaje de JQL no válida solo aplica a la búsqueda; get_issue da el genérico."""
    with pytest.raises(ExternalServiceError) as info:
        make_tracker(Recorder(error_response(400))).get_issue("DEMO-3")
    assert "JQL" not in str(info.value)
    assert "HTTP 400" in str(info.value)


@pytest.mark.parametrize("status", [401, 403])
def test_search_raises_authentication_error_when_401_or_403(status: int) -> None:
    """RF-01/RF-02 (error): credenciales rechazadas → AuthenticationError sin reintentos."""
    recorder = Recorder(error_response(status))
    with pytest.raises(AuthenticationError) as info:
        make_tracker(recorder).search("project = DEMO")
    assert info.value.service == "jira"
    assert len(recorder.requests) == 1
    assert_safe_message(info.value)


def test_search_retries_page_with_same_token_when_429() -> None:
    """§8: un 429 en la 2.ª página se reintenta tras Retry-After con el mismo token."""
    recorder = Recorder(
        search_page(issues_range(1, 2), token="token-ficticio-1"),
        error_response(429, {"Retry-After": "1"}),
        search_page(issues_range(3, 1)),
    )
    sleep = RecordingSleep()
    results = make_tracker(recorder, sleep).search("project = DEMO", limit=10)
    assert keys(results) == ["DEMO-1", "DEMO-2", "DEMO-3"]
    assert sleep.waits == [1.0]
    assert len(recorder.requests) == 3
    assert recorder.requests[1].url.params == recorder.requests[2].url.params
    assert recorder.requests[2].url.params["nextPageToken"] == "token-ficticio-1"


def test_search_raises_rate_limit_when_429_persists() -> None:
    """§8 (error): 429 persistente → RateLimitError tras max_retries."""
    recorder = Recorder(error_response(429, {"Retry-After": "1"}))
    with pytest.raises(RateLimitError) as info:
        make_tracker(recorder, max_retries=1).search("project = DEMO")
    assert info.value.service == "jira"
    assert len(recorder.requests) == 2
    assert_safe_message(info.value)


# --- list_epics y list_children (T-14, RF-02) --------------------------------------------------


def test_list_epics_sends_hierarchy_level_jql_with_quoted_project() -> None:
    """RF-02: épicas con `project = "KEY" AND hierarchyLevel = 1 ORDER BY key`."""
    recorder = Recorder(search_page([fake_issue(1)], is_last=True))
    results = make_tracker(recorder).list_epics("DEMO")
    assert keys(results) == ["DEMO-1"]
    params = recorder.requests[0].url.params
    assert recorder.requests[0].url.path == SEARCH_PATH
    assert params["jql"] == 'project = "DEMO" AND hierarchyLevel = 1 ORDER BY key'
    assert params["maxResults"] == str(PAGE_SIZE)
    assert params["fields"] == SEARCH_FIELDS


def test_list_epics_follows_pagination() -> None:
    """RF-02: list_epics recorre todas las páginas."""
    recorder = Recorder(
        search_page([fake_issue(1)], token="token-ficticio-1"),
        search_page([fake_issue(6)], is_last=True),
    )
    assert keys(make_tracker(recorder).list_epics("DEMO")) == ["DEMO-1", "DEMO-6"]
    assert recorder.requests[1].url.params["nextPageToken"] == "token-ficticio-1"


INVALID_PROJECT_KEYS = [
    pytest.param("demo", id="minusculas"),
    pytest.param("DE MO", id="espacio"),
    pytest.param('DEMO"', id="comilla"),
    pytest.param('DEMO" OR project = "OTRO', id="inyeccion-comillas"),
    pytest.param("DEMO OR project = OTRO", id="inyeccion-or"),
    pytest.param("", id="vacia"),
    pytest.param("D", id="una-letra"),
    pytest.param("DEMO\n", id="salto-final"),
    pytest.param("DEMO-1", id="clave-de-incidencia"),
]


@pytest.mark.parametrize("project", INVALID_PROJECT_KEYS)
def test_list_epics_raises_not_found_without_request_when_project_invalid(project: str) -> None:
    """§11 (error): clave de proyecto no válida → NotFoundError sin llamar a Jira."""
    with pytest.raises(NotFoundError) as info:
        make_tracker(fail_if_called).list_epics(project)
    assert info.value.service == "jira"
    assert_safe_message(info.value)


def test_list_epics_error_message_is_truncated() -> None:
    """§11: el mensaje no repite entradas arbitrariamente largas."""
    with pytest.raises(NotFoundError) as info:
        make_tracker(fail_if_called).list_epics("x" * 500)
    assert len(str(info.value)) < 120


def test_list_children_sends_parent_jql() -> None:
    """RF-02: HU hijas con `parent = KEY ORDER BY key`."""
    recorder = Recorder(search_page(issues_range(2, 4), is_last=True))
    results = make_tracker(recorder).list_children("DEMO-1")
    assert keys(results) == ["DEMO-2", "DEMO-3", "DEMO-4", "DEMO-5"]
    params = recorder.requests[0].url.params
    assert params["jql"] == "parent = DEMO-1 ORDER BY key"
    assert params["maxResults"] == str(PAGE_SIZE)
    assert params["fields"] == SEARCH_FIELDS


def test_list_children_returns_empty_when_epic_has_no_children() -> None:
    """RF-02: épica sin hijas → lista vacía."""
    assert make_tracker(Recorder(search_page([], is_last=True))).list_children("DEMO-1") == []


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("demo-1", id="minusculas"),
        pytest.param("DEMO", id="sin-numero"),
        pytest.param("DEMO-1 OR project = X", id="inyeccion-or"),
        pytest.param("DEMO-1\n", id="salto-final"),
        pytest.param("DEMO-1 ORDER BY key", id="order-by"),
        pytest.param("", id="vacia"),
    ],
)
def test_list_children_raises_not_found_without_request_when_key_invalid(key: str) -> None:
    """§11 (error): clave de épica no válida → NotFoundError sin llamar a Jira."""
    with pytest.raises(NotFoundError) as info:
        make_tracker(fail_if_called).list_children(key)
    assert info.value.service == "jira"
    assert_safe_message(info.value)


def test_list_children_raises_external_error_when_400() -> None:
    """RF-02 (error): un 400 en list_children se traduce al mensaje de JQL no válida."""
    with pytest.raises(ExternalServiceError, match="consulta JQL no es válida"):
        make_tracker(Recorder(error_response(400))).list_children("DEMO-1")


# --- list_projects (SPEC-00 v1.3, RF-02) ------------------------------------------------


def project_page(keys: list[str], *, is_last: bool) -> httpx.Response:
    values = [{"key": key, "name": f"Proyecto ficticio {key}"} for key in keys]
    return httpx.Response(200, json={"values": values, "isLast": is_last})


def test_list_projects_maps_key_and_name() -> None:
    recorder = Recorder(project_page(["DEMO", "OTRO"], is_last=True))
    projects = make_tracker(recorder).list_projects()
    assert [(p.key, p.name) for p in projects] == [
        ("DEMO", "Proyecto ficticio DEMO"),
        ("OTRO", "Proyecto ficticio OTRO"),
    ]
    (request,) = recorder.requests
    assert request.url.path == "/rest/api/3/project/search"
    assert request.url.params["startAt"] == "0"


def test_list_projects_follows_start_at_until_is_last() -> None:
    recorder = Recorder(
        project_page(["AAA", "BBB"], is_last=False), project_page(["CCC"], is_last=True)
    )
    projects = make_tracker(recorder).list_projects()
    assert [p.key for p in projects] == ["AAA", "BBB", "CCC"]
    assert [r.url.params["startAt"] for r in recorder.requests] == ["0", "2"]


def test_list_projects_stops_on_empty_page_and_skips_entries_without_key() -> None:
    recorder = Recorder(
        httpx.Response(200, json={"values": [{"name": "sin clave"}, {"key": "DEMO"}]}),
    )
    assert [p.key for p in make_tracker(recorder).list_projects()] == ["DEMO"]


def test_list_projects_raises_authentication_error_when_401() -> None:
    with pytest.raises(AuthenticationError):
        make_tracker(Recorder(error_response(401))).list_projects()


def test_list_projects_is_bounded_when_pages_never_have_keys() -> None:
    endless = httpx.Response(200, json={"values": [{"name": "x"}] * 100, "isLast": False})
    recorder = Recorder(endless)
    assert make_tracker(recorder).list_projects() == []
    assert len(recorder.requests) == tracker_module.MAX_RESULTS // tracker_module.PAGE_SIZE
