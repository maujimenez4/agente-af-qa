"""PA-113: si la conversación de QA recogida falla antes de su primera versión, la HU vuelve a
la lista de QA (`release_failed_take`) y la puede recoger otra persona.

Sobre `fake_runtime` (entregas en `InMemoryHandoffStore`) con un `FakeLLMProvider` que falla al
generar la `TestSuite`. Solo fakes, sin red, sin `.env`, sin Jira ni LLM reales; datos ficticios.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from structlog.testing import capture_logs

from adapters.base import Message, User
from adapters.errors import ExternalServiceError
from api import service
from api.runtime import Run, Runtime
from core.handoff import HandoffError, InMemoryHandoffStore, QaStart, load_taken_handoff
from schemas.test_case import TestSuite
from tests.fakes.api import fake_runtime
from tests.fakes.llm import FakeLLMProvider, _default_builders
from tests.unit.test_api_handoffs import QA, Api, _fakes, _handed_off, _store

QA2 = ("qa-ficticio-2", "contrasena-ficticia-qa2")
LLM_DOWN = "El proveedor ficticio de modelos no responde."


def _failing_suite(_messages: list[Message]) -> BaseModel:
    raise ExternalServiceError(LLM_DOWN, service="llm")


class SwitchableLLM(FakeLLMProvider):
    """FakeLLMProvider cuya respuesta de TestSuite se puede romper y arreglar."""

    def break_suite(self) -> None:
        self.builders[TestSuite] = _failing_suite

    def fix_suite(self) -> None:
        self.builders[TestSuite] = _default_builders()[TestSuite]


@pytest.fixture
def llm() -> SwitchableLLM:
    return SwitchableLLM()


@pytest.fixture
def rt(tmp_path: Path, llm: SwitchableLLM) -> Runtime:
    runtime = fake_runtime(tmp_path, llm=llm)
    runtime.auth.users[QA2[0]] = (QA2[1], User(username=QA2[0], role="qa"))  # type: ignore[attr-defined]
    return runtime


def _failed_take(rt: Runtime, llm: SwitchableLLM) -> tuple[Api, dict[str, Any], dict[str, Any]]:
    """af-demo entrega DEMO-3; qa-demo la recoge con la generación de la suite rota."""
    _af, _cid, handoff = _handed_off(rt)
    llm.break_suite()
    qa = Api(rt, QA)
    taken = qa.post(f"/qa/handoffs/{handoff['id']}/take")
    assert taken.status_code == 202, taken.text
    return qa, handoff, taken.json()


def test_failed_take_leaves_qa_conversation_in_error(rt: Runtime, llm: SwitchableLLM) -> None:
    """Criterio 7: la conversación de QA queda en error, con el mensaje en español."""
    qa, _handoff, conv = _failed_take(rt, llm)

    detail = qa.get(f"/conversations/{conv['id']}").json()
    assert detail["state"] == "error", detail
    assert detail["error"]["code"] == "service_unavailable"
    assert detail["error"]["message"] == LLM_DOWN
    assert detail["review"] is None


def test_failed_take_returns_handoff_to_pending_list(rt: Runtime, llm: SwitchableLLM) -> None:
    """Criterio 7: la entrega vuelve a `pending`, sin quién ni hilo, y aparece en la lista."""
    qa, handoff, _conv = _failed_take(rt, llm)

    row = _store(rt).get(handoff["id"])
    assert row is not None
    assert (row.status, row.taken_by, row.taken_at, row.qa_thread_id) == (
        "pending",
        None,
        None,
        None,
    )
    assert [h["id"] for h in qa.get("/qa/handoffs").json()] == [handoff["id"]]
    tracker, testmgmt = _fakes(rt)
    assert tracker.writes == [] and testmgmt.publish_calls == 0


def test_released_handoff_can_be_taken_by_another_qa_person(
    rt: Runtime, llm: SwitchableLLM
) -> None:
    """Criterio 7: otra persona de QA la recoge y su conversación llega a revisión."""
    _qa, handoff, failed = _failed_take(rt, llm)
    llm.fix_suite()
    qa2 = Api(rt, QA2)

    taken = qa2.post(f"/qa/handoffs/{handoff['id']}/take")

    assert taken.status_code == 202, taken.text
    conv = taken.json()
    assert conv["state"] == "in_review", conv
    assert conv["id"] != failed["id"]
    row = _store(rt).get(handoff["id"])
    assert row is not None and row.taken_by == QA2[0] and row.qa_thread_id == conv["id"]
    assert qa2.get("/qa/handoffs").json() == []


def test_failed_thread_cannot_reuse_released_handoff(rt: Runtime, llm: SwitchableLLM) -> None:
    """Criterio 7: el hilo fallido ya no puede usar la entrega (ni libre ni de otra persona)."""
    qa, handoff, failed = _failed_take(rt, llm)
    store = _store(rt)

    with pytest.raises(HandoffError):
        load_taken_handoff(store, handoff["id"], QA[0], failed["id"])

    llm.fix_suite()
    qa2 = Api(rt, QA2)
    assert qa2.post(f"/qa/handoffs/{handoff['id']}/take").status_code == 202
    with pytest.raises(HandoffError):
        load_taken_handoff(store, handoff["id"], QA[0], failed["id"])
    # Reintentar en la conversación fallida no genera nada ni cambia la entrega.
    retried = qa.post(f"/conversations/{failed['id']}/iterate", {"feedback": "Reintento ficticio."})
    assert retried.status_code == 409, retried.text
    assert retried.json()["error"]["code"] == "not_in_review"
    row = store.get(handoff["id"])
    assert row is not None and row.taken_by == QA2[0]


def test_failure_after_first_version_does_not_release(rt: Runtime, llm: SwitchableLLM) -> None:
    """Criterio 7: si falla al iterar (ya hay artefacto), la entrega sigue recogida."""
    _af, _cid, handoff = _handed_off(rt)
    qa = Api(rt, QA)
    conv = qa.post(f"/qa/handoffs/{handoff['id']}/take").json()
    assert conv["state"] == "in_review", conv
    llm.break_suite()

    iterated = qa.post(f"/conversations/{conv['id']}/iterate", {"feedback": "Cambio ficticio."})

    assert iterated.status_code == 202, iterated.text
    assert qa.get(f"/conversations/{conv['id']}").json()["state"] == "error"
    row = _store(rt).get(handoff["id"])
    assert row is not None
    assert (row.status, row.taken_by, row.qa_thread_id) == ("taken", QA[0], conv["id"])
    assert qa.get("/qa/handoffs").json() == []


# --- _run_taken en aislamiento -----------------------------------------------------------------


class SpyStore:
    def __init__(self) -> None:
        self.released: list[tuple[str, str, str]] = []

    def release(self, handoff_id: str, username: str, qa_thread_id: str) -> bool:
        self.released.append((handoff_id, username, qa_thread_id))
        return True


def _run(error: bool) -> Run:
    return Run(
        thread_id="hilo-qa-ficticio",
        owner="qa-demo",
        flow="tests",
        mode="qa",
        project="DEMO",
        title="Preparar las pruebas de DEMO-3",
        error=SimpleNamespace(code="x") if error else None,  # type: ignore[arg-type]
    )


def _start() -> QaStart:
    handoff = SimpleNamespace(id="ab" * 16)
    return QaStart(
        config={"configurable": {"thread_id": "hilo-qa-ficticio"}}, state={}, handoff=handoff
    )  # type: ignore[arg-type]


def _ws(values: dict[str, Any] | Exception) -> Any:
    def get_state(_config: Any) -> Any:
        if isinstance(values, Exception):
            raise values
        return SimpleNamespace(values=values)

    return SimpleNamespace(graph=SimpleNamespace(get_state=get_state))


@pytest.mark.parametrize(
    ("error", "values", "released"),
    [
        (True, {}, True),
        (True, {"artifact": object()}, False),
        (False, {}, False),
    ],
    ids=["fails-before-artifact", "fails-with-artifact", "succeeds"],
)
def test_run_taken_releases_only_when_failing_before_artifact(
    monkeypatch: pytest.MonkeyPatch, error: bool, values: dict[str, Any], released: bool
) -> None:
    """Criterio 7: solo se libera si la operación falló y no hay artefacto."""
    run = _run(error)
    monkeypatch.setattr(service, "_run_graph", lambda *_a, **_k: None)
    store = SpyStore()

    service._run_taken(None, _ws(values), run, _start(), store)  # type: ignore[arg-type]

    expected = [("ab" * 16, "qa-demo", "hilo-qa-ficticio")] if released else []
    assert store.released == expected


def test_run_taken_keeps_handoff_if_state_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterio 7 (error): sin poder leer el estado no se libera; solo se registra el tipo."""
    monkeypatch.setattr(service, "_run_graph", lambda *_a, **_k: None)
    store = SpyStore()
    secret = "detalle-interno-ficticio-0000"

    with capture_logs() as logs:
        service._run_taken(None, _ws(RuntimeError(secret)), _run(True), _start(), store)  # type: ignore[arg-type]

    assert store.released == []
    (entry,) = [e for e in logs if e.get("action") == "release_handoff"]
    assert entry["error_type"] == "RuntimeError"
    assert secret not in str(logs)


def test_in_memory_store_type_is_used_by_fake_runtime(rt: Runtime) -> None:
    """Comprobación de montaje: las pruebas de PA-113 usan el almacén en memoria."""
    assert isinstance(rt.handoffs, InMemoryHandoffStore)
