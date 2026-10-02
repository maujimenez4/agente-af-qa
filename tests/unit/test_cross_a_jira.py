"""Prueba cruzada T-35 (RNF-19): el área B prueba `adapters/jira/` del área A (T-11, T-14, T-27).

Cubre RF-02 (búsqueda `/rest/api/3/search/jql` con `nextPageToken`/`isLast`, proyectos, épicas e
HU hijas), RF-03 (`get_issue`: ADF → texto y relaciones), RF-04…RF-06 (`create_story`,
`update_story` con comentario del diff, `link`), RNF-13 (la escritura parcial se informa),
RNF-04 (https obligatorio y gateway con `cloudId`), SPEC-00 §4, §8 (errores envueltos, backoff
solo en lecturas, ADF) y las filas «Jira y scopes», `list_projects` y `create_story` del anexo
§11, más el principio 2 de CLAUDE.md (ni secretos ni cuerpos de respuesta en mensajes ni logs).

Se centra en los bordes que `test_jira_*.py` no fija: redirecciones en lecturas, token de página
repetido, respuestas 2xx con forma inesperada, backoff acotado con muchos reintentos,
`Retry-After` raros, `cloudId` fuera de los mensajes, claves con recorridos de ruta, Markdown
hostil (enlaces ofuscados, bidi, tamaño, backtracking de expresiones regulares) y redirecciones
307 en las tres escrituras.

Sin red: todo el HTTP pasa por `httpx.MockTransport` y `sleep` se sustituye por un registro.
Datos 100 % ficticios (proyecto DEMO, dominio example.com, credenciales «de prueba»). Los
defectos confirmados van como `xfail(strict=True)` con su PA; el resto fija el comportamiento.
"""

import base64
import json
import logging
import math
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from adapters.errors import (
    AgentError,
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    PublishError,
    RateLimitError,
)
from adapters.jira.adf import MAX_MARKDOWN_CHARS, Node, markdown_to_adf
from adapters.jira.story_template import prefixed_summary, story_to_adf
from adapters.jira.tracker import MAX_RESULTS, PAGE_SIZE, JiraCloudTracker
from tests.fakes.dataset import EPIC_KEY, PROJECT_KEY, renewal_story

BASE_URL = "https://demo-ficticio.example"
EMAIL = "persona.ficticia@example.com"
TOKEN = "token-de-prueba-ficticio-0000"
CLOUD_ID = "nube-ficticia-0000"
BODY_MARKER = "CUERPO-RESPUESTA-FICTICIO-7f3a"
BASIC = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
SEARCH_PATH = "/rest/api/3/search/jql"
FORBIDDEN = (TOKEN, EMAIL, BASIC, BODY_MARKER, CLOUD_ID)

Responder = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


# --- utilidades --------------------------------------------------------------------------


class Sleeps:
    """Sustituto de `time.sleep`: registra las esperas sin dormir."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


class Script:
    """Handler de `MockTransport`: registra peticiones y responde en orden (la última se repite)."""

    def __init__(self, *responses: Responder) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses[min(len(self.requests), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        if callable(response) and not isinstance(response, httpx.Response):
            return response(request)
        return response


def _tracker(
    script: Script,
    sleeps: Sleeps | None = None,
    *,
    base_url: str = BASE_URL,
    cloud_id: str | None = None,
    max_retries: int = 2,
    max_wait_s: float = 30.0,
    follow_redirects: bool = False,
    timeout: float = 30.0,
) -> JiraCloudTracker:
    client = httpx.Client(transport=httpx.MockTransport(script), follow_redirects=follow_redirects)
    return JiraCloudTracker(
        base_url,
        SecretStr(EMAIL),
        SecretStr(TOKEN),
        cloud_id=SecretStr(cloud_id) if cloud_id else None,
        http_client=client,
        max_retries=max_retries,
        max_wait_s=max_wait_s,
        sleep=sleeps or Sleeps(),
        timeout=timeout,
    )


def _no_http(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"No debería haber petición HTTP: {request.method} {request.url.path}")


def _error(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    body = {"errorMessages": [f"{BODY_MARKER} {EMAIL} {TOKEN} {CLOUD_ID}"], "errors": {}}
    return httpx.Response(status, json=body, headers=headers)


def _safe(exc: BaseException) -> None:
    message = str(exc)
    assert message.strip()
    for forbidden in FORBIDDEN:
        assert forbidden not in message, forbidden
    assert "Authorization" not in message
    assert "Basic " not in message


def _issue(key: str, summary: str = "Resumen ficticio") -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "issuetype": {"name": "Historia"},
            "status": {"name": "Por hacer"},
        },
    }


def _page(keys: list[str], token: str | None = None, is_last: bool | None = None) -> httpx.Response:
    body: dict[str, Any] = {"issues": [_issue(k) for k in keys]}
    if token is not None:
        body["nextPageToken"] = token
    if is_last is not None:
        body["isLast"] = is_last
    return httpx.Response(200, json=body)


def _params(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.url.query.decode(), keep_blank_values=True)


def _walk(node: Any) -> Iterator[Node]:
    if isinstance(node, dict):
        yield node
        for child in node.get("content") or []:
            yield from _walk(child)


def _texts(node: Node) -> list[str]:
    return [n["text"] for n in _walk(node) if n.get("type") == "text"]


def _hrefs(node: Node) -> list[str]:
    return [
        mark["attrs"]["href"]
        for n in _walk(node)
        for mark in n.get("marks") or []
        if mark.get("type") == "link"
    ]


ALLOWED_NODES = {
    "doc",
    "paragraph",
    "text",
    "hardBreak",
    "heading",
    "bulletList",
    "orderedList",
    "listItem",
    "table",
    "tableRow",
    "tableHeader",
    "tableCell",
    "codeBlock",
    "rule",
}
ALLOWED_MARKS = {"strong", "code", "link"}
# Bidi_Control de Unicode (Trojan Source, CVE-2021-42574) más otros invisibles que reordenan.
REMOVED_INVISIBLES = [
    "‪",
    "‫",
    "‬",
    "‭",
    "‮",
    "⁦",
    "⁧",
    "⁨",
    "⁩",
    "​",
    "﻿",
    "\x00",
    "\x1b",
    "\x7f",
    "\x85",
]
BIDI_MARKS = ["‎", "‏", "؜"]  # LRM, RLM y ALM: también Bidi_Control


# --- https, gateway y datos sensibles fuera de los mensajes (RNF-04, CLAUDE.md §2) --------


@pytest.mark.parametrize(
    "url",
    ["http://demo-ficticio.example", "ftp://demo-ficticio.example", "//demo-ficticio.example", ""],
)
def test_constructor_rejects_base_url_when_not_https(url: str) -> None:
    """RNF-04: con Basic auth, el sitio debe ser https; se rechaza antes de cualquier petición."""
    with pytest.raises(AuthenticationError) as excinfo:
        _tracker(Script(_no_http), base_url=url)
    assert "https://" in str(excinfo.value)
    assert excinfo.value.service == "jira"


def test_constructor_accepts_https_when_scheme_uppercase() -> None:
    """RNF-04: el esquema no distingue mayúsculas."""
    script = Script(httpx.Response(200, json={"values": []}))
    _tracker(script, base_url="HTTPS://demo-ficticio.example").test_connection()
    assert script.requests[0].url.scheme == "https"


def test_cloud_id_routes_every_call_to_https_gateway_when_base_url_is_not_used() -> None:
    """Anexo §11 «Jira y scopes»: con `cloudId` todo va a `api.atlassian.com/ex/jira/<id>`."""
    script = Script(httpx.Response(200, json={"values": [], "isLast": True}))
    tracker = _tracker(script, cloud_id=CLOUD_ID)
    tracker.test_connection()
    tracker.list_projects()
    for request in script.requests:
        assert request.url.scheme == "https"
        assert request.url.host == "api.atlassian.com"
        assert request.url.path.startswith(f"/ex/jira/{CLOUD_ID}/rest/api/3/")


@pytest.mark.parametrize(
    "response",
    [_error(400), _error(401), _error(404), _error(429), _error(503), httpx.ConnectError("x")],
)
def test_read_errors_never_reveal_cloud_id_body_or_credentials_when_gateway(
    response: Responder,
) -> None:
    """CLAUDE.md §2 y §8: el `cloudId` (dato de tenant) no aparece en los mensajes de error."""
    tracker = _tracker(Script(response), cloud_id=CLOUD_ID, max_retries=0)
    with pytest.raises(ExternalServiceError) as excinfo:
        tracker.search("project = DEMO")
    _safe(excinfo.value)
    assert excinfo.value.service == "jira"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_write_errors_never_reveal_cloud_id_body_or_credentials_when_gateway(status: int) -> None:
    """CLAUDE.md §2 y §8: tampoco en las escrituras."""
    tracker = _tracker(Script(_error(status)), cloud_id=CLOUD_ID)
    with pytest.raises(AgentError) as excinfo:
        tracker.create_story(renewal_story(None), EPIC_KEY, PROJECT_KEY)
    _safe(excinfo.value)


def test_network_errors_do_not_chain_httpx_exception_when_wrapped() -> None:
    """§8: el error envuelto no arrastra la petición (con `Authorization`) como causa visible."""
    tracker = _tracker(Script(httpx.ConnectError("fallo ficticio")), max_retries=0)
    with pytest.raises(ExternalServiceError) as excinfo:
        tracker.get_issue("DEMO-3")
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


def test_logs_never_contain_credentials_when_reads_and_writes_fail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CLAUDE.md §2: ni token, ni email, ni Basic, ni cuerpo de respuesta en ningún registro."""
    caplog.set_level(logging.DEBUG)
    tracker = _tracker(Script(_error(500)), max_retries=1)
    with capture_logs() as structured:
        with pytest.raises(ExternalServiceError):
            tracker.search("project = DEMO")
        with pytest.raises(PublishError):
            tracker.create_story(renewal_story(None), EPIC_KEY, PROJECT_KEY)
        with pytest.raises(ExternalServiceError):
            tracker.link("DEMO-3", "DEMO-2", "relates to", "Motivo ficticio")
    dumped = "\n".join(r.getMessage() for r in caplog.records) + json.dumps(structured, default=str)
    for forbidden in (TOKEN, EMAIL, BASIC, BODY_MARKER):
        assert forbidden not in dumped


# --- lecturas: reintentos y backoff acotados (§8) ------------------------------------------


def test_read_backoff_waits_never_exceed_max_wait_when_many_retries() -> None:
    """§8: el backoff exponencial se recorta a `max_wait_s` y el número de intentos es finito."""
    script = Script(_error(503))
    sleeps = Sleeps()
    tracker = _tracker(script, sleeps, max_retries=6, max_wait_s=3.0)
    with pytest.raises(ExternalServiceError) as excinfo:
        tracker.test_connection()
    assert len(script.requests) == 7
    assert sleeps.waits == [1.0, 2.0, 3.0, 3.0, 3.0, 3.0]
    assert "HTTP 503" in str(excinfo.value)
    _safe(excinfo.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout("t"), httpx.ConnectTimeout("t")])
def test_read_timeout_is_retried_then_wrapped_in_spanish_when_persists(error: Exception) -> None:
    """§8: un timeout de lectura se reintenta con backoff y acaba en `ExternalServiceError`."""
    script = Script(error)
    sleeps = Sleeps()
    with pytest.raises(ExternalServiceError) as excinfo:
        _tracker(script, sleeps).get_issue("DEMO-3")
    assert len(script.requests) == 3
    assert sleeps.waits == [1.0, 2.0]
    assert "No se pudo conectar con Jira" in str(excinfo.value)


def test_every_request_carries_the_configured_finite_timeout() -> None:
    """§8: ninguna petición (lectura o escritura) puede quedarse esperando sin límite."""
    script = Script(
        _page(["DEMO-2"], is_last=True),
        httpx.Response(201, json={"key": "DEMO-40"}),
    )
    tracker = _tracker(script, timeout=7.5)
    tracker.search("project = DEMO")
    tracker.create_story(renewal_story(None), EPIC_KEY, PROJECT_KEY)
    for request in script.requests:
        values = request.extensions["timeout"].values()
        assert values and all(v is not None and math.isfinite(v) and v <= 7.5 for v in values)


@pytest.mark.parametrize(
    ("header", "expected"),
    [("0", 0.0), ("-5", 0.0), ("pronto-ficticio", None), ("Fri, 02 Oct 2026 07:28:00 GMT", None)],
)
def test_read_429_handles_odd_retry_after_when_retries_exhausted(
    header: str, expected: float | None
) -> None:
    """§8: `Retry-After` negativo, no numérico o en fecha no rompe el backoff ni el error."""
    script = Script(httpx.Response(429, headers={"Retry-After": header}))
    sleeps = Sleeps()
    with pytest.raises(RateLimitError) as excinfo:
        _tracker(script, sleeps).search("project = DEMO")
    assert len(script.requests) == 3
    assert all(0.0 <= w <= 30.0 for w in sleeps.waits) and len(sleeps.waits) == 2
    assert excinfo.value.retry_after == expected
    assert "límite de peticiones" in str(excinfo.value)


def test_read_429_raises_without_sleeping_when_retry_after_is_infinite() -> None:
    """§8: una espera que supera `max_wait_s` no se duerme; se informa con `retry_after`."""
    script = Script(httpx.Response(429, headers={"Retry-After": "inf"}))
    sleeps = Sleeps()
    with pytest.raises(RateLimitError) as excinfo:
        _tracker(script, sleeps).list_projects()
    assert len(script.requests) == 1
    assert sleeps.waits == []
    assert excinfo.value.retry_after == math.inf


@pytest.mark.parametrize("status", [405, 409, 410, 422])
def test_read_other_4xx_is_not_retried_and_wrapped_when_client_error(status: int) -> None:
    """§8: solo 429 y 5xx se reintentan; el resto de 4xx falla a la primera y sin cuerpo."""
    script = Script(_error(status))
    sleeps = Sleeps()
    with pytest.raises(ExternalServiceError) as excinfo:
        _tracker(script, sleeps).get_issue("DEMO-3")
    assert len(script.requests) == 1 and sleeps.waits == []
    assert f"HTTP {status}" in str(excinfo.value)
    _safe(excinfo.value)


# --- lecturas: redirecciones (PA-183) ------------------------------------------------------


REDIRECT = httpx.Response(302, headers={"Location": "https://otro-sitio.example/login"})


@pytest.mark.parametrize("operation", ["test_connection", "search", "get_issue", "list_projects"])
def test_read_fails_with_external_error_when_jira_answers_redirect(operation: str) -> None:
    """RF-01/RF-02 y §8: un 3xx (URL del sitio mal puesta) no puede parecer un éxito vacío."""
    tracker = _tracker(Script(REDIRECT))
    calls: dict[str, Callable[[], object]] = {
        "test_connection": tracker.test_connection,
        "search": lambda: tracker.search("project = DEMO"),
        "get_issue": lambda: tracker.get_issue("DEMO-3"),
        "list_projects": tracker.list_projects,
    }
    with pytest.raises(ExternalServiceError):
        calls[operation]()


def test_read_does_not_follow_redirect_when_injected_client_follows_redirects() -> None:
    """§8: como en las escrituras, una lectura no se reenvía a otro sitio."""
    script = Script(REDIRECT, _page(["OTRO-1"], is_last=True))
    tracker = _tracker(script, follow_redirects=True)
    with pytest.raises(ExternalServiceError):
        tracker.search("project = DEMO")
    assert len(script.requests) == 1


# --- search: /search/jql con nextPageToken (RF-02, CLAUDE.md) ------------------------------


def test_search_uses_search_jql_get_without_start_at_when_paginating() -> None:
    """CLAUDE.md: `/rest/api/3/search/jql` con `nextPageToken`; nunca `startAt` ni `/search`."""
    script = Script(_page(["DEMO-2"], token="tk-1"), _page(["DEMO-3"], is_last=True))
    _tracker(script).search("project = DEMO")
    assert [r.url.path for r in script.requests] == [SEARCH_PATH, SEARCH_PATH]
    for request in script.requests:
        assert request.method == "GET"
        assert request.content == b""
        assert "startAt" not in _params(request)


def test_search_keeps_jql_verbatim_and_maxresults_shrinks_when_paginating() -> None:
    """RF-02: la JQL viaja igual en cada página (sin inyectar parámetros); la última pide menos."""
    jql = 'summary ~ "préstamo & renovación" AND text ~ "a=b&maxResults=5000"'
    script = Script(
        _page([f"DEMO-{n}" for n in range(1, 101)], token="tk-1"),
        _page([f"DEMO-{n}" for n in range(101, 151)], is_last=True),
    )
    results = _tracker(script).search(jql, limit=150)
    assert len(results) == 150
    first, second = (_params(r) for r in script.requests)
    assert first["jql"] == [jql] and second["jql"] == [jql]
    assert first["maxResults"] == [str(PAGE_SIZE)] and second["maxResults"] == ["50"]
    assert "nextPageToken" not in first and second["nextPageToken"] == ["tk-1"]


def test_search_sends_each_page_the_token_of_the_previous_page() -> None:
    """RF-02: cada página usa el `nextPageToken` recibido en la anterior, no el primero."""
    script = Script(
        _page(["DEMO-2"], token="tk-a"),
        _page(["DEMO-3"], token="tk-b"),
        _page(["DEMO-4"], token="tk-c", is_last=True),
    )
    results = _tracker(script).search("project = DEMO")
    tokens = [_params(r).get("nextPageToken") for r in script.requests]
    assert tokens == [None, ["tk-a"], ["tk-b"]]
    assert [r.key for r in results] == ["DEMO-2", "DEMO-3", "DEMO-4"]


def test_search_requests_one_result_when_limit_is_one() -> None:
    """Límite inferior: `limit=1` pide una sola incidencia y no pagina aunque haya token."""
    script = Script(_page(["DEMO-2", "DEMO-3"], token="tk-1"))
    results = _tracker(script).search("project = DEMO", limit=1)
    assert [r.key for r in results] == ["DEMO-2"]
    assert len(script.requests) == 1
    assert _params(script.requests[0])["maxResults"] == ["1"]


def test_search_is_bounded_by_max_results_when_token_repeats_forever() -> None:
    """RF-02: un token que se repite nunca provoca un bucle infinito (como mucho, el tope)."""
    script = Script(_page(["DEMO-2"], token="tk-repetido", is_last=False))
    results = _tracker(script).list_epics(PROJECT_KEY)
    assert len(script.requests) <= MAX_RESULTS
    assert len(results) <= MAX_RESULTS


def test_search_stops_without_duplicates_when_next_page_token_repeats() -> None:
    """RF-02: si Jira (o un proxy) repite el token, se para y no se duplican incidencias."""
    script = Script(_page(["DEMO-2"], token="tk-repetido", is_last=False))
    results = _tracker(script).list_epics(PROJECT_KEY)
    assert len(script.requests) <= 2
    keys = [r.key for r in results]
    assert len(keys) == len(set(keys))


# --- list_projects, list_epics y list_children (RF-02, anexo §11) ---------------------------


def test_list_projects_advances_start_at_by_values_received() -> None:
    """Anexo §11 `list_projects`: `/project/search` paginado con `startAt` según lo recibido."""
    script = Script(
        httpx.Response(
            200,
            json={"values": [{"key": "DEMO", "name": "D"}, {"key": "PRUEBA"}], "isLast": False},
        ),
        httpx.Response(200, json={"values": [{"key": "ZETA", "name": None}], "isLast": True}),
    )
    projects = _tracker(script).list_projects()
    assert [(p.key, p.name) for p in projects] == [("DEMO", "D"), ("PRUEBA", ""), ("ZETA", "")]
    assert [_params(r)["startAt"] for r in script.requests] == [["0"], ["2"]]
    assert all(r.url.path == "/rest/api/3/project/search" for r in script.requests)


def test_list_projects_stops_after_first_page_when_is_last_missing() -> None:
    """Anexo §11: sin `isLast` se asume la última página (lado seguro: no se itera a ciegas)."""
    script = Script(httpx.Response(200, json={"values": [{"key": "DEMO", "name": "D"}]}))
    assert [p.key for p in _tracker(script).list_projects()] == ["DEMO"]
    assert len(script.requests) == 1


@pytest.mark.parametrize("project", ["demo", 'DEMO" OR project = "OTRO', "DEMO-1", "DEMO\n", "D"])
def test_list_epics_rejects_project_without_request_when_invalid_or_injected(project: str) -> None:
    """RF-02: la clave del proyecto se valida antes de construir la JQL (sin inyección)."""
    with pytest.raises(NotFoundError) as excinfo:
        _tracker(Script(_no_http)).list_epics(project)
    assert "no es una clave de proyecto válida" in str(excinfo.value)


def test_list_children_uses_parent_jql_and_full_page_size_when_valid_epic() -> None:
    """RF-02: HU hijas con `parent = <épica>` y páginas de `PAGE_SIZE` hasta el tope."""
    script = Script(_page(["DEMO-2", "DEMO-3"], is_last=True))
    children = _tracker(script).list_children(EPIC_KEY)
    params = _params(script.requests[0])
    assert params["jql"] == [f"parent = {EPIC_KEY} ORDER BY key"]
    assert params["maxResults"] == [str(PAGE_SIZE)]
    assert [c.key for c in children] == ["DEMO-2", "DEMO-3"]


@pytest.mark.parametrize(
    "key", ["DEMO-1 OR project = OTRO", "DEMO-1\n", "../DEMO-1", "DEMO-1/../../myself"]
)
def test_list_children_rejects_key_without_request_when_injected(key: str) -> None:
    """RF-02: la clave va sin comillas en la JQL; si no es una clave exacta, no hay petición."""
    with pytest.raises(NotFoundError):
        _tracker(Script(_no_http)).list_children(key)


# --- get_issue: ADF → texto y relaciones (RF-03) -------------------------------------------


@pytest.mark.parametrize(
    "key", ["DEMO-1/../../myself", "../DEMO-1", "DEMO-1?expand=all", "DEMO-1#x", "DEMO-1\n", ""]
)
def test_get_issue_rejects_key_without_request_when_path_traversal_or_query(key: str) -> None:
    """§8: la clave entra en la ruta; no se puede salir de `/issue/{key}` ni añadir parámetros."""
    with pytest.raises(NotFoundError) as excinfo:
        _tracker(Script(_no_http)).get_issue(key)
    assert "no es una clave de Jira válida" in str(excinfo.value)


def test_get_issue_maps_relations_and_skips_links_without_issue() -> None:
    """RF-03: padre, subtareas, vínculos en ambos sentidos, etiquetas; un vínculo vacío se omite."""
    payload = {
        "key": "DEMO-3",
        "fields": {
            "summary": "[HU-02] Renovar un préstamo",
            "issuetype": {"name": "Historia"},
            "status": {"name": "En curso"},
            "parent": {"key": EPIC_KEY},
            "subtasks": [_issue("DEMO-31", "[CP-01] Caso ficticio")],
            "issuelinks": [
                {"type": {"outward": "relates to"}, "outwardIssue": {"key": "DEMO-2"}},
                {"type": {"inward": "is blocked by"}, "inwardIssue": {"key": "DEMO-4"}},
                {"type": {"outward": "relates to"}},
            ],
            "labels": ["ficticia"],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Texto ficticio"}]}
                ],
            },
        },
    }
    detail = _tracker(Script(httpx.Response(200, json=payload))).get_issue("DEMO-3")
    assert detail.parent_key == EPIC_KEY
    assert [s.key for s in detail.subtasks] == ["DEMO-31"]
    assert [(link.link_type, link.key) for link in detail.links] == [
        ("relates to", "DEMO-2"),
        ("is blocked by", "DEMO-4"),
    ]
    assert detail.description_text == "Texto ficticio"
    assert detail.labels == ["ficticia"]


def test_get_issue_404_names_the_key_without_body_when_missing() -> None:
    """§8: 404 → `NotFoundError` en español con la clave pedida y sin el cuerpo de Jira."""
    with pytest.raises(NotFoundError) as excinfo:
        _tracker(Script(_error(404))).get_issue("DEMO-999")
    assert "DEMO-999" in str(excinfo.value)
    _safe(excinfo.value)


MALFORMED_ISSUES = {
    "json-lista": [],
    "descripcion-texto": {"key": "DEMO-3", "fields": {"description": "texto v2 ficticio"}},
    "subtarea-texto": {"key": "DEMO-3", "fields": {"subtasks": ["DEMO-31"]}},
    "vinculo-sin-clave": {
        "key": "DEMO-3",
        "fields": {"issuelinks": [{"type": {"outward": "x"}, "outwardIssue": {"id": "1"}}]},
    },
}


@pytest.mark.parametrize("body", MALFORMED_ISSUES.values(), ids=MALFORMED_ISSUES.keys())
def test_get_issue_wraps_unexpected_payload_in_external_error(body: Any) -> None:
    """§8: todo fallo de Jira llega a la UI como `ExternalServiceError` en español."""
    with pytest.raises(ExternalServiceError):
        _tracker(Script(httpx.Response(200, json=body))).get_issue("DEMO-3")


@pytest.mark.parametrize("body", [[], {"issues": {"DEMO-2": {}}}], ids=["lista", "issues-objeto"])
def test_search_wraps_unexpected_page_in_external_error(body: Any) -> None:
    """§8: la búsqueda tampoco deja escapar excepciones de Python a la UI."""
    with pytest.raises(ExternalServiceError):
        _tracker(Script(httpx.Response(200, json=body))).search("project = DEMO")


# --- ADF seguro: markdown_to_adf y plantilla (SPEC-00 §8, PA-49) ---------------------------


HOSTILE_MARKDOWN = [
    "[clic](javascript:alert(1))",
    "[clic](JaVaScRiPt:alert(1))",
    "[clic](\x01javascript:alert(1))",
    "[clic](java\tscript:alert(1))",
    "[clic](data:text/html;base64,PHNjcmlwdD4=)",
    "[clic](vbscript:msgbox)",
    "[clic](file:///etc/passwd)",
    "[clic](//sitio-ajeno.example/x)",
    "[clic](https:sin-host)",
    "[clic](mailto:persona.ficticia@example.com)",
    "<a href='javascript:alert(1)'>x</a> <img src=x onerror=alert(1)>",
    "| <script>alert(1)</script> | [x](javascript:y) |\n|---|---|\n| a \\| b | **c** |",
    "**[x](https://ok.example)** `[y](javascript:z)` [w](https://ok.example/‮exe.fdp)",
    "- [a](javascript:x)\n  - <b>b</b>\n1. ```\n```js\n<script>\n```",
]


@pytest.mark.parametrize("md", HOSTILE_MARKDOWN)
def test_markdown_to_adf_emits_only_allowlisted_nodes_marks_and_https_links(md: str) -> None:
    """PA-49 y §8: solo nodos y marcas conocidos, enlaces http(s) con host y sin texto vacío."""
    adf = markdown_to_adf(md)
    for node in _walk(adf):
        assert node["type"] in ALLOWED_NODES, node["type"]
        for mark in node.get("marks") or []:
            assert mark["type"] in ALLOWED_MARKS
        if node["type"] == "text":
            assert node["text"]
    for href in _hrefs(adf):
        assert href.startswith(("http://", "https://")) and "‮" not in href


def test_markdown_to_adf_keeps_html_as_literal_text_when_tags() -> None:
    """PA-49: el HTML se publica como texto, sin interpretarse."""
    adf = markdown_to_adf("<img src=x onerror=alert(1)>")
    assert _texts(adf) == ["<img src=x onerror=alert(1)>"]


@pytest.mark.parametrize("char", REMOVED_INVISIBLES, ids=[hex(ord(c)) for c in REMOVED_INVISIBLES])
def test_markdown_to_adf_removes_control_and_bidi_override_chars(char: str) -> None:
    """PA-49: los caracteres de control y de reordenación bidi no llegan a Jira."""
    adf = markdown_to_adf(f"| a{char}b | [c{char}](https://ok.example/{char}) |")
    assert all(char not in t for t in _texts(adf))
    assert all(char not in h for h in _hrefs(adf))


@pytest.mark.parametrize("char", BIDI_MARKS, ids=[hex(ord(c)) for c in BIDI_MARKS])
def test_bidi_marks_are_removed_from_adf_and_summary(char: str) -> None:
    """PA-49: ningún carácter Bidi_Control altera el orden visual de lo publicado."""
    assert all(char not in t for t in _texts(markdown_to_adf(f"Texto {char}ficticio")))
    assert char not in prefixed_summary("HU-01", f"Título {char}ficticio")


@pytest.mark.parametrize(
    ("row", "cells"),
    [
        ("| a \\| b | c |", ["a | b", "c"]),
        ("|a|b|", ["a", "b"]),
        ("| | |", ["", ""]),
        ("| sin cierre", ["sin cierre"]),
        ("| **neg|rita** | x |", ["**neg", "rita**", "x"]),
    ],
)
def test_markdown_to_adf_splits_cells_only_on_unescaped_pipes(row: str, cells: list[str]) -> None:
    """PA-49: `\\|` es una barra literal; las `|` sin escapar separan celdas."""
    table = markdown_to_adf(row)["content"][0]
    assert table["type"] == "table"
    got = ["".join(_texts(cell)) for cell in table["content"][0]["content"]]
    assert got == cells


def test_markdown_to_adf_caps_published_text_when_input_exceeds_max() -> None:
    """§8: un comentario enorme se trunca a `MAX_MARKDOWN_CHARS` antes de convertir."""
    adf = markdown_to_adf("x" * (MAX_MARKDOWN_CHARS + 50_000))
    assert sum(len(t) for t in _texts(adf)) == MAX_MARKDOWN_CHARS


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-187): `_TABLE_SEPARATOR` tiene backtracking cuadrático (`\\s*` "
        "adyacentes); una segunda fila de tabla «| -» + espacios + «x» de 20 000 caracteres "
        "tarda >1 s y una de 100 000 (el tope) decenas de segundos (adapters/jira/adf.py:230, 354)"
    ),
)
def test_markdown_to_adf_runs_in_linear_time_when_table_separator_is_pathological() -> None:
    """§8: el comentario del diff (texto no fiable) no puede bloquear la publicación."""
    md = "| a |\n| -" + " " * 20_000 + "x"
    start = time.perf_counter()
    markdown_to_adf(md)
    assert time.perf_counter() - start < 0.5


def test_story_to_adf_publishes_markdown_in_fields_as_literal_text() -> None:
    """PA-49 y RF-15: lo que escribe el LLM en la HU no crea enlaces ni estructura."""
    story = renewal_story().model_copy(
        update={
            "description": "[clic](https://ok.example) **negrita** <script>x</script>\n# título",
            "assumptions": ["| a | b |", "```\ncódigo\n```"],
        }
    )
    adf = story_to_adf(story)
    assert _hrefs(adf) == []
    assert all(not n.get("marks") or n["marks"] == [{"type": "strong"}] for n in _walk(adf))
    assert "[clic](https://ok.example) **negrita** <script>x</script>" in _texts(adf)
    assert not any(n["type"] == "table" for n in _walk(adf))


# --- escritura: un solo intento, sin redirecciones, mismo proyecto (RF-04…RF-06, §8) --------


WRITE_CALLS: dict[str, Callable[[JiraCloudTracker], object]] = {
    "create": lambda t: t.create_story(renewal_story(None), EPIC_KEY, PROJECT_KEY),
    "update": lambda t: t.update_story("DEMO-3", renewal_story(), "**Cambios** ficticios"),
    "link": lambda t: t.link("DEMO-3", "DEMO-2", "relates to", "Motivo ficticio"),
}


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("operation", WRITE_CALLS)
def test_write_is_not_resent_when_redirect_and_client_follows_redirects(
    operation: str, status: int
) -> None:
    """§8: un 3xx (incluido 307/308, que reenviaría el cuerpo) falla sin reenviar la escritura."""
    script = Script(
        httpx.Response(status, headers={"Location": "https://otro-sitio.example/rest"}),
        httpx.Response(201, json={"key": "DEMO-40"}),
    )
    tracker = _tracker(script, follow_redirects=True)
    with pytest.raises(AgentError) as excinfo:
        WRITE_CALLS[operation](tracker)
    assert len(script.requests) == 1
    assert "redirección" in str(excinfo.value)
    _safe(excinfo.value)


@pytest.mark.parametrize("operation", WRITE_CALLS)
def test_write_429_reports_retry_after_without_retrying_or_sleeping(operation: str) -> None:
    """§8: la escritura no se reintenta ni espera; `retry_after` llega a quien publica."""
    script = Script(_error(429, headers={"Retry-After": "12"}))
    sleeps = Sleeps()
    with pytest.raises(AgentError) as excinfo:
        WRITE_CALLS[operation](_tracker(script, sleeps))
    assert len(script.requests) == 1 and sleeps.waits == []
    error = excinfo.value
    if operation == "update":  # el PUT falla antes del comentario: es el propio 429
        assert isinstance(error, RateLimitError)
    assert isinstance(error, RateLimitError) and error.retry_after == 12.0
    _safe(error)


@pytest.mark.parametrize("operation", WRITE_CALLS)
def test_write_timeout_is_not_retried_and_asks_to_check_jira(operation: str) -> None:
    """§8 y RNF-13: un timeout de escritura no se reintenta y avisa de comprobar Jira."""
    script = Script(httpx.ReadTimeout("t"))
    sleeps = Sleeps()
    with pytest.raises(AgentError) as excinfo:
        WRITE_CALLS[operation](_tracker(script, sleeps))
    assert len(script.requests) == 1 and sleeps.waits == []
    assert "Comprueba en Jira" in str(excinfo.value)


@pytest.mark.parametrize("epic", ["DEMOX-1", "DEMO_A-1", "XDEMO-1", "DEMO-1\n", "demo-1"])
def test_create_story_rejects_epic_without_request_when_other_project_or_lookalike(
    epic: str,
) -> None:
    """Anexo §11 `create_story`: la épica es del mismo proyecto (sin prefijos parecidos)."""
    with pytest.raises(PublishError):
        _tracker(Script(_no_http)).create_story(renewal_story(None), epic, PROJECT_KEY)


def test_create_story_posts_once_to_issue_endpoint_with_project_and_parent() -> None:
    """RF-04: una sola petición POST `/rest/api/3/issue` con proyecto, tipo y épica."""
    script = Script(httpx.Response(201, json={"id": "1", "key": "DEMO-40"}))
    key = _tracker(script).create_story(renewal_story(None), EPIC_KEY, PROJECT_KEY)
    assert key == "DEMO-40"
    (request,) = script.requests
    assert (request.method, request.url.path) == ("POST", "/rest/api/3/issue")
    fields = json.loads(request.content)["fields"]
    assert fields["project"] == {"key": PROJECT_KEY}
    assert fields["parent"] == {"key": EPIC_KEY}
    assert fields["summary"].startswith("[HU-02] ")


def test_update_story_comment_is_safe_adf_when_diff_is_hostile() -> None:
    """RF-05 y PA-49: el comentario del diff se publica en ADF seguro tras el PUT."""
    script = Script(httpx.Response(204), httpx.Response(201, json={"id": "9"}))
    diff = "| Campo | Antes |\n|---|---|\n| title | [x](javascript:y) <b>z</b> ‮ |"
    _tracker(script).update_story("DEMO-3", renewal_story(), diff)
    put, post = script.requests
    assert (put.method, put.url.path) == ("PUT", "/rest/api/3/issue/DEMO-3")
    assert (post.method, post.url.path) == ("POST", "/rest/api/3/issue/DEMO-3/comment")
    body = json.loads(post.content)["body"]
    assert body == markdown_to_adf(diff)
    assert _hrefs(body) == []
    assert all("‮" not in t for t in _texts(body))


@pytest.mark.parametrize("status", [401, 429, 500])
def test_update_story_reports_partial_publication_when_comment_fails(status: int) -> None:
    """RNF-13: si falla el comentario, se informa que la HU sí se actualizó (sin reintentar)."""
    script = Script(httpx.Response(204), _error(status))
    sleeps = Sleeps()
    with pytest.raises(PublishError) as excinfo:
        _tracker(script, sleeps).update_story("DEMO-3", renewal_story(), "**Cambios**")
    assert len(script.requests) == 2 and sleeps.waits == []
    assert "DEMO-3 se ha actualizado" in str(excinfo.value)
    _safe(excinfo.value)


def test_link_comment_is_safe_adf_and_link_type_is_relates() -> None:
    """RF-06 y D-09: vínculo «Relates» con comentario en ADF seguro."""
    script = Script(httpx.Response(201))
    _tracker(script).link("DEMO-3", "DEMO-2", "relates to", "Ver [x](javascript:y) <i>i</i>")
    body = json.loads(script.requests[0].content)
    assert body["type"] == {"name": "Relates"}
    assert _hrefs(body["comment"]["body"]) == []
    assert "<i>i</i>" in "".join(_texts(body["comment"]["body"]))


@pytest.mark.parametrize("link_type", ["blocks", "Relates", "relates to\n", "clones"])
def test_link_rejects_link_type_without_request_when_not_allowed(link_type: str) -> None:
    """D-09: solo «relates to» (el nombre interno, no el de la API)."""
    with pytest.raises(PublishError):
        _tracker(Script(_no_http)).link("DEMO-3", "DEMO-2", link_type)
