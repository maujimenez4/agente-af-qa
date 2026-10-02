"""JiraNativeTests (T-30: RF-30, RNF-13, D-09 §6.2, PA-05, PA-46; SPEC-00 §4, §8).

Sin red: todo el HTTP pasa por `httpx.MockTransport` con un Jira simulado (`FakeJira`) que
enruta por método y ruta y guarda estado (subtareas y adjuntos) entre llamadas. Datos 100 %
sintéticos del dominio ficticio de la Biblioteca de Villaficticia; credenciales obviamente de
prueba (las de `test_jira_tracker`).
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from adapters import base
from adapters.base import IssueSummary
from adapters.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    PublishError,
    RateLimitError,
)
from adapters.jira.adf import adf_to_text
from adapters.jira.jql import CASE_LABEL
from adapters.jira.tracker import SEARCH_FIELDS
from adapters.testmgmt.jira_native import (
    DEFAULT_EXECUTION_TRANSITIONS,
    EXECUTION_LABELS,
    MAX_CASES,
    MAX_EVIDENCE_CHARS,
    PAGE_SIZE,
    STATUS_TEXT,
    ExecutionStatus,
    JiraNativeTests,
    attachment_files,
    case_labels,
    case_to_adf,
    execution_comment,
)
from schemas.common import Priority
from schemas.test_case import TestCase, TestCaseType, TestStep, TestSuite
from tests.unit.test_jira_tracker import (
    BASE_URL,
    BASIC_CREDENTIALS,
    BODY_MARKER,
    CLOUD_ID,
    EMAIL,
    TOKEN,
    Recorder,
    RecordingSleep,
    assert_safe_message,
    error_response,
    fail_if_called,
)

STORY = "DEMO-3"
PROJECT = "DEMO"
SUBTASK_TYPE = "Subtarea"
SEARCH_PATH = "/rest/api/3/search/jql"
ISSUE_PATH = "/rest/api/3/issue"
STORY_PATH = f"/rest/api/3/issue/{STORY}"
ATTACH_PATH = f"/rest/api/3/issue/{STORY}/attachments"
STRATEGY_FILE = f"estrategia-{STORY}.md"
MATRIX_FILE = f"matriz-{STORY}.md"
EXPECTED_JQL = 'parent = DEMO-3 AND labels = "caso-prueba" ORDER BY key'
STRATEGY_MD = "# Estrategia de pruebas ficticia\n\n- Enfoque: caja negra sobre datos sintéticos.\n"
LITERAL_TITLE = "**Rechazar** la <b>renovación</b> con reserva"

Handler = Callable[[httpx.Request], httpx.Response]
Reply = httpx.Response | Exception


# --- Datos sintéticos ------------------------------------------------------------------------


def make_suite(story: str = STORY, cases: list[TestCase] | None = None) -> TestSuite:
    """Suite ficticia: CP-01 positivo con Gherkin, CP-02 negativo sin Gherkin, CP-03 excepción."""
    default_cases = [
        TestCase(
            internal_id="CP-01",
            title="Renovar un préstamo sin reservas",
            criterion_ids=["CA-01"],
            rule_ids=["RN-01"],
            type=TestCaseType.POSITIVE,
            preconditions=["La persona socia ficticia tiene un préstamo activo", "   "],
            steps=[
                TestStep(action="Abrir «Mis préstamos»", data=None, expected="Se ve el listado"),
                TestStep(
                    action="Pulsar «Renovar»",
                    data="Préstamo PR-0001",
                    expected="La fecha de devolución se amplía 15 días",
                ),
            ],
            gherkin=(
                "Escenario: renovar sin reservas\n"
                "  Dado un préstamo activo\n"
                "  Cuando pulso «Renovar»\n"
                "  Entonces se amplía la fecha"
            ),
            priority=Priority.MUST,
        ),
        TestCase(
            internal_id="CP-02",
            title=LITERAL_TITLE,
            criterion_ids=["CA-02"],
            type=TestCaseType.NEGATIVE,
            preconditions=[],
            steps=[
                TestStep(
                    action="Pulsar «Renovar» en `PR-0002` <script>x</script>",
                    data="**reservado**",
                    expected="Mensaje [enlace](https://ejemplo.invalid)",
                )
            ],
            gherkin=None,
            priority=Priority.SHOULD,
        ),
        TestCase(
            internal_id="CP-03",
            title="[CP-03] Fallo del servicio de préstamos",
            criterion_ids=["CA-01", "CA-02"],
            rule_ids=["RN-01"],
            type=TestCaseType.EXCEPTION,
            preconditions=["El servicio ficticio no responde"],
            steps=[TestStep(action="Pulsar «Renovar»", expected="Aviso de error temporal")],
            gherkin="   ",
            priority=Priority.COULD,
        ),
    ]
    return TestSuite(
        story_jira_key=story,
        cases=default_cases if cases is None else cases,
        strategy_md=STRATEGY_MD,
    )


def subtask(key: str, summary: str) -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "issuetype": {"name": SUBTASK_TYPE},
            "status": {"name": "Por hacer"},
        },
    }


def search_page(
    issues: list[dict[str, Any]], token: str | None = None, is_last: bool | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"issues": issues}
    if token is not None:
        body["nextPageToken"] = token
    if is_last is not None:
        body["isLast"] = is_last
    return httpx.Response(200, json=body)


# --- Jira simulado ---------------------------------------------------------------------------


@dataclass
class FakeJira:
    """Handler de MockTransport con estado: enruta por método y ruta y registra las peticiones.

    - `case_replies[CP-XX]`: respuesta (o excepción) a la creación de ese CP en lugar del 201.
    - `attach_replies[nombre]`: idem para la subida de ese adjunto.
    - `search_replies` / `attachments_replies`: respuestas en secuencia a la búsqueda y a la
      consulta de adjuntos (sustituyen al estado).
    - `key_override[CP-XX]`: cuerpo devuelto por el 201 de ese CP.
    """

    subtasks: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    case_replies: dict[str, Reply] = field(default_factory=dict)
    attach_replies: dict[str, Reply] = field(default_factory=dict)
    search_replies: list[Reply] = field(default_factory=list)
    attachments_replies: list[Reply] = field(default_factory=list)
    key_override: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    uploads: dict[str, bytes] = field(default_factory=dict)
    next_number: int = 20

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        route = (request.method, request.url.path)
        if route == ("GET", SEARCH_PATH):
            return self._search()
        if route == ("GET", STORY_PATH):
            return self._attachments()
        if route == ("POST", ISSUE_PATH):
            return self._create(request)
        if route == ("POST", ATTACH_PATH):
            return self._upload(request)
        pytest.fail(f"Petición no esperada: {request.method} {request.url.path}")

    def _search(self) -> httpx.Response:
        if self.search_replies:
            return _reply(self.search_replies.pop(0))
        return search_page(list(self.subtasks))

    def _attachments(self) -> httpx.Response:
        if self.attachments_replies:
            return _reply(self.attachments_replies.pop(0))
        files = [{"id": str(i), "filename": name} for i, name in enumerate(self.attachments)]
        return httpx.Response(200, json={"key": STORY, "fields": {"attachment": files}})

    def _create(self, request: httpx.Request) -> httpx.Response:
        fields = json.loads(request.content)["fields"]
        case_id = re.match(r"^\[(CP-\d+)\]", fields["summary"]).group(1)  # type: ignore[union-attr]
        if case_id in self.case_replies:
            return _reply(self.case_replies[case_id])
        if case_id in self.key_override:
            return httpx.Response(201, json=self.key_override[case_id])
        self.next_number += 1
        key = f"{PROJECT}-{self.next_number}"
        self.subtasks.append(subtask(key, fields["summary"]))
        return httpx.Response(201, json={"id": str(self.next_number), "key": key})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        name = multipart_filename(request)
        if name in self.attach_replies:
            return _reply(self.attach_replies[name])
        self.attachments.append(name)
        self.uploads[name] = request.content
        return httpx.Response(200, json=[{"id": "900", "filename": name}])

    # --- Consultas de las peticiones registradas ---

    def by_route(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]

    def creates(self) -> list[httpx.Request]:
        return self.by_route("POST", ISSUE_PATH)

    def created_case_ids(self) -> list[str]:
        return [summary_of(r)[1:6] for r in self.creates()]

    def upload_requests(self) -> list[httpx.Request]:
        return self.by_route("POST", ATTACH_PATH)

    def uploaded_names(self) -> list[str]:
        return [multipart_filename(r) for r in self.upload_requests()]

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]


def _reply(reply: Reply) -> httpx.Response:
    if isinstance(reply, Exception):
        raise reply
    return reply


def multipart_filename(request: httpx.Request) -> str:
    match = re.search(rb'filename="([^"]+)"', request.content)
    assert match, "el adjunto no va en multipart con filename"
    return match.group(1).decode()


def fields_of(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)["fields"]


def summary_of(request: httpx.Request) -> str:
    return str(fields_of(request)["summary"])


def make_tests(
    handler: Handler,
    sleep: RecordingSleep | None = None,
    *,
    base_url: str = BASE_URL,
    cloud_id: SecretStr | None = None,
    subtask_type: str = SUBTASK_TYPE,
    max_retries: int = 2,
    follow_redirects: bool = False,
) -> JiraNativeTests:
    return JiraNativeTests(
        base_url,
        SecretStr(EMAIL),
        SecretStr(TOKEN),
        subtask_type=subtask_type,
        cloud_id=cloud_id,
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=follow_redirects
        ),
        max_retries=max_retries,
        sleep=sleep or RecordingSleep(),
    )


def jira_and_tests(
    jira: FakeJira | None = None, **kwargs: Any
) -> tuple[FakeJira, JiraNativeTests, RecordingSleep]:
    jira = jira or FakeJira()
    sleep = RecordingSleep()
    return jira, make_tests(jira, sleep, **kwargs), sleep


def all_texts(node: Any) -> list[str]:
    """Textos de todos los nodos `text` del ADF, en orden."""
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "text":
            found.append(node["text"])
        for child in node.get("content") or []:
            found += all_texts(child)
    return found


def node_types(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        found.append(str(node.get("type")))
        for child in node.get("content") or []:
            found += node_types(child)
    return found


def cell_text(cell: dict[str, Any]) -> str:
    return "".join(all_texts(cell))


def steps_table(document: dict[str, Any]) -> dict[str, Any]:
    [table] = [b for b in document["content"] if b["type"] == "table"]
    return table


def headings(document: dict[str, Any]) -> list[str]:
    return [cell_text(b) for b in document["content"] if b["type"] == "heading"]


FAILURE_REPLIES: dict[str, Reply] = {
    "400": error_response(400),
    "404": error_response(404),
    "500": error_response(500),
    "red": httpx.ConnectError("fallo de red ficticio"),
}
STOP_REPLIES: dict[str, Reply] = {
    "401": error_response(401),
    "403": error_response(403),
    "429": error_response(429, headers={"Retry-After": "1"}),
}


# --- Protocolo y constructor -----------------------------------------------------------------


def test_jira_native_tests_implements_test_management_protocol() -> None:
    """SPEC-00 §4: JiraNativeTests cumple el Protocol TestManagement de adapters/base.py."""
    assert isinstance(make_tests(fail_if_called), base.TestManagement)


@pytest.mark.parametrize(
    "subtask_type",
    ["", "   ", "Sub\ntarea", "Sub\x00tarea", "x" * 61, "  " + "x" * 61 + "  "],
    ids=["vacio", "espacios", "salto-medio", "control", "61-chars", "61-chars-con-espacios"],
)
def test_constructor_raises_value_error_when_subtask_type_is_invalid(subtask_type: str) -> None:
    """D-09: JIRA_TEST_SUBTASK_TYPE vacío, en blanco, multilínea o > 60 caracteres → ValueError."""
    with pytest.raises(ValueError, match="JIRA_TEST_SUBTASK_TYPE") as info:
        make_tests(fail_if_called, subtask_type=subtask_type)
    assert_safe_message(info.value)


def test_constructor_accepts_subtask_type_of_exactly_60_chars() -> None:
    """D-09 (límite): 60 caracteres es válido y se envía tal cual."""
    jira, tests, _ = jira_and_tests(subtask_type="x" * 60)
    tests.publish_suite(make_suite())
    assert {fields_of(r)["issuetype"]["name"] for r in jira.creates()} == {"x" * 60}


def test_constructor_strips_surrounding_spaces_from_subtask_type() -> None:
    """D-09: los espacios alrededor del tipo de subtarea se recortan."""
    jira, tests, _ = jira_and_tests(subtask_type="  Sub-task  ")
    tests.publish_suite(make_suite())
    assert {fields_of(r)["issuetype"]["name"] for r in jira.creates()} == {"Sub-task"}


def test_constructor_strips_trailing_newline_from_subtask_type() -> None:
    """Un salto de línea final (copiado del `.env`) se recorta como el resto de espacios."""
    jira, tests, _ = jira_and_tests(subtask_type="Subtarea\n")
    tests.publish_suite(make_suite())
    assert {fields_of(r)["issuetype"]["name"] for r in jira.creates()} == {"Subtarea"}


def test_constructor_raises_value_error_when_subtask_type_has_carriage_return() -> None:
    """D-09: un tipo de subtarea con retorno de carro no es un nombre de tipo válido."""
    with pytest.raises(ValueError):
        make_tests(fail_if_called, subtask_type="Sub\rtarea")


@pytest.mark.parametrize("base_url", ["http://villaficticia.example", "ftp://x.example", ""])
def test_constructor_raises_authentication_error_when_base_url_not_https_without_cloud_id(
    base_url: str,
) -> None:
    """RNF-04, §8: con Basic auth y sin cloud_id la URL debe ser https:// → AuthenticationError."""
    with pytest.raises(AuthenticationError) as info:
        make_tests(fail_if_called, base_url=base_url)
    assert_safe_message(info.value)
    assert "https://" in str(info.value)


def test_constructor_raises_authentication_error_when_cloud_id_has_invalid_format() -> None:
    """RNF-04: un JIRA_CLOUD_ID con caracteres no válidos se rechaza sin mostrarlo."""
    with pytest.raises(AuthenticationError) as info:
        make_tests(fail_if_called, cloud_id=SecretStr("id/../../evil"))
    assert_safe_message(info.value)
    assert "evil" not in str(info.value)


def test_requests_go_to_atlassian_gateway_when_cloud_id_even_with_http_base_url() -> None:
    """RNF-04: con cloud_id se usa api.atlassian.com/ex/jira/{cloudId}, aunque la URL sea http."""
    recorder = Recorder(search_page([]))
    tests = make_tests(
        recorder, base_url="http://villaficticia.example", cloud_id=SecretStr(CLOUD_ID)
    )
    tests.list_cases(STORY)
    [request] = recorder.requests
    assert request.url.scheme == "https"
    assert request.url.host == "api.atlassian.com"
    assert request.url.path == f"/ex/jira/{CLOUD_ID}{SEARCH_PATH}"


def test_requests_use_basic_auth_with_synthetic_credentials() -> None:
    """RNF-04, §8: Basic auth (email:token) en la cabecera Authorization."""
    recorder = Recorder(search_page([]))
    make_tests(recorder).list_cases(STORY)
    assert recorder.requests[0].headers["Authorization"] == f"Basic {BASIC_CREDENTIALS}"


# --- list_cases ------------------------------------------------------------------------------


def test_list_cases_sends_get_with_exact_jql_and_fields() -> None:
    """D-09, §8: GET /search/jql con la JQL exacta de subtareas `caso-prueba` y los campos."""
    recorder = Recorder(search_page([]))
    assert make_tests(recorder).list_cases(STORY) == []
    [request] = recorder.requests
    assert request.method == "GET"
    assert request.url.host == "villaficticia.example"
    assert request.url.path == SEARCH_PATH
    params = request.url.params
    assert params["jql"] == EXPECTED_JQL
    assert params["fields"] == SEARCH_FIELDS
    assert params["maxResults"] == str(PAGE_SIZE)
    assert "nextPageToken" not in params


def test_list_cases_maps_issues_to_summaries() -> None:
    """D-09: cada subtarea se devuelve como IssueSummary (clave, título, tipo y estado)."""
    recorder = Recorder(search_page([subtask("DEMO-11", "[CP-01] Renovar")]))
    assert make_tests(recorder).list_cases(STORY) == [
        IssueSummary(
            key="DEMO-11", summary="[CP-01] Renovar", issue_type=SUBTASK_TYPE, status="Por hacer"
        )
    ]


def test_list_cases_follows_next_page_token_until_is_last() -> None:
    """§8: paginación con nextPageToken hasta isLast."""
    recorder = Recorder(
        search_page([subtask("DEMO-11", "[CP-01] A")], token="tok-1", is_last=False),
        search_page([subtask("DEMO-12", "[CP-02] B")], token="tok-2", is_last=False),
        search_page([subtask("DEMO-13", "[CP-03] C")], token="tok-3", is_last=True),
    )
    cases = make_tests(recorder).list_cases(STORY)
    assert [c.key for c in cases] == ["DEMO-11", "DEMO-12", "DEMO-13"]
    tokens = [r.url.params.get("nextPageToken") for r in recorder.requests]
    assert tokens == [None, "tok-1", "tok-2"]
    assert all(r.url.params["jql"] == EXPECTED_JQL for r in recorder.requests)
    assert {r.method for r in recorder.requests} == {"GET"}


def test_list_cases_stops_when_page_has_no_next_page_token() -> None:
    """§8: sin nextPageToken no se piden más páginas."""
    recorder = Recorder(search_page([subtask("DEMO-11", "[CP-01] A")]))
    assert len(make_tests(recorder).list_cases(STORY)) == 1
    assert len(recorder.requests) == 1


def test_list_cases_stops_when_page_is_empty_even_with_token() -> None:
    """§8 (límite): una página vacía termina la paginación aunque traiga token."""
    recorder = Recorder(search_page([], token="tok-1", is_last=False), search_page([]))
    assert make_tests(recorder).list_cases(STORY) == []
    assert len(recorder.requests) == 1


def test_list_cases_caps_results_at_max_cases() -> None:
    """D-09 (límite): como mucho MAX_CASES subtareas aunque Jira siga devolviendo páginas."""
    number = iter(range(1000, 10_000))

    def endless(request: httpx.Request) -> httpx.Response:
        requested = int(request.url.params["maxResults"])
        issues = [subtask(f"DEMO-{next(number)}", "[CP-01] A") for _ in range(requested)]
        return search_page(issues, token="tok-siguiente", is_last=False)

    recorder = Recorder()
    recorder_handler: Handler = lambda r: (recorder.requests.append(r), endless(r))[1]  # noqa: E731
    cases = make_tests(recorder_handler).list_cases(STORY)
    assert len(cases) == MAX_CASES
    assert len(recorder.requests) == MAX_CASES // PAGE_SIZE
    assert all(int(r.url.params["maxResults"]) <= PAGE_SIZE for r in recorder.requests)


def test_list_cases_truncates_to_max_cases_when_page_is_larger_than_requested() -> None:
    """D-09 (límite): si Jira devuelve más de lo pedido, se recorta a MAX_CASES."""
    issues = [subtask(f"DEMO-{n}", "[CP-01] A") for n in range(1000, 1000 + MAX_CASES + 7)]
    recorder = Recorder(search_page(issues))
    assert len(make_tests(recorder).list_cases(STORY)) == MAX_CASES


@pytest.mark.parametrize(
    "key",
    ["demo-3", "DEMO", "DEMO-", "3", "DEMO-3 OR project = OTRO", 'DEMO-3"', "DEMO-3\n", "X" * 80],
)
def test_list_cases_raises_not_found_without_http_when_key_is_invalid(key: str) -> None:
    """§8: una clave no válida → NotFoundError sin petición HTTP (sin inyección de JQL)."""
    with pytest.raises(NotFoundError) as info:
        make_tests(fail_if_called).list_cases(key)
    assert_safe_message(info.value)
    assert len(str(info.value)) < 120


def test_list_cases_retries_429_and_5xx_with_backoff() -> None:
    """§8: las lecturas reintentan 429 (Retry-After) y 5xx (backoff exponencial)."""
    recorder = Recorder(
        error_response(429, headers={"Retry-After": "1"}),
        error_response(503),
        search_page([subtask("DEMO-11", "[CP-01] A")]),
    )
    sleep = RecordingSleep()
    cases = make_tests(recorder, sleep).list_cases(STORY)
    assert [c.key for c in cases] == ["DEMO-11"]
    assert len(recorder.requests) == 3
    assert sleep.waits == [1.0, 2.0]
    assert {r.method for r in recorder.requests} == {"GET"}


def test_list_cases_retries_network_error_then_succeeds() -> None:
    """§8: un fallo de red en lectura se reintenta con backoff."""
    recorder = Recorder(httpx.ConnectError("red ficticia"), search_page([]))
    sleep = RecordingSleep()
    assert make_tests(recorder, sleep).list_cases(STORY) == []
    assert sleep.waits == [1.0]


def test_list_cases_raises_rate_limit_when_429_retries_are_exhausted() -> None:
    """§8: 429 persistente → RateLimitError tras max_retries reintentos."""
    recorder = Recorder(error_response(429, headers={"Retry-After": "1"}))
    sleep = RecordingSleep()
    with pytest.raises(RateLimitError) as info:
        make_tests(recorder, sleep).list_cases(STORY)
    assert len(recorder.requests) == 3
    assert sleep.waits == [1.0, 1.0]
    assert_safe_message(info.value)


def test_list_cases_raises_external_error_when_5xx_retries_are_exhausted() -> None:
    """§8: 5xx persistente → ExternalServiceError con mensaje seguro."""
    recorder = Recorder(error_response(500))
    with pytest.raises(ExternalServiceError) as info:
        make_tests(recorder).list_cases(STORY)
    assert len(recorder.requests) == 3
    assert_safe_message(info.value)


@pytest.mark.parametrize("status", [401, 403])
def test_list_cases_raises_authentication_error_without_retry(status: int) -> None:
    """§8, RNF-04: 401/403 → AuthenticationError sin reintentos."""
    recorder = Recorder(error_response(status))
    sleep = RecordingSleep()
    with pytest.raises(AuthenticationError) as info:
        make_tests(recorder, sleep).list_cases(STORY)
    assert len(recorder.requests) == 1
    assert sleep.waits == []
    assert_safe_message(info.value)


def test_list_cases_raises_external_error_when_jql_is_rejected_with_400() -> None:
    """§8: un 400 de la búsqueda → ExternalServiceError sin reintentos."""
    recorder = Recorder(error_response(400))
    with pytest.raises(ExternalServiceError, match="HTTP 400") as info:
        make_tests(recorder).list_cases(STORY)
    assert len(recorder.requests) == 1
    assert_safe_message(info.value)


# --- publish_suite: subtareas CP (RF-30, §6.2) -----------------------------------------------


def test_publish_suite_creates_one_subtask_per_case_in_order() -> None:
    """RF-30, RNF-13: un POST /issue por CP, uno a uno y en el orden de la suite."""
    jira, tests, _ = jira_and_tests()
    result = tests.publish_suite(make_suite())
    assert jira.created_case_ids() == ["CP-01", "CP-02", "CP-03"]
    assert result.created == ["DEMO-21", "DEMO-22", "DEMO-23"]
    assert result.failed == []


def test_publish_suite_sends_project_parent_and_received_subtask_type() -> None:
    """RF-30, D-09: proyecto de la HU, parent = HU e issuetype = tipo de subtarea recibido."""
    jira, tests, _ = jira_and_tests(subtask_type="Sub-tarea ficticia")
    tests.publish_suite(make_suite())
    for request in jira.creates():
        fields = fields_of(request)
        assert fields["project"] == {"key": PROJECT}
        assert fields["parent"] == {"key": STORY}
        assert fields["issuetype"] == {"name": "Sub-tarea ficticia"}
        assert set(fields) == {"project", "parent", "issuetype", "summary", "labels", "description"}
        assert request.headers["Content-Type"] == "application/json"


def test_publish_suite_prefixes_summary_with_case_id_without_duplicating() -> None:
    """R-05: título `[CP-XX] …`; si el título ya lleva el prefijo no se duplica."""
    jira, tests, _ = jira_and_tests()
    tests.publish_suite(make_suite())
    assert [summary_of(r) for r in jira.creates()] == [
        "[CP-01] Renovar un préstamo sin reservas",
        f"[CP-02] {LITERAL_TITLE}",
        "[CP-03] Fallo del servicio de préstamos",
    ]


def test_publish_suite_truncates_long_summary_keeping_prefix() -> None:
    """R-05 (límite): el título se recorta a 255 caracteres conservando `[CP-XX]`."""
    case = make_suite().cases[0].model_copy(update={"title": "a" * 400})
    jira, tests, _ = jira_and_tests()
    tests.publish_suite(make_suite(cases=[case]))
    summary = summary_of(jira.creates()[0])
    assert len(summary) == 255
    assert summary.startswith("[CP-01] a")


def test_publish_suite_sends_exact_traceability_labels() -> None:
    """§6.2: etiquetas `caso-prueba`, CA, RN y `tipo-<valor>` en ese orden."""
    jira, tests, _ = jira_and_tests()
    tests.publish_suite(make_suite())
    assert [fields_of(r)["labels"] for r in jira.creates()] == [
        [CASE_LABEL, "CA-01", "RN-01", "tipo-positivo"],
        [CASE_LABEL, "CA-02", "tipo-negativo"],
        [CASE_LABEL, "CA-01", "CA-02", "RN-01", "tipo-excepcion"],
    ]


@pytest.mark.parametrize("case_type", list(TestCaseType))
def test_case_labels_include_type_label_for_every_type(case_type: TestCaseType) -> None:
    """§6.2: `tipo-<valor>` para positivo, negativo, alterno y excepción."""
    case = make_suite().cases[0].model_copy(update={"type": case_type})
    assert case_labels(case)[-1] == f"tipo-{case_type.value}"


def test_case_labels_removes_duplicates_keeping_order() -> None:
    """§6.2: sin etiquetas repetidas aunque se repitan CA o RN."""
    case = (
        make_suite()
        .cases[0]
        .model_copy(
            update={"criterion_ids": ["CA-02", "CA-01", "CA-02"], "rule_ids": ["RN-01", "RN-01"]}
        )
    )
    assert case_labels(case) == [CASE_LABEL, "CA-02", "CA-01", "RN-01", "tipo-positivo"]


def test_publish_suite_sends_description_built_by_case_to_adf() -> None:
    """§6.2, §8: la descripción es el ADF de `case_to_adf` (doc versión 1)."""
    suite = make_suite()
    jira, tests, _ = jira_and_tests()
    tests.publish_suite(suite)
    for case, request in zip(suite.cases, jira.creates(), strict=True):
        description = fields_of(request)["description"]
        assert description == case_to_adf(case, STORY)
        assert description["type"] == "doc"
        assert description["version"] == 1


def test_case_to_adf_shows_type_priority_story_and_coverage() -> None:
    """§6.2, trazabilidad: tipo, prioridad, HU y CA/RN cubiertos al inicio."""
    document = case_to_adf(make_suite().cases[2], STORY)
    first, second = document["content"][:2]
    assert cell_text(first) == "Tipo: excepcion · Prioridad: Could"
    assert cell_text(second) == "HU: DEMO-3 · Cubre: CA-01, CA-02, RN-01"
    strong = [n for n in first["content"] if n.get("marks") == [{"type": "strong"}]]
    assert [n["text"] for n in strong] == ["Tipo: ", " · Prioridad: "]


def test_case_to_adf_lists_non_blank_preconditions() -> None:
    """§6.2: precondiciones en una lista; las vacías o en blanco se omiten."""
    document = case_to_adf(make_suite().cases[0], STORY)
    assert headings(document) == ["Precondiciones", "Pasos", "Escenario Gherkin"]
    [bullets] = [b for b in document["content"] if b["type"] == "bulletList"]
    assert [cell_text(item) for item in bullets["content"]] == [
        "La persona socia ficticia tiene un préstamo activo"
    ]


def test_case_to_adf_omits_preconditions_heading_when_there_are_none() -> None:
    """§6.2 (límite): sin precondiciones no hay sección ni lista vacía."""
    document = case_to_adf(make_suite().cases[1], STORY)
    assert "Precondiciones" not in headings(document)
    assert "bulletList" not in node_types(document)


def test_case_to_adf_renders_steps_table_with_header_and_dash_for_missing_data() -> None:
    """§6.2: tabla de pasos (#, Acción, Datos, Resultado esperado); data None → «—»."""
    table = steps_table(case_to_adf(make_suite().cases[0], STORY))
    rows = [[cell_text(c) for c in row["content"]] for row in table["content"]]
    assert rows == [
        ["#", "Acción", "Datos", "Resultado esperado"],
        ["1", "Abrir «Mis préstamos»", "—", "Se ve el listado"],
        ["2", "Pulsar «Renovar»", "Préstamo PR-0001", "La fecha de devolución se amplía 15 días"],
    ]
    assert {c["type"] for c in table["content"][0]["content"]} == {"tableHeader"}
    assert {c["type"] for row in table["content"][1:] for c in row["content"]} == {"tableCell"}


def test_case_to_adf_includes_gherkin_code_block_when_case_has_gherkin() -> None:
    """§6.2: el escenario Gherkin va en un bloque de código con lenguaje `gherkin`."""
    document = case_to_adf(make_suite().cases[0], STORY)
    [block] = [b for b in document["content"] if b["type"] == "codeBlock"]
    assert block["attrs"] == {"language": "gherkin"}
    assert block["content"][0]["text"].startswith("Escenario: renovar sin reservas\n  Dado")
    assert document["content"][-1] is block


@pytest.mark.parametrize("index", [1, 2], ids=["gherkin-none", "gherkin-en-blanco"])
def test_case_to_adf_omits_gherkin_block_when_case_has_no_gherkin(index: int) -> None:
    """§6.2 (negativa): sin Gherkin (None o en blanco) no hay sección ni bloque de código."""
    document = case_to_adf(make_suite().cases[index], STORY)
    assert "Escenario Gherkin" not in headings(document)
    assert "codeBlock" not in node_types(document)


def test_publish_suite_sends_markdown_and_html_of_case_as_literal_text() -> None:
    """PA-49: el Markdown/HTML del CP se publica literal (sin negritas, enlaces ni HTML)."""
    jira, tests, _ = jira_and_tests()
    tests.publish_suite(make_suite())
    request = jira.creates()[1]
    assert summary_of(request) == f"[CP-02] {LITERAL_TITLE}"
    description = fields_of(request)["description"]
    texts = all_texts(description)
    assert "Pulsar «Renovar» en `PR-0002` <script>x</script>" in texts
    assert "**reservado**" in texts
    assert "Mensaje [enlace](https://ejemplo.invalid)" in texts
    marks = [m["type"] for n in _walk(description) for m in n.get("marks", [])]
    assert set(marks) <= {"strong"}  # solo las etiquetas «Tipo:», «HU:»…, nunca link ni code
    assert "link" not in json.dumps(description)


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for child in node.get("content") or []:
            found += _walk(child)
    return found


def test_case_to_adf_round_trips_to_readable_text() -> None:
    """RF-03: la descripción se puede volver a leer con adf_to_text."""
    readable = adf_to_text(case_to_adf(make_suite().cases[0], STORY))
    assert "Tipo: positivo · Prioridad: Must" in readable
    assert "| 1 | Abrir «Mis préstamos» | — | Se ve el listado |" in readable


# --- publish_suite: adjuntos (§6.2) ----------------------------------------------------------


def test_attachment_files_names_and_content() -> None:
    """§6.2: `estrategia-<HU>.md` = strategy_md y `matriz-<HU>.md` = coverage_md()."""
    suite = make_suite()
    assert attachment_files(suite) == {
        STRATEGY_FILE: STRATEGY_MD,
        MATRIX_FILE: suite.coverage_md(),
    }


def test_publish_suite_uploads_strategy_and_matrix_as_multipart() -> None:
    """§6.2: POST /issue/HU/attachments multipart con X-Atlassian-Token: no-check."""
    suite = make_suite()
    jira, tests, _ = jira_and_tests()
    result = tests.publish_suite(suite)
    uploads = jira.upload_requests()
    assert [multipart_filename(r) for r in uploads] == [STRATEGY_FILE, MATRIX_FILE]
    for request in uploads:
        assert request.headers["X-Atlassian-Token"] == "no-check"
        assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
        assert b'name="file"' in request.content
    assert STRATEGY_MD.encode() in jira.uploads[STRATEGY_FILE]
    assert suite.coverage_md().encode() in jira.uploads[MATRIX_FILE]
    assert result.failed == []


def test_publish_suite_queries_existing_attachments_before_uploading() -> None:
    """PA-05: antes de subir se consulta GET /issue/HU?fields=attachment."""
    jira, tests, _ = jira_and_tests()
    tests.publish_suite(make_suite())
    routes = [(r.method, r.url.path) for r in jira.requests]
    assert routes == [
        ("GET", SEARCH_PATH),
        ("POST", ISSUE_PATH),
        ("POST", ISSUE_PATH),
        ("POST", ISSUE_PATH),
        ("GET", STORY_PATH),
        ("POST", ATTACH_PATH),
        ("POST", ATTACH_PATH),
    ]
    [query] = jira.by_route("GET", STORY_PATH)
    assert query.url.params["fields"] == "attachment"


# --- RNF-13: publicación parcial -------------------------------------------------------------


@pytest.mark.parametrize("reply", FAILURE_REPLIES.values(), ids=FAILURE_REPLIES.keys())
def test_publish_suite_continues_with_other_cases_when_one_case_fails(reply: Reply) -> None:
    """RNF-13: un CP que falla (400/404/500/red) va a failed y los demás se crean."""
    jira, tests, sleep = jira_and_tests(FakeJira(case_replies={"CP-02": reply}))
    result = tests.publish_suite(make_suite())
    assert jira.created_case_ids() == ["CP-01", "CP-02", "CP-03"]
    assert result.created == ["DEMO-21", "DEMO-22"]
    assert result.failed == ["CP-02"]
    assert jira.uploaded_names() == [STRATEGY_FILE, MATRIX_FILE]
    assert sleep.waits == []


def test_publish_suite_reports_every_failed_case_id() -> None:
    """RNF-13: varios CP fallidos aparecen todos en failed, por orden."""
    replies = {"CP-01": error_response(500), "CP-03": error_response(400)}
    _, tests, _ = jira_and_tests(FakeJira(case_replies=replies))
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-21"]
    assert result.failed == ["CP-01", "CP-03"]


@pytest.mark.parametrize("reply", FAILURE_REPLIES.values(), ids=FAILURE_REPLIES.keys())
def test_publish_suite_reports_attachment_name_when_upload_fails(reply: Reply) -> None:
    """RNF-13: un adjunto fallido aparece por su nombre en failed; el otro se sube."""
    jira, tests, _ = jira_and_tests(FakeJira(attach_replies={STRATEGY_FILE: reply}))
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-21", "DEMO-22", "DEMO-23"]
    assert result.failed == [STRATEGY_FILE]
    assert jira.uploaded_names() == [STRATEGY_FILE, MATRIX_FILE]


@pytest.mark.parametrize("reply", STOP_REPLIES.values(), ids=STOP_REPLIES.keys())
def test_publish_suite_stops_writing_when_first_case_gets_auth_or_rate_limit(
    reply: Reply,
) -> None:
    """RNF-13, §8: 401/403/429 en un CP → el resto y ambos adjuntos fallan sin petición."""
    jira, tests, sleep = jira_and_tests(FakeJira(case_replies={"CP-01": reply}))
    result = tests.publish_suite(make_suite())
    assert result.created == []
    assert result.failed == ["CP-01", "CP-02", "CP-03", STRATEGY_FILE, MATRIX_FILE]
    assert len(jira.creates()) == 1
    assert jira.upload_requests() == []
    assert jira.by_route("GET", STORY_PATH) == []
    assert sleep.waits == []


@pytest.mark.parametrize("reply", STOP_REPLIES.values(), ids=STOP_REPLIES.keys())
def test_publish_suite_keeps_created_cases_when_later_case_gets_auth_or_rate_limit(
    reply: Reply,
) -> None:
    """RNF-13: lo creado antes del 401/403/429 se conserva en created."""
    jira, tests, _ = jira_and_tests(FakeJira(case_replies={"CP-02": reply}))
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-21"]
    assert result.failed == ["CP-02", "CP-03", STRATEGY_FILE, MATRIX_FILE]
    assert jira.created_case_ids() == ["CP-01", "CP-02"]
    assert jira.upload_requests() == []


def test_publish_suite_still_reuses_existing_case_after_stopping() -> None:
    """PA-05 + RNF-13: tras un 401 un CP que ya existe sigue contando como publicado."""
    jira = FakeJira(
        subtasks=[subtask("DEMO-15", "[CP-03] Fallo del servicio de préstamos")],
        case_replies={"CP-01": error_response(401)},
    )
    jira, tests, _ = jira_and_tests(jira)
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-15"]
    assert result.failed == ["CP-01", "CP-02", STRATEGY_FILE, MATRIX_FILE]
    assert len(jira.creates()) == 1


@pytest.mark.parametrize("reply", STOP_REPLIES.values(), ids=STOP_REPLIES.keys())
def test_publish_suite_skips_second_attachment_when_first_gets_auth_or_rate_limit(
    reply: Reply,
) -> None:
    """RNF-13: 401/403/429 en un adjunto → el segundo no se intenta y va a failed."""
    jira, tests, sleep = jira_and_tests(FakeJira(attach_replies={STRATEGY_FILE: reply}))
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-21", "DEMO-22", "DEMO-23"]
    assert result.failed == [STRATEGY_FILE, MATRIX_FILE]
    assert jira.uploaded_names() == [STRATEGY_FILE]
    assert sleep.waits == []


# --- PA-05: idempotencia ---------------------------------------------------------------------


def test_publish_suite_reuses_existing_cases_and_creates_only_missing() -> None:
    """PA-05: las subtareas `[CP-01]` y `[CP-02]` existentes no se recrean; solo CP-03."""
    jira = FakeJira(
        subtasks=[
            subtask("DEMO-11", "[CP-01] Renovar un préstamo sin reservas"),
            subtask("DEMO-12", "[CP-02] Título antiguo"),
        ]
    )
    jira, tests, _ = jira_and_tests(jira)
    result = tests.publish_suite(make_suite())
    assert jira.created_case_ids() == ["CP-03"]
    assert result.created == ["DEMO-11", "DEMO-12", "DEMO-21"]
    assert result.failed == []


def test_publish_suite_uses_first_subtask_when_case_id_is_duplicated() -> None:
    """PA-05: con dos subtareas del mismo `[CP-XX]` se usa la primera (orden de clave)."""
    jira = FakeJira(
        subtasks=[subtask("DEMO-11", "[CP-01] Primera"), subtask("DEMO-14", "[CP-01] Copia")]
    )
    jira, tests, _ = jira_and_tests(jira)
    result = tests.publish_suite(make_suite())
    assert result.created[0] == "DEMO-11"
    assert "DEMO-14" not in result.created
    assert jira.created_case_ids() == ["CP-02", "CP-03"]


@pytest.mark.parametrize(
    "summary",
    ["Subtarea creada a mano", "CP-01 sin corchetes", " [CP-01] con espacio delante", "[CP-1x]"],
)
def test_publish_suite_ignores_subtasks_without_case_prefix(summary: str) -> None:
    """PA-05 (negativa): títulos sin prefijo `[CP-XX]` al inicio no cuentan como publicados."""
    jira, tests, _ = jira_and_tests(FakeJira(subtasks=[subtask("DEMO-11", summary)]))
    result = tests.publish_suite(make_suite())
    assert jira.created_case_ids() == ["CP-01", "CP-02", "CP-03"]
    assert "DEMO-11" not in result.created


def test_publish_suite_does_not_match_case_with_longer_id() -> None:
    """PA-05 (límite): `[CP-010]` no es `[CP-01]`."""
    jira, tests, _ = jira_and_tests(FakeJira(subtasks=[subtask("DEMO-11", "[CP-010] Otro")]))
    tests.publish_suite(make_suite())
    assert jira.created_case_ids() == ["CP-01", "CP-02", "CP-03"]


def test_publish_suite_does_not_upload_attachment_already_present() -> None:
    """PA-05: un adjunto con el mismo nombre no se vuelve a subir ni cuenta como fallido."""
    jira, tests, _ = jira_and_tests(FakeJira(attachments=[STRATEGY_FILE, "otro.md"]))
    result = tests.publish_suite(make_suite())
    assert jira.uploaded_names() == [MATRIX_FILE]
    assert result.failed == []


def test_publish_suite_makes_no_write_when_everything_already_exists() -> None:
    """PA-05: si todos los CP y adjuntos existen, solo hay lecturas."""
    jira = FakeJira(
        subtasks=[
            subtask("DEMO-11", "[CP-01] A"),
            subtask("DEMO-12", "[CP-02] B"),
            subtask("DEMO-13", "[CP-03] C"),
        ],
        attachments=[STRATEGY_FILE, MATRIX_FILE],
    )
    jira, tests, _ = jira_and_tests(jira)
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-11", "DEMO-12", "DEMO-13"]
    assert result.failed == []
    assert jira.writes() == []


def test_publish_suite_retry_after_partial_failure_creates_only_failed_items() -> None:
    """PA-05 + RNF-13: el reintento tras un fallo parcial solo crea lo que falló."""
    jira = FakeJira(
        case_replies={"CP-02": error_response(500)},
        attach_replies={MATRIX_FILE: httpx.ConnectError("red ficticia")},
    )
    jira, tests, _ = jira_and_tests(jira)
    suite = make_suite()

    first = tests.publish_suite(suite)
    assert first.created == ["DEMO-21", "DEMO-22"]
    assert first.failed == ["CP-02", MATRIX_FILE]

    jira.case_replies.clear()
    jira.attach_replies.clear()
    jira.requests.clear()
    second = tests.publish_suite(suite)

    assert jira.created_case_ids() == ["CP-02"]
    assert jira.uploaded_names() == [MATRIX_FILE]
    assert second.created == ["DEMO-21", "DEMO-23", "DEMO-22"]
    assert second.failed == []
    assert len(jira.subtasks) == 3


def test_publish_suite_twice_does_not_duplicate_anything() -> None:
    """PA-05: publicar dos veces la misma suite no duplica subtareas ni adjuntos."""
    jira, tests, _ = jira_and_tests()
    suite = make_suite()
    first = tests.publish_suite(suite)
    second = tests.publish_suite(suite)
    assert second.created == first.created
    assert len(jira.creates()) == 3
    assert len(jira.upload_requests()) == 2
    assert jira.attachments == [STRATEGY_FILE, MATRIX_FILE]


# --- Fallos de las lecturas previas ----------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (error_response(401), AuthenticationError),
        (error_response(403), AuthenticationError),
        (error_response(500), ExternalServiceError),
        (error_response(429, headers={"Retry-After": "1"}), RateLimitError),
        (httpx.ConnectError("red ficticia"), ExternalServiceError),
    ],
    ids=["401", "403", "500-agotado", "429-agotado", "red-agotada"],
)
def test_publish_suite_raises_without_writing_when_list_cases_fails(
    reply: Reply, error: type[Exception]
) -> None:
    """PA-05: si la búsqueda de CP existentes falla, publish_suite lanza y no escribe nada."""
    jira = FakeJira(search_replies=[reply] * 5)
    jira, tests, _ = jira_and_tests(jira)
    with pytest.raises(error) as info:
        tests.publish_suite(make_suite())
    assert jira.writes() == []
    assert {r.url.path for r in jira.requests} == {SEARCH_PATH}
    assert_safe_message(info.value)


@pytest.mark.parametrize(
    "reply",
    [error_response(500), error_response(404), error_response(401), httpx.ReadTimeout("t")],
    ids=["500-agotado", "404", "401", "timeout-agotado"],
)
def test_publish_suite_fails_both_attachments_without_upload_when_attachment_query_fails(
    reply: Reply,
) -> None:
    """PA-05: si falla la consulta de adjuntos, ambos van a failed sin subir; los CP se crean."""
    jira, tests, _ = jira_and_tests(FakeJira(attachments_replies=[reply] * 5))
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-21", "DEMO-22", "DEMO-23"]
    assert result.failed == [STRATEGY_FILE, MATRIX_FILE]
    assert jira.upload_requests() == []


# --- PA-46: clave devuelta -------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{"id": "10021"}, {"key": None}, {"key": 21}, {"key": "demo-21"}, {"key": "DEMO-21 x"}, {}],
    ids=["sin-key", "key-null", "key-numero", "minusculas", "con-espacio", "vacio"],
)
def test_publish_suite_marks_case_failed_when_returned_key_is_missing_or_invalid(
    body: dict[str, Any],
) -> None:
    """RNF-13: sin clave válida en la respuesta, el CP va a failed y el resto sigue."""
    _jira, tests, _ = jira_and_tests(FakeJira(key_override={"CP-01": body}))
    result = tests.publish_suite(make_suite())
    assert result.failed == ["CP-01"]
    assert result.created == ["DEMO-21", "DEMO-22"]


def test_publish_suite_marks_case_failed_when_created_in_other_project() -> None:
    """PA-46: una clave de otro proyecto (OTRO-9) no cuenta como creada."""
    _jira, tests, _ = jira_and_tests(FakeJira(key_override={"CP-02": {"key": "OTRO-9"}}))
    result = tests.publish_suite(make_suite())
    assert "OTRO-9" not in result.created
    assert result.failed == ["CP-02"]
    assert result.created == ["DEMO-21", "DEMO-22"]


def test_publish_suite_marks_case_failed_when_201_has_no_body() -> None:
    """RNF-13: un 2xx sin cuerpo no da clave → CP en failed."""
    _jira, tests, _ = jira_and_tests(FakeJira(case_replies={"CP-01": httpx.Response(201)}))
    assert tests.publish_suite(make_suite()).failed == ["CP-01"]


def test_publish_suite_marks_case_failed_when_201_body_is_not_json() -> None:
    """RNF-13: un 2xx con cuerpo no JSON → CP en failed."""
    reply = httpx.Response(201, content=b"<html>ok</html>")
    _, tests, _ = jira_and_tests(FakeJira(case_replies={"CP-01": reply}))
    assert tests.publish_suite(make_suite()).failed == ["CP-01"]


# --- Clave de la HU --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["demo-3", "DEMO", "3", "DEMO-3 OR 1=1", "DEMO-3/attachments", "DEMO-3\n", "X" * 90]
)
def test_publish_suite_raises_publish_error_without_http_when_story_key_is_invalid(
    key: str,
) -> None:
    """§8: story_jira_key no válida → PublishError sin ninguna petición HTTP."""
    with pytest.raises(PublishError) as info:
        make_tests(fail_if_called).publish_suite(make_suite(story=key))
    assert_safe_message(info.value)
    assert len(str(info.value)) < 120


# --- Escrituras de un solo intento (§8) ------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [*FAILURE_REPLIES.values(), *STOP_REPLIES.values()],
    ids=[*FAILURE_REPLIES.keys(), *STOP_REPLIES.keys()],
)
def test_publish_suite_never_retries_a_failed_write(reply: Reply) -> None:
    """§8: ningún POST se repite ni se espera, sea cual sea el error."""
    jira = FakeJira(case_replies={"CP-01": reply}, attach_replies={STRATEGY_FILE: reply})
    jira, tests, sleep = jira_and_tests(jira)
    tests.publish_suite(make_suite())
    assert jira.created_case_ids().count("CP-01") == 1
    assert jira.uploaded_names().count(STRATEGY_FILE) <= 1
    assert sleep.waits == []


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_publish_suite_marks_case_failed_when_write_gets_redirect(status: int) -> None:
    """§8: un 3xx en escritura es un fallo y no se sigue la redirección."""
    reply = httpx.Response(status, headers={"Location": "https://otro.example/rest/api/3/issue"})
    jira, tests, _ = jira_and_tests(FakeJira(case_replies={"CP-01": reply}), follow_redirects=True)
    result = tests.publish_suite(make_suite())
    assert result.failed == ["CP-01"]
    assert {r.url.host for r in jira.requests} == {"villaficticia.example"}
    assert jira.created_case_ids().count("CP-01") == 1


def test_publish_suite_marks_attachment_failed_when_upload_gets_redirect() -> None:
    """§8: un 3xx en la subida de un adjunto es un fallo."""
    reply = httpx.Response(302, headers={"Location": "https://otro.example/x"})
    jira, tests, _ = jira_and_tests(FakeJira(attach_replies={MATRIX_FILE: reply}))
    result = tests.publish_suite(make_suite())
    assert result.failed == [MATRIX_FILE]
    assert jira.uploaded_names() == [STRATEGY_FILE, MATRIX_FILE]


# --- Seguridad: logs -------------------------------------------------------------------------


def test_publish_suite_logs_counts_without_secrets() -> None:
    """Seguridad: el log de publicación no contiene credenciales ni cuerpos de respuesta."""
    _jira, tests, _ = jira_and_tests(FakeJira(case_replies={"CP-02": error_response(500)}))
    with capture_logs() as logs:
        tests.publish_suite(make_suite())
    [entry] = [e for e in logs if e.get("action") == "publish_suite"]
    assert entry["jira_key"] == STORY
    assert (entry["created"], entry["failed"]) == (2, 1)
    dumped = json.dumps(logs, default=str)
    for forbidden in (TOKEN, EMAIL, BASIC_CREDENTIALS, BODY_MARKER):
        assert forbidden not in dumped


# =============================================================================================
# T-47: registro de la ejecución de un CP (RF-28, R-01 opción A, UI.md §6.6)
# =============================================================================================

CASE_KEY = "DEMO-21"
CASE_PATH = f"/rest/api/3/issue/{CASE_KEY}"
TRANSITIONS_PATH = f"{CASE_PATH}/transitions"
COMMENT_PATH = f"{CASE_PATH}/comment"
EVIDENCE = "El sistema ficticio muestra «Préstamo no renovable» en PR-0002."
EVIDENCE_MARKER = "MARCADOR-EVIDENCIA-FICTICIA"
Route = tuple[str, str]
GET_CASE: Route = ("GET", CASE_PATH)
GET_TRANSITIONS: Route = ("GET", TRANSITIONS_PATH)
POST_TRANSITION: Route = ("POST", TRANSITIONS_PATH)
PUT_LABELS: Route = ("PUT", CASE_PATH)
POST_COMMENT: Route = ("POST", COMMENT_PATH)
REGISTERED_EVENT = "ejecución registrada en Jira"


def workflow_transitions() -> list[Any]:
    """Flujo ficticio de una subtarea: Tareas por hacer → En curso → Done."""
    return [
        {"id": "11", "name": "Tareas por hacer", "to": {"name": "Tareas por hacer"}},
        {"id": "21", "name": "En curso", "to": {"name": "En curso"}},
        {"id": "31", "name": "Finalizar", "to": {"name": "Done"}},
    ]


@dataclass
class ExecutionJira:
    """Jira simulado para `record_execution`: la subtarea CP, sus transiciones y escrituras.

    `replies[ruta]` es una secuencia de respuestas (o excepciones) que sustituye, una a una, a la
    respuesta por defecto de esa ruta.
    """

    labels: list[str] = field(default_factory=lambda: [CASE_LABEL, "CA-01", "tipo-positivo"])
    status: str = "En curso"
    subtask: bool = True
    transitions: list[Any] = field(default_factory=workflow_transitions)
    replies: dict[Route, list[Reply]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        route = (request.method, request.url.path)
        if self.replies.get(route):
            return _reply(self.replies[route].pop(0))
        if route == GET_CASE:
            fields = {
                "labels": self.labels,
                "status": {"name": self.status},
                "issuetype": {"name": "Subtarea", "subtask": self.subtask},
            }
            return httpx.Response(200, json={"key": CASE_KEY, "fields": fields})
        if route == GET_TRANSITIONS:
            return httpx.Response(200, json={"transitions": self.transitions})
        if route in (POST_TRANSITION, PUT_LABELS):
            return httpx.Response(204)
        if route == POST_COMMENT:
            return httpx.Response(201, json={"id": "10001"})
        pytest.fail(f"Petición no esperada: {request.method} {request.url.path}")

    def routes(self) -> list[Route]:
        return [(r.method, r.url.path) for r in self.requests]

    def writes(self) -> list[Route]:
        return [route for route in self.routes() if route[0] != "GET"]

    def count(self, route: Route) -> int:
        return self.routes().count(route)

    def body(self, route: Route) -> dict[str, Any]:
        [request] = [r for r in self.requests if (r.method, r.url.path) == route]
        return json.loads(request.content)


def make_execution_tests(
    handler: Handler,
    sleep: RecordingSleep | None = None,
    execution_transitions: dict[Any, Any] | None = None,
) -> JiraNativeTests:
    return JiraNativeTests(
        BASE_URL,
        SecretStr(EMAIL),
        SecretStr(TOKEN),
        subtask_type=SUBTASK_TYPE,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleep or RecordingSleep(),
        execution_transitions=execution_transitions,
    )


def execution_setup(
    jira: ExecutionJira | None = None, execution_transitions: dict[Any, Any] | None = None
) -> tuple[ExecutionJira, JiraNativeTests, RecordingSleep]:
    jira = jira or ExecutionJira()
    sleep = RecordingSleep()
    return jira, make_execution_tests(jira, sleep, execution_transitions), sleep


def label_update(jira: ExecutionJira) -> list[dict[str, str]]:
    return jira.body(PUT_LABELS)["update"]["labels"]


def comment_body(jira: ExecutionJira) -> dict[str, Any]:
    return jira.body(POST_COMMENT)["body"]


def link_marks(node: Any) -> list[dict[str, Any]]:
    return [
        mark
        for item in _walk(node)
        if item.get("type") == "text"
        for mark in item.get("marks") or []
        if mark.get("type") == "link"
    ]


def registered_entries(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in logs if e.get("event") == REGISTERED_EVENT]


# --- Validaciones previas, sin ninguna petición HTTP ----------------------------------------


@pytest.mark.parametrize("key", ["", "demo-21", "DEMO", "DEMO-21/../x", "DEMO-21\n", "1-DEMO"])
def test_record_execution_raises_publish_error_without_http_when_key_is_invalid(
    key: str,
) -> None:
    """RF-28: una clave inválida → PublishError sin ninguna petición HTTP."""
    tests = make_execution_tests(fail_if_called)
    with pytest.raises(PublishError) as exc_info:
        tests.record_execution(key, ExecutionStatus.PASSED, EVIDENCE)
    assert_safe_message(exc_info.value)


@pytest.mark.parametrize("status", ["pasó", "PASO", "", "ok", "ejecucion-paso"])
def test_record_execution_raises_publish_error_without_http_when_status_is_unknown(
    status: str,
) -> None:
    """RF-28: un resultado que no es de `ExecutionStatus` → PublishError sin HTTP."""
    tests = make_execution_tests(fail_if_called)
    with pytest.raises(PublishError, match="no es un resultado de ejecución"):
        tests.record_execution(CASE_KEY, status, EVIDENCE)


def test_record_execution_truncates_unknown_status_in_message() -> None:
    """RF-28 (límite): el resultado desconocido se muestra recortado a 30 caracteres."""
    tests = make_execution_tests(fail_if_called)
    with pytest.raises(PublishError) as exc_info:
        tests.record_execution(CASE_KEY, "z" * 200, EVIDENCE)
    assert "z" * 30 in str(exc_info.value)
    assert "z" * 31 not in str(exc_info.value)


@pytest.mark.parametrize("status", [ExecutionStatus.FAILED, "fallo"], ids=["enum", "str"])
@pytest.mark.parametrize("evidence", ["", "   ", "\n\t  \n"], ids=["vacia", "espacios", "blancos"])
def test_record_execution_raises_publish_error_without_http_when_failed_has_no_evidence(
    status: ExecutionStatus | str, evidence: str
) -> None:
    """RF-28, UI.md §6.6: «fallo» sin evidencia (vacía o solo espacios) → PublishError sin HTTP."""
    tests = make_execution_tests(fail_if_called)
    with pytest.raises(PublishError, match="necesita evidencia"):
        tests.record_execution(CASE_KEY, status, evidence)


def test_record_execution_raises_publish_error_without_http_when_evidence_exceeds_max() -> None:
    """RF-28 (límite): evidencia de MAX_EVIDENCE_CHARS + 1 caracteres → PublishError sin HTTP."""
    tests = make_execution_tests(fail_if_called)
    with pytest.raises(PublishError, match=str(MAX_EVIDENCE_CHARS)):
        tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, "x" * (MAX_EVIDENCE_CHARS + 1))


def test_record_execution_accepts_evidence_of_exactly_max_chars_after_strip() -> None:
    """RF-28 (límite): MAX_EVIDENCE_CHARS caracteres (más espacios en los extremos) se acepta."""
    jira, tests, _ = execution_setup()
    evidence = "  " + "x" * MAX_EVIDENCE_CHARS + "\n"
    tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, evidence)
    assert jira.count(POST_COMMENT) == 1


@pytest.mark.parametrize("as_str", [False, True], ids=["enum", "str"])
@pytest.mark.parametrize("status", list(ExecutionStatus))
def test_record_execution_accepts_enum_or_its_str_value(
    status: ExecutionStatus, as_str: bool
) -> None:
    """RF-28: se acepta el enum o su valor str; la etiqueta y el comentario son los del estado."""
    jira, tests, _ = execution_setup()
    tests.record_execution(CASE_KEY, status.value if as_str else status, EVIDENCE)
    assert label_update(jira)[-1] == {"add": EXECUTION_LABELS[status]}
    assert STATUS_TEXT[status] in all_texts(comment_body(jira))


# --- Lectura previa de la subtarea ----------------------------------------------------------


def test_record_execution_reads_labels_and_status_before_anything_else() -> None:
    """RF-28: la primera petición es GET /issue/{key}?fields=labels,status,issuetype."""
    jira, tests, _ = execution_setup()
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    first = jira.requests[0]
    assert (first.method, first.url.path) == GET_CASE
    assert dict(first.url.params) == {"fields": "labels,status,issuetype"}


@pytest.mark.parametrize(
    "labels",
    [[], ["CA-01", "tipo-positivo"], ["Caso-Prueba"], ["caso-prueba-x"], ["ejecucion-paso"]],
    ids=["sin-etiquetas", "sin-caso-prueba", "mayusculas", "prefijo", "solo-ejecucion"],
)
def test_record_execution_raises_publish_error_without_writes_when_issue_is_not_a_case(
    labels: list[str],
) -> None:
    """RF-28: sin la etiqueta `caso-prueba` → PublishError y ninguna escritura (ni POST ni PUT)."""
    jira, tests, _ = execution_setup(ExecutionJira(labels=labels))
    with pytest.raises(PublishError, match=CASE_LABEL) as exc_info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == []
    assert jira.routes() == [GET_CASE]
    assert_safe_message(exc_info.value)


@pytest.mark.parametrize(
    "payload", [{}, {"key": CASE_KEY}, {"fields": {}}, {"fields": {"labels": None}}]
)
def test_record_execution_raises_publish_error_without_writes_when_labels_are_missing(
    payload: dict[str, Any],
) -> None:
    """RF-28 (límite): respuesta sin `fields` o sin `labels` → no es un CP, no se escribe."""
    jira = ExecutionJira(replies={GET_CASE: [httpx.Response(200, json=payload)]})
    jira, tests, _ = execution_setup(jira)
    with pytest.raises(PublishError):
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == []


# --- Transición ------------------------------------------------------------------------------


def test_record_execution_posts_transition_matching_transition_name_case_insensitive() -> None:
    """RF-28: se elige la transición por su nombre, sin distinguir mayúsculas."""
    transitions = [
        {"id": "21", "name": "En curso", "to": {"name": "En curso"}},
        {"id": "41", "name": "dONE", "to": {"name": "Cerrada"}},
    ]
    jira, tests, _ = execution_setup(ExecutionJira(transitions=transitions))
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.body(POST_TRANSITION) == {"transition": {"id": "41"}}


def test_record_execution_posts_transition_matching_target_status_name() -> None:
    """RF-28: se elige la transición por el nombre del estado de destino (`to.name`)."""
    jira, tests, _ = execution_setup()  # «Finalizar» → «Done»
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.body(POST_TRANSITION) == {"transition": {"id": "31"}}
    assert jira.count(GET_TRANSITIONS) == 1


@pytest.mark.parametrize(
    ("status", "name"),
    [
        (ExecutionStatus.PASSED, "Done"),
        (ExecutionStatus.PASSED, "Hecho"),
        (ExecutionStatus.PASSED, "listo"),
        (ExecutionStatus.FAILED, "Falló"),
        (ExecutionStatus.FAILED, "FAILED"),
        (ExecutionStatus.BLOCKED, "Bloqueado"),
        (ExecutionStatus.BLOCKED, "blocked"),
        (ExecutionStatus.NOT_RUN, "Tareas por hacer"),
        (ExecutionStatus.NOT_RUN, "To Do"),
    ],
)
def test_record_execution_uses_default_transition_names(status: ExecutionStatus, name: str) -> None:
    """RF-28, PA-207: nombres por defecto de DEFAULT_EXECUTION_TRANSITIONS para cada estado."""
    transitions = [
        {"id": "21", "name": "En curso", "to": {"name": "En curso"}},
        {"id": "77", "name": f"Ir a {name}", "to": {"name": name}},
    ]
    jira, tests, _ = execution_setup(ExecutionJira(status="Revisión", transitions=transitions))
    tests.record_execution(CASE_KEY, status, EVIDENCE)
    assert jira.body(POST_TRANSITION) == {"transition": {"id": "77"}}


def test_default_execution_transitions_cover_every_status() -> None:
    """RF-28: hay nombres por defecto para todos los resultados."""
    assert set(DEFAULT_EXECUTION_TRANSITIONS) == set(ExecutionStatus)
    assert "Done" in DEFAULT_EXECUTION_TRANSITIONS[ExecutionStatus.PASSED]
    assert "Tareas por hacer" in DEFAULT_EXECUTION_TRANSITIONS[ExecutionStatus.NOT_RUN]


def test_record_execution_skips_transition_with_non_numeric_id() -> None:
    """RF-28: una transición con id no numérico se ignora y se usa la siguiente válida."""
    transitions = [
        {"id": "abc", "name": "Done"},
        {"id": "", "name": "Done"},
        {"name": "Done"},
        {"id": "52", "name": "Cerrar", "to": {"name": "Done"}},
    ]
    jira, tests, _ = execution_setup(ExecutionJira(transitions=transitions))
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.body(POST_TRANSITION) == {"transition": {"id": "52"}}


@pytest.mark.parametrize("current", ["Done", "DONE", "hecho"])
def test_record_execution_does_not_request_transitions_when_already_in_target_status(
    current: str,
) -> None:
    """RF-28: si el estado actual ya es uno de los nombres, no se piden transiciones."""
    jira, tests, _ = execution_setup(ExecutionJira(status=current))
    with capture_logs() as logs:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.routes() == [GET_CASE, PUT_LABELS, POST_COMMENT]
    [entry] = registered_entries(logs)
    assert entry["transitioned"] is False


@pytest.mark.parametrize(
    "transitions",
    [
        workflow_transitions(),
        [],
        [None, "Falló", 7],
        [{"id": "abc", "name": "Falló"}],
    ],
    ids=["sin-coincidencia", "vacia", "no-dict", "id-no-numerico"],
)
def test_record_execution_writes_label_and_comment_without_transition_when_none_matches(
    transitions: list[Any],
) -> None:
    """RF-28: sin transición válida no hay POST de transición, pero sí etiqueta y comentario."""
    jira, tests, _ = execution_setup(ExecutionJira(transitions=transitions))
    with capture_logs() as logs:
        tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, EVIDENCE)
    assert jira.routes() == [GET_CASE, GET_TRANSITIONS, PUT_LABELS, POST_COMMENT]
    assert any(e.get("event") == "sin transición para el resultado" for e in logs)
    [entry] = registered_entries(logs)
    assert entry["transitioned"] is False


def test_record_execution_handles_transitions_response_without_list() -> None:
    """RF-28 (límite): respuesta de transiciones sin la lista → sin transición, se registra."""
    jira = ExecutionJira(replies={GET_TRANSITIONS: [httpx.Response(200, json={})]})
    jira, tests, _ = execution_setup(jira)
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == [PUT_LABELS, POST_COMMENT]


def test_record_execution_uses_custom_mapping_and_keeps_defaults_for_other_statuses() -> None:
    """PA-207: `execution_transitions` sobrescribe un estado; los demás siguen por defecto."""
    transitions = [
        *workflow_transitions(),
        {"id": "61", "name": "Marcar rechazado", "to": {"name": "Rechazado"}},
    ]
    custom = {ExecutionStatus.FAILED: ["Rechazado"]}
    jira, tests, _ = execution_setup(ExecutionJira(transitions=transitions), custom)
    tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, EVIDENCE)
    assert jira.body(POST_TRANSITION) == {"transition": {"id": "61"}}

    jira2, tests2, _ = execution_setup(ExecutionJira(transitions=transitions), custom)
    tests2.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira2.body(POST_TRANSITION) == {"transition": {"id": "31"}}  # «Done» por defecto


def test_record_execution_custom_mapping_replaces_default_names_of_that_status() -> None:
    """PA-207: con un mapeo propio, los nombres por defecto de ese estado ya no se usan."""
    transitions = [{"id": "71", "name": "Failed", "to": {"name": "Failed"}}]
    custom = {ExecutionStatus.FAILED: ["Rechazado"]}
    jira, tests, _ = execution_setup(ExecutionJira(transitions=transitions), custom)
    tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, EVIDENCE)
    assert POST_TRANSITION not in jira.routes()
    assert jira.writes() == [PUT_LABELS, POST_COMMENT]


def test_record_execution_custom_mapping_strips_and_ignores_case() -> None:
    """PA-207: los nombres configurados se comparan sin espacios extremos ni mayúsculas."""
    transitions = [{"id": "81", "name": "Validado OK", "to": {"name": "QA"}}]
    custom = {ExecutionStatus.PASSED: ["  VALIDADO ok  "]}
    jira, tests, _ = execution_setup(ExecutionJira(transitions=transitions), custom)
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.body(POST_TRANSITION) == {"transition": {"id": "81"}}


@pytest.mark.parametrize(
    "names",
    [[], [""], ["   "], ["Re\nchazado"], ["Re\rchazado"], ["Re\tchazado"], ["x" * 61]],
    ids=["vacio", "cadena-vacia", "espacios", "salto-linea", "retorno", "tabulador", "61"],
)
def test_constructor_raises_value_error_when_execution_transitions_are_invalid(
    names: list[str],
) -> None:
    """PA-207: mapeo inválido (vacío, con salto de línea o > 60) → ValueError sin HTTP."""
    with pytest.raises(ValueError, match="no son válidas"):
        make_execution_tests(fail_if_called, execution_transitions={ExecutionStatus.FAILED: names})


def test_constructor_accepts_execution_transition_name_of_exactly_60_chars() -> None:
    """PA-207 (límite): un nombre de 60 caracteres se acepta."""
    custom = {ExecutionStatus.BLOCKED: ["x" * 60]}
    assert isinstance(make_execution_tests(fail_if_called, None, custom), JiraNativeTests)


# --- Orden de las escrituras ----------------------------------------------------------------


def test_record_execution_writes_transition_then_label_then_comment() -> None:
    """RF-28: orden transición → PUT etiqueta → POST comentario (el comentario, el último)."""
    jira, tests, _ = execution_setup()
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.routes() == [GET_CASE, GET_TRANSITIONS, POST_TRANSITION, PUT_LABELS, POST_COMMENT]


# --- Etiqueta ejecucion-<estado> ------------------------------------------------------------


def test_execution_labels_use_ejecucion_prefix_for_every_status() -> None:
    """RF-28: etiquetas `ejecucion-paso`, `ejecucion-fallo`, `ejecucion-bloqueado`…"""
    assert EXECUTION_LABELS == {
        ExecutionStatus.PASSED: "ejecucion-paso",
        ExecutionStatus.FAILED: "ejecucion-fallo",
        ExecutionStatus.BLOCKED: "ejecucion-bloqueado",
        ExecutionStatus.NOT_RUN: "ejecucion-sin-ejecutar",
    }


def test_record_execution_removes_only_other_present_execution_labels() -> None:
    """RF-28: quita solo las `ejecucion-*` presentes y distintas; no toca caso-prueba ni CA-01."""
    labels = [
        CASE_LABEL,
        "CA-01",
        "ejecucion-paso",
        "tipo-positivo",
        "ejecucion-bloqueado",
        "ejecucion-fallo",
    ]
    jira, tests, _ = execution_setup(ExecutionJira(labels=labels))
    tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, EVIDENCE)
    assert jira.body(PUT_LABELS) == {
        "update": {
            "labels": [
                {"remove": "ejecucion-paso"},
                {"remove": "ejecucion-bloqueado"},
                {"add": "ejecucion-fallo"},
            ]
        }
    }


def test_record_execution_only_adds_label_when_there_is_no_previous_execution() -> None:
    """RF-28: sin etiquetas `ejecucion-*` previas solo se añade la nueva."""
    jira, tests, _ = execution_setup()
    tests.record_execution(CASE_KEY, ExecutionStatus.BLOCKED, EVIDENCE)
    assert label_update(jira) == [{"add": "ejecucion-bloqueado"}]
    assert "fields" not in jira.body(PUT_LABELS)  # nunca sustituye la lista de etiquetas


def test_record_execution_never_removes_non_execution_labels() -> None:
    """RF-28: `caso-prueba`, los CA, RN y `tipo-*` nunca aparecen en el PUT."""
    labels = [CASE_LABEL, "CA-01", "RN-02", "tipo-negativo", "ejecucion-paso"]
    jira, tests, _ = execution_setup(ExecutionJira(labels=labels))
    tests.record_execution(CASE_KEY, ExecutionStatus.NOT_RUN, "")
    touched = {value for change in label_update(jira) for value in change.values()}
    assert touched == {"ejecucion-paso", "ejecucion-sin-ejecutar"}


# --- Comentario ADF --------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(ExecutionStatus))
def test_execution_comment_shows_status_text_for_each_status(status: ExecutionStatus) -> None:
    """RF-28: «Resultado de la ejecución: <STATUS_TEXT>» en el primer párrafo."""
    document = execution_comment(status, EVIDENCE)
    assert document["type"] == "doc"
    first = document["content"][0]
    assert first["type"] == "paragraph"
    assert "".join(all_texts(first)) == f"Resultado de la ejecución: {STATUS_TEXT[status]}"


def test_status_text_has_spanish_text_for_every_status() -> None:
    """RF-28: textos del resultado en español."""
    assert STATUS_TEXT == {
        ExecutionStatus.PASSED: "Pasó",
        ExecutionStatus.FAILED: "Falló",
        ExecutionStatus.BLOCKED: "Bloqueado",
        ExecutionStatus.NOT_RUN: "Sin ejecutar",
    }


def test_record_execution_comment_has_result_and_stripped_evidence() -> None:
    """RF-28: el comentario es execution_comment(estado, evidencia sin espacios extremos)."""
    jira, tests, _ = execution_setup()
    tests.record_execution(CASE_KEY, "fallo", f"\n  {EVIDENCE}  \n")
    body = comment_body(jira)
    assert body == execution_comment(ExecutionStatus.FAILED, EVIDENCE)
    texts = all_texts(body)
    assert "Resultado de la ejecución: " in texts
    assert "Falló" in texts
    assert "Evidencia:" in texts
    assert EVIDENCE in texts


def test_execution_comment_converts_https_link_to_link_mark() -> None:
    """RF-28: un enlace https de la evidencia → marca `link`."""
    document = execution_comment(
        ExecutionStatus.FAILED, "Captura: [pantalla](https://ejemplo.invalid/captura.png)"
    )
    assert link_marks(document) == [
        {"type": "link", "attrs": {"href": "https://ejemplo.invalid/captura.png"}}
    ]


def test_execution_comment_keeps_javascript_link_as_literal_text() -> None:
    """RF-28, PA-49: un enlace `javascript:` no se convierte en enlace; queda literal."""
    document = execution_comment(ExecutionStatus.FAILED, "[pulsa](javascript:alert(1))")
    assert link_marks(document) == []
    assert "javascript:alert(1)" in "".join(all_texts(document))


def test_execution_comment_keeps_html_as_literal_text() -> None:
    """RF-28: el HTML de la evidencia queda como texto literal."""
    document = execution_comment(ExecutionStatus.FAILED, "Salida <script>x</script> <b>ok</b>")
    joined = "".join(all_texts(document))
    assert "<script>x</script>" in joined
    assert "<b>ok</b>" in joined


def test_execution_comment_renders_markdown_evidence_as_adf() -> None:
    """RF-28: la evidencia en Markdown pasa por markdown_to_adf (listas, negrita…)."""
    document = execution_comment(ExecutionStatus.FAILED, "- Paso 1 **falla**\n- Paso 2 ok")
    assert "bulletList" in node_types(document)


@pytest.mark.parametrize(
    "status", [ExecutionStatus.PASSED, ExecutionStatus.BLOCKED, ExecutionStatus.NOT_RUN]
)
def test_record_execution_comment_says_sin_evidencia_when_evidence_is_blank(
    status: ExecutionStatus,
) -> None:
    """RF-28: sin evidencia (resultado distinto de «fallo») → «Sin evidencia.»."""
    jira, tests, _ = execution_setup()
    tests.record_execution(CASE_KEY, status, "   ")
    texts = all_texts(comment_body(jira))
    assert "Sin evidencia." in texts
    assert "Evidencia:" not in texts


# --- Errores ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (error_response(401), AuthenticationError),
        (error_response(403), AuthenticationError),
        (error_response(404), NotFoundError),
        (error_response(429, headers={"Retry-After": "1"}), RateLimitError),
        (error_response(500), ExternalServiceError),
    ],
    ids=["401", "403", "404", "429", "500"],
)
def test_record_execution_raises_without_writes_when_read_fails(
    reply: Reply, error: type[Exception]
) -> None:
    """RF-28: fallo en la lectura previa → su excepción y ninguna escritura."""
    jira = ExecutionJira(replies={GET_CASE: [reply] * 5})
    jira, tests, _ = execution_setup(jira)
    with pytest.raises(error) as exc_info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == []
    assert GET_TRANSITIONS not in jira.routes()
    assert_safe_message(exc_info.value)


def test_record_execution_raises_not_found_naming_the_key_when_case_does_not_exist() -> None:
    """RF-28: un 404 en la lectura nombra la clave del CP."""
    _jira, tests, _ = execution_setup(ExecutionJira(replies={GET_CASE: [error_response(404)]}))
    with pytest.raises(NotFoundError, match=CASE_KEY):
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (error_response(401), AuthenticationError),
        (error_response(404), NotFoundError),
        (error_response(429, headers={"Retry-After": "1"}), RateLimitError),
    ],
    ids=["401", "404", "429"],
)
def test_record_execution_raises_without_writes_when_transitions_query_fails(
    reply: Reply, error: type[Exception]
) -> None:
    """RF-28: fallo al pedir las transiciones → su excepción y ninguna escritura."""
    jira = ExecutionJira(replies={GET_TRANSITIONS: [reply] * 5})
    jira, tests, _ = execution_setup(jira)
    with pytest.raises(error) as exc_info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == []
    assert_safe_message(exc_info.value)


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (error_response(400), PublishError),
        (error_response(500), PublishError),
        (httpx.ConnectError("fallo de red ficticio"), PublishError),
        (httpx.Response(302, headers={"Location": "https://otro.example/x"}), PublishError),
        (error_response(401), AuthenticationError),
        (error_response(403), AuthenticationError),
        (error_response(404), NotFoundError),
        (error_response(429, headers={"Retry-After": "1"}), RateLimitError),
    ],
    ids=["400", "500", "red", "302", "401", "403", "404", "429"],
)
def test_record_execution_raises_without_label_or_comment_when_transition_fails(
    reply: Reply, error: type[Exception]
) -> None:
    """RF-28, §8: fallo en la transición → su excepción, una sola petición y nada más escrito."""
    jira, tests, sleep = execution_setup(ExecutionJira(replies={POST_TRANSITION: [reply]}))
    with pytest.raises(error) as exc_info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == [POST_TRANSITION]
    assert sleep.waits == []
    assert_safe_message(exc_info.value)


ALL_WRITE_FAILURES: dict[str, Reply] = {**FAILURE_REPLIES, **STOP_REPLIES}


@pytest.mark.parametrize(
    "reply", list(ALL_WRITE_FAILURES.values()), ids=list(ALL_WRITE_FAILURES.keys())
)
def test_record_execution_reports_incomplete_with_state_changed_when_label_put_fails(
    reply: Reply,
) -> None:
    """RF-28, §8: fallo del PUT tras la transición → PublishError «Registro incompleto … (con el
    estado ya cambiado)», sin comentario y sin reintentos."""
    jira, tests, sleep = execution_setup(ExecutionJira(replies={PUT_LABELS: [reply]}))
    with pytest.raises(PublishError) as exc_info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    message = str(exc_info.value)
    assert message.startswith(f"Registro incompleto de la ejecución en {CASE_KEY}")
    assert "(con el estado ya cambiado)" in message
    assert jira.writes() == [POST_TRANSITION, PUT_LABELS]
    assert sleep.waits == []
    assert_safe_message(exc_info.value)


def test_record_execution_reports_incomplete_without_state_change_when_label_put_fails() -> None:
    """RF-28: fallo del PUT sin transición previa → «(sin cambiar el estado)»."""
    jira = ExecutionJira(status="Done", replies={PUT_LABELS: [error_response(500)]})
    jira, tests, _ = execution_setup(jira)
    with pytest.raises(PublishError, match=r"\(sin cambiar el estado\)") as exc_info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == [PUT_LABELS]
    assert_safe_message(exc_info.value)


@pytest.mark.parametrize(
    "reply", list(ALL_WRITE_FAILURES.values()), ids=list(ALL_WRITE_FAILURES.keys())
)
def test_record_execution_reports_incomplete_when_comment_fails(reply: Reply) -> None:
    """RF-28, §8: fallo del comentario → PublishError «Registro incompleto», un solo intento."""
    jira, tests, sleep = execution_setup(ExecutionJira(replies={POST_COMMENT: [reply]}))
    with pytest.raises(PublishError, match="Registro incompleto") as exc_info:
        tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, EVIDENCE)
    assert "(sin cambiar el estado)" in str(exc_info.value)  # el flujo no tiene «Falló»
    assert jira.writes() == [PUT_LABELS, POST_COMMENT]
    assert sleep.waits == []
    assert_safe_message(exc_info.value)


def test_record_execution_makes_exactly_one_request_per_write() -> None:
    """§8: en el camino feliz cada escritura se envía una sola vez y no se espera."""
    jira, tests, sleep = execution_setup()
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert [jira.count(r) for r in (POST_TRANSITION, PUT_LABELS, POST_COMMENT)] == [1, 1, 1]
    assert sleep.waits == []


def test_record_execution_retries_read_but_not_writes() -> None:
    """§8: la lectura previa se reintenta ante 5xx; las escrituras no."""
    jira = ExecutionJira(replies={GET_CASE: [error_response(503)]})
    jira, tests, sleep = execution_setup(jira)
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.count(GET_CASE) == 2
    assert len(sleep.waits) == 1
    assert jira.writes() == [POST_TRANSITION, PUT_LABELS, POST_COMMENT]


# --- Log -------------------------------------------------------------------------------------


def test_record_execution_logs_key_status_transitioned_and_duration_without_secrets() -> None:
    """Seguridad, RF-28: log `record_execution` con jira_key, status, transitioned y
    duration_ms; sin credenciales ni la evidencia."""
    _jira, tests, _ = execution_setup()
    with capture_logs() as logs:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, f"{EVIDENCE} {EVIDENCE_MARKER}")
    [entry] = registered_entries(logs)
    assert entry["action"] == "record_execution"
    assert entry["jira_key"] == CASE_KEY
    assert entry["status"] == "paso"
    assert entry["transitioned"] is True
    assert isinstance(entry["duration_ms"], int)
    assert entry["duration_ms"] >= 0
    dumped = json.dumps(logs, default=str)
    for forbidden in (TOKEN, EMAIL, BASIC_CREDENTIALS, BODY_MARKER, EVIDENCE_MARKER):
        assert forbidden not in dumped


def test_record_execution_does_not_log_success_when_a_write_fails() -> None:
    """RF-28: si la escritura falla no se registra en el log como completada."""
    jira = ExecutionJira(replies={POST_COMMENT: [error_response(500)]})
    _jira, tests, _ = execution_setup(jira)
    with capture_logs() as logs, pytest.raises(PublishError):
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert registered_entries(logs) == []


# --- Respuestas malformadas y configuración inválida ------------------------------------------


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        (
            GET_CASE,
            {
                "fields": {
                    "labels": [CASE_LABEL],
                    "status": "En curso",
                    "issuetype": {"subtask": True},
                }
            },
        ),
        (GET_TRANSITIONS, {"transitions": [{"id": "31", "name": "Finalizar", "to": "Done"}]}),
    ],
    ids=["status-texto", "to-texto"],
)
def test_record_execution_tolerates_unexpected_response_shape(
    route: Route, payload: dict[str, Any]
) -> None:
    """Un `status` o un `to` que no son objetos se ignoran (como en las lecturas del tracker):
    sin `AttributeError`; la etiqueta y el comentario se registran igualmente."""
    jira = ExecutionJira(replies={route: [httpx.Response(200, json=payload)]})
    jira, tests, _ = execution_setup(jira)
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.count(PUT_LABELS) == 1
    assert jira.count(POST_COMMENT) == 1


def test_constructor_raises_value_error_when_execution_transitions_value_is_bare_str() -> None:
    """PA-207: un nombre suelto (str) en vez de una secuencia de nombres es un mapeo inválido."""
    custom = {ExecutionStatus.FAILED: "Rechazado"}
    with pytest.raises(ValueError):
        make_execution_tests(fail_if_called, None, custom)


@pytest.mark.parametrize("issuetype", [{"subtask": False}, {}, "Subtarea", None])
def test_record_execution_raises_without_writes_when_issue_is_not_a_subtask(
    issuetype: Any,
) -> None:
    """Seguridad: con la etiqueta `caso-prueba` puesta a mano en una HU no basta; debe ser una
    subtarea (`issuetype.subtask`), y si no, `PublishError` sin ninguna escritura."""
    payload = {"fields": {"labels": [CASE_LABEL], "status": {"name": "En curso"}}}
    if issuetype is not None:
        payload["fields"]["issuetype"] = issuetype
    jira, tests, _ = execution_setup(
        ExecutionJira(replies={GET_CASE: [httpx.Response(200, json=payload)]})
    )
    with pytest.raises(PublishError) as info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.writes() == []
    assert_safe_message(info.value)


@pytest.mark.parametrize("transition_id", ["²", "١٢", "3 1", "-31", ""])
def test_record_execution_skips_transition_with_non_ascii_numeric_id(transition_id: str) -> None:
    """Seguridad: el id de la transición debe ser numérico ASCII; si no, se ignora."""
    jira = ExecutionJira(
        transitions=[{"id": transition_id, "name": "Done", "to": {"name": "Done"}}]
    )
    jira, tests, _ = execution_setup(jira)
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, EVIDENCE)
    assert jira.count(POST_TRANSITION) == 0
    assert jira.count(POST_COMMENT) == 1


def test_record_execution_unknown_status_message_has_no_control_characters() -> None:
    """El resultado desconocido se muestra sin caracteres de control."""
    with pytest.raises(PublishError) as info:
        make_execution_tests(fail_if_called).record_execution(CASE_KEY, "x\n\x1b[31m", EVIDENCE)
    assert "\n" not in str(info.value)
    assert "\x1b" not in str(info.value)
