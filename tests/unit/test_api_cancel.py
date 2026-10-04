"""PA-314: `POST /conversations/{id}/cancel` detiene una generación en curso sin matar hilos.

Las operaciones van en segundo plano (`fake_runtime(..., run_inline=False)`, ThreadPoolExecutor)
y se detienen en una llamada concreta con las puertas de `tests/fakes/blocking.py`: la prueba
espera a que la llamada llegue, cancela y la suelta. Todas las esperas tienen tiempo máximo.
Solo fakes de `tests/fakes/`, sin red, sin `.env`, sin Jira ni LLM reales; datos ficticios.
"""

import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from pydantic import BaseModel

from adapters.base import Message, TaskType, User
from adapters.errors import RateLimitError
from api.app import create_app
from api.cancel import (
    CANCELLED_MESSAGE,
    CancellableLLM,
    GenerationCancelledError,
    cancellation,
    raise_if_cancelled,
)
from api.export_openapi import OPENAPI_PATH
from api.runtime import Run, RunRegistry, Runtime
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes.api import fake_runtime
from tests.fakes.blocking import (
    DEFAULT_WAIT,
    BlockingEmbeddings,
    BlockingIssueTracker,
    BlockingLLM,
    Gate,
    wait_until,
)
from tests.fakes.llm import FakeLLMProvider, _default_builders
from tests.fakes.test_management import FakeTestManagement
from tests.unit.test_api_app import AF, EVOLVE, NEED, QA, TESTS, Api
from tests.unit.test_api_handoffs import Api as HandoffApi
from tests.unit.test_api_handoffs import _handed_off, _store

CANCEL_PATH = "/api/v1/conversations/{conversation_id}/cancel"
CHANGED_TITLE = "Renovar un préstamo desde la web (iteración ficticia)"


# --- Infraestructura de las pruebas ------------------------------------------------------------


@pytest.fixture
def llm() -> BlockingLLM:
    return BlockingLLM()


@pytest.fixture
def tracker() -> BlockingIssueTracker:
    return BlockingIssueTracker()


@pytest.fixture
def embeddings() -> BlockingEmbeddings:
    return BlockingEmbeddings()


def _gates(llm: BlockingLLM, tracker: BlockingIssueTracker, emb: BlockingEmbeddings) -> list[Gate]:
    return [llm.gate, tracker.read_gate, tracker.write_gate, emb.gate]


def _make_rt(
    tmp_path: Path,
    llm: BlockingLLM,
    tracker: BlockingIssueTracker,
    embeddings: BlockingEmbeddings,
    **overrides: Any,
) -> Iterator[Runtime]:
    runtime = fake_runtime(
        tmp_path, llm=llm, issue_tracker=tracker, embeddings=embeddings, **overrides
    )
    yield runtime
    for gate in _gates(llm, tracker, embeddings):  # nunca deja un hilo esperando
        gate.release()
    runtime.shutdown()


@pytest.fixture
def rt(
    tmp_path: Path, llm: BlockingLLM, tracker: BlockingIssueTracker, embeddings: BlockingEmbeddings
) -> Iterator[Runtime]:
    yield from _make_rt(tmp_path, llm, tracker, embeddings)


@pytest.fixture
def live_rt(
    tmp_path: Path, llm: BlockingLLM, tracker: BlockingIssueTracker, embeddings: BlockingEmbeddings
) -> Iterator[Runtime]:
    yield from _make_rt(tmp_path, llm, tracker, embeddings, publish_mode="live")


@pytest.fixture
def api(rt: Runtime) -> Api:
    a = Api(rt)
    assert a.login().status_code == 200
    return a


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def _cancel(a: Any, cid: str, csrf: bool = True) -> Any:
    return a.post(f"/conversations/{cid}/cancel", csrf=csrf)


def _finished(rt: Runtime, cid: str, timeout: float = DEFAULT_WAIT) -> bool:
    def done() -> bool:
        run = rt.runs.get(cid)
        return run is not None and not run.running

    return wait_until(done, timeout)


def _start_blocked(rt: Runtime, a: Api, body: dict[str, Any], gate: Gate, **arm: int) -> str:
    """Crea la conversación en segundo plano y espera a que llegue a la puerta."""
    gate.arm(**arm)
    rt.run_inline = False
    response = a.post("/conversations", body)
    assert response.status_code == 202, response.text
    assert gate.wait_hits(1), "la operación no llegó a la llamada bloqueada"
    return str(response.json()["id"])


def _in_review(rt: Runtime, a: Api, body: dict[str, Any] = EVOLVE) -> dict[str, Any]:
    """Conversación ya en revisión (en el mismo hilo, sin bloquear)."""
    rt.run_inline = True
    conv = a.post("/conversations", body).json()
    assert conv["state"] == "in_review", conv
    return dict(conv)


def _nothing_written(rt: Runtime) -> None:
    container = rt.workspace_factory().container
    tracker, testmgmt = container.issue_tracker, container.test_management
    assert isinstance(testmgmt, FakeTestManagement)
    assert tracker.writes == []  # type: ignore[attr-defined]
    assert testmgmt.publish_calls == 0


def _changed_story(messages: list[Message]) -> BaseModel:
    """Como la respuesta por defecto (cita el contexto), pero con otro título: hay diff."""
    story = _default_builders()[UserStory](messages)
    return story.model_copy(update={"title": CHANGED_TITLE})


# --- D · Entre llamadas al LLM -----------------------------------------------------------------


def test_cancel_during_first_llm_call_skips_the_next_call(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 D: con el LLM en la primera de las dos llamadas de `generate` (estructurar y
    evolucionar), cancelar → 202 con `cancel_requested=true`; la llamada en curso termina, la
    siguiente no se hace y queda `error` con `code=cancelled` y el mensaje en español."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)

    response = _cancel(api, cid)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "generating"
    assert body["cancel_requested"] is True
    during = api.get(f"/conversations/{cid}").json()
    assert during["state"] == "generating" and during["cancel_requested"] is True
    llm.gate.release()
    assert _finished(rt, cid)

    assert llm.started == ["UserStory"]  # la de evolucionar nunca empezó
    assert len(llm.calls) == 1  # la que estaba en curso sí terminó
    final = api.get(f"/conversations/{cid}").json()
    assert final["state"] == "error", final
    assert final["error"]["code"] == "cancelled"
    assert final["error"]["message"] == CANCELLED_MESSAGE
    assert "detenida" in final["error"]["message"]
    assert final["cancel_requested"] is False
    assert final["review"] is None and final["versions"] == []
    assert not llm.gate.timed_out


def test_cancel_request_is_idempotent_while_stopping(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 D (límite): pedir detener dos veces mientras termina → 202 las dos veces."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)

    first, second = _cancel(api, cid), _cancel(api, cid)

    assert first.status_code == second.status_code == 202
    assert second.json()["cancel_requested"] is True
    llm.gate.release()
    assert _finished(rt, cid)
    assert api.get(f"/conversations/{cid}").json()["error"]["code"] == "cancelled"


def test_cancel_bumps_run_seq_for_sse(rt: Runtime, api: Api, llm: BlockingLLM) -> None:
    """PA-314 D: cancelar avisa a quien espera (SSE) aunque no termine ningún nodo."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)
    run = rt.runs.get(cid)
    assert run is not None
    seq = run.seq

    _cancel(api, cid)

    assert run.seq > seq
    llm.gate.release()
    assert _finished(rt, cid)


# --- E · Entre nodos ---------------------------------------------------------------------------


@pytest.mark.parametrize("node", ["load_origin", "retrieve_context"])
def test_cancel_between_nodes_never_runs_generate_and_retry_continues(
    rt: Runtime,
    api: Api,
    llm: BlockingLLM,
    tracker: BlockingIssueTracker,
    embeddings: BlockingEmbeddings,
    node: str,
) -> None:
    """PA-314 E: bloqueado en `load_origin` (lectura de Jira) o en `retrieve_context` (RAG),
    cancelar → no se ejecuta `generate` (cero llamadas al LLM) y queda error/cancelled; luego
    `/retry` continúa desde ahí y llega a revisión."""
    gate = tracker.read_gate if node == "load_origin" else embeddings.gate
    cid = _start_blocked(rt, api, EVOLVE, gate)

    assert _cancel(api, cid).status_code == 202
    gate.release()
    assert _finished(rt, cid)

    assert llm.started == [] and llm.calls == []
    run = rt.runs.get(cid)
    assert run is not None and node in run.nodes and "generate" not in run.nodes
    failed = api.get(f"/conversations/{cid}").json()
    assert failed["state"] == "error" and failed["error"]["code"] == "cancelled"
    _nothing_written(rt)

    rt.run_inline = True
    retried = api.post(f"/conversations/{cid}/retry")

    assert retried.status_code == 202, retried.text
    conv = retried.json()
    assert conv["state"] == "in_review", conv
    assert conv["review"]["version"] == 1
    assert llm.calls  # ahora sí se generó
    assert node not in rt.runs.get(cid).nodes  # type: ignore[union-attr]


# --- A · La señal es por run y se reinicia -----------------------------------------------------


def test_retry_after_cancel_is_not_born_cancelled(rt: Runtime, api: Api, llm: BlockingLLM) -> None:
    """PA-314 A: tras cancelar (error/cancelled), `/retry` estrena señal: con el LLM sano llega
    a `in_review`, sin `cancel_requested` ni error."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)
    _cancel(api, cid)
    llm.gate.release()
    assert _finished(rt, cid)
    run = rt.runs.get(cid)
    assert run is not None and run.cancel.is_set()
    old_signal = run.cancel

    rt.run_inline = True
    response = api.post(f"/conversations/{cid}/retry")

    assert response.status_code == 202, response.text
    conv = response.json()
    assert conv["state"] == "in_review", conv
    assert conv["error"] is None and conv["cancel_requested"] is False
    assert run.cancel is not old_signal and not run.cancel.is_set()
    assert run.operation == "retry"


def test_retry_after_cancel_can_be_cancelled_again(rt: Runtime, api: Api, llm: BlockingLLM) -> None:
    """PA-314 A (límite): el reintento en segundo plano también se puede detener."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)
    _cancel(api, cid)
    llm.gate.release()
    assert _finished(rt, cid)

    llm.gate.arm()
    response = api.post(f"/conversations/{cid}/retry")
    assert response.status_code == 202, response.text
    assert llm.gate.wait_hits(1)
    assert _cancel(api, cid).status_code == 202
    llm.gate.release()
    assert _finished(rt, cid)

    conv = api.get(f"/conversations/{cid}").json()
    assert conv["state"] == "error" and conv["error"]["code"] == "cancelled"


def test_cancel_one_conversation_does_not_affect_another_generating_at_once(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 A: dos conversaciones del mismo workspace bloqueadas a la vez en hilos distintos;
    se cancela una → esa queda error/cancelled y la otra termina en `in_review`."""
    llm.gate.arm(count=2)
    rt.run_inline = False
    first = api.post("/conversations", EVOLVE).json()["id"]
    second = api.post("/conversations", EVOLVE).json()["id"]
    assert llm.gate.wait_hits(2), "las dos generaciones no llegaron a la vez al LLM"

    assert _cancel(api, first).status_code == 202
    other = api.get(f"/conversations/{second}").json()
    assert other["state"] == "generating" and other["cancel_requested"] is False
    second_run = rt.runs.get(second)
    assert second_run is not None and not second_run.cancel.is_set()
    llm.gate.release()
    assert _finished(rt, first) and _finished(rt, second)

    cancelled = api.get(f"/conversations/{first}").json()
    survived = api.get(f"/conversations/{second}").json()
    assert cancelled["state"] == "error" and cancelled["error"]["code"] == "cancelled"
    assert survived["state"] == "in_review", survived
    assert survived["error"] is None and survived["cancel_requested"] is False
    assert survived["review"]["version"] == 1


def test_cancel_of_another_users_conversation_does_not_affect_mine(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 A: dos personas (AF y QA, cada una con su workspace) generando a la vez; la
    cancelación de la de QA no toca la de AF."""
    qa = Api(rt)
    assert qa.login(QA).status_code == 200
    llm.gate.arm(count=2)
    rt.run_inline = False
    mine = api.post("/conversations", NEED).json()["id"]
    theirs = qa.post("/conversations", TESTS).json()["id"]
    assert llm.gate.wait_hits(2)

    assert _cancel(qa, theirs).status_code == 202
    llm.gate.release()
    assert _finished(rt, mine) and _finished(rt, theirs)

    assert api.get(f"/conversations/{mine}").json()["state"] == "in_review"
    assert qa.get(f"/conversations/{theirs}").json()["state"] == "error"


# --- B · Versiones anteriores tras cancelar una iteración --------------------------------------


def test_cancelled_iteration_keeps_previous_versions(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 B: se cancela una iteración (evolucionar + analizar el impacto) en su primera
    llamada → `error`/cancelled y `GET` sigue mostrando la versión 1 en `versions`; `/retry`
    retoma la iteración y llega a la versión 2 sin perder la 1."""
    conv = _in_review(rt, api)
    cid = conv["id"]
    v1 = conv["versions"]
    assert [v["version"] for v in v1] == [1]
    llm.builders[UserStory] = _changed_story  # con cambios: la iteración también analiza
    llm.started.clear()
    llm.gate.arm()
    rt.run_inline = False

    response = api.post(f"/conversations/{cid}/iterate", {"feedback": "Cambio ficticio."})
    assert response.status_code == 202, response.text
    assert llm.gate.wait_hits(1)
    assert _cancel(api, cid).status_code == 202
    llm.gate.release()
    assert _finished(rt, cid)

    assert llm.started == ["UserStory"]  # el análisis del impacto no empezó
    after = api.get(f"/conversations/{cid}").json()
    assert after["state"] == "error", after
    assert after["error"]["code"] == "cancelled"
    assert after["versions"] == v1
    assert after["feedback"] == ["Cambio ficticio."]

    rt.run_inline = True
    retried = api.post(f"/conversations/{cid}/retry").json()

    assert retried["state"] == "in_review", retried
    assert [v["version"] for v in retried["versions"]] == [1, 2]
    assert retried["versions"][0] == v1[0]
    assert retried["review"]["artifact"]["content"]["title"] == CHANGED_TITLE


# --- C · Si lo siguiente es la revisión, queda en revisión -------------------------------------

# PA-314 C: se decide por el nodo que acaba de terminar (no por el checkpoint, que LangGraph
# guarda después de emitir la actualización): tras `generate` se deja pausar en la revisión.


@pytest.mark.parametrize(
    ("body", "skip"),
    [(EVOLVE, 1), (NEED, 0)],
    ids=["evolucionar-ultima-llamada", "necesidad-unica-llamada"],
)
def test_cancel_during_last_llm_call_leaves_review(
    rt: Runtime, api: Api, llm: BlockingLLM, body: dict[str, Any], skip: int
) -> None:
    """PA-314 C: se cancela mientras el LLM hace la ÚLTIMA llamada de `generate` (el siguiente
    paso es `human_review`) → la propuesta no se pierde: `in_review`, `cancel_requested=false`
    al terminar y sin error."""
    cid = _start_blocked(rt, api, body, llm.gate, skip=skip)

    response = _cancel(api, cid)

    assert response.status_code == 202
    assert response.json()["cancel_requested"] is True
    llm.gate.release()
    assert _finished(rt, cid)
    conv = api.get(f"/conversations/{cid}").json()
    assert conv["state"] == "in_review", conv
    assert conv["cancel_requested"] is False
    assert conv["error"] is None
    assert conv["review"]["version"] == 1
    assert len(llm.calls) == skip + 1


def test_cancel_during_last_call_of_iteration_leaves_new_version_in_review(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 C: iteración sin cambios frente a Jira (una sola llamada, sin análisis) cancelada
    durante esa llamada → queda la versión 2 en revisión."""
    cid = _in_review(rt, api)["id"]
    llm.gate.arm()
    rt.run_inline = False

    api.post(f"/conversations/{cid}/iterate", {"feedback": "Cambio ficticio."})
    assert llm.gate.wait_hits(1)
    _cancel(api, cid)
    llm.gate.release()
    assert _finished(rt, cid)

    conv = api.get(f"/conversations/{cid}").json()
    assert conv["state"] == "in_review", conv
    assert conv["cancel_requested"] is False and conv["error"] is None
    assert conv["review"]["version"] == 2
    assert [v["version"] for v in conv["versions"]] == [1, 2]


def test_cancel_during_last_llm_call_never_leaves_a_dead_end(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 C (error): cancelar en la última llamada nunca deja un callejón sin salida: queda
    en revisión o, si terminara en `error`, se puede reintentar o descartar."""
    cid = _start_blocked(rt, api, NEED, llm.gate)
    _cancel(api, cid)
    llm.gate.release()
    assert _finished(rt, cid)
    conv = api.get(f"/conversations/{cid}").json()
    if conv["state"] == "in_review":
        return
    rt.run_inline = True

    retried = api.post(f"/conversations/{cid}/retry")

    assert retried.status_code == 202, retried.text
    assert retried.json()["state"] == "in_review"


# --- F · Nunca escribe en Jira -----------------------------------------------------------------


def test_cancel_never_writes_to_jira_in_live_mode(live_rt: Runtime, llm: BlockingLLM) -> None:
    """PA-314 F: aun en publicación real (`live`), cancelar no escribe nada en Jira."""
    a = Api(live_rt)
    assert a.login().status_code == 200
    cid = _start_blocked(live_rt, a, EVOLVE, llm.gate)

    _cancel(a, cid)
    llm.gate.release()
    assert _finished(live_rt, cid)

    assert a.get(f"/conversations/{cid}").json()["state"] == "error"
    _nothing_written(live_rt)


# --- G · 409 not_cancellable -------------------------------------------------------------------


def test_cancel_in_review_is_409_not_cancellable(rt: Runtime, api: Api) -> None:
    """PA-314 G: en revisión no hay nada que detener → 409 `not_cancellable`; la revisión sigue
    igual y la señal no se fija."""
    conv = _in_review(rt, api)

    response = _cancel(api, conv["id"])

    assert response.status_code == 409
    assert _code(response) == "not_cancellable"
    after = api.get(f"/conversations/{conv['id']}").json()
    assert after["state"] == "in_review" and after["review"]["version"] == 1
    assert after["cancel_requested"] is False
    assert not rt.runs.get(conv["id"]).cancel.is_set()  # type: ignore[union-attr]


@pytest.mark.parametrize("ending", ["discard", "approve"])
def test_cancel_finished_conversation_is_409_not_cancellable(
    rt: Runtime, api: Api, ending: str
) -> None:
    """PA-314 G: terminada (descartada o publicada en simulación) → 409 `not_cancellable`."""
    conv = _in_review(rt, api)
    cid = conv["id"]
    if ending == "discard":
        api.post(f"/conversations/{cid}/discard")
    else:
        api.post(f"/conversations/{cid}/approve", {"fingerprint": conv["review"]["fingerprint"]})
    state = api.get(f"/conversations/{cid}").json()["state"]
    assert state in ("discarded", "simulated")

    response = _cancel(api, cid)

    assert response.status_code == 409
    assert _code(response) == "not_cancellable"
    assert api.get(f"/conversations/{cid}").json()["state"] == state


def test_cancel_conversation_in_error_is_409_not_cancellable(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 G: en error (429 del LLM) → 409 `not_cancellable`; sigue en error y reintentable."""
    llm.error = RateLimitError("Límite ficticio del LLM.", "llm", 5)
    rt.run_inline = True
    cid = api.post("/conversations", EVOLVE).json()["id"]
    assert api.get(f"/conversations/{cid}").json()["state"] == "error"

    response = _cancel(api, cid)

    assert response.status_code == 409
    assert _code(response) == "not_cancellable"
    llm.error = None
    assert api.post(f"/conversations/{cid}/retry").json()["state"] == "in_review"


def test_cancel_already_cancelled_conversation_is_409(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 G (límite): una vez detenida (error/cancelled), volver a cancelar → 409."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)
    _cancel(api, cid)
    llm.gate.release()
    assert _finished(rt, cid)

    response = _cancel(api, cid)

    assert response.status_code == 409
    assert _code(response) == "not_cancellable"


def test_cancel_while_approving_is_409_and_publication_finishes(
    live_rt: Runtime, tracker: BlockingIssueTracker
) -> None:
    """PA-314 G: con `approve` en curso (publicación real bloqueada en `update_story`, nodo
    `publish`) → 409 `not_cancellable`; la señal no se fija y la publicación termina."""
    a = Api(live_rt)
    assert a.login().status_code == 200
    conv = _in_review(live_rt, a)
    cid = conv["id"]
    tracker.write_gate.arm()
    live_rt.run_inline = False

    approved = a.post(
        f"/conversations/{cid}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert approved.status_code == 202, approved.text
    assert tracker.write_gate.wait_hits(1), "la publicación no llegó a escribir en Jira"

    response = _cancel(a, cid)

    assert response.status_code == 409
    assert _code(response) == "not_cancellable"
    assert "publicar" in response.json()["error"]["message"]
    run = live_rt.runs.get(cid)
    assert run is not None and run.operation == "approve" and not run.cancel.is_set()
    during = a.get(f"/conversations/{cid}").json()
    assert during["state"] == "generating" and during["cancel_requested"] is False
    tracker.write_gate.release()
    assert _finished(live_rt, cid)

    final = a.get(f"/conversations/{cid}").json()
    assert final["state"] == "published", final
    assert final["error"] is None
    assert ("update_story", {"key": "DEMO-3"}) in tracker.writes


# --- H · Propiedad, permisos y CSRF ------------------------------------------------------------


def test_cancel_foreign_and_missing_conversation_are_the_same_404(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 H: la conversación ajena (aunque esté generando) y la inexistente → mismo 404;
    la ajena no se detiene y termina en revisión."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)
    other = Api(rt)
    assert other.login(QA).status_code == 200

    foreign = _cancel(other, cid)
    missing = _cancel(other, str(uuid4()))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert not rt.runs.get(cid).cancel.is_set()  # type: ignore[union-attr]
    llm.gate.release()
    assert _finished(rt, cid)
    assert api.get(f"/conversations/{cid}").json()["state"] == "in_review"


def test_cancel_foreign_conversation_before_load_origin_is_404(
    rt: Runtime, api: Api, tracker: BlockingIssueTracker
) -> None:
    """PA-314 H (límite): recién creada, aún sin fila en la lista (bloqueada en `load_origin`):
    la ajena también es 404 y no se detiene."""
    cid = _start_blocked(rt, api, EVOLVE, tracker.read_gate)
    other = Api(rt)
    assert other.login(QA).status_code == 200

    foreign = _cancel(other, cid)

    assert foreign.status_code == 404
    assert foreign.json() == _cancel(other, str(uuid4())).json()
    assert not rt.runs.get(cid).cancel.is_set()  # type: ignore[union-attr]
    tracker.read_gate.release()
    assert _finished(rt, cid)


def test_cancel_with_role_without_flow_permission_is_403(
    rt: Runtime, api: Api, llm: BlockingLLM
) -> None:
    """PA-314 H: el dueño con un rol sin permiso del flujo (QA en una HU) → 403 `forbidden`;
    no se detiene."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)
    api.session.user = User(username=AF[0], role="qa")

    response = _cancel(api, cid)

    assert response.status_code == 403
    assert _code(response) == "forbidden"
    assert not rt.runs.get(cid).cancel.is_set()  # type: ignore[union-attr]
    llm.gate.release()
    assert _finished(rt, cid)
    assert rt.runs.get(cid).error is None  # type: ignore[union-attr]


def test_cancel_without_csrf_is_403(rt: Runtime, api: Api, llm: BlockingLLM) -> None:
    """PA-314 H: sin `X-CSRF-Token` → 403 y la generación sigue hasta la revisión."""
    cid = _start_blocked(rt, api, EVOLVE, llm.gate)

    response = _cancel(api, cid, csrf=False)

    assert response.status_code == 403
    assert not rt.runs.get(cid).cancel.is_set()  # type: ignore[union-attr]
    llm.gate.release()
    assert _finished(rt, cid)
    assert api.get(f"/conversations/{cid}").json()["state"] == "in_review"


def test_cancel_without_session_is_401(rt: Runtime) -> None:
    """PA-314 H: sin sesión → 401 `unauthenticated`."""
    response = Api(rt).client.post(f"/api/v1/conversations/{uuid4()}/cancel")

    assert response.status_code == 401
    assert _code(response) == "unauthenticated"


# --- I · QA encadenada -------------------------------------------------------------------------


@pytest.fixture
def qa_parts() -> tuple[FakeLLMProvider, BlockingEmbeddings]:
    return FakeLLMProvider(), BlockingEmbeddings()


@pytest.fixture
def qa_rt(
    tmp_path: Path, qa_parts: tuple[FakeLLMProvider, BlockingEmbeddings]
) -> Iterator[Runtime]:
    qa_llm, emb = qa_parts
    runtime = fake_runtime(tmp_path, llm=qa_llm, embeddings=emb)
    yield runtime
    emb.gate.release()
    runtime.shutdown()


def test_cancel_taken_qa_conversation_before_first_version_releases_handoff(
    qa_rt: Runtime, qa_parts: tuple[FakeLLMProvider, BlockingEmbeddings]
) -> None:
    """PA-314 I (PA-113): se cancela la conversación de QA recogida antes de su primera versión
    (bloqueada en `retrieve_context`) → error/cancelled, sin generar la suite; la entrega vuelve
    a `pending` y aparece en `GET /qa/handoffs`."""
    qa_llm, emb = qa_parts
    _af, _cid, handoff = _handed_off(qa_rt)  # en el mismo hilo
    suites = sum(1 for c in qa_llm.calls if c["schema"] is TestSuite)
    emb.gate.arm()
    qa_rt.run_inline = False
    qa = HandoffApi(qa_rt, QA)

    taken = qa.post(f"/qa/handoffs/{handoff['id']}/take")
    assert taken.status_code == 202, taken.text
    cid = taken.json()["id"]
    assert emb.gate.wait_hits(1)
    response = qa.post(f"/conversations/{cid}/cancel")
    assert response.status_code == 202, response.text
    emb.gate.release()
    assert _finished(qa_rt, cid)

    conv = qa.get(f"/conversations/{cid}").json()
    assert conv["state"] == "error" and conv["error"]["code"] == "cancelled"
    assert sum(1 for c in qa_llm.calls if c["schema"] is TestSuite) == suites
    row = _store(qa_rt).get(handoff["id"])
    assert row is not None
    assert (row.status, row.taken_by, row.qa_thread_id) == ("pending", None, None)
    assert [h["id"] for h in qa.get("/qa/handoffs").json()] == [handoff["id"]]


# --- api/cancel.py y RunRegistry (unidad) ------------------------------------------------------


def test_cancellable_llm_raises_before_call_when_signal_is_set() -> None:
    """PA-314: con la señal activa, `CancellableLLM` no llama al LLM (ni texto ni estructurado)."""
    inner = FakeLLMProvider()
    llm = CancellableLLM(inner)
    signal = threading.Event()
    signal.set()
    messages = [Message(role="user", content="Texto ficticio.")]

    with cancellation(signal):
        with pytest.raises(GenerationCancelledError) as caught:
            llm.generate_structured(messages, UserStory, TaskType.GENERATE_STORY)
        with pytest.raises(GenerationCancelledError):
            llm.generate(messages, TaskType.GENERATE_STORY)

    assert inner.calls == []
    assert str(caught.value) == CANCELLED_MESSAGE


def test_cancellable_llm_passes_through_without_signal_or_outside_block() -> None:
    """PA-314: sin señal activa, o fuera de `cancellation`, la llamada llega al LLM; el resto de
    atributos se delega tal cual."""
    inner = FakeLLMProvider()
    llm = CancellableLLM(inner)
    messages = [Message(role="user", content="Texto ficticio.")]
    signal = threading.Event()

    with cancellation(signal):
        llm.generate(messages, TaskType.GENERATE_STORY)
    signal.set()
    llm.generate(messages, TaskType.GENERATE_STORY)  # fuera del bloque: la señal no aplica
    raise_if_cancelled()

    assert len(inner.calls) == 2
    assert llm.model == "fake-model"


def test_cancellation_signal_is_per_thread() -> None:
    """PA-314 A: la señal fijada en un hilo no la ve otro hilo (ContextVar)."""
    signal = threading.Event()
    signal.set()
    seen: list[bool] = []

    def other_thread() -> None:
        try:
            raise_if_cancelled()
            seen.append(False)
        except GenerationCancelledError:
            seen.append(True)

    with cancellation(signal):
        worker = threading.Thread(target=other_thread)
        worker.start()
        worker.join(timeout=DEFAULT_WAIT)
        with pytest.raises(GenerationCancelledError):
            raise_if_cancelled()

    assert seen == [False]


def test_run_registry_begin_renews_the_signal() -> None:
    """PA-314 A: cada `begin` estrena señal; `touch` solo avisa (sube `seq`)."""
    registry = RunRegistry()
    run = registry.add(
        Run(
            thread_id="hilo-ficticio",
            owner="af-demo",
            flow="evolve",
            mode="functional",
            project="DEMO",
            title="Título ficticio",
        )
    )
    assert registry.begin(run, "start")
    first = run.cancel
    first.set()
    registry.finish(run)
    seq = run.seq

    registry.touch(run)
    assert run.seq == seq + 1
    assert registry.begin(run, "retry")

    assert run.cancel is not first and not run.cancel.is_set()


# --- L · Contrato ------------------------------------------------------------------------------


def _published() -> dict[str, Any]:
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_contract_publishes_cancel_route_with_202_and_409() -> None:
    """PA-314 L: el contrato (publicado y el del código) tiene POST …/cancel con 202 y 409
    `not_cancellable`, además de 401/403/404."""
    for doc in (_published(), create_app().openapi()):
        op = doc["paths"][CANCEL_PATH]["post"]
        assert {"202", "401", "403", "404", "409"} <= set(op["responses"])
    op = _published()["paths"][CANCEL_PATH]["post"]
    example = op["responses"]["409"]["content"]["application/json"]
    assert "not_cancellable" in yaml.safe_dump(example)
    example_202 = yaml.safe_dump(op["responses"]["202"]["content"]["application/json"])
    assert "cancel_requested: true" in example_202


def test_contract_error_codes_include_cancelled_and_not_cancellable() -> None:
    """PA-314 L: `cancelled` y `not_cancellable` están en el enumerado `ErrorCode`."""
    schemas = _published()["components"]["schemas"]
    code = schemas["ErrorBody"]["properties"]["code"]
    codes = code.get("enum") or schemas[code["$ref"].rsplit("/", 1)[-1]]["enum"]

    assert {"cancelled", "not_cancellable", "not_in_error", "not_in_review"} <= set(codes)


def test_contract_conversation_out_has_optional_cancel_and_baseline_fields() -> None:
    """PA-314/PA-316 L: `ConversationOut.cancel_requested` (booleano, default false) y
    `jira_baseline` (UserStory o null) son opcionales: el frontend actual no se rompe."""
    schema = _published()["components"]["schemas"]["ConversationOut"]
    props, required = schema["properties"], set(schema.get("required", []))

    assert props["cancel_requested"]["type"] == "boolean"
    assert props["cancel_requested"]["default"] is False
    variants = props["jira_baseline"]["anyOf"]
    assert {"$ref": "#/components/schemas/UserStory"} in variants
    assert {"type": "null"} in variants
    assert not {"cancel_requested", "jira_baseline"} & required


def test_contract_keeps_every_route_of_the_committed_contract() -> None:
    """PA-314 L: respecto al contrato de HEAD no desaparece ninguna ruta ni método; la ruta de
    cancelar está publicada."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git no está disponible")
    shown = subprocess.run(  # noqa: S603 - argumentos fijos, sin entrada externa
        [git, "show", "HEAD:docs/api/openapi.yaml"],
        cwd=OPENAPI_PATH.parents[2],
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
    assert (CANCEL_PATH, "post") in after


# --- Carrera con una aprobación (security-reviewer) --------------------------------------------


def test_request_cancel_checks_and_sets_under_the_lock() -> None:
    """Solo se activa la señal de una operación que se puede cancelar y que está en curso."""
    from api.runtime import Run, RunRegistry
    from api.service import CANCELLABLE_OPERATIONS

    runs = RunRegistry()
    run = runs.add(Run("hilo-ficticio", "af-demo", "evolve", "functional", "DEMO", "t"))
    assert runs.request_cancel(run, CANCELLABLE_OPERATIONS) == "idle"
    runs.begin(run, "approve")
    assert runs.request_cancel(run, CANCELLABLE_OPERATIONS) == "operation"
    assert not run.cancel.is_set()
    runs.finish(run)
    runs.begin(run, "iterate")
    assert runs.request_cancel(run, CANCELLABLE_OPERATIONS) == "ok"
    assert run.cancel.is_set()


def test_signal_raised_during_approve_never_stops_the_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aunque la señal se active en una aprobación (carrera), se publica igual: `_run_graph`
    solo respeta la señal de crear, iterar o reintentar."""
    from api.runtime import RunRegistry

    rt = fake_runtime(tmp_path, run_inline=True)
    a = Api(rt)
    assert a.login().status_code == 200
    conv = a.post("/conversations", EVOLVE).json()
    original_begin = RunRegistry.begin

    def begin_and_signal(self: RunRegistry, run: Any, operation: str) -> bool:
        started = original_begin(self, run, operation)
        if operation == "approve":
            run.cancel.set()  # la señal «se cuela» en la aprobación
        return started

    monkeypatch.setattr(RunRegistry, "begin", begin_and_signal)
    done = a.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    ).json()

    assert done["state"] == "simulated", done
    assert done["error"] is None
