"""Prueba cruzada T-35 (RNF-19): el área B prueba `adapters/testmgmt/` del área A (T-30, T-47).

Cubre D-09 §6.2 (cada CP es una subtarea `[CP-XX] …` de la HU con las etiquetas `caso-prueba`,
CA, RN y `tipo-<tipo>` y una descripción ADF literal; `estrategia-<CLAVE>.md` y
`matriz-<CLAVE>.md` como adjuntos), RF-30, RNF-13 (publicación uno a uno; `failed` con IDs de CP
y nombres de adjunto; ante 401/403/429 se deja de escribir), PA-05 (los CP que ya existen cuentan
en `created` con su clave y no se duplican; si `list_cases` falla no se escribe nada), RF-28
(`record_execution`, T-47) y SPEC-00 §4, §8 y anexo §11 (escrituras de un solo intento, errores
en español sin cuerpos ni credenciales).

Se centra en los bordes que `test_testmgmt_jira_native.py` no fija: etiquetas válidas para Jira,
títulos largos o ya prefijados con otro CP, claves manipuladas en el nombre del adjunto, tamaño
del adjunto y 413, `JIRA_TEST_SUBTASK_TYPE` desde `Settings`, un CP existente con otro título,
IDs repetidos, respuestas 200 con una forma inesperada, transiciones inexistentes y mensajes.

Sin red: todo el HTTP pasa por `httpx.MockTransport` con un Jira simulado propio. Datos 100 %
ficticios (proyecto DEMO, dominio example) y credenciales obviamente de prueba. Los defectos
confirmados van como `xfail(strict=True)` con su PA; el resto fija el comportamiento actual.
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
from adapters.errors import (
    AgentError,
    AuthenticationError,
    ExternalServiceError,
    PublishError,
)
from adapters.jira.jql import CASE_LABEL
from adapters.testmgmt.jira_native import (
    JiraNativeTests,
    attachment_files,
    case_labels,
)
from core.config import Settings
from core.factories import build_test_management
from schemas.common import Priority
from schemas.test_case import ExecutionStatus, TestCase, TestCaseType, TestStep, TestSuite

BASE_URL = "https://villaficticia-t35.example"
EMAIL = "qa.ficticia.t35@example.com"
TOKEN = "TOKEN-FICTICIO-T35-NO-ES-REAL"
BODY_MARKER = "CUERPO-INTERNO-FICTICIO-T35"
STORY = "DEMO-7"
PROJECT = "DEMO"
SUBTASK_TYPE = "Subtarea"
SEARCH_PATH = "/rest/api/3/search/jql"
ISSUE_PATH = "/rest/api/3/issue"
STORY_PATH = f"/rest/api/3/issue/{STORY}"
ATTACH_PATH = f"{STORY_PATH}/attachments"
STRATEGY_FILE = f"estrategia-{STORY}.md"
MATRIX_FILE = f"matriz-{STORY}.md"
CASE_KEY = "DEMO-71"
CASE_PATH = f"/rest/api/3/issue/{CASE_KEY}"
TRANSITIONS_PATH = f"{CASE_PATH}/transitions"
COMMENT_PATH = f"{CASE_PATH}/comment"
EVIDENCE = "Evidencia ficticia-t35: el formulario ficticio no guarda el préstamo PR-0007."
# Jira: una etiqueta no puede tener espacios y tiene como mucho 255 caracteres.
JIRA_LABEL = re.compile(r"^\S{1,255}$")

Reply = httpx.Response | Exception
Route = tuple[str, str]


# --- Datos sintéticos ------------------------------------------------------------------------


def make_case(
    internal_id: str = "CP-01",
    title: str = "Renovar un préstamo ficticio",
    *,
    criteria: list[str] | None = None,
    rules: list[str] | None = None,
    case_type: TestCaseType = TestCaseType.POSITIVE,
    action: str = "Pulsar «Renovar»",
    gherkin: str | None = None,
) -> TestCase:
    return TestCase(
        internal_id=internal_id,
        title=title,
        criterion_ids=criteria or ["CA-01"],
        rule_ids=rules or [],
        type=case_type,
        preconditions=["Préstamo ficticio activo"],
        steps=[TestStep(action=action, data="PR-0007", expected="Se amplía la fecha")],
        gherkin=gherkin,
        priority=Priority.MUST,
    )


def make_suite(
    cases: list[TestCase] | None = None, story: str = STORY, strategy: str = "# Estrategia\n"
) -> TestSuite:
    return TestSuite(
        story_jira_key=story,
        cases=cases or [make_case("CP-01"), make_case("CP-02"), make_case("CP-03")],
        strategy_md=strategy,
    )


def error_response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    """Error de Jira con un cuerpo que nunca debe llegar a los mensajes."""
    body = {"errorMessages": [BODY_MARKER], "errors": {"summary": BODY_MARKER}}
    return httpx.Response(status, json=body, headers=headers)


def assert_safe(message: object) -> None:
    """Mensaje en español sin cuerpo de la respuesta ni credenciales (§8)."""
    text = str(message)
    for forbidden in (BODY_MARKER, TOKEN, EMAIL, "Authorization", "Basic "):
        assert forbidden not in text


def _reply(reply: Reply) -> httpx.Response:
    if isinstance(reply, Exception):
        raise reply
    return reply


# --- Jira simulado ---------------------------------------------------------------------------


@dataclass
class FakeSite:
    """Handler de `MockTransport` con estado: subtareas y adjuntos de la HU `STORY`.

    `replies[(método, ruta)]` sustituye, una a una, a la respuesta por defecto de esa ruta;
    `case_replies[CP-XX]` y `attach_replies[nombre]` sustituyen la de una creación o subida.
    """

    subtasks: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    replies: dict[Route, list[Reply]] = field(default_factory=dict)
    case_replies: dict[str, Reply] = field(default_factory=dict)
    attach_replies: dict[str, Reply] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    next_number: int = 100

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        route = (request.method, request.url.path)
        if self.replies.get(route):
            return _reply(self.replies[route].pop(0))
        if route == ("GET", SEARCH_PATH):
            return httpx.Response(200, json={"issues": list(self.subtasks), "isLast": True})
        if route == ("GET", STORY_PATH):
            files = [{"id": str(i), "filename": n} for i, n in enumerate(self.attachments)]
            return httpx.Response(200, json={"key": STORY, "fields": {"attachment": files}})
        if route == ("POST", ISSUE_PATH):
            return self._create(request)
        if route == ("POST", ATTACH_PATH):
            name = filename_of(request)
            if name in self.attach_replies:
                return _reply(self.attach_replies[name])
            self.attachments.append(name)
            return httpx.Response(200, json=[{"id": "900", "filename": name}])
        pytest.fail(f"Petición no esperada: {request.method} {request.url.path}")

    def _create(self, request: httpx.Request) -> httpx.Response:
        summary = fields_of(request)["summary"]
        case_id = summary[1 : summary.index("]")]
        if case_id in self.case_replies:
            return _reply(self.case_replies[case_id])
        self.next_number += 1
        key = f"{PROJECT}-{self.next_number}"
        self.subtasks.append(subtask(key, summary))
        return httpx.Response(201, json={"id": str(self.next_number), "key": key})

    def creates(self) -> list[httpx.Request]:
        return [r for r in self.requests if (r.method, r.url.path) == ("POST", ISSUE_PATH)]

    def uploads(self) -> list[httpx.Request]:
        return [r for r in self.requests if (r.method, r.url.path) == ("POST", ATTACH_PATH)]

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]


def subtask(key: str, summary: str) -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "issuetype": {"name": SUBTASK_TYPE},
            "status": {"name": "Por hacer"},
        },
    }


def fields_of(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)["fields"]


def filename_of(request: httpx.Request) -> str:
    match = re.search(rb'filename="([^"]+)"', request.content)
    assert match, "el adjunto no va en multipart con filename"
    return match.group(1).decode()


class Sleeps:
    """`sleep` inyectado: registra las esperas sin dormir."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def make_tests(
    handler: Callable[[httpx.Request], httpx.Response],
    sleep: Sleeps | None = None,
    **kwargs: Any,
) -> JiraNativeTests:
    return JiraNativeTests(
        BASE_URL,
        SecretStr(EMAIL),
        SecretStr(TOKEN),
        subtask_type=kwargs.pop("subtask_type", SUBTASK_TYPE),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleep or Sleeps(),
        **kwargs,
    )


def setup(site: FakeSite | None = None) -> tuple[FakeSite, JiraNativeTests, Sleeps]:
    site = site or FakeSite()
    sleep = Sleeps()
    return site, make_tests(site, sleep), sleep


def fail_if_called(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"No debía haber HTTP: {request.method} {request.url.path}")


# --- Protocolo y composición (SPEC-00 §4, anexo §11) -----------------------------------------


def test_jira_native_tests_satisfies_test_management_protocol_including_record_execution() -> None:
    """SPEC-00 §4 y anexo §11 (T-47): cumple `TestManagement`, con `record_execution`."""
    tests = make_tests(fail_if_called)
    assert isinstance(tests, base.TestManagement)
    assert callable(tests.record_execution)


def test_build_test_management_uses_subtask_type_from_settings() -> None:
    """D-09: `JIRA_TEST_SUBTASK_TYPE` de `Settings` llega como `issuetype` de cada CP."""
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        jira_base_url=BASE_URL,
        jira_email=SecretStr(EMAIL),
        jira_api_token=SecretStr(TOKEN),
        jira_cloud_id=None,
        jira_test_subtask_type="Sub-task ficticia",
    )
    site = FakeSite()
    tests = build_test_management(
        settings, http_client=httpx.Client(transport=httpx.MockTransport(site)), sleep=Sleeps()
    )
    tests.publish_suite(make_suite([make_case("CP-01")]))
    assert [fields_of(r)["issuetype"] for r in site.creates()] == [{"name": "Sub-task ficticia"}]


def test_settings_default_subtask_type_is_subtarea() -> None:
    """D-09: sin configurar, el tipo de subtarea es «Subtarea»."""
    assert Settings(_env_file=None).jira_test_subtask_type == "Subtarea"  # type: ignore[call-arg]


# --- Subtarea CP: título, etiquetas y descripción (D-09 §6.2, R-05) ---------------------------


def test_publish_suite_sends_parent_project_and_prefixed_summary_for_each_case() -> None:
    """D-09, R-05: cada CP es subtarea de la HU, en su proyecto, con título `[CP-XX] …`."""
    site, tests, _ = setup()
    tests.publish_suite(make_suite())
    sent = [fields_of(r) for r in site.creates()]
    assert [f["summary"] for f in sent] == [
        "[CP-01] Renovar un préstamo ficticio",
        "[CP-02] Renovar un préstamo ficticio",
        "[CP-03] Renovar un préstamo ficticio",
    ]
    assert {json.dumps(f["parent"]) for f in sent} == {json.dumps({"key": STORY})}
    assert {json.dumps(f["project"]) for f in sent} == {json.dumps({"key": PROJECT})}


def test_publish_suite_truncates_long_summary_to_255_keeping_case_prefix() -> None:
    """Límite: un título de 400 caracteres se recorta a 255 y conserva `[CP-04]`."""
    site, tests, _ = setup()
    tests.publish_suite(make_suite([make_case("CP-04", "Título ficticio " + "x" * 400)]))
    [summary] = [fields_of(r)["summary"] for r in site.creates()]
    assert len(summary) == 255
    assert summary.startswith("[CP-04] Título ficticio ")


def test_publish_suite_collapses_newlines_and_control_chars_in_summary() -> None:
    """R-05: el título va en una sola línea, sin caracteres de control."""
    site, tests, _ = setup()
    tests.publish_suite(make_suite([make_case("CP-05", "Línea uno\r\nlínea\tdos\x00\x07 fin")]))
    [summary] = [fields_of(r)["summary"] for r in site.creates()]
    assert summary == "[CP-05] Línea uno línea dos fin"


def test_publish_suite_keeps_own_prefix_when_title_starts_with_other_case_id() -> None:
    """R-05: un título que empieza por `[CP-09]` en el CP-06 no suplanta su identificador."""
    site, tests, _ = setup()
    tests.publish_suite(make_suite([make_case("CP-06", "[CP-09] Título ficticio")]))
    [summary] = [fields_of(r)["summary"] for r in site.creates()]
    assert summary == "[CP-06] [CP-09] Título ficticio"


def test_publish_suite_does_not_duplicate_prefix_when_title_already_has_it() -> None:
    """R-05: un título que ya lleva `[CP-07]` no se prefija dos veces."""
    site, tests, _ = setup()
    tests.publish_suite(make_suite([make_case("CP-07", "  [CP-07]  Título ficticio")]))
    [summary] = [fields_of(r)["summary"] for r in site.creates()]
    assert summary == "[CP-07] Título ficticio"


@pytest.mark.parametrize("case_type", list(TestCaseType))
def test_case_labels_are_valid_jira_labels_for_every_type(case_type: TestCaseType) -> None:
    """D-09 §6.2: `caso-prueba`, CA, RN y `tipo-<tipo>`, todas sin espacios y ≤ 255."""
    case = make_case(criteria=["CA-01", "CA-12"], rules=["RN-03"], case_type=case_type)
    labels = case_labels(case)
    assert labels == [CASE_LABEL, "CA-01", "CA-12", "RN-03", f"tipo-{case_type.value}"]
    assert all(JIRA_LABEL.fullmatch(label) for label in labels)


def test_publish_suite_sends_labels_as_list_of_strings_without_duplicates() -> None:
    """D-09: la misma referencia repetida en CA no genera etiquetas duplicadas."""
    site, tests, _ = setup()
    tests.publish_suite(make_suite([make_case("CP-01", criteria=["CA-02", "CA-02"])]))
    [labels] = [fields_of(r)["labels"] for r in site.creates()]
    assert labels == [CASE_LABEL, "CA-02", "tipo-positivo"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-205, ya anotada): `schemas/test_case.py` valida CA/RN con `re.match` "
        "y `$`, "
        "que acepta un salto de línea final; la etiqueta `CA-01\\n` no es válida para Jira "
        "(schemas/test_case.py:60-61)"
    ),
)
def test_case_labels_are_valid_jira_labels_even_with_trailing_newline_in_criterion() -> None:
    """D-09: ninguna etiqueta enviada puede tener espacios ni saltos de línea."""
    labels = case_labels(make_case(criteria=["CA-01\n"]))
    assert all(JIRA_LABEL.fullmatch(label) for label in labels)


def test_publish_suite_description_is_literal_adf_without_markdown_html_or_controls() -> None:
    """D-09 §6.2: la descripción es ADF literal: ni Markdown ni HTML se interpretan y los
    caracteres de control y bidi se quitan."""
    action = "**Pulsar** <b>Renovar</b> [x](javascript:alert(1))\x00‮"
    site, tests, _ = setup()
    tests.publish_suite(make_suite([make_case("CP-01", action=action)]))
    [description] = [fields_of(r)["description"] for r in site.creates()]
    assert description["type"] == "doc" and description["version"] == 1
    dumped = json.dumps(description, ensure_ascii=False)
    assert "**Pulsar** <b>Renovar</b> [x](javascript:alert(1))" in dumped
    assert '"link"' not in dumped
    assert "\\u0000" not in dumped and "‮" not in dumped


# --- Adjuntos (D-09 §6.2) --------------------------------------------------------------------


def test_attachment_files_are_named_after_story_key() -> None:
    """D-09 §6.2: `estrategia-<CLAVE>.md` y `matriz-<CLAVE>.md`."""
    assert list(attachment_files(make_suite())) == [STRATEGY_FILE, MATRIX_FILE]


@pytest.mark.parametrize(
    "story",
    ["../DEMO-7", "DEMO-7/../../x", "DEMO-7\\..\\x", "DEMO-7.md", "DEMO-7\n", "DEMO-7%2F.."],
)
def test_attachment_files_rejects_manipulated_story_key(story: str) -> None:
    """Seguridad: una clave con `../`, separadores o saltos de línea no da nombre de archivo."""
    with pytest.raises(PublishError) as info:
        attachment_files(make_suite(story=story))
    assert_safe(info.value)


@pytest.mark.parametrize("story", ["../DEMO-7", "DEMO-7/../../x", "DEMO-7%2F.."])
def test_publish_suite_makes_no_http_when_story_key_is_manipulated(story: str) -> None:
    """Seguridad: con una clave manipulada no sale ninguna petición."""
    with pytest.raises(PublishError):
        make_tests(fail_if_called).publish_suite(make_suite(story=story))


def test_publish_suite_uploads_both_files_as_markdown_multipart_with_xsrf_header() -> None:
    """D-09: los dos adjuntos van en multipart (`file`, `text/markdown`) con
    `X-Atlassian-Token: no-check` y el nombre exacto."""
    site, tests, _ = setup()
    tests.publish_suite(make_suite())
    uploads = site.uploads()
    assert [filename_of(r) for r in uploads] == [STRATEGY_FILE, MATRIX_FILE]
    for request in uploads:
        assert request.headers["X-Atlassian-Token"] == "no-check"
        assert request.headers["Content-Type"].startswith("multipart/form-data")
        assert b'name="file"' in request.content
        assert b"Content-Type: text/markdown" in request.content


def test_publish_suite_uploads_large_strategy_in_a_single_request() -> None:
    """Límite: una estrategia de ~2 MB se sube entera en una sola petición (UTF-8)."""
    strategy = "# Estrategia ficticia\n" + ("línea ficticia ñ\n" * 120_000)
    site, tests, _ = setup()
    result = tests.publish_suite(make_suite(strategy=strategy))
    [strategy_upload] = [r for r in site.uploads() if filename_of(r) == STRATEGY_FILE]
    assert strategy.encode("utf-8") in strategy_upload.content
    assert result.failed == []


def test_publish_suite_marks_attachment_failed_when_jira_rejects_size_with_413() -> None:
    """RNF-13: un 413 (adjunto demasiado grande) deja el nombre en `failed`, sin reintentar,
    y el resto sigue."""
    site = FakeSite(attach_replies={STRATEGY_FILE: error_response(413)})
    site, tests, sleep = setup(site)
    result = tests.publish_suite(make_suite())
    assert result.failed == [STRATEGY_FILE]
    assert [filename_of(r) for r in site.uploads()] == [STRATEGY_FILE, MATRIX_FILE]
    assert sleep.waits == []


# --- Publicación parcial (RNF-13) ------------------------------------------------------------


def test_publish_suite_reports_failed_case_ids_and_attachment_names_together() -> None:
    """RNF-13: `failed` lleva los IDs de CP y los nombres de adjunto, en orden."""
    site = FakeSite(
        case_replies={"CP-02": error_response(500)},
        attach_replies={MATRIX_FILE: error_response(400)},
    )
    site, tests, _ = setup(site)
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-101", "DEMO-102"]
    assert result.failed == ["CP-02", MATRIX_FILE]


@pytest.mark.parametrize("status", [401, 403, 429])
def test_publish_suite_stops_all_writes_after_auth_or_rate_limit_on_a_case(status: int) -> None:
    """RNF-13: tras un 401/403/429 en CP-02 no se escribe nada más (ni CP-03 ni adjuntos)
    y todo lo pendiente queda en `failed`."""
    headers = {"Retry-After": "1"} if status == 429 else None
    site = FakeSite(case_replies={"CP-02": error_response(status, headers)})
    site, tests, sleep = setup(site)
    result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-101"]
    assert result.failed == ["CP-02", "CP-03", STRATEGY_FILE, MATRIX_FILE]
    assert len(site.writes()) == 2
    assert sleep.waits == []


def test_publish_suite_does_not_wait_even_with_short_retry_after_on_write_429() -> None:
    """§8: un 429 en una escritura nunca se espera ni se repite, aunque `Retry-After` sea 0."""
    site = FakeSite(case_replies={"CP-01": error_response(429, {"Retry-After": "0"})})
    site, tests, sleep = setup(site)
    tests.publish_suite(make_suite([make_case("CP-01")]))
    assert len(site.creates()) == 1
    assert sleep.waits == []


@pytest.mark.parametrize("status", [400, 404, 409, 500, 503])
def test_publish_suite_continues_after_non_stopping_error_without_retry(status: int) -> None:
    """RNF-13: un error que no es 401/403/429 marca ese CP y sigue con el resto; un solo
    intento por CP (§8)."""
    site = FakeSite(case_replies={"CP-01": error_response(status)})
    site, tests, sleep = setup(site)
    result = tests.publish_suite(make_suite())
    assert result.failed == ["CP-01"]
    assert len(result.created) == 2
    assert [fields_of(r)["summary"][:7] for r in site.creates()] == [
        "[CP-01]",
        "[CP-02]",
        "[CP-03]",
    ]
    assert sleep.waits == []


def test_publish_suite_marks_case_failed_on_network_error_without_retry() -> None:
    """§8: un fallo de red en una escritura no se reintenta (podría haberse aplicado)."""
    site = FakeSite(case_replies={"CP-02": httpx.ReadTimeout("tiempo agotado ficticio")})
    site, tests, sleep = setup(site)
    result = tests.publish_suite(make_suite())
    assert result.failed == ["CP-02"]
    assert len(site.creates()) == 3
    assert sleep.waits == []


def test_publish_suite_stops_attachments_after_auth_error_on_first_upload() -> None:
    """RNF-13: un 401 en la estrategia impide subir la matriz."""
    site = FakeSite(attach_replies={STRATEGY_FILE: error_response(401)})
    site, tests, _ = setup(site)
    result = tests.publish_suite(make_suite())
    assert result.failed == [STRATEGY_FILE, MATRIX_FILE]
    assert [filename_of(r) for r in site.uploads()] == [STRATEGY_FILE]


# --- Idempotencia (PA-05) --------------------------------------------------------------------


def test_publish_suite_reuses_existing_case_with_other_title_without_rewriting_it() -> None:
    """PA-05: un `[CP-02]` ya publicado con otro título cuenta en `created` con su clave y no
    se vuelve a crear ni se modifica (comportamiento actual; ver PA-204)."""
    site = FakeSite(subtasks=[subtask("DEMO-55", "[CP-02] Título antiguo ficticio")])
    site, tests, _ = setup(site)
    with capture_logs() as logs:
        result = tests.publish_suite(make_suite())
    assert result.created == ["DEMO-101", "DEMO-55", "DEMO-102"]
    assert [fields_of(r)["summary"][:7] for r in site.creates()] == ["[CP-01]", "[CP-03]"]
    assert not [r for r in site.requests if r.method == "PUT"]
    [entry] = [e for e in logs if e.get("action") == "publish_suite"]
    assert entry["reused"] == 1


def test_publish_suite_reuses_first_key_when_case_id_appears_twice_in_jira() -> None:
    """PA-05: si Jira ya tiene dos `[CP-01]`, se usa el primero y no se crea un tercero."""
    site = FakeSite(
        subtasks=[subtask("DEMO-40", "[CP-01] Copia A"), subtask("DEMO-41", "[CP-01] Copia B")]
    )
    site, tests, _ = setup(site)
    result = tests.publish_suite(make_suite([make_case("CP-01")]))
    assert result.created == ["DEMO-40"]
    assert site.creates() == []


def test_publish_suite_does_not_treat_unpadded_id_as_same_case() -> None:
    """PA-05: `[CP-1]` en Jira no es `CP-01` (los IDs se comparan literalmente)."""
    site = FakeSite(subtasks=[subtask("DEMO-40", "[CP-1] Caso ficticio")])
    site, tests, _ = setup(site)
    result = tests.publish_suite(make_suite([make_case("CP-01")]))
    assert result.created == ["DEMO-101"]


def test_publish_suite_second_run_writes_nothing() -> None:
    """PA-05: publicar dos veces la misma suite no hace ninguna escritura la segunda vez."""
    site, tests, _ = setup()
    first = tests.publish_suite(make_suite())
    writes = len(site.writes())
    second = tests.publish_suite(make_suite())
    assert second.created == first.created
    assert second.failed == []
    assert len(site.writes()) == writes


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-190): `publish_suite` confía en que los IDs de la suite sean únicos; "
        "si la suite se modifica tras validarse (`TestSuite` es mutable), un CP repetido crea "
        "dos subtareas `[CP-01]` en la misma llamada (adapters/testmgmt/jira_native.py:165-180)"
    ),
)
def test_publish_suite_creates_case_only_once_when_id_is_repeated_in_mutated_suite() -> None:
    """PA-05: un mismo `[CP-01]` nunca se crea dos veces en Jira."""
    suite = make_suite([make_case("CP-01")])
    suite.cases.append(make_case("CP-01", "Otra versión ficticia"))  # sin revalidar
    site, tests, _ = setup()
    tests.publish_suite(suite)
    assert len(site.creates()) == 1


@pytest.mark.parametrize(
    "reply",
    [error_response(401), error_response(500), httpx.ConnectError("red ficticia")],
    ids=["401", "500-agotado", "red"],
)
def test_publish_suite_writes_nothing_when_list_cases_fails(reply: Reply) -> None:
    """PA-05: si la búsqueda de CP existentes falla, no se escribe nada y el error es un
    `AgentError` con mensaje seguro."""
    site = FakeSite(replies={("GET", SEARCH_PATH): [reply, reply, reply]})
    site, tests, _ = setup(site)
    with pytest.raises(AgentError) as info:
        tests.publish_suite(make_suite())
    assert site.writes() == []
    assert_safe(info.value)


def test_publish_suite_retries_list_cases_429_with_injected_sleep_then_publishes() -> None:
    """§8: la búsqueda (lectura) sí reintenta con backoff; las esperas usan el `sleep`."""
    site = FakeSite(replies={("GET", SEARCH_PATH): [error_response(429, {"Retry-After": "2"})]})
    site, tests, sleep = setup(site)
    result = tests.publish_suite(make_suite([make_case("CP-01")]))
    assert sleep.waits == [2.0]
    assert result.created == ["DEMO-101"]


@pytest.mark.parametrize("payload", [[], {"fields": "x"}], ids=["lista", "fields-texto"])
def test_publish_suite_reports_attachments_failed_when_attachment_query_has_unexpected_shape(
    payload: Any,
) -> None:
    """RNF-13: lo creado nunca se pierde; los adjuntos quedan en `failed`."""
    site = FakeSite(replies={("GET", STORY_PATH): [httpx.Response(200, json=payload)]})
    site, tests, _ = setup(site)
    result = tests.publish_suite(make_suite([make_case("CP-01")]))
    assert result.created == ["DEMO-101"]
    assert result.failed == [STRATEGY_FILE, MATRIX_FILE]


@pytest.mark.parametrize(
    "payload", [[], {"issues": ["DEMO-9"]}], ids=["pagina-lista", "incidencia-texto"]
)
def test_list_cases_raises_external_error_when_search_has_unexpected_shape(payload: Any) -> None:
    """§8: una respuesta con forma inesperada es un error externo con mensaje en español."""
    site = FakeSite(replies={("GET", SEARCH_PATH): [httpx.Response(200, json=payload)]})
    _site, tests, _ = setup(site)
    with pytest.raises(ExternalServiceError):
        tests.list_cases(STORY)


def test_publish_suite_creates_nothing_when_search_has_unexpected_shape() -> None:
    """PA-05 (lado seguro de PA-189): aunque el error no sea el esperado, no se escribe nada."""
    site = FakeSite(replies={("GET", SEARCH_PATH): [httpx.Response(200, json=[])]})
    site, tests, _ = setup(site)
    with pytest.raises(Exception):  # noqa: B017 - PA-189: hoy AttributeError
        tests.publish_suite(make_suite())
    assert site.writes() == []


def test_publish_suite_error_messages_and_logs_have_no_bodies_or_credentials() -> None:
    """§8, CLAUDE.md: ni el log ni los errores llevan cuerpos de Jira ni credenciales."""
    site = FakeSite(case_replies={"CP-01": error_response(400)})
    site, tests, _ = setup(site)
    with capture_logs() as logs:
        tests.publish_suite(make_suite())
    assert_safe(json.dumps(logs, default=str, ensure_ascii=False))
    site = FakeSite(replies={("GET", SEARCH_PATH): [error_response(403)]})
    site, tests, _ = setup(site)
    with pytest.raises(AuthenticationError) as info:
        tests.publish_suite(make_suite())
    assert_safe(info.value)
    assert "HTTP 403" in str(info.value) and "Revisa" in str(info.value)


# --- Registro de la ejecución (T-47, RF-28) --------------------------------------------------


@dataclass
class ExecutionSite:
    """Jira simulado de una subtarea CP para `record_execution`."""

    transitions: list[Any] = field(
        default_factory=lambda: [
            {"id": "11", "name": "Por hacer", "to": {"name": "Por hacer"}},
            {"id": "31", "name": "Finalizar", "to": {"name": "Done"}},
        ]
    )
    status: str = "En curso"
    replies: dict[Route, list[Reply]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        route = (request.method, request.url.path)
        if self.replies.get(route):
            return _reply(self.replies[route].pop(0))
        if route == ("GET", CASE_PATH):
            fields = {
                "labels": [CASE_LABEL, "CA-01", "tipo-positivo"],
                "status": {"name": self.status},
                "issuetype": {"name": SUBTASK_TYPE, "subtask": True},
            }
            return httpx.Response(200, json={"key": CASE_KEY, "fields": fields})
        if route == ("GET", COMMENT_PATH):
            return httpx.Response(200, json={"comments": []})
        if route == ("GET", TRANSITIONS_PATH):
            return httpx.Response(200, json={"transitions": self.transitions})
        if route in (("POST", TRANSITIONS_PATH), ("PUT", CASE_PATH)):
            return httpx.Response(204)
        if route == ("POST", COMMENT_PATH):
            return httpx.Response(201, json={"id": "10001"})
        pytest.fail(f"Petición no esperada: {request.method} {request.url.path}")

    def writes(self) -> list[Route]:
        return [(r.method, r.url.path) for r in self.requests if r.method != "GET"]


def exec_setup(
    site: ExecutionSite | None = None, **kwargs: Any
) -> tuple[ExecutionSite, JiraNativeTests, Sleeps]:
    site = site or ExecutionSite()
    sleep = Sleeps()
    return site, make_tests(site, sleep, **kwargs), sleep


@pytest.mark.parametrize(
    "status", [ExecutionStatus.FAILED, ExecutionStatus.BLOCKED], ids=["fallo", "bloqueado"]
)
def test_record_execution_writes_label_and_comment_when_workflow_has_no_matching_transition(
    status: ExecutionStatus,
) -> None:
    """RF-28: sin transición «Falló»/«Bloqueado» en el flujo, no se envía ninguna transición;
    la etiqueta `ejecucion-<estado>` y el comentario sí se registran."""
    site, tests, _ = exec_setup()
    with capture_logs() as logs:
        tests.record_execution(CASE_KEY, status, EVIDENCE)
    assert site.writes() == [("PUT", CASE_PATH), ("POST", COMMENT_PATH)]
    assert any(e.get("event") == "sin transición para el resultado" for e in logs)


def test_record_execution_ignores_custom_transition_name_missing_from_workflow() -> None:
    """PA-207: un nombre configurado que no existe en el flujo no provoca ninguna transición."""
    custom = {ExecutionStatus.PASSED: ["Aprobado ficticio"]}
    site, tests, _ = exec_setup(execution_transitions=custom)
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, "")
    assert ("POST", TRANSITIONS_PATH) not in site.writes()
    assert ("PUT", CASE_PATH) in site.writes()


def test_record_execution_ignores_transitions_without_id_or_name() -> None:
    """RF-28: transiciones mal formadas (sin `id`, sin nombre, no objeto) se ignoran."""
    broken = ["x", {"name": "Finalizar", "to": {"name": "Done"}}, {"id": "41"}, None]
    site, tests, _ = exec_setup(ExecutionSite(transitions=broken))
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, "")
    assert ("POST", TRANSITIONS_PATH) not in site.writes()


@pytest.mark.parametrize("status_code", [500, 409])
def test_record_execution_never_retries_writes(status_code: int) -> None:
    """§8: un error en la etiqueta no se reintenta ni se espera; el comentario no se envía."""
    site = ExecutionSite(replies={("PUT", CASE_PATH): [error_response(status_code)]})
    site, tests, sleep = exec_setup(site)
    with pytest.raises(PublishError) as info:
        tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, EVIDENCE)
    assert site.writes().count(("PUT", CASE_PATH)) == 1
    assert ("POST", COMMENT_PATH) not in site.writes()
    assert sleep.waits == []
    assert_safe(info.value)
    assert "Registro incompleto" in str(info.value)


def test_record_execution_retries_read_of_case_with_backoff() -> None:
    """§8: la lectura previa sí reintenta (5xx) con el `sleep` inyectado."""
    site = ExecutionSite(replies={("GET", CASE_PATH): [error_response(503)]})
    site, tests, sleep = exec_setup(site)
    tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, "")
    assert sleep.waits == [1.0]


def test_record_execution_error_has_no_evidence_body_or_credentials() -> None:
    """Seguridad: el error de un comentario rechazado no lleva la evidencia ni el cuerpo."""
    site = ExecutionSite(replies={("POST", COMMENT_PATH): [error_response(400)]})
    site, tests, _ = exec_setup(site)
    with pytest.raises(PublishError) as info:
        tests.record_execution(CASE_KEY, ExecutionStatus.FAILED, EVIDENCE)
    assert_safe(info.value)
    assert EVIDENCE not in str(info.value)


def test_record_execution_raises_auth_error_without_label_when_transition_is_forbidden() -> None:
    """RF-28: un 403 en la transición se propaga como `AuthenticationError` y no se escribe
    ni la etiqueta ni el comentario."""
    site = ExecutionSite(replies={("POST", TRANSITIONS_PATH): [error_response(403)]})
    site, tests, _ = exec_setup(site)
    with pytest.raises(AuthenticationError) as info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, "")
    assert site.writes() == [("POST", TRANSITIONS_PATH)]
    assert_safe(info.value)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-195): un 400 en la transición de `record_execution` muestra el mensaje "
        "genérico de creación («Revisa el tipo de incidencia, la épica…»), que no aplica a una "
        "transición (p. ej. con campos obligatorios en su pantalla) "
        "(adapters/jira/http.py:242-246; adapters/testmgmt/jira_native.py:356-358)"
    ),
)
def test_record_execution_transition_400_message_does_not_mention_epic() -> None:
    """§8: el mensaje en español debe orientar sobre la transición, no sobre la épica."""
    site = ExecutionSite(replies={("POST", TRANSITIONS_PATH): [error_response(400)]})
    site, tests, _ = exec_setup(site)
    with pytest.raises(PublishError) as info:
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, "")
    assert "épica" not in str(info.value)


def test_record_execution_raises_agent_error_when_case_read_has_unexpected_shape() -> None:
    """§8: una respuesta con forma inesperada es un error de la familia `AgentError`."""
    site = ExecutionSite(replies={("GET", CASE_PATH): [httpx.Response(200, json=[])]})
    site, tests, _ = exec_setup(site)
    with pytest.raises(AgentError):
        tests.record_execution(CASE_KEY, ExecutionStatus.PASSED, "")
    assert site.writes() == []
