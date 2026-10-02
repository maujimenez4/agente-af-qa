"""API del registro de la ejecución (T-47 · RF-28, R-01 opción A; UI.md §6.6).

Sobre `fake_runtime`: sin `.env`, sin red, sin Jira ni LLM reales. Datos 100 % ficticios (claves
DEMO-5xx). Las operaciones terminan antes de responder (`run_inline`).
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from adapters.base import IssueSummary, User
from api.app import API_PREFIX
from api.export_openapi import openapi_document
from api.runtime import Runtime
from tests.fakes.api import fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.test_management import FakeTestManagement
from tests.unit.test_api_app import ADMIN, AF, QA, TESTS, Api

STORY = "DEMO-3"
CASES = [
    IssueSummary(
        key="DEMO-501",
        summary="[CP-01] Caso ficticio uno",
        issue_type="Subtarea",
        status="Por hacer",
    ),
    IssueSummary(
        key="DEMO-502",
        summary="[CP-02] Caso ficticio dos",
        issue_type="Subtarea",
        status="Por hacer",
    ),
]
EVIDENCE = "Evidencia ficticia-9c2e: el botón no se desactiva."
RESULTS = {
    "results": [
        {"case_key": "DEMO-501", "status": "paso", "evidence_md": ""},
        {"case_key": "DEMO-502", "status": "fallo", "evidence_md": EVIDENCE},
    ],
    "environment": "preproducción ficticia",
}
NOT_YOURS = "No existe ese registro o no es tuyo."


# --- utilidades --------------------------------------------------------------------------


def _tm(rt: Runtime) -> FakeTestManagement:
    tm = rt.workspace_factory().container.test_management
    assert isinstance(tm, FakeTestManagement)
    return tm


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    # Jira de los fakes: estas pruebas publican en `live`; la simulación tiene las suyas abajo.
    runtime = fake_runtime(tmp_path, publish_mode="live")
    _tm(runtime).cases[STORY] = list(CASES)
    return runtime


@pytest.fixture
def qa(rt: Runtime) -> Api:
    a = Api(rt)
    assert a.login(QA).status_code == 200
    return a


def _create(api: Api) -> dict[str, Any]:
    response = api.post("/executions", {"story_key": STORY})
    assert response.status_code == 200, response.text
    return response.json()


def _nothing_written(rt: Runtime) -> None:
    container = rt.workspace_factory().container
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    assert tracker.writes == []
    assert _tm(rt).executions == []
    assert _tm(rt).publish_calls == 0


# --- flujo completo -------------------------------------------------------------------------


def test_full_flow_create_save_approve_records_in_jira(qa: Api, rt: Runtime) -> None:
    """RF-28 · principio 1: crear → guardar → aprobar registra cada caso una vez."""
    created = _create(qa)
    assert created["state"] == "in_review"
    assert created["story_key"] == STORY and created["project"] == "DEMO"
    assert [c["key"] for c in created["cases"]] == ["DEMO-501", "DEMO-502"]
    assert created["results"] == [] and created["plan"] == []
    assert len(created["fingerprint"]) == 64
    eid = created["id"]

    saved = qa.put(f"/executions/{eid}/results", RESULTS)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["state"] == "in_review" and body["review_error"] is None
    assert body["environment"] == "preproducción ficticia"
    assert [op["key"] for op in body["plan"]] == ["DEMO-501", "DEMO-502"]
    assert body["fingerprint"] != created["fingerprint"]
    assert _tm(rt).executions == []  # guardar no escribe

    assert qa.get(f"/executions/{eid}").json()["fingerprint"] == body["fingerprint"]

    approved = qa.post(f"/executions/{eid}/approve", {"fingerprint": body["fingerprint"]})
    assert approved.status_code == 200, approved.text
    result = approved.json()
    assert result["state"] == "recorded"
    assert result["outcome"]["recorded"] == ["DEMO-501", "DEMO-502"]
    assert result["outcome"]["failed"] == []
    assert result["outcome"]["approved_by"] == "qa-demo"
    assert result["outcome"]["approved_at"]
    assert result["fingerprint"] is None and result["plan"] == []
    assert _tm(rt).executions == [
        ("DEMO-501", "paso", "Entorno: preproducción ficticia"),
        ("DEMO-502", "fallo", f"Entorno: preproducción ficticia\n\n{EVIDENCE}"),
    ]
    assert qa.get(f"/executions/{eid}").json()["state"] == "recorded"


def test_approve_twice_is_409_and_writes_once(qa: Api, rt: Runtime) -> None:
    """Principio 1: la aprobación es de un solo uso; la segunda vez → 409 not_in_review."""
    eid = _create(qa)["id"]
    fp = qa.put(f"/executions/{eid}/results", RESULTS).json()["fingerprint"]
    assert qa.post(f"/executions/{eid}/approve", {"fingerprint": fp}).status_code == 200
    again = qa.post(f"/executions/{eid}/approve", {"fingerprint": fp})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "not_in_review"
    assert len(_tm(rt).executions) == 2


@pytest.mark.parametrize("op", ["save", "discard"])
def test_operations_after_recording_are_409(qa: Api, rt: Runtime, op: str) -> None:
    """Un registro ya escrito no admite más cambios."""
    eid = _create(qa)["id"]
    fp = qa.put(f"/executions/{eid}/results", RESULTS).json()["fingerprint"]
    qa.post(f"/executions/{eid}/approve", {"fingerprint": fp})
    response = (
        qa.put(f"/executions/{eid}/results", RESULTS)
        if op == "save"
        else qa.post(f"/executions/{eid}/discard")
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_in_review"
    assert len(_tm(rt).executions) == 2


def test_partial_failure_is_partial_with_failed_cases(qa: Api, rt: Runtime) -> None:
    """RNF-13: un caso que falla en Jira deja el registro `partial` con `outcome.failed`."""
    _tm(rt).fail_execution_keys = {"DEMO-502"}
    eid = _create(qa)["id"]
    fp = qa.put(f"/executions/{eid}/results", RESULTS).json()["fingerprint"]
    response = qa.post(f"/executions/{eid}/approve", {"fingerprint": fp})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "partial"
    assert body["outcome"]["recorded"] == ["DEMO-501"]
    assert body["outcome"]["failed"] == ["DEMO-502"]
    assert body["outcome"]["errors"] == ["No se pudo registrar la ejecución en DEMO-502."]
    assert qa.post(f"/executions/{eid}/approve", {"fingerprint": fp}).status_code == 409


def test_discard_is_discarded_and_writes_nothing(qa: Api, rt: Runtime) -> None:
    """Principio 1: descartar no escribe en Jira."""
    eid = _create(qa)["id"]
    qa.put(f"/executions/{eid}/results", RESULTS)
    response = qa.post(f"/executions/{eid}/discard")
    assert response.status_code == 200
    assert response.json()["state"] == "discarded"
    assert qa.get(f"/executions/{eid}").json()["state"] == "discarded"
    _nothing_written(rt)


# --- errores de revisión sin error HTTP --------------------------------------------------------


@pytest.mark.parametrize(
    ("results", "fragment"),
    [
        ([{"case_key": "DEMO-502", "status": "fallo", "evidence_md": ""}], "necesita evidencia"),
        ([{"case_key": "DEMO-999", "status": "paso"}], "no es un caso de esta HU"),
        (
            [
                {"case_key": "DEMO-501", "status": "paso"},
                {"case_key": "DEMO-501", "status": "paso"},
            ],
            "aparece dos veces",
        ),
    ],
    ids=["fallo-sin-evidencia", "otra-hu", "duplicado"],
)
def test_invalid_results_give_review_error_without_http_error(
    qa: Api, rt: Runtime, results: list[dict[str, str]], fragment: str
) -> None:
    """RF-28: un borrador no válido no es un error HTTP; sigue en revisión con `review_error`."""
    eid = _create(qa)["id"]
    response = qa.put(f"/executions/{eid}/results", {"results": results})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "in_review"
    assert fragment in body["review_error"]
    assert body["results"] == []
    _nothing_written(rt)


def test_wrong_fingerprint_keeps_review_with_error(qa: Api, rt: Runtime) -> None:
    """Principio 1: una huella que no casa no aprueba; 200 con `review_error`."""
    eid = _create(qa)["id"]
    qa.put(f"/executions/{eid}/results", RESULTS)
    response = qa.post(f"/executions/{eid}/approve", {"fingerprint": "0" * 64})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "in_review"
    assert body["review_error"] == (
        "La aprobación no corresponde al registro revisado; vuelve a revisarlo."
    )
    _nothing_written(rt)


@pytest.mark.parametrize(
    "body",
    [
        {"results": [{"case_key": "DEMO-501", "status": "aprobado"}]},
        {"results": [{"case_key": "DEMO-501", "status": "paso", "evidence_md": "x" * 20_001}]},
        {"results": [], "environment": "e" * 101},
    ],
    ids=["estado", "evidencia-larga", "entorno-largo"],
)
def test_out_of_contract_body_is_422_and_writes_nothing(
    qa: Api, rt: Runtime, body: dict[str, Any]
) -> None:
    """Límites del contrato: estado fuera del enum, evidencia > 20 000 o entorno > 100 → 422."""
    eid = _create(qa)["id"]
    response = qa.put(f"/executions/{eid}/results", body)
    assert response.status_code == 422
    assert qa.get(f"/executions/{eid}").json()["state"] == "in_review"
    _nothing_written(rt)


def test_story_without_cases_is_409_publish_failed(qa: Api, rt: Runtime) -> None:
    """RF-28: una HU sin suite publicada no se puede registrar."""
    _tm(rt).cases.clear()
    response = qa.post("/executions", {"story_key": STORY})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "publish_failed"
    assert error["message"] == (
        "La HU DEMO-3 no tiene casos de prueba publicados en Jira: publica antes su suite."
    )
    _nothing_written(rt)


# --- permisos y propiedad -------------------------------------------------------------------


@pytest.mark.parametrize("who", [AF, ADMIN], ids=["af-demo", "admin-demo"])
def test_roles_without_publish_tests_are_403(rt: Runtime, qa: Api, who: tuple[str, str]) -> None:
    """UI.md §3: registrar la ejecución es del rol QA (permiso `publish_tests`)."""
    eid = _create(qa)["id"]
    fp = qa.put(f"/executions/{eid}/results", RESULTS).json()["fingerprint"]
    other = Api(rt)
    assert other.login(who).status_code == 200
    responses = [
        other.post("/executions", {"story_key": STORY}),
        other.put(f"/executions/{eid}/results", RESULTS),
        other.post(f"/executions/{eid}/approve", {"fingerprint": fp}),
        other.post(f"/executions/{eid}/discard"),
    ]
    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"
    assert qa.get(f"/executions/{eid}").json()["state"] == "in_review"
    _nothing_written(rt)


def test_foreign_execution_404_is_identical_to_missing_one(rt: Runtime, qa: Api) -> None:
    """Req. 5: el 404 de un registro ajeno es idéntico al de uno inexistente."""
    eid = _create(qa)["id"]
    fp = qa.put(f"/executions/{eid}/results", RESULTS).json()["fingerprint"]
    other = Api(rt)
    other.login(QA)
    other.session.user = User(username="qa-otra-ficticia", role="qa")  # otra persona con permiso
    missing = other.get(f"/executions/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == NOT_YOURS
    for response in (
        other.get(f"/executions/{eid}"),
        other.put(f"/executions/{eid}/results", RESULTS),
        other.post(f"/executions/{eid}/approve", {"fingerprint": fp}),
        other.post(f"/executions/{eid}/discard"),
    ):
        assert response.status_code == 404
        assert response.json() == missing.json()
    assert qa.get(f"/executions/{eid}").json()["state"] == "in_review"
    _nothing_written(rt)


def test_conversation_id_is_not_an_execution_and_vice_versa(qa: Api, rt: Runtime) -> None:
    """Los hilos de HU/suite y los de ejecución no se mezclan: 404 cruzado."""
    conv = qa.post("/conversations", TESTS)
    assert conv.status_code == 202, conv.text
    cid = conv.json()["id"]
    eid = _create(qa)["id"]

    as_execution = qa.get(f"/executions/{cid}")
    assert as_execution.status_code == 404
    assert as_execution.json()["error"]["message"] == NOT_YOURS
    assert qa.post(f"/executions/{cid}/discard").status_code == 404

    as_conversation = qa.get(f"/conversations/{eid}")
    assert as_conversation.status_code == 404
    assert qa.post(f"/conversations/{eid}/discard").status_code == 404
    assert qa.get(f"/executions/{eid}").json()["state"] == "in_review"
    assert _tm(rt).executions == []


# --- sesión y CSRF ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/executions", {"story_key": STORY}),
        ("get", "/executions/{eid}", None),
        ("put", "/executions/{eid}/results", RESULTS),
        ("post", "/executions/{eid}/approve", {"fingerprint": "0" * 64}),
        ("post", "/executions/{eid}/discard", None),
    ],
    ids=["create", "get", "save", "approve", "discard"],
)
def test_without_session_is_401(rt: Runtime, qa: Api, method: str, path: str, body: Any) -> None:
    """Sin sesión → 401 unauthenticated en las cinco rutas."""
    eid = _create(qa)["id"]
    anon = Api(rt)
    url = path.format(eid=eid)
    response = anon.get(url) if method == "get" else getattr(anon, method)(url, body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/executions", {"story_key": STORY}),
        ("put", "/executions/{eid}/results", RESULTS),
        ("post", "/executions/{eid}/approve", {"fingerprint": "0" * 64}),
        ("post", "/executions/{eid}/discard", None),
    ],
    ids=["create", "save", "approve", "discard"],
)
def test_without_csrf_is_403(qa: Api, rt: Runtime, method: str, path: str, body: Any) -> None:
    """Sin cabecera X-CSRF-Token → 403 en PUT/POST, sin cambios."""
    eid = _create(qa)["id"]
    response = getattr(qa, method)(path.format(eid=eid), body, csrf=False)
    assert response.status_code == 403
    assert qa.get(f"/executions/{eid}").json()["state"] == "in_review"
    _nothing_written(rt)


def test_invalid_story_key_is_422(qa: Api, rt: Runtime) -> None:
    """Contrato: la clave de la HU sigue el patrón de Jira."""
    assert qa.post("/executions", {"story_key": "no es una clave"}).status_code == 422
    _nothing_written(rt)


# --- contrato --------------------------------------------------------------------------------


EXECUTION_ROUTES = [
    (f"{API_PREFIX}/executions", "post"),
    (f"{API_PREFIX}/executions/{{execution_id}}", "get"),
    (f"{API_PREFIX}/executions/{{execution_id}}/results", "put"),
    (f"{API_PREFIX}/executions/{{execution_id}}/approve", "post"),
    (f"{API_PREFIX}/executions/{{execution_id}}/discard", "post"),
]


@pytest.mark.parametrize(("path", "method"), EXECUTION_ROUTES)
def test_contract_declares_execution_routes_with_errors_and_examples(
    path: str, method: str
) -> None:
    """El contrato declara las 5 rutas con 401/403/429/413/500/503 y ejemplos."""
    doc = openapi_document()
    op = doc["paths"][path][method]
    responses = op["responses"]
    for code in ("200", "401", "403", "429", "413", "500", "503"):
        assert code in responses, (path, method, code)
    for code, response in responses.items():
        media = response["content"]["application/json"]
        assert "example" in media or "examples" in media, (path, method, code)
    if path.endswith("{execution_id}") or "/executions/" in path:
        assert "404" in responses
        not_found = responses["404"]["content"]["application/json"]
        example = not_found.get("example") or next(iter(not_found["examples"].values()))["value"]
        assert example["error"]["message"] == NOT_YOURS
    if method != "get" and path != f"{API_PREFIX}/executions":
        assert "409" in responses


def test_contract_execution_body_limits() -> None:
    """Contrato: evidencia ≤ 20 000, entorno ≤ 100 y estados cerrados."""
    schemas = openapi_document()["components"]["schemas"]
    result = schemas["ExecutionResultIn"]["properties"]
    assert result["evidence_md"]["maxLength"] == 20_000
    assert set(result["status"]["enum"]) == {"paso", "fallo", "bloqueado", "sin-ejecutar"}
    assert schemas["ExecutionResultsIn"]["properties"]["environment"]["maxLength"] == 100


@pytest.mark.parametrize(("path", "method"), EXECUTION_ROUTES[2:])
def test_contract_409_example_matches_execution_message(path: str, method: str) -> None:
    """El ejemplo 409 del contrato es el mensaje real del registro de la ejecución."""
    from api.executions import NOT_IN_REVIEW_EXECUTION

    media = openapi_document()["paths"][path][method]["responses"]["409"]["content"]
    example = media["application/json"]["example"]
    assert example["error"]["message"] == NOT_IN_REVIEW_EXECUTION.message


# --- modo simulación (T-25): por defecto no se escribe nada ----------------------------------


def test_simulation_mode_approves_without_writing(tmp_path: Path) -> None:
    """Con `JIRA_PUBLISH_MODE=simulation` (por defecto) aprobar no escribe en Jira."""
    runtime = fake_runtime(tmp_path)  # simulación
    _tm(runtime).cases[STORY] = list(CASES)
    api = Api(runtime)
    assert api.login(QA).status_code == 200
    created = _create(api)
    saved = api.client.put(
        f"{API_PREFIX}/executions/{created['id']}/results",
        json={"results": [{"case_key": "DEMO-501", "status": "paso"}]},
        headers={"X-CSRF-Token": api.csrf},
    ).json()
    done = api.post(
        f"/executions/{created['id']}/approve", {"fingerprint": saved["fingerprint"]}
    ).json()
    assert done["state"] == "simulated"
    assert done["outcome"]["simulated"] is True and done["outcome"]["recorded"] == []
    assert _tm(runtime).executions == []
    again = api.post(f"/executions/{created['id']}/approve", {"fingerprint": saved["fingerprint"]})
    assert again.status_code == 409
