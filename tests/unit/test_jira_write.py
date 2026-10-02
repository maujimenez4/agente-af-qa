"""JiraCloudTracker de escritura (T-27: RF-04, RF-05, RF-06, PA-46; SPEC-00 §4, §8).

Sin red: todo el HTTP pasa por `httpx.MockTransport`. Las escrituras no se reintentan nunca
(§8): cada fallo hace exactamente una petición y no espera. Datos 100 % sintéticos;
credenciales obviamente de prueba (las de `test_jira_tracker`).
"""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from adapters.errors import (
    AgentError,
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    PublishError,
    RateLimitError,
)
from adapters.jira.adf import markdown_to_adf
from adapters.jira.story_template import story_summary, story_to_adf
from adapters.jira.tracker import STORY_ISSUE_TYPE, JiraCloudTracker
from tests.fakes.dataset import EPIC_KEY, PROJECT_KEY, renewal_story
from tests.unit.test_jira_tracker import (
    BASE_URL,
    BASIC_CREDENTIALS,
    BODY_MARKER,
    CLOUD_ID,
    DEMO_3_PAYLOAD,
    EMAIL,
    TOKEN,
    Recorder,
    RecordingSleep,
    assert_safe_message,
    error_response,
    fail_if_called,
    make_tracker,
)

ISSUE_PATH = "/rest/api/3/issue"
LINK_PATH = "/rest/api/3/issueLink"
DIFF_MD = "**Cambios**\n\n| Campo | Antes | Después |\n|---|---|---|\n| title | A | B |"


def created(key: str = "DEMO-20") -> httpx.Response:
    return httpx.Response(201, json={"id": "10020", "key": key, "self": "https://x.example"})


def no_content() -> httpx.Response:
    return httpx.Response(204)


def body_of(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def tracker_and_recorder(
    *responses: httpx.Response | Exception, cloud_id: SecretStr | None = None
) -> tuple[JiraCloudTracker, Recorder, RecordingSleep]:
    recorder = Recorder(*responses)
    sleep = RecordingSleep()
    return make_tracker(recorder, sleep, cloud_id=cloud_id), recorder, sleep


def no_http_tracker() -> JiraCloudTracker:
    return make_tracker(fail_if_called)


# Las tres escrituras, con los parámetros mínimos para llegar a la red.
WRITES = {
    "create": lambda t: t.create_story(renewal_story(None), EPIC_KEY, PROJECT_KEY),
    "update": lambda t: t.update_story("DEMO-3", renewal_story(), DIFF_MD),
    "link": lambda t: t.link("DEMO-3", "DEMO-2", "relates to", "Motivo ficticio"),
}
# Excepción esperada para errores 400/5xx/red/no JSON: create/update → PublishError; link →
# ExternalServiceError (el nodo publish solo captura ExternalServiceError en los vínculos).
GENERIC_FAILURE = {"create": PublishError, "update": PublishError, "link": ExternalServiceError}


# --- create_story (RF-04, R-05) --------------------------------------------------------------


def test_create_story_posts_issue_with_project_type_summary_description_and_parent() -> None:
    """RF-04, R-05: POST /issue con proyecto, tipo, título `[HU-XX]`, ADF y épica como parent."""
    tracker, recorder, _ = tracker_and_recorder(created())
    story = renewal_story(None)

    assert tracker.create_story(story, EPIC_KEY, PROJECT_KEY) == "DEMO-20"

    [request] = recorder.requests
    assert request.method == "POST"
    assert request.url.path == ISSUE_PATH
    fields = body_of(request)["fields"]
    assert fields["project"] == {"key": PROJECT_KEY}
    assert fields["issuetype"] == {"name": STORY_ISSUE_TYPE}
    assert fields["summary"] == "[HU-02] Renovar un préstamo"
    assert fields["summary"] == story_summary(story)
    assert fields["description"] == story_to_adf(story)
    assert fields["description"]["type"] == "doc"
    assert fields["description"]["version"] == 1
    assert fields["parent"] == {"key": EPIC_KEY}
    assert set(fields) == {"project", "issuetype", "summary", "description", "parent"}


def test_create_story_omits_parent_when_epic_is_none() -> None:
    """RF-04: sin épica, la HU se crea sin `parent`."""
    tracker, recorder, _ = tracker_and_recorder(created())
    tracker.create_story(renewal_story(None), None, PROJECT_KEY)
    assert "parent" not in body_of(recorder.requests[0])["fields"]


def test_create_story_sends_json_content_type_and_accept() -> None:
    """§8: la petición va en JSON."""
    tracker, recorder, _ = tracker_and_recorder(created())
    tracker.create_story(renewal_story(None), None, PROJECT_KEY)
    headers = recorder.requests[0].headers
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_create_story_uses_gateway_url_when_cloud_id() -> None:
    """RNF-04: con cloud_id, la escritura va al gateway de Atlassian."""
    tracker, recorder, _ = tracker_and_recorder(created(), cloud_id=SecretStr(CLOUD_ID))
    tracker.create_story(renewal_story(None), EPIC_KEY, PROJECT_KEY)
    assert str(recorder.requests[0].url) == (
        f"https://api.atlassian.com/ex/jira/{CLOUD_ID}/rest/api/3/issue"
    )


@pytest.mark.parametrize("project", ["", "demo", "DEMO-1", "1DEMO", "DE MO", 'DEMO" OR 1=1'])
def test_create_story_raises_publish_error_without_request_when_project_invalid(
    project: str,
) -> None:
    """RF-04 (negativa): un proyecto con formato inválido no llega a Jira."""
    with pytest.raises(PublishError) as info:
        no_http_tracker().create_story(renewal_story(None), None, project)
    assert str(info.value)


@pytest.mark.parametrize("epic_key", ["OTRO-1", "DEMOX-1", "demo-1", "DEMO", "DEMO-", "DEMO-1 "])
def test_create_story_raises_publish_error_without_request_when_epic_invalid_or_foreign(
    epic_key: str,
) -> None:
    """RF-04 (negativa): la épica debe ser una clave válida del mismo proyecto."""
    with pytest.raises(PublishError):
        no_http_tracker().create_story(renewal_story(None), epic_key, PROJECT_KEY)


def test_create_story_error_message_is_truncated_when_epic_key_huge() -> None:
    """RF-04: el mensaje no repite entradas arbitrariamente largas."""
    with pytest.raises(PublishError) as info:
        no_http_tracker().create_story(renewal_story(None), "X" * 500, PROJECT_KEY)
    assert len(str(info.value)) < 150


def test_create_story_raises_publish_error_when_returned_key_from_other_project() -> None:
    """PA-46: la clave devuelta debe pertenecer al proyecto pedido."""
    tracker, recorder, _ = tracker_and_recorder(created("OTRO-7"))
    with pytest.raises(PublishError) as info:
        tracker.create_story(renewal_story(None), None, PROJECT_KEY)
    assert "OTRO-7" in str(info.value)
    assert len(recorder.requests) == 1


def test_create_story_raises_publish_error_when_returned_key_has_project_prefix() -> None:
    """PA-46 (límite): `DEMOX-1` no es del proyecto `DEMO` aunque empiece igual."""
    tracker, _, _ = tracker_and_recorder(created("DEMOX-1"))
    with pytest.raises(PublishError):
        tracker.create_story(renewal_story(None), None, PROJECT_KEY)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, json={"id": "10020"}),
        httpx.Response(201, json={"key": None}),
        httpx.Response(201, json={"key": 20}),
        httpx.Response(201, json={"key": "demo-20"}),
        httpx.Response(201, json={"key": "DEMO-20; borrar"}),
        httpx.Response(201, json=["DEMO-20"]),
        httpx.Response(201),
    ],
)
def test_create_story_raises_publish_error_when_response_key_missing_or_invalid(
    response: httpx.Response,
) -> None:
    """PA-46: sin clave válida en la respuesta, la publicación falla con PublishError."""
    tracker, recorder, _ = tracker_and_recorder(response)
    with pytest.raises(PublishError) as info:
        tracker.create_story(renewal_story(None), None, PROJECT_KEY)
    assert "Comprueba en Jira" in str(info.value)
    assert len(recorder.requests) == 1


# --- update_story (RF-05) --------------------------------------------------------------------


def test_update_story_puts_summary_and_description_then_posts_diff_comment() -> None:
    """RF-05: PUT /issue/{key} con título y ADF y, después, POST del comentario del diff."""
    tracker, recorder, _ = tracker_and_recorder(no_content(), httpx.Response(201, json={}))
    story = renewal_story()

    assert tracker.update_story("DEMO-3", story, DIFF_MD) is None

    put, comment = recorder.requests
    assert put.method == "PUT"
    assert put.url.path == f"{ISSUE_PATH}/DEMO-3"
    assert body_of(put) == {
        "fields": {"summary": story_summary(story), "description": story_to_adf(story)}
    }
    assert comment.method == "POST"
    assert comment.url.path == f"{ISSUE_PATH}/DEMO-3/comment"
    assert body_of(comment) == {"body": markdown_to_adf(DIFF_MD)}
    table = body_of(comment)["body"]["content"][1]
    assert table["type"] == "table"
    assert table["content"][0]["content"][0]["type"] == "tableHeader"


def test_update_story_does_not_change_project_issue_type_or_parent() -> None:
    """RF-05: la actualización solo toca `summary` y `description`."""
    tracker, recorder, _ = tracker_and_recorder(no_content(), httpx.Response(201, json={}))
    tracker.update_story("DEMO-3", renewal_story(), DIFF_MD)
    assert set(body_of(recorder.requests[0])["fields"]) == {"summary", "description"}


@pytest.mark.parametrize("diff", ["", "   ", "\n\n\t"])
def test_update_story_skips_comment_when_diff_empty(diff: str) -> None:
    """RF-05: sin diff, no se añade comentario."""
    tracker, recorder, _ = tracker_and_recorder(no_content())
    tracker.update_story("DEMO-3", renewal_story(), diff)
    assert [r.method for r in recorder.requests] == ["PUT"]


def test_update_story_uses_gateway_url_when_cloud_id() -> None:
    """RNF-04: PUT y comentario van al gateway con cloud_id."""
    tracker, recorder, _ = tracker_and_recorder(
        no_content(), httpx.Response(201, json={}), cloud_id=SecretStr(CLOUD_ID)
    )
    tracker.update_story("DEMO-3", renewal_story(), DIFF_MD)
    root = f"https://api.atlassian.com/ex/jira/{CLOUD_ID}"
    assert [str(r.url) for r in recorder.requests] == [
        f"{root}/rest/api/3/issue/DEMO-3",
        f"{root}/rest/api/3/issue/DEMO-3/comment",
    ]


@pytest.mark.parametrize("key", ["", "demo-3", "DEMO", "DEMO-3/comment", "../DEMO-3", "DEMO-3?x"])
def test_update_story_raises_publish_error_without_request_when_key_invalid(key: str) -> None:
    """RF-05 (negativa): una clave inválida no llega a Jira (ni a la ruta)."""
    with pytest.raises(PublishError):
        no_http_tracker().update_story(key, renewal_story(), DIFF_MD)


@pytest.mark.parametrize(
    "failure",
    [
        error_response(500),
        error_response(400),
        error_response(403),
        error_response(429, {"Retry-After": "5"}),
        httpx.ConnectError("sin red ficticia"),
    ],
)
def test_update_story_reports_story_updated_when_comment_fails_after_put(
    failure: httpx.Response | Exception,
) -> None:
    """RF-05, RNF-13: si falla el comentario tras el PUT, el mensaje dice que la HU se actualizó."""
    tracker, recorder, sleep = tracker_and_recorder(no_content(), failure)
    with pytest.raises(PublishError) as info:
        tracker.update_story("DEMO-3", renewal_story(), DIFF_MD)
    message = str(info.value)
    assert "DEMO-3 se ha actualizado" in message
    assert "comentario" in message
    assert_safe_message(info.value)
    assert info.value.__cause__ is None
    assert len(recorder.requests) == 2
    assert sleep.waits == []


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_update_story_does_not_post_comment_when_put_fails(status: int) -> None:
    """RF-05: si falla el PUT, no se envía el comentario."""
    tracker, recorder, sleep = tracker_and_recorder(error_response(status), created())
    with pytest.raises(AgentError) as info:
        tracker.update_story("DEMO-3", renewal_story(), DIFF_MD)
    assert [r.method for r in recorder.requests] == ["PUT"]
    assert sleep.waits == []
    assert_safe_message(info.value)
    assert "se ha actualizado" not in str(info.value)


def test_update_story_mentions_key_when_put_404() -> None:
    """RF-05: el 404 del PUT nombra la incidencia."""
    tracker, _, _ = tracker_and_recorder(error_response(404))
    with pytest.raises(NotFoundError) as info:
        tracker.update_story("DEMO-3", renewal_story(), DIFF_MD)
    assert "DEMO-3" in str(info.value)


# --- link (RF-06, D-09) ----------------------------------------------------------------------


def test_link_posts_relates_link_with_outward_from_and_inward_to_and_comment() -> None:
    """RF-06, D-09: POST /issueLink «Relates» con comentario ADF."""
    tracker, recorder, _ = tracker_and_recorder(httpx.Response(201))

    assert tracker.link("DEMO-3", "DEMO-2", "relates to", "Comparte la **RN-01**") is None

    [request] = recorder.requests
    assert request.method == "POST"
    assert request.url.path == LINK_PATH
    assert body_of(request) == {
        "type": {"name": "Relates"},
        "outwardIssue": {"key": "DEMO-3"},
        "inwardIssue": {"key": "DEMO-2"},
        "comment": {"body": markdown_to_adf("Comparte la **RN-01**")},
    }


@pytest.mark.parametrize("comment", [None, "", "   ", "\n"])
def test_link_omits_comment_when_none_or_blank(comment: str | None) -> None:
    """RF-06: el comentario solo se envía si hay texto."""
    tracker, recorder, _ = tracker_and_recorder(httpx.Response(201))
    tracker.link("DEMO-3", "DEMO-2", "relates to", comment)
    assert "comment" not in body_of(recorder.requests[0])


def test_link_omits_comment_when_argument_not_passed() -> None:
    """RF-06: `comment_md` es opcional."""
    tracker, recorder, _ = tracker_and_recorder(httpx.Response(201))
    tracker.link("DEMO-3", "DEMO-2", "relates to")
    assert "comment" not in body_of(recorder.requests[0])


def test_link_uses_gateway_url_when_cloud_id() -> None:
    """RNF-04: el vínculo va al gateway con cloud_id."""
    tracker, recorder, _ = tracker_and_recorder(httpx.Response(201), cloud_id=SecretStr(CLOUD_ID))
    tracker.link("DEMO-3", "DEMO-2", "relates to")
    assert str(recorder.requests[0].url) == (
        f"https://api.atlassian.com/ex/jira/{CLOUD_ID}/rest/api/3/issueLink"
    )


@pytest.mark.parametrize(
    "link_type", ["blocks", "Relates", "RELATES TO", "relates", "", "duplicates"]
)
def test_link_raises_publish_error_without_request_when_link_type_not_allowed(
    link_type: str,
) -> None:
    """D-09 (negativa): solo se admite «relates to»."""
    with pytest.raises(PublishError):
        no_http_tracker().link("DEMO-3", "DEMO-2", link_type)


@pytest.mark.parametrize(
    ("from_key", "to_key"),
    [("demo-3", "DEMO-2"), ("DEMO-3", "DEMO-2 "), ("", "DEMO-2"), ("DEMO-3", "DEMO")],
)
def test_link_raises_not_found_without_request_when_key_invalid(from_key: str, to_key: str) -> None:
    """RF-06 (negativa): las claves inválidas no llegan a Jira."""
    with pytest.raises(NotFoundError):
        no_http_tracker().link(from_key, to_key, "relates to")


def test_link_raises_external_error_without_request_when_same_key() -> None:
    """RF-06 (negativa): una HU no se vincula consigo misma."""
    with pytest.raises(ExternalServiceError) as info:
        no_http_tracker().link("DEMO-3", "DEMO-3", "relates to")
    assert not isinstance(info.value, PublishError)


@pytest.mark.parametrize(
    "failure",
    [
        error_response(400),
        error_response(401),
        error_response(403),
        error_response(404),
        error_response(429),
        error_response(500),
        error_response(502),
        httpx.ConnectError("sin red ficticia"),
        httpx.ReadTimeout("tiempo ficticio"),
        httpx.Response(201, text="<html>no json</html>"),
    ],
)
def test_link_http_failures_are_always_external_service_errors(
    failure: httpx.Response | Exception,
) -> None:
    """RF-06, RNF-13: el nodo publish solo captura ExternalServiceError en los vínculos."""
    tracker, recorder, sleep = tracker_and_recorder(failure)
    with pytest.raises(ExternalServiceError) as info:
        tracker.link("DEMO-3", "DEMO-2", "relates to", "Motivo ficticio")
    assert not isinstance(info.value, PublishError)
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


# --- Errores de escritura comunes (§8) -------------------------------------------------------


@pytest.mark.parametrize("operation", list(WRITES))
@pytest.mark.parametrize("status", [401, 403])
def test_write_raises_authentication_error_once_when_401_or_403(
    operation: str, status: int
) -> None:
    """§8: 401/403 → AuthenticationError, sin reintento ni cuerpo en el mensaje."""
    tracker, recorder, sleep = tracker_and_recorder(error_response(status))
    with pytest.raises(AuthenticationError) as info:
        WRITES[operation](tracker)
    assert f"HTTP {status}" in str(info.value)
    assert info.value.service == "jira"
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


@pytest.mark.parametrize("operation", ["create", "link"])
def test_write_raises_not_found_once_when_404(operation: str) -> None:
    """§8: 404 → NotFoundError."""
    tracker, recorder, sleep = tracker_and_recorder(error_response(404))
    with pytest.raises(NotFoundError) as info:
        WRITES[operation](tracker)
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


@pytest.mark.parametrize("operation", list(WRITES))
@pytest.mark.parametrize(("header", "expected"), [("7", 7.0), (None, None), ("pronto", None)])
def test_write_raises_rate_limit_without_retry_or_sleep_when_429(
    operation: str, header: str | None, expected: float | None
) -> None:
    """§8: 429 → RateLimitError con retry_after; la escritura no se reintenta ni espera."""
    headers = {"Retry-After": header} if header is not None else None
    tracker, recorder, sleep = tracker_and_recorder(error_response(429, headers), created())
    with pytest.raises(RateLimitError) as info:
        WRITES[operation](tracker)
    assert info.value.retry_after == expected
    assert "no se ha reintentado" in str(info.value)
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


@pytest.mark.parametrize("operation", list(WRITES))
@pytest.mark.parametrize("status", [400, 409, 422, 500, 502, 503, 504])
def test_write_raises_generic_failure_once_when_400_or_5xx(operation: str, status: int) -> None:
    """§8: 400/5xx → PublishError (create/update) o ExternalServiceError (link), sin reintento."""
    tracker, recorder, sleep = tracker_and_recorder(error_response(status), created())
    with pytest.raises(GENERIC_FAILURE[operation]) as info:
        WRITES[operation](tracker)
    if operation != "link":
        assert not isinstance(info.value, ExternalServiceError)
    assert f"HTTP {status}" in str(info.value)
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


@pytest.mark.parametrize("operation", list(WRITES))
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError(f"sin red {EMAIL} {TOKEN}"),
        httpx.ReadTimeout("tiempo agotado ficticio"),
        httpx.RemoteProtocolError("protocolo ficticio"),
    ],
)
def test_write_raises_generic_failure_once_when_network_fails(
    operation: str, error: Exception
) -> None:
    """§8: un fallo de red no se reintenta (podría duplicar la escritura)."""
    tracker, recorder, sleep = tracker_and_recorder(error, created())
    with pytest.raises(GENERIC_FAILURE[operation]) as info:
        WRITES[operation](tracker)
    assert "Comprueba en Jira" in str(info.value)
    assert info.value.__cause__ is None
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


@pytest.mark.parametrize("operation", list(WRITES))
def test_write_raises_generic_failure_when_2xx_body_not_json(operation: str) -> None:
    """§8: una respuesta 2xx que no es JSON es un fallo, sin filtrar el cuerpo."""
    bad = httpx.Response(200, text=f"<html>{BODY_MARKER}</html>")
    tracker, recorder, sleep = tracker_and_recorder(bad, bad)
    with pytest.raises(GENERIC_FAILURE[operation]) as info:
        WRITES[operation](tracker)
    assert info.value.__cause__ is None
    assert sleep.waits == []
    assert_safe_message(info.value)
    # update: el PUT no JSON falla antes del comentario; create/link: una sola petición.
    assert len(recorder.requests) == 1


def redirect(status: int) -> httpx.Response:
    return httpx.Response(status, headers={"Location": "https://otro.example/"})


@pytest.mark.parametrize("status", [301, 302, 307])
def test_create_story_fails_when_jira_answers_redirect(status: int) -> None:
    """§8, PA-46: una redirección no devuelve clave; create_story no la da por creada."""
    tracker, recorder, _ = tracker_and_recorder(redirect(status))
    with pytest.raises(PublishError):
        WRITES["create"](tracker)
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("operation", ["update", "link"])
@pytest.mark.parametrize("status", [301, 302, 307])
def test_write_fails_when_jira_answers_redirect(operation: str, status: int) -> None:
    """§8: una redirección no confirma la escritura; debe fallar en lugar de darla por hecha."""
    tracker, _, _ = tracker_and_recorder(redirect(status))
    with pytest.raises(AgentError):
        WRITES[operation](tracker)


# --- Autenticación ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation", list(WRITES))
def test_write_sends_basic_authorization_header(operation: str) -> None:
    """RNF-04: las escrituras van con Basic auth (email + token)."""
    tracker, recorder, _ = tracker_and_recorder(created(), created())
    WRITES[operation](tracker)
    for request in recorder.requests:
        assert request.headers["Authorization"] == f"Basic {BASIC_CREDENTIALS}"


@pytest.mark.parametrize("operation", list(WRITES))
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
def test_write_error_never_contains_authorization_or_credentials(
    operation: str, status: int
) -> None:
    """RNF-04, §8: ni la cabecera Authorization ni las credenciales aparecen en el mensaje."""
    tracker, _, _ = tracker_and_recorder(error_response(status))
    with pytest.raises(AgentError) as info:
        WRITES[operation](tracker)
    message = str(info.value)
    assert "Basic" not in message
    assert "Authorization" not in message
    assert_safe_message(info.value)
    assert TOKEN not in repr(info.value)


# --- Solo las escrituras escriben ------------------------------------------------------------


def read_only_handler(request: httpx.Request) -> httpx.Response:
    """Responde a las lecturas y falla si llega cualquier método distinto de GET."""
    if request.method != "GET":
        pytest.fail(f"Una lectura ha escrito en Jira: {request.method} {request.url.path}")
    path = request.url.path
    if path == "/rest/api/3/project/search":
        return httpx.Response(200, json={"values": [{"key": "DEMO", "name": "x"}], "isLast": True})
    if path == "/rest/api/3/search/jql":
        issue = {"key": "DEMO-2", "fields": {"summary": "s"}}
        return httpx.Response(200, json={"issues": [issue], "isLast": True})
    if path.startswith("/rest/api/3/issue/"):
        return httpx.Response(200, json=DEMO_3_PAYLOAD)
    pytest.fail(f"Ruta inesperada: {path}")


def test_read_methods_only_send_get_requests() -> None:
    """§4, T-27: nada escribe en Jira fuera de create_story/update_story/link."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return read_only_handler(request)

    tracker = make_tracker(handler)
    tracker.test_connection()
    tracker.get_issue("DEMO-3")
    tracker.search('project = "DEMO"')
    tracker.list_projects()
    tracker.list_epics(PROJECT_KEY)
    tracker.list_children(EPIC_KEY)
    assert calls and set(calls) == {"GET"}
    assert len(calls) == 6


def test_read_methods_do_not_send_body() -> None:
    """§4: las lecturas no llevan cuerpo."""
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return read_only_handler(request)

    tracker = make_tracker(handler)
    tracker.test_connection()
    tracker.get_issue("DEMO-3")
    tracker.list_children(EPIC_KEY)
    assert bodies == [b"", b"", b""]


def test_write_does_not_follow_redirect_when_client_follows_redirects() -> None:
    """§8: aunque el cliente inyectado siga redirecciones, una escritura no se reenvía."""
    recorder = Recorder(httpx.Response(307, headers={"Location": "https://otro.example/x"}))
    tracker = JiraCloudTracker(
        BASE_URL,
        SecretStr(EMAIL),
        SecretStr(TOKEN),
        http_client=httpx.Client(transport=httpx.MockTransport(recorder), follow_redirects=True),
        sleep=RecordingSleep(),
    )
    with pytest.raises(ExternalServiceError) as excinfo:
        tracker.link("DEMO-3", "DEMO-2", "relates to")
    assert len(recorder.requests) == 1
    assert_safe_message(excinfo.value)
