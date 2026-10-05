"""Contrato de QA de la API (ronda 12 · PA-326 y PA-327).

- PA-327: los pasos de una conversación de QA son los 4 de `QA_STEP_LABELS` (sin `memorize`),
  en el detalle, en el SSE y en `/take`; los de la HU (`STEP_LABELS`, 5 pasos) no cambian.
- PA-326: la revisión de QA trae `coverage_md` (= `TestSuite.coverage_md()`) y `uncovered`
  (CA y RN de la HU de origen sin casos), calculados sin LLM; `null` = «no se sabe», listas
  vacías = «todo cubierto». En una revisión de HU, ambos `null`.
- El ejemplo `CONVERSATION_QA_REVIEW` y `components.examples.ConversationQaInReview`.

Solo fakes de `tests/fakes/`, sin red, sin `.env`, sin Jira ni LLM reales; datos 100 % ficticios.
Las operaciones largas se ejecutan en el mismo hilo (`run_inline`).
"""

import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from api import app as app_module
from api import examples as ex
from api import service
from api.export_openapi import OPENAPI_PATH
from api.models import ConversationOut
from api.runtime import Run, Runtime
from api.service import QA_STEP_LABELS, STEP_LABELS
from core.artifact_state import InMemoryArtifactStateStore
from core.handoff import InMemoryHandoffStore
from core.personal_data import personal_data_kind
from schemas.test_case import TestSuite
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory
from tests.fakes.api import fake_runtime
from tests.fakes.llm import FakeLLMProvider
from tests.unit.test_api_app import AF, EVOLVE, QA, TESTS, Api

QA_NODES = ["load_origin", "retrieve_context", "generate", "publish"]
STORY_NODES = [*QA_NODES, "memorize"]
# Textos del contrato (PA-327): si cambian, el frontend debe enterarse.
EXPECTED_QA_LABELS = {
    "load_origin": "Recuperar la HU de origen",
    "retrieve_context": "Recuperar el contexto (Jira, documentos y memoria)",
    "generate": "Generar casos y escenarios, validar la cobertura y preparar datos, riesgos y "
    "estrategia",
    "publish": "Publicar (o simular la publicación de) los casos de prueba en Jira",
}
EXPECTED_STORY_LABELS = {
    "load_origin": "Leer el origen en Jira",
    "retrieve_context": "Recuperar el contexto (Jira, documentos y memoria)",
    "generate": "Generar la propuesta, validar las citas y analizar el impacto",
    "publish": "Publicar (o simular la publicación) en Jira",
    "memorize": "Guardar la memoria de la HU publicada",
}
EXTRA_RULE = BusinessRule(id="RN-09", description="Regla ficticia sin ningún caso de prueba.")
EXTRA_CRITERION = AcceptanceCriterion(
    id="CA-03",
    title="Criterio ficticio sin casos",
    given=["un préstamo ficticio"],
    when=["se consulta"],
    then=["se muestra"],
)
HEX64 = re.compile(r"[0-9a-f]{64}")


# --- Fixtures y ayudantes ----------------------------------------------------------------------


@pytest.fixture
def llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def rt(tmp_path: Path, llm: FakeLLMProvider) -> Runtime:
    return fake_runtime(tmp_path, llm=llm)


@pytest.fixture
def live_rt(tmp_path: Path, llm: FakeLLMProvider) -> Runtime:
    return fake_runtime(tmp_path, llm=llm, publish_mode="live")


@pytest.fixture
def fast_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "SSE_POLL_S", 0.02)


def _login(rt: Runtime, who: tuple[str, str]) -> Api:
    a = Api(rt)
    assert a.login(who).status_code == 200
    return a


def _qa_review(a: Api) -> dict[str, Any]:
    """QA desde Jira (DEMO-3) hasta la revisión de la suite."""
    response = a.post("/conversations", TESTS)
    assert response.status_code == 202, response.text
    conv = response.json()
    assert conv["state"] == "in_review" and conv["mode"] == "qa", conv
    return dict(conv)


def _story_review(a: Api) -> dict[str, Any]:
    response = a.post("/conversations", EVOLVE)
    assert response.status_code == 202, response.text
    conv = response.json()
    assert conv["state"] == "in_review" and conv["mode"] == "functional", conv
    return dict(conv)


def _approve(a: Api, conv: dict[str, Any]) -> dict[str, Any]:
    response = a.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    )
    assert response.status_code == 202, response.text
    return dict(response.json())


def _labels(progress: list[dict[str, Any]]) -> dict[str, str]:
    return {step["node"]: step["label"] for step in progress}


def _states(progress: list[dict[str, Any]]) -> dict[str, str]:
    return {step["node"]: step["state"] for step in progress}


def _store(rt: Runtime) -> InMemoryArtifactStateStore:
    store = rt.workspace_factory().container.state_store
    assert isinstance(store, InMemoryArtifactStateStore)
    return store


def _handoffs(rt: Runtime) -> InMemoryHandoffStore:
    assert isinstance(rt.handoffs, InMemoryHandoffStore)
    return rt.handoffs


def _artifact_id(conv: dict[str, Any]) -> str:
    return str(conv["review"]["artifact"]["id"])


def _events(text: str) -> list[tuple[str, str]]:
    """(evento, data) de un texto SSE; se ignoran los comentarios `: ping`."""
    out: list[tuple[str, str]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if lines:
            fields = dict(line.split(": ", 1) for line in lines)
            out.append((fields["event"], fields["data"]))
    return out


def _progress_events(a: Api, cid: str, *, open_ended: bool) -> list[dict[str, Any]]:
    """Eventos `progress` del SSE. Si la conversación sigue abierta (en revisión), se cierra la
    sesión al poco para que el flujo termine (como en `test_api_app.py`)."""
    session = a.session
    timers: list[threading.Timer] = []
    if open_ended:
        timers.append(threading.Timer(0.3, lambda: a.rt.sessions.drop(session.id)))
    timers.append(threading.Timer(10.0, lambda: a.rt.sessions.drop(session.id)))  # nunca colgar
    for timer in timers:
        timer.start()
    try:
        response = a.get(f"/conversations/{cid}/events")
    finally:
        for timer in timers:
            timer.cancel()
    assert response.status_code == 200, response.text
    return [json.loads(data) for name, data in _events(response.text) if name == "progress"]


def _with_extra(story: UserStory, *, rule: bool = True, criterion: bool = False) -> UserStory:
    update: dict[str, Any] = {}
    if rule:
        update["business_rules"] = [*story.business_rules, EXTRA_RULE]
    if criterion:
        update["acceptance_criteria"] = [*story.acceptance_criteria, EXTRA_CRITERION]
    return story.model_copy(update=update)


def _llm_with_extra_rule(llm: FakeLLMProvider) -> None:
    """Toda HU que estructure o evolucione el LLM ficticio lleva una RN-09 que la suite no cubre."""
    base = llm.builders[UserStory]

    def build(messages: Any) -> BaseModel:
        story = base(messages)
        assert isinstance(story, UserStory)
        return _with_extra(story)

    llm.builders[UserStory] = build


def _taken(rt: Runtime) -> tuple[Api, str, dict[str, Any]]:
    """af-demo aprueba la evolución de DEMO-3 y la entrega; qa-demo la recoge."""
    af = _login(rt, AF)
    story = _story_review(af)
    assert _approve(af, story)["state"] in ("simulated", "published")
    handoff = af.post(f"/conversations/{story['id']}/handoff")
    assert handoff.status_code == 200, handoff.text
    handoff_id = handoff.json()["id"]
    qa = _login(rt, QA)
    taken = qa.post(f"/qa/handoffs/{handoff_id}/take")
    assert taken.status_code == 202, taken.text
    conv = taken.json()
    assert conv["state"] == "in_review" and conv["mode"] == "qa", conv
    return qa, handoff_id, dict(conv)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


# --- PA-327 · Pasos de QA: constantes y `_progress` -------------------------------------------


def test_qa_step_labels_are_the_four_qa_nodes_with_their_texts() -> None:
    """PA-327: `QA_STEP_LABELS` son 4 nodos (los de la HU menos `memorize`) con sus textos."""
    assert QA_STEP_LABELS == EXPECTED_QA_LABELS
    assert list(QA_STEP_LABELS) == QA_NODES
    assert "memorize" not in QA_STEP_LABELS


def test_story_step_labels_are_unchanged() -> None:
    """PA-327: las etiquetas de la HU (`STEP_LABELS`) siguen siendo los mismos 5 pasos."""
    assert STEP_LABELS == EXPECTED_STORY_LABELS
    assert list(STEP_LABELS) == STORY_NODES


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("qa", EXPECTED_QA_LABELS), ("functional", EXPECTED_STORY_LABELS), (None, STEP_LABELS)],
    ids=["qa", "funcional", "sin-modo"],
)
def test_step_labels_depend_on_mode(mode: str | None, expected: dict[str, str]) -> None:
    """PA-327: `step_labels(mode)` devuelve las etiquetas de QA solo en modo `qa`."""
    assert service.step_labels(mode) == expected


def test_qa_progress_while_approving_never_runs_memorize() -> None:
    """PA-327: aprobando en QA, si `publish` ya terminó, ningún paso queda «running» por
    `memorize` (no está en la lista); antes de terminar, `publish` es el que corre."""
    run = Run(
        thread_id="hilo-ficticio",
        owner="qa-demo",
        flow="tests",
        mode="qa",
        project="DEMO",
        title="Ficticio",
        operation="approve",
        running=True,
        nodes=["publish"],
    )
    values = {"artifact": object()}
    after = service._progress("generating", run, values, "qa")
    assert [s.node for s in after] == QA_NODES
    assert {s.node: s.state for s in after} == dict.fromkeys(QA_NODES, "done")

    run.nodes = []
    before = service._progress("generating", run, values, "qa")
    assert {s.node: s.state for s in before}["publish"] == "running"
    assert all(s.node != "memorize" for s in before)


def test_story_progress_while_approving_still_runs_memorize() -> None:
    """PA-327: en la HU nada cambia: tras `publish`, `memorize` es el paso que corre."""
    run = Run(
        thread_id="hilo-ficticio",
        owner="af-demo",
        flow="evolve",
        mode="functional",
        project="DEMO",
        title="Ficticio",
        operation="approve",
        running=True,
        nodes=["publish"],
    )
    steps = service._progress("generating", run, {"artifact": object()}, "functional")
    assert [s.node for s in steps] == STORY_NODES
    assert {s.node: s.state for s in steps}["memorize"] == "running"


# --- PA-327 · Pasos de QA en el detalle -------------------------------------------------------


def test_qa_detail_has_qa_steps_when_in_review(rt: Runtime) -> None:
    """PA-327: respuesta de creación y `GET` de QA en revisión: 4 pasos de QA, `publish`
    pendiente, sin `memorize`."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    detail = qa.get(f"/conversations/{conv['id']}").json()
    for body in (conv, detail):
        assert _labels(body["progress"]) == EXPECTED_QA_LABELS
        assert [s["node"] for s in body["progress"]] == QA_NODES
        assert _states(body["progress"]) == {
            "load_origin": "done",
            "retrieve_context": "done",
            "generate": "done",
            "publish": "pending",
        }


@pytest.mark.parametrize(
    ("runtime", "final"), [("rt", "simulated"), ("live_rt", "published")], ids=["sim", "live"]
)
def test_qa_detail_after_approve_marks_publish_done_without_memorize(
    request: pytest.FixtureRequest, runtime: str, final: str
) -> None:
    """PA-327: tras aprobar (simulación y `live`) los 4 pasos de QA quedan `done`; `memorize`
    no aparece ni en el detalle ni entre los nodos terminados de la operación."""
    runtime_obj: Runtime = request.getfixturevalue(runtime)
    qa = _login(runtime_obj, QA)
    conv = _qa_review(qa)
    approved = _approve(qa, conv)
    assert approved["state"] == final, approved
    detail = qa.get(f"/conversations/{conv['id']}").json()
    for body in (approved, detail):
        assert _labels(body["progress"]) == EXPECTED_QA_LABELS
        assert _states(body["progress"]) == dict.fromkeys(QA_NODES, "done")
    run = runtime_obj.runs.get(conv["id"])
    assert run is not None and "memorize" not in run.nodes and "publish" in run.nodes


@pytest.mark.parametrize(
    ("runtime", "final"), [("rt", "simulated"), ("live_rt", "published")], ids=["sim", "live"]
)
def test_story_detail_keeps_five_story_steps(
    request: pytest.FixtureRequest, runtime: str, final: str
) -> None:
    """PA-327: la HU sigue con 5 pasos y sus textos; tras aprobar, `memorize` también `done`."""
    runtime_obj: Runtime = request.getfixturevalue(runtime)
    af = _login(runtime_obj, AF)
    conv = _story_review(af)
    assert _labels(conv["progress"]) == EXPECTED_STORY_LABELS
    assert _states(conv["progress"])["memorize"] == "pending"
    approved = _approve(af, conv)
    assert approved["state"] == final, approved
    detail = af.get(f"/conversations/{conv['id']}").json()
    for body in (approved, detail):
        assert _labels(body["progress"]) == EXPECTED_STORY_LABELS
        assert _states(body["progress"]) == dict.fromkeys(STORY_NODES, "done")


# --- PA-327 · Pasos de QA en el SSE -----------------------------------------------------------


def test_qa_sse_progress_uses_qa_steps_in_review(rt: Runtime, fast_sse: None) -> None:
    """PA-327: eventos `progress` de una QA en revisión: solo nodos y textos de QA."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    steps = _progress_events(qa, conv["id"], open_ended=True)
    assert steps
    assert {s["node"] for s in steps} == set(QA_NODES)
    assert all(s["label"] == EXPECTED_QA_LABELS[s["node"]] for s in steps)
    assert _states(steps)["publish"] == "pending"


@pytest.mark.parametrize("runtime", ["rt", "live_rt"], ids=["sim", "live"])
def test_qa_sse_progress_after_approve_has_publish_done_and_no_memorize(
    request: pytest.FixtureRequest, runtime: str, fast_sse: None
) -> None:
    """PA-327: tras aprobar, el SSE emite los 4 pasos de QA `done` y nunca `memorize`."""
    runtime_obj: Runtime = request.getfixturevalue(runtime)
    qa = _login(runtime_obj, QA)
    conv = _qa_review(qa)
    _approve(qa, conv)
    steps = _progress_events(qa, conv["id"], open_ended=False)
    assert {s["node"] for s in steps} == set(QA_NODES)
    assert all(s["label"] == EXPECTED_QA_LABELS[s["node"]] for s in steps)
    assert _states(steps) == dict.fromkeys(QA_NODES, "done")


def test_story_sse_progress_keeps_story_steps(rt: Runtime, fast_sse: None) -> None:
    """PA-327: en la HU, el SSE sigue con los 5 pasos y sus textos (en revisión y tras aprobar)."""
    af = _login(rt, AF)
    conv = _story_review(af)
    in_review = _progress_events(af, conv["id"], open_ended=True)
    assert {s["node"] for s in in_review} == set(STORY_NODES)
    assert all(s["label"] == EXPECTED_STORY_LABELS[s["node"]] for s in in_review)

    af = _login(rt, AF)  # la sesión anterior se cerró para terminar el flujo
    _approve(af, af.get(f"/conversations/{conv['id']}").json())
    done = _progress_events(af, conv["id"], open_ended=False)
    assert _states(done) == dict.fromkeys(STORY_NODES, "done")
    assert all(s["label"] == EXPECTED_STORY_LABELS[s["node"]] for s in done)


# --- PA-327 · `/take` -------------------------------------------------------------------------


def test_take_answers_with_qa_steps(rt: Runtime) -> None:
    """PA-327: recoger una entrega (QA encadenada) responde con los 4 pasos de QA."""
    qa, _handoff_id, conv = _taken(rt)
    assert _labels(conv["progress"]) == EXPECTED_QA_LABELS
    assert [s["node"] for s in conv["progress"]] == QA_NODES
    assert _states(conv["progress"])["publish"] == "pending"
    detail = qa.get(f"/conversations/{conv['id']}").json()
    assert _labels(detail["progress"]) == EXPECTED_QA_LABELS


# --- PA-326 · `coverage_md` -------------------------------------------------------------------


def test_coverage_md_in_qa_review_is_the_suite_matrix(rt: Runtime) -> None:
    """PA-326: `coverage_md` = `TestSuite.coverage_md()` del artefacto en revisión."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    detail = qa.get(f"/conversations/{conv['id']}").json()
    for body in (conv, detail):
        suite = TestSuite.model_validate(body["review"]["artifact"]["content"])
        assert body["review"]["coverage_md"] == suite.coverage_md()
        assert body["review"]["coverage_md"].startswith("# Matriz de cobertura · DEMO-3")


def test_coverage_md_follows_the_edited_version(rt: Runtime) -> None:
    """PA-326: tras editar la suite, la matriz es la de la versión nueva (no la anterior)."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    content = dict(conv["review"]["artifact"]["content"])
    first = dict(content["cases"][0])
    content["cases"] = [*content["cases"], first | {"internal_id": "CP-99"}]
    edited = qa.post(
        f"/conversations/{conv['id']}/edit",
        {"content": content, "fingerprint": conv["review"]["fingerprint"]},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["review"]["version"] == 2
    assert "CP-99" in body["review"]["coverage_md"]
    assert body["review"]["coverage_md"] == TestSuite.model_validate(content).coverage_md()


def test_coverage_md_and_uncovered_are_null_in_story_review(rt: Runtime) -> None:
    """PA-326 (e): en una revisión de HU, `coverage_md` y `uncovered` están presentes y `null`."""
    af = _login(rt, AF)
    conv = _story_review(af)
    detail = af.get(f"/conversations/{conv['id']}").json()
    for body in (conv, detail):
        assert "coverage_md" in body["review"] and body["review"]["coverage_md"] is None
        assert "uncovered" in body["review"] and body["review"]["uncovered"] is None


# --- PA-326 · `uncovered` (a) QA desde Jira ---------------------------------------------------


def test_uncovered_is_empty_lists_when_everything_is_covered(rt: Runtime) -> None:
    """PA-326 (a): todo cubierto → listas vacías (no `null`)."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    assert conv["review"]["uncovered"] == {"criteria": [], "rules": []}
    detail = qa.get(f"/conversations/{conv['id']}").json()
    assert detail["review"]["uncovered"] == {"criteria": [], "rules": []}


def test_uncovered_lists_rule_without_cases_from_generated_baseline(
    rt: Runtime, llm: FakeLLMProvider
) -> None:
    """PA-326 (a): la HU de Jira estructurada tiene RN-09 sin casos → `rules == ["RN-09"]`."""
    _llm_with_extra_rule(llm)
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    assert conv["review"]["uncovered"] == {"criteria": [], "rules": ["RN-09"]}


def test_uncovered_is_computed_from_the_saved_baseline(rt: Runtime) -> None:
    """PA-326 (a): sale de la versión de partida guardada (`state_store`), leída en cada GET."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    store = _store(rt)
    artifact_id = _artifact_id(conv)
    state = store.states[artifact_id]
    baseline = UserStory.model_validate(state["baseline"])
    state["baseline"] = _with_extra(baseline, rule=True, criterion=True).model_dump(mode="json")

    detail = qa.get(f"/conversations/{conv['id']}").json()

    assert detail["review"]["uncovered"] == {"criteria": ["CA-03"], "rules": ["RN-09"]}


# --- PA-326 · `uncovered` (b) QA encadenada ---------------------------------------------------


def test_uncovered_in_chained_qa_is_empty_when_covered(rt: Runtime) -> None:
    """PA-326 (b): QA encadenada con la HU aprobada cubierta → listas vacías."""
    qa, _handoff_id, conv = _taken(rt)
    assert conv["review"]["uncovered"] == {"criteria": [], "rules": []}
    assert qa.get(f"/conversations/{conv['id']}").json()["review"]["uncovered"] == {
        "criteria": [],
        "rules": [],
    }


def test_uncovered_in_chained_qa_comes_from_the_handoff_story(
    rt: Runtime, llm: FakeLLMProvider
) -> None:
    """PA-326 (b): la HU aprobada de la entrega tiene RN-09 sin casos → `rules == ["RN-09"]`."""
    _llm_with_extra_rule(llm)
    _qa, _handoff_id, conv = _taken(rt)
    assert conv["review"]["uncovered"] == {"criteria": [], "rules": ["RN-09"]}


def test_uncovered_in_chained_qa_reads_the_story_of_its_own_handoff(rt: Runtime) -> None:
    """PA-326 (b): se calcula sobre la HU de la entrega recogida (si cambia, cambia el cálculo)
    y no sobre una versión de partida de Jira (no la hay en QA encadenada)."""
    qa, handoff_id, conv = _taken(rt)
    store = _handoffs(rt)
    handoff = store.rows[handoff_id]
    store.rows[handoff_id] = handoff.model_copy(
        update={"story": _with_extra(handoff.story, rule=True, criterion=True)}
    )
    detail = qa.get(f"/conversations/{conv['id']}").json()
    assert detail["review"]["uncovered"] == {"criteria": ["CA-03"], "rules": ["RN-09"]}
    assert (_store(rt).load(_artifact_id(conv)) or {}).get("baseline") is None


# --- PA-326 · `uncovered` (c) sin versión de partida o error al leerla ------------------------


def test_uncovered_is_null_without_saved_baseline(rt: Runtime) -> None:
    """PA-326 (c): sin versión de partida guardada → `null` («no se sabe»), no listas vacías."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    _store(rt).states[_artifact_id(conv)].pop("baseline")

    response = qa.get(f"/conversations/{conv['id']}")

    assert response.status_code == 200
    review = response.json()["review"]
    assert review["uncovered"] is None
    assert review["coverage_md"]  # la matriz no depende de la HU de origen


def test_uncovered_is_null_when_state_store_fails(
    rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-326 (c): si el `state_store` falla al leer → `null`, sin 500."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)

    def broken(_artifact_id: str) -> dict[str, Any] | None:
        raise RuntimeError("almacén ficticio caído")

    monkeypatch.setattr(_store(rt), "load", broken)
    response = qa.get(f"/conversations/{conv['id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "in_review"
    assert body["review"]["uncovered"] is None
    assert body["review"]["coverage_md"]
    assert "almacén ficticio caído" not in response.text


def test_uncovered_is_null_when_saved_baseline_is_invalid(rt: Runtime) -> None:
    """PA-326 (c): una versión de partida que no es una HU válida → `null`, sin 500."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    _store(rt).states[_artifact_id(conv)]["baseline"] = {"title": ""}

    response = qa.get(f"/conversations/{conv['id']}")

    assert response.status_code == 200
    assert response.json()["review"]["uncovered"] is None


# --- PA-326 · `uncovered` (d) entrega ajena, de otro hilo o no tomada -------------------------


@pytest.mark.parametrize(
    "tamper",
    [
        {"taken_by": "qa-ficticio-dos"},
        {"qa_thread_id": "00000000-0000-4000-8000-000000000000"},
        {"status": "pending", "taken_by": None, "qa_thread_id": None},
        None,  # la entrega ya no existe
    ],
    ids=["otra-persona", "otro-hilo", "no-tomada", "inexistente"],
)
def test_uncovered_is_null_when_handoff_is_not_this_persons(
    rt: Runtime, llm: FakeLLMProvider, tamper: dict[str, Any] | None
) -> None:
    """PA-326 (d): si la entrega no es de esta persona y este hilo → `null`; nunca la HU de
    otra entrega (que aquí tiene RN-09 sin cubrir)."""
    _llm_with_extra_rule(llm)
    qa, handoff_id, conv = _taken(rt)
    assert conv["review"]["uncovered"] == {"criteria": [], "rules": ["RN-09"]}
    store = _handoffs(rt)
    if tamper is None:
        del store.rows[handoff_id]
    else:
        store.rows[handoff_id] = store.rows[handoff_id].model_copy(update=tamper)

    response = qa.get(f"/conversations/{conv['id']}")

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["uncovered"] is None
    assert review["coverage_md"]


# --- PA-326 · sin LLM al pedir el detalle -----------------------------------------------------


def test_detail_never_calls_the_llm_in_qa_from_jira(rt: Runtime, llm: FakeLLMProvider) -> None:
    """PA-326: varios `GET` de una QA en revisión no llaman al LLM (aunque esté caído)."""
    qa = _login(rt, QA)
    conv = _qa_review(qa)
    calls = len(llm.calls)
    llm.error = RuntimeError("LLM ficticio caído")

    bodies = [qa.get(f"/conversations/{conv['id']}").json() for _ in range(3)]

    assert len(llm.calls) == calls
    assert all(b["review"]["uncovered"] == {"criteria": [], "rules": []} for b in bodies)
    assert all(b["review"]["coverage_md"] == conv["review"]["coverage_md"] for b in bodies)


def test_detail_never_calls_the_llm_in_chained_qa(rt: Runtime, llm: FakeLLMProvider) -> None:
    """PA-326: en QA encadenada, los `GET` tampoco llaman al LLM."""
    qa, _handoff_id, conv = _taken(rt)
    calls = len(llm.calls)

    for _ in range(3):
        assert qa.get(f"/conversations/{conv['id']}").json()["review"]["uncovered"] is not None

    assert len(llm.calls) == calls


# --- PA-326 / PA-327 · Ejemplos del contrato --------------------------------------------------


def test_qa_review_example_validates_and_describes_a_qa_review() -> None:
    """PA-326: `CONVERSATION_QA_REVIEW` es un `ConversationOut` válido de QA en revisión."""
    dumped = ex.CONVERSATION_QA_REVIEW.model_dump(mode="json")
    conv = ConversationOut.model_validate(dumped)
    assert (conv.flow, conv.mode, conv.state) == ("tests", "qa", "in_review")
    assert conv.review is not None
    review = conv.review
    assert review.artifact.type.value == "test_suite"
    suite = review.artifact.content
    assert isinstance(suite, TestSuite)
    assert 3 <= len(suite.cases) <= 4
    assert {i for c in suite.cases for i in c.criterion_ids} == {"CA-01", "CA-02"}
    assert {i for c in suite.cases for i in c.rule_ids} == {"RN-01", "RN-02"}
    assert any(step.get("op") == "publish_suite" for step in review.plan)
    assert HEX64.fullmatch(review.fingerprint)
    assert review.coverage_md == ex.SUITE.coverage_md()
    assert review.uncovered is not None
    assert (review.uncovered.criteria, review.uncovered.rules) == ([], [])
    assert {s.node: s.label for s in conv.progress} == EXPECTED_QA_LABELS
    assert {s.node: s.state for s in conv.progress} == {
        "load_origin": "done",
        "retrieve_context": "done",
        "generate": "done",
        "publish": "pending",
    }


def test_qa_generating_example_uses_qa_steps() -> None:
    """PA-327: `CONVERSATION_QA` (generando) lleva los pasos de QA y no `memorize`."""
    conv = ConversationOut.model_validate(ex.CONVERSATION_QA.model_dump(mode="json"))
    assert conv.mode == "qa"
    assert {s.node: s.label for s in conv.progress} == EXPECTED_QA_LABELS
    assert {s.node: s.state for s in conv.progress} == {
        "load_origin": "done",
        "retrieve_context": "running",
        "generate": "pending",
        "publish": "pending",
    }


def test_qa_steps_helper_has_the_qa_labels() -> None:
    """PA-327: `qa_steps()` produce los 4 pasos de QA con sus estados."""
    steps = ex.qa_steps("load_origin", running="generate")
    assert [s.node for s in steps] == QA_NODES
    assert [s.label for s in steps] == list(EXPECTED_QA_LABELS.values())
    assert [s.state for s in steps] == ["done", "pending", "running", "pending"]


def _openapi() -> dict[str, Any]:
    return dict(yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8")))


def test_openapi_publishes_named_qa_review_example() -> None:
    """PA-326: `components.examples.ConversationQaInReview.value` = el ejemplo de QA en revisión."""
    named = _openapi()["components"]["examples"]["ConversationQaInReview"]
    assert named["value"] == ex.dump(ex.CONVERSATION_QA_REVIEW)
    assert named["summary"]


def test_conversation_detail_example_is_still_the_story() -> None:
    """PA-326: el `example` de `GET /conversations/{conversation_id}` 200 no cambió: la HU."""
    paths = _openapi()["paths"]
    [path] = [p for p in paths if p.endswith("/conversations/{conversation_id}")]
    example = paths[path]["get"]["responses"]["200"]["content"]["application/json"]["example"]
    # El `example` de cada respuesta se publica sin los campos `null` (así lo serializa FastAPI).
    assert example == _without_none(ex.dump(ex.CONVERSATION))
    assert example["flow"] == "evolve" and example["mode"] == "functional"
    assert example["review"]["artifact"]["type"] == "user_story"
    assert all(s["node"] in STORY_NODES for s in example["progress"])
    assert example["review"].get("coverage_md") is None
    assert example["review"].get("uncovered") is None


def _without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_without_none(v) for v in value]
    return value


def test_qa_review_example_has_only_synthetic_data() -> None:
    """PA-326 / CLAUDE.md: el ejemplo no contiene emails, DNI/NIE, IBAN ni teléfonos."""
    found = {
        text: kind
        for text in _strings(ex.dump(ex.CONVERSATION_QA_REVIEW))
        if (kind := personal_data_kind(text))
    }
    assert found == {}
    assert "@" not in str(ex.dump(ex.CONVERSATION_QA_REVIEW))
