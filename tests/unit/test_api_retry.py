"""PA-276: `POST /conversations/{id}/retry` retoma una conversación en `error` desde su último
checkpoint, sin repetir lo que ya terminó (cargar el origen, reunir el contexto).

Sobre `fake_runtime` con `run_inline` (la respuesta trae el estado final). Solo fakes de
`tests/fakes/`, sin red, sin `.env`, sin Jira ni LLM reales; datos 100 % ficticios.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from adapters.base import IssueDetail, User
from adapters.errors import RateLimitError
from api import service
from api.export_openapi import OPENAPI_PATH
from api.runtime import Runtime
from schemas.test_case import TestSuite
from tests.fakes.api import fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.unit.test_api_app import AF, EVOLVE, NEED, QA, Api
from tests.unit.test_api_handoff_release import SwitchableLLM
from tests.unit.test_api_handoffs import Api as HandoffApi
from tests.unit.test_api_handoffs import _handed_off, _store

RETRY_PATH = "/api/v1/conversations/{conversation_id}/retry"


class CountingTracker(FakeIssueTracker):
    """FakeIssueTracker que cuenta las lecturas (para comprobar que el reintento no recarga)."""

    def __init__(self) -> None:
        super().__init__()
        self.reads: list[str] = []

    def get_issue(self, key: str) -> IssueDetail:
        self.reads.append(key)
        return super().get_issue(key)

    def search(self, jql: str, limit: int = 50) -> list[Any]:
        self.reads.append("search")
        return super().search(jql, limit)


def _rate_limit() -> RateLimitError:
    return RateLimitError("Límite ficticio del LLM.", "llm", 5)


@pytest.fixture
def llm() -> FakeLLMProvider:
    return FakeLLMProvider(error=_rate_limit())


@pytest.fixture
def tracker() -> CountingTracker:
    return CountingTracker()


@pytest.fixture
def rt(tmp_path: Path, llm: FakeLLMProvider, tracker: CountingTracker) -> Runtime:
    return fake_runtime(tmp_path, llm=llm, issue_tracker=tracker)


def _failed(rt: Runtime, body: dict[str, Any] = EVOLVE) -> tuple[Api, str]:
    a = Api(rt)
    assert a.login().status_code == 200
    conv = a.post("/conversations", body).json()
    assert conv["state"] == "error", conv
    return a, conv["id"]


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# --- Reintento correcto ------------------------------------------------------------------------


@pytest.mark.parametrize("body", [EVOLVE, NEED], ids=["evolucionar", "necesidad"])
def test_retry_failed_conversation_reaches_review_without_reloading(
    rt: Runtime, llm: FakeLLMProvider, tracker: CountingTracker, body: dict[str, Any]
) -> None:
    """Criterio 3: fallo del LLM (429) → `error`; con el LLM ya sano, retry → 202 e `in_review`,
    sin repetir `load_origin` ni `retrieve_context` (ni lecturas de Jira)."""
    a, cid = _failed(rt, body)
    reads_before = list(tracker.reads)
    llm.error = None

    response = a.post(f"/conversations/{cid}/retry")

    assert response.status_code == 202, response.text
    conv = response.json()
    assert conv["state"] == "in_review", conv
    assert conv["review"]["version"] == 1
    assert conv["error"] is None
    assert tracker.reads == reads_before
    run = rt.runs.get(cid)
    assert run is not None and run.operation == "retry"
    assert "load_origin" not in run.nodes and "retrieve_context" not in run.nodes
    assert a.get(f"/conversations/{cid}").json()["state"] == "in_review"


def test_retry_repeats_only_the_failed_llm_call(rt: Runtime, llm: FakeLLMProvider) -> None:
    """Criterio 3: el reintento solo vuelve a llamar al LLM para la tarea que falló."""
    a, cid = _failed(rt, NEED)
    tasks_before = [c["task"] for c in llm.calls]
    llm.error = None

    a.post(f"/conversations/{cid}/retry")

    new_tasks = [c["task"] for c in llm.calls][len(tasks_before) :]
    assert new_tasks and set(new_tasks) == set(tasks_before)


def test_retry_that_fails_again_stays_in_error(rt: Runtime) -> None:
    """Criterio 3 (error): si el LLM sigue fallando, la conversación vuelve a `error`."""
    a, cid = _failed(rt)

    response = a.post(f"/conversations/{cid}/retry")

    assert response.status_code == 202, response.text
    conv = response.json()
    assert conv["state"] == "error"
    assert conv["error"]["code"] == "rate_limited"


# --- Propiedad, permisos y CSRF ----------------------------------------------------------------


def test_retry_foreign_and_missing_conversation_are_the_same_404(rt: Runtime) -> None:
    """Criterio 3: ajena e inexistente responden el mismo 404 sin revelar nada."""
    _owner, cid = _failed(rt)
    other = Api(rt)
    assert other.login(QA).status_code == 200

    foreign = other.post(f"/conversations/{cid}/retry")
    missing = other.post(f"/conversations/{uuid4()}/retry")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert rt.runs.get(cid).error is not None  # type: ignore[union-attr]


def test_retry_without_flow_permission_is_403(rt: Runtime, llm: FakeLLMProvider) -> None:
    """Criterio 3: el mismo dueño con un rol sin permiso del flujo → 403 y no se reintenta."""
    a, cid = _failed(rt)
    llm.error = None
    calls = len(llm.calls)
    a.session.user = User(username=AF[0], role="qa")  # sin permiso de generar HU

    response = a.post(f"/conversations/{cid}/retry")

    assert response.status_code == 403
    assert _code(response) == "forbidden"
    assert len(llm.calls) == calls


def test_retry_without_csrf_is_403(rt: Runtime, llm: FakeLLMProvider) -> None:
    """Criterio 3: sin `X-CSRF-Token` → 403 y la conversación sigue en error."""
    a, cid = _failed(rt)
    llm.error = None

    response = a.post(f"/conversations/{cid}/retry", csrf=False)

    assert response.status_code == 403
    assert a.get(f"/conversations/{cid}").json()["state"] == "error"


# --- 409 not_in_error --------------------------------------------------------------------------


@pytest.fixture
def healthy_api(tmp_path: Path) -> Api:
    a = Api(fake_runtime(tmp_path))
    assert a.login().status_code == 200
    return a


def test_retry_in_review_is_409_not_in_error(healthy_api: Api) -> None:
    """Criterio 3: en revisión → 409 `not_in_error`; la revisión no cambia."""
    conv = healthy_api.post("/conversations", EVOLVE).json()
    assert conv["state"] == "in_review"

    response = healthy_api.post(f"/conversations/{conv['id']}/retry")

    assert response.status_code == 409
    assert _code(response) == "not_in_error"
    after = healthy_api.get(f"/conversations/{conv['id']}").json()
    assert after["state"] == "in_review"
    assert after["review"]["version"] == 1


def test_retry_while_generating_is_409_not_in_error(rt: Runtime) -> None:
    """Criterio 3: con una operación en curso → 409 `not_in_error`."""
    a, cid = _failed(rt)
    run = rt.runs.get(cid)
    assert run is not None
    run.running = True

    response = a.post(f"/conversations/{cid}/retry")

    assert response.status_code == 409
    assert _code(response) == "not_in_error"


def test_retry_finished_conversation_is_409_not_in_error(healthy_api: Api) -> None:
    """Criterio 3: terminada (descartada) → 409 `not_in_error`."""
    cid = healthy_api.post("/conversations", EVOLVE).json()["id"]
    assert healthy_api.post(f"/conversations/{cid}/discard").json()["state"] == "discarded"

    response = healthy_api.post(f"/conversations/{cid}/retry")

    assert response.status_code == 409
    assert _code(response) == "not_in_error"


def test_retry_simulated_publish_is_409_not_in_error(healthy_api: Api) -> None:
    """Criterio 3 (límite): publicada en simulación → 409 `not_in_error`."""
    conv = healthy_api.post("/conversations", EVOLVE).json()
    healthy_api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )

    response = healthy_api.post(f"/conversations/{conv['id']}/retry")

    assert response.status_code == 409
    assert _code(response) == "not_in_error"


# --- QA encadenada -----------------------------------------------------------------------------


@pytest.fixture
def qa_llm() -> SwitchableLLM:
    return SwitchableLLM()


@pytest.fixture
def qa_rt(tmp_path: Path, qa_llm: SwitchableLLM) -> Runtime:
    return fake_runtime(tmp_path, llm=qa_llm)


def _suite_calls(llm: FakeLLMProvider) -> int:
    return sum(1 for c in llm.calls if c["schema"] is TestSuite)


def test_retry_released_handoff_is_409_handoff_unavailable(
    qa_rt: Runtime, qa_llm: SwitchableLLM
) -> None:
    """Criterio 3: la recogida falló sin artefacto y la entrega volvió a la lista (PA-113) →
    409 `handoff_unavailable`; el hilo no se reintenta y la entrega sigue libre."""
    _af, _cid, handoff = _handed_off(qa_rt)
    qa_llm.break_suite()
    qa = HandoffApi(qa_rt, QA)
    conv = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()
    assert conv["state"] == "error", conv
    assert _store(qa_rt).get(handoff["id"]).status == "pending"  # type: ignore[union-attr]
    qa_llm.fix_suite()
    calls = _suite_calls(qa_llm)

    response = qa.post(f"/conversations/{conv['id']}/retry")

    assert response.status_code == 409
    assert _code(response) == "handoff_unavailable"
    assert _suite_calls(qa_llm) == calls
    assert qa.get(f"/conversations/{conv['id']}").json()["state"] == "error"
    assert _store(qa_rt).get(handoff["id"]).status == "pending"  # type: ignore[union-attr]


def test_retry_with_handoff_still_taken_after_artifact_reaches_review(
    qa_rt: Runtime, qa_llm: SwitchableLLM
) -> None:
    """Criterio 3: falla al iterar (ya hay artefacto, la entrega sigue recogida) → se reintenta
    y llega a revisión con la versión 2; la entrega sigue recogida por la misma persona."""
    _af, _cid, handoff = _handed_off(qa_rt)
    qa = HandoffApi(qa_rt, QA)
    conv = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()
    assert conv["state"] == "in_review", conv
    qa_llm.break_suite()
    qa.post(f"/conversations/{conv['id']}/iterate", {"feedback": "Cambio ficticio."})
    assert qa.get(f"/conversations/{conv['id']}").json()["state"] == "error"
    qa_llm.fix_suite()

    response = qa.post(f"/conversations/{conv['id']}/retry")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "in_review", body
    assert body["review"]["version"] == 2
    row = _store(qa_rt).get(handoff["id"])
    assert row is not None
    assert (row.status, row.taken_by, row.qa_thread_id) == ("taken", QA[0], conv["id"])


def _take_without_release(
    qa_rt: Runtime, qa_llm: SwitchableLLM, monkeypatch: pytest.MonkeyPatch
) -> tuple[HandoffApi, dict[str, Any], str]:
    """Recogida que falla sin artefacto pero cuya entrega sigue recogida (p. ej. si la
    devolución no pudo hacerse): se anula `_release_if_unstarted` solo durante la recogida."""
    _af, _cid, handoff = _handed_off(qa_rt)
    qa_llm.break_suite()
    qa = HandoffApi(qa_rt, QA)
    with monkeypatch.context() as m:
        m.setattr(service, "_release_if_unstarted", lambda *_a, **_k: None)
        conv = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()
    assert conv["state"] == "error", conv
    assert _store(qa_rt).get(handoff["id"]).status == "taken"  # type: ignore[union-attr]
    return qa, handoff, conv["id"]


def test_retry_with_handoff_still_taken_before_artifact_reaches_review(
    qa_rt: Runtime, qa_llm: SwitchableLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterio 3: fallo sin artefacto con la entrega aún recogida → se reintenta."""
    qa, handoff, cid = _take_without_release(qa_rt, qa_llm, monkeypatch)
    qa_llm.fix_suite()

    response = qa.post(f"/conversations/{cid}/retry")

    assert response.status_code == 202, response.text
    assert response.json()["state"] == "in_review"
    row = _store(qa_rt).get(handoff["id"])
    assert row is not None and (row.status, row.qa_thread_id) == ("taken", cid)


def test_retry_failing_again_releases_handoff_before_run_finishes(
    qa_rt: Runtime, qa_llm: SwitchableLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterio 3: si el reintento vuelve a fallar sin artefacto, la entrega se libera ANTES de
    que el run aparezca terminado (espía en `rt.runs.finish`)."""
    qa, handoff, cid = _take_without_release(qa_rt, qa_llm, monkeypatch)
    store = _store(qa_rt)
    seen: list[tuple[bool, str]] = []
    original_finish = qa_rt.runs.finish

    def spy_finish(run: Any, error: Any = None) -> None:
        row = store.get(handoff["id"])
        seen.append((error is not None, row.status if row else "?"))
        original_finish(run, error)

    monkeypatch.setattr(qa_rt.runs, "finish", spy_finish)

    response = qa.post(f"/conversations/{cid}/retry")

    assert response.status_code == 202, response.text
    assert response.json()["state"] == "error"
    assert seen == [(True, "pending")]  # al terminar con error, la entrega ya estaba libre
    row = store.get(handoff["id"])
    assert row is not None and (row.status, row.taken_by, row.qa_thread_id) == (
        "pending",
        None,
        None,
    )
    # Y ya no se puede volver a reintentar ese hilo.
    again = qa.post(f"/conversations/{cid}/retry")
    assert again.status_code == 409 and _code(again) == "handoff_unavailable"


def test_take_failure_releases_handoff_before_run_finishes(
    qa_rt: Runtime, qa_llm: SwitchableLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterio 3 (PA-113 con PA-276): en la recogida, la entrega también se libera antes de que
    el run aparezca terminado (nadie puede reintentar con la entrega aún recogida)."""
    _af, _cid, handoff = _handed_off(qa_rt)
    qa_llm.break_suite()
    store = _store(qa_rt)
    seen: list[str] = []
    original_finish = qa_rt.runs.finish

    def spy_finish(run: Any, error: Any = None) -> None:
        if error is not None:
            seen.append(store.get(handoff["id"]).status)  # type: ignore[union-attr]
        original_finish(run, error)

    monkeypatch.setattr(qa_rt.runs, "finish", spy_finish)
    qa = HandoffApi(qa_rt, QA)

    conv = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()

    assert conv["state"] == "error"
    assert seen == ["pending"]


# --- Contrato ----------------------------------------------------------------------------------


def _published() -> dict[str, Any]:
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_contract_publishes_retry_route_with_202_and_409() -> None:
    """Criterio 3: el contrato publicado tiene POST /conversations/{conversation_id}/retry."""
    op = _published()["paths"][RETRY_PATH]["post"]

    assert {"202", "404", "409"} <= set(op["responses"])


def test_contract_error_code_enum_contains_not_in_error() -> None:
    """Criterio 3: `not_in_error` es un código del enumerado `ErrorCode` publicado."""
    schemas = _published()["components"]["schemas"]
    code = schemas["ErrorBody"]["properties"]["code"]
    codes = code.get("enum") or schemas[code["$ref"].rsplit("/", 1)[-1]]["enum"]

    assert "not_in_error" in codes
    assert {"not_in_review", "handoff_unavailable"} <= set(codes)


def test_contract_keeps_every_route_of_the_committed_contract() -> None:
    """Criterio 3: respecto al contrato de HEAD, solo se añade la ruta de reintento; ninguna
    ruta ni método existente desaparece."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git no está disponible")
    root = OPENAPI_PATH.parents[2]
    shown = subprocess.run(  # noqa: S603 - argumentos fijos, sin entrada externa
        [git, "show", "HEAD:docs/api/openapi.yaml"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if shown.returncode != 0:
        pytest.skip("sin contrato en HEAD")

    def operations(doc: dict[str, Any]) -> set[tuple[str, str]]:
        return {(p, m) for p, item in doc["paths"].items() for m in item}

    before = operations(yaml.safe_load(shown.stdout.decode("utf-8")))
    after = operations(_published())
    assert before <= after
    assert after - before <= {(RETRY_PATH, "post")}


# --- Lo que no se reintenta: publicar (security-reviewer) --------------------------------------


class FailingWriteTracker(FakeIssueTracker):
    """FakeIssueTracker cuyo `update_story` falla una vez (publicación en `live` que se corta)."""

    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    def update_story(self, key: str, story: Any, diff_comment_md: str) -> None:
        if self.failures:
            self.failures -= 1
            from adapters.errors import ExternalServiceError

            raise ExternalServiceError("Jira ficticio caído al escribir.", service="jira")
        super().update_story(key, story, diff_comment_md)


def test_retry_after_failed_publish_is_409_and_never_writes_jira_again(tmp_path: Path) -> None:
    """PA-276: si falló `publish` (en `live`), no se reintenta: nunca se escribe dos veces."""
    tracker = FailingWriteTracker()
    rt = fake_runtime(tmp_path, issue_tracker=tracker, publish_mode="live")
    a = Api(rt)
    assert a.login().status_code == 200
    conv = a.post("/conversations", EVOLVE).json()
    approved = a.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    ).json()
    assert approved["state"] == "error", approved
    writes = list(tracker.writes)

    response = a.post(RETRY_PATH.format(conversation_id=conv["id"]).removeprefix("/api/v1"))

    assert response.status_code == 409
    assert _code(response) == "not_in_error"
    assert "no se reintenta" in response.json()["error"]["message"]
    assert tracker.writes == writes
    assert tracker.failures == 0  # el siguiente intento habría escrito: no lo hubo


def test_retryable_nodes_never_include_jira_writes() -> None:
    """Solo pasos sin escrituras en Jira: nunca `human_review` ni `publish`."""
    assert {"human_review", "publish"}.isdisjoint(service.RETRYABLE_NODES)
