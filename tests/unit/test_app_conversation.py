"""Conversaciones de la UI sobre el grafo real (T-24 · `docs/specs/UI.md` §4.3–4.5 y §5).

`build_graph(container, memory_checkpointer())` con `tests.fakes.container.fake_container`:
arranque con `graph.stream`, pausa de `human_review`, iterar, editar a mano, respuestas
rechazadas y descartar. Nunca se escribe en Jira (principio 1), aunque el fake esté en `live`.

Solo fakes de `tests/fakes/` y datos 100 % ficticios.
"""

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from langgraph.types import Command

import app.conversation as app_conversation
from adapters.base import User
from adapters.errors import ExternalServiceError, NotFoundError, PublishError, RateLimitError
from app.conversation import (
    _ENDED,
    MEMORY_FAILED,
    PUBLISH_INCOMPLETE,
    RESTART,
    UNEXPECTED,
    Conversation,
    Workspace,
    _refresh,
    publish_permission,
    reopen,
    resume,
    run_start,
    start,
)
from app.editing import form_to_content, story_to_form
from app.origin import (
    StartRequest,
    build_initial_state,
    fix_origin,
    with_excluded,
    with_restrictions,
)
from app.progress import STEPS, phase_of
from app.qa import case_rows, qa_feedback, suite_summary
from app.review import (
    approve_answer,
    describe_operation,
    discard_answer,
    edit_answer,
    iterate_answer,
    pending_from_result,
    pending_from_state,
    summarize,
)
from core.approvals import ApprovalError
from core.container import Container
from core.conversations import NOT_YOURS, THREAD_ID
from core.graph import build_graph, memory_checkpointer
from core.permissions import Permission
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, Priority
from schemas.test_case import TestCase, TestCaseType, TestStep, TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement

AF_USER = dataset.DEMO_USERS["af-demo"][1].username
QA_USER = dataset.DEMO_USERS["qa-demo"][1].username
AF_ACTOR = dataset.DEMO_USERS["af-demo"][1]
QA_ACTOR = dataset.DEMO_USERS["qa-demo"][1]
NO_PERMISSION = "No tienes permiso para realizar esta acción."
EVOLVE_TEXT = "DEMO-3: permitir renovar desde la app (texto ficticio)"
EVOLVE_CHANGE = "permitir renovar desde la app (texto ficticio)"  # EVOLVE_TEXT sin la clave
NEED_TEXT = "Avisar por correo tres días antes del vencimiento del préstamo (ficticio)."
RESTRICTIONS = "Mismas reglas que en la web ficticia."
EDITED_TITLE = "Renovar un préstamo editado a mano (ficticio)"
STREAMED_NODES = [step.node for step in STEPS]
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


# --- utilidades --------------------------------------------------------------------------------


def _workspace(tmp_path: Path, **overrides: object) -> Workspace:
    container = fake_container(tmp_path, **overrides)
    return Workspace(container=container, graph=build_graph(container, memory_checkpointer()))


def _evolve() -> StartRequest:
    return fix_origin("evolve", "DEMO", key="DEMO-3", text=EVOLVE_TEXT)


def _started(ws: Workspace, request: StartRequest, user: str = AF_USER) -> Conversation:
    conv = Conversation(request=request, user=user)
    assert run_start(ws, conv) == STREAMED_NODES
    assert conv.error is None, conv.error
    assert conv.view is not None
    return conv


def _values(ws: Workspace, conv: Conversation) -> dict[str, Any]:
    return dict(ws.graph.get_state(conv.config).values)


def _story(conv: Conversation) -> UserStory:
    assert conv.view is not None
    story = conv.view.artifact.content
    assert isinstance(story, UserStory)
    return story


def _edited(conv: Conversation, title: str = EDITED_TITLE) -> dict[str, Any]:
    story = _story(conv)
    form = story_to_form(story)
    form["title"] = title
    return form_to_content(story, form)


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _testmgmt(container: Container) -> FakeTestManagement:
    assert isinstance(container.test_management, FakeTestManagement)
    return container.test_management


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _assert_nothing_written(container: Container) -> None:
    assert _tracker(container).writes == []
    assert _testmgmt(container).publish_calls == 0


# --- Conversación sin grafo --------------------------------------------------------------------


def test_conversation_title_is_first_line_of_text_truncated() -> None:
    """UI.md §2: la lista de conversaciones muestra la primera línea del texto (60 car.)."""
    long_text = "Necesidad ficticia " * 6 + "\nsegunda línea"
    conv = Conversation(request=fix_origin("need", "DEMO", text=long_text), user=AF_USER)
    assert conv.title == long_text.strip().splitlines()[0][:60]
    assert len(conv.title) == 60


def test_conversation_title_without_text_is_the_operation() -> None:
    """UI.md §4.3: sin texto, el título es la operación fijada."""
    conv = Conversation(request=fix_origin("evolve", "DEMO", key="DEMO-3"), user=AF_USER)
    assert conv.title == "Evolucionar DEMO-3"


def test_conversations_have_their_own_thread_id() -> None:
    """PROMPT-06 §1: un `thread_id` por conversación."""
    first = Conversation(request=_evolve(), user=AF_USER)
    second = Conversation(request=_evolve(), user=AF_USER)
    assert first.thread_id != second.thread_id
    # T-52: la config lleva quién actúa; la app rechaza la que no lo trae.
    assert first.config == {"configurable": {"thread_id": first.thread_id, "user": AF_USER}}


def test_conversation_runs_against_container_that_requires_actor(tmp_path: Path) -> None:
    """Integración con T-52: el contenedor de la app (`require_actor`) acepta la config de la UI."""
    container = fake_container(tmp_path, require_actor=True)
    ws = Workspace(container=container, graph=build_graph(container, memory_checkpointer()))
    conv = Conversation(request=_evolve(), user=AF_USER)
    nodes = run_start(ws, conv)
    assert conv.error is None and conv.view is not None
    assert "generate" in nodes


def test_resume_without_view_sets_error(tmp_path: Path) -> None:
    """UI.md §5 (error): no se reanuda una conversación que no tiene propuesta en revisión."""
    ws = _workspace(tmp_path)
    conv = Conversation(request=_evolve(), user=AF_USER)
    resume(ws, conv, iterate_answer("Cambio ficticio"))
    assert conv.error == "No hay ninguna propuesta en revisión."
    _assert_nothing_written(ws.container)


# --- Mixta 2b · Arranque (UI.md §4.4) ----------------------------------------------------------


def test_run_start_pauses_with_version_1_fingerprint_and_plan(tmp_path: Path) -> None:
    """UI.md §4.4 y §5.1: arranque → pausa con versión 1, huella y plan de la evolución."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    view = conv.view
    assert view is not None
    assert view.version == 1
    assert HEX_64.fullmatch(view.fingerprint)
    assert view.plan[0] == {"op": "update_story", "project": "DEMO", "key": "DEMO-3"}
    assert view.error is None
    assert "edit" in view.decisions
    assert view.target
    assert view.artifact.status is ArtifactStatus.IN_REVIEW
    assert phase_of(view.artifact.status) == 2
    assert conv.versions == [view]
    assert conv.finished is None
    assert ws.conversations == [conv]
    assert summarize(view).startswith("Versión 1 lista")
    _assert_nothing_written(ws.container)


def test_start_yields_each_node_as_it_finishes(tmp_path: Path) -> None:
    """UI.md §4.4 · PA-66: `start` devuelve los nodos de `graph.stream` uno a uno."""
    ws = _workspace(tmp_path)
    conv = Conversation(request=_evolve(), user=AF_USER)
    progress = start(ws, conv)
    assert next(progress) == "load_origin"
    assert conv in ws.conversations  # la conversación aparece en la lista desde el principio
    assert conv.view is None
    assert list(progress) == ["retrieve_context", "generate"]
    assert conv.view is not None


def test_start_need_puts_restrictions_in_origin_text(tmp_path: Path) -> None:
    """UI.md §4.3: necesidad nueva → restricciones en `origin.text`, sin feedback previo."""
    ws = _workspace(tmp_path)
    request = with_restrictions(fix_origin("need", "DEMO", text=NEED_TEXT), RESTRICTIONS)
    conv = _started(ws, request)
    values = _values(ws, conv)
    assert values["origin"]["text"] == f"{NEED_TEXT}\n\nRestricciones: {RESTRICTIONS}"
    assert values["feedback"] == []
    assert conv.view is not None
    assert conv.view.plan[0] == {"op": "create_story", "project": "DEMO", "epic": ""}


def test_start_evolution_sends_restrictions_as_feedback(tmp_path: Path) -> None:
    """UI.md §4.3 · T-51: evolución → lo pedido y las restricciones van como feedback."""
    ws = _workspace(tmp_path)
    conv = _started(ws, with_restrictions(_evolve(), RESTRICTIONS))
    values = _values(ws, conv)
    assert values["feedback"] == [EVOLVE_CHANGE, RESTRICTIONS]
    assert all("DEMO-3" not in item for item in values["feedback"])
    assert values["origin"] == {"kind": "story", "key": "DEMO-3", "project": "DEMO"}


def test_start_passes_excluded_sources_to_the_graph(tmp_path: Path) -> None:
    """T-51 · RF-21: las fuentes desmarcadas llegan al estado y la propuesta no las cita."""
    ws = _workspace(tmp_path)
    conv = _started(ws, with_excluded(_evolve(), ["doc-glosario"]))
    assert _values(ws, conv)["excluded_sources"] == ["doc-glosario"]
    assert all(source.ref != "doc-glosario" for source in _story(conv).sources)


def test_start_with_excluded_origin_shows_error_without_exception(tmp_path: Path) -> None:
    """T-51 (error): excluir la HU de origen deja el mensaje en `conv.error`, sin excepción."""
    ws = _workspace(tmp_path)
    conv = Conversation(request=with_excluded(_evolve(), ["DEMO-3"]), user=AF_USER)
    assert run_start(ws, conv) == []
    assert conv.error is not None
    assert "no se puede excluir" in conv.error
    assert conv.view is None
    assert conv.versions == []


def test_start_with_unknown_issue_of_other_project_shows_jira_error(tmp_path: Path) -> None:
    """T-50 (error): una clave de otro proyecto que no existe → mensaje de Jira en la UI."""
    ws = _workspace(tmp_path)
    request = fix_origin("evolve", "DEMO", key="OTRO-7", text="Evolucionar OTRO-7 (ficticio)")
    assert request.project == "OTRO"
    conv = Conversation(request=request, user=AF_USER)
    assert run_start(ws, conv) == []
    assert conv.error == "La incidencia OTRO-7 no existe."
    assert conv.view is None


def test_start_llm_rate_limit_shows_its_message(tmp_path: Path) -> None:
    """RNF · UI.md §7 (error): un `AgentError` del modelo se muestra con su mensaje."""
    message = "Límite de uso ficticio alcanzado; prueba con otro modelo."
    ws = _workspace(tmp_path, llm=FakeLLMProvider(error=RateLimitError(message, service="fake")))
    conv = Conversation(request=_evolve(), user=AF_USER)
    assert run_start(ws, conv) == ["load_origin", "retrieve_context"]
    assert conv.error == message
    assert conv.view is None
    _assert_nothing_written(ws.container)


def test_start_unexpected_error_shows_generic_message(tmp_path: Path) -> None:
    """UI.md §7 (seguridad): un error inesperado no expone su detalle interno."""
    ws = _workspace(tmp_path, llm=FakeLLMProvider(error=RuntimeError("detalle interno ficticio")))
    conv = Conversation(request=_evolve(), user=AF_USER)
    run_start(ws, conv)
    assert conv.error == UNEXPECTED
    assert conv.view is None


# --- Pausa: resultado de invoke y estado del hilo (UI.md §5.1) ---------------------------------


def test_pending_from_result_and_from_state_return_the_same_view(tmp_path: Path) -> None:
    """UI.md §5.1: `__interrupt__` de `invoke` y `get_state().tasks` dan la misma pausa."""
    container = fake_container(tmp_path)
    graph = build_graph(container, memory_checkpointer())
    config = {"configurable": {"thread_id": "hilo-ficticio-1"}}

    result = graph.invoke(build_initial_state(AF_USER, _evolve()), config)
    from_result = pending_from_result(result)
    assert from_result is not None
    assert from_result == pending_from_state(graph.get_state(config))

    rejected = graph.invoke(Command(resume={"decision": "publicar-ficticio"}), config)
    after_rejection = pending_from_result(rejected)
    assert after_rejection is not None
    assert after_rejection.error
    assert after_rejection == pending_from_state(graph.get_state(config))
    assert after_rejection.fingerprint == from_result.fingerprint

    final = graph.invoke(Command(resume=discard_answer()), config)
    assert pending_from_result(final) is None
    assert pending_from_state(graph.get_state(config)) is None


# --- Mixta 3 · Iterar, editar, rechazos y descartar (UI.md §4.5 y §5.3) ------------------------


def test_resume_iterate_adds_version_2(tmp_path: Path) -> None:
    """RF-20 · UI.md §4.5: iterar → versión 2 con huella nueva; la v1 queda en el historial."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    first = conv.view
    assert first is not None

    resume(ws, conv, iterate_answer("Añade un criterio de error ficticio"))

    assert conv.error is None
    assert conv.view is not None
    assert conv.view.version == 2
    assert conv.view.error is None
    assert conv.view.fingerprint != first.fingerprint
    assert [v.version for v in conv.versions] == [1, 2]
    assert conv.versions[0] == first
    assert _values(ws, conv)["feedback"] == [EVOLVE_CHANGE, "Añade un criterio de error ficticio"]
    _assert_nothing_written(ws.container)


def test_resume_edit_creates_new_version_with_new_fingerprint(tmp_path: Path) -> None:
    """RF-32 · UI.md §5.3: editar a mano → versión nueva, huella nueva y sin llamar al modelo."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    first = conv.view
    assert first is not None
    original = _story(conv)
    calls = len(_llm(ws.container).calls)

    resume(ws, conv, edit_answer(first, _edited(conv)))

    assert conv.error is None
    view = conv.view
    assert view is not None
    assert view.error is None
    assert view.version == 2
    assert view.fingerprint != first.fingerprint
    assert HEX_64.fullmatch(view.fingerprint)
    edited = _story(conv)
    assert edited.title == EDITED_TITLE
    assert (edited.jira_key, edited.internal_id) == (original.jira_key, original.internal_id)
    assert len(_llm(ws.container).calls) == calls
    assert [v.version for v in conv.versions] == [1, 2]
    _assert_nothing_written(ws.container)


def test_resume_edit_after_iterate_uses_latest_fingerprint(tmp_path: Path) -> None:
    """UI.md §5.4: la UI devuelve la huella del último payload (v2), no la de la v1."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    resume(ws, conv, iterate_answer("Cambio ficticio previo"))
    assert conv.view is not None and conv.view.version == 2

    resume(ws, conv, edit_answer(conv.view, _edited(conv)))

    assert conv.view is not None
    assert conv.view.error is None
    assert conv.view.version == 3
    assert _story(conv).title == EDITED_TITLE


def test_resume_edit_with_fake_fingerprint_is_rejected_without_exception(tmp_path: Path) -> None:
    """UI.md §5.3: una edición con huella falsa vuelve a pausar con `error`, sin excepción."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    first = conv.view
    assert first is not None
    answer = {"decision": "edit", "content": _edited(conv), "fingerprint": "0" * 64}

    resume(ws, conv, answer)

    assert conv.error is None
    assert conv.finished is None
    view = conv.view
    assert view is not None
    assert view.error is not None
    assert "no parte de la versión revisada" in view.error
    assert view.version == 1
    assert view.fingerprint == first.fingerprint
    assert len(conv.versions) == 1  # misma versión: se sustituye, no se duplica
    assert conv.versions[0].error == view.error
    _assert_nothing_written(ws.container)


def test_resume_invalid_decision_is_rejected_with_message(tmp_path: Path) -> None:
    """UI.md §5.3: una decisión no válida vuelve con el motivo en español."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())

    resume(ws, conv, {"decision": "publicar-ficticio"})

    assert conv.error is None
    assert conv.view is not None
    assert conv.view.error is not None
    assert "Decisión no válida" in conv.view.error


def test_resume_valid_answer_after_rejection_continues(tmp_path: Path) -> None:
    """UI.md §5.3: tras un rechazo la revisión sigue abierta y admite una respuesta válida."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    resume(ws, conv, {"decision": "edit", "content": _edited(conv), "fingerprint": "0" * 64})
    assert conv.view is not None and conv.view.error

    resume(ws, conv, iterate_answer("Cambio ficticio tras el rechazo"))

    assert conv.error is None
    assert conv.view is not None
    assert conv.view.error is None
    assert conv.view.version == 2
    assert [v.version for v in conv.versions] == [1, 2]


def test_resume_discard_finishes_and_later_resume_sets_error(tmp_path: Path) -> None:
    """UI.md §5.3: descartar termina la conversación; reanudar después deja `conv.error`."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())

    resume(ws, conv, discard_answer())

    assert conv.error is None
    assert conv.finished == "Has descartado la propuesta. Nada se ha escrito en Jira."
    assert conv.view is None
    assert _values(ws, conv)["artifact"].status is ArtifactStatus.DISCARDED
    assert [v.version for v in conv.versions] == [1]

    resume(ws, conv, iterate_answer("Cambio ficticio tardío"))

    assert conv.error == "No hay ninguna propuesta en revisión."
    assert [v.version for v in conv.versions] == [1]
    _assert_nothing_written(ws.container)


def test_resume_llm_error_while_iterating_closes_the_conversation(tmp_path: Path) -> None:
    """UI.md §5.3 y §7 (error): si el modelo falla al iterar, se muestra el mensaje y se cierra."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    message = "Límite de uso ficticio alcanzado."
    _llm(ws.container).error = RateLimitError(message, service="fake")

    resume(ws, conv, iterate_answer("Cambio ficticio"))

    assert conv.error == message
    assert conv.finished == RESTART
    assert conv.view is None  # ya no hay revisión pendiente: no se ofrece la pausa anterior
    assert conv.versions[-1].version == 1  # las versiones anteriores se conservan
    assert [v.version for v in conv.versions] == [1]
    _assert_nothing_written(ws.container)


def test_whole_conversation_never_writes_to_jira(tmp_path: Path) -> None:
    """Principio 1 · UI.md §5.7: iterar, editar, rechazar y descartar nunca escriben en Jira."""
    ws = _workspace(tmp_path, publish_mode="live")
    conv = _started(ws, with_restrictions(_evolve(), RESTRICTIONS))
    resume(ws, conv, iterate_answer("Cambio ficticio"))
    assert conv.view is not None
    resume(ws, conv, edit_answer(conv.view, _edited(conv)))
    resume(ws, conv, {"decision": "approve", "fingerprint": "f" * 64}, AF_ACTOR)  # huella falsa
    assert conv.view is not None and conv.view.error
    resume(ws, conv, discard_answer())

    assert conv.finished
    assert [v.version for v in conv.versions] == [1, 2, 3]
    _assert_nothing_written(ws.container)


# --- Plan de operaciones mostrado (UI.md §5.2, RF-31) ------------------------------------------


def test_plan_of_evolution_is_described(tmp_path: Path) -> None:
    """RF-31: el plan real de la evolución se describe operación a operación."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    assert conv.view is not None
    plan = conv.view.plan
    assert describe_operation(plan[0]) == "Actualizar DEMO-3 con la versión revisada"
    assert describe_operation(plan[1]) == "Añadir a DEMO-3 un comentario con los cambios"  # PA-319
    for op in plan:
        assert describe_operation(op) != op["op"]  # todas las operaciones son conocidas
    for op in plan[2:]:
        assert op["op"] == "link"
        assert describe_operation(op) == f"Vincular DEMO-3 con {op['to']} (relates to)"


def test_plan_of_epic_origin_creates_story_in_epic(tmp_path: Path) -> None:
    """RF-31 · PA-38: desde una épica se crea la HU en ella y nunca se vincula a la épica."""
    ws = _workspace(tmp_path)
    conv = _started(ws, fix_origin("need", "DEMO", key="DEMO-1", kind="epic"))
    assert conv.view is not None
    plan = conv.view.plan
    assert plan[0] == {"op": "create_story", "project": "DEMO", "epic": "DEMO-1"}
    assert describe_operation(plan[0]) == "Crear una HU nueva en la épica DEMO-1"
    assert all(op["to"] != "DEMO-1" for op in plan if op["op"] == "link")


def test_plan_of_need_creates_story_in_project(tmp_path: Path) -> None:
    """RF-31: una necesidad nueva crea la HU en el proyecto de la conversación."""
    ws = _workspace(tmp_path)
    conv = _started(ws, fix_origin("need", "DEMO", text=NEED_TEXT))
    assert conv.view is not None
    assert describe_operation(conv.view.plan[0]) == "Crear una HU nueva en el proyecto DEMO"


def test_plan_of_tests_flow_publishes_suite(tmp_path: Path) -> None:
    """RF-31 · UI.md §6: el modo QA muestra `publish_suite` con el número de casos."""
    ws = _workspace(tmp_path)
    conv = _started(
        ws, fix_origin("tests", "DEMO", key="DEMO-3", text="Casos de DEMO-3"), user=QA_USER
    )
    assert conv.view is not None
    assert conv.view.plan == [
        {"op": "publish_suite", "project": "DEMO", "story": "DEMO-3", "cases": "2"}
    ]
    assert describe_operation(conv.view.plan[0]) == "Publicar 2 casos de prueba en DEMO-3"
    _assert_nothing_written(ws.container)


@pytest.mark.parametrize("flow", ["need", "evolve"])
def test_versions_list_has_one_entry_per_version(tmp_path: Path, flow: str) -> None:
    """UI.md §4.5: panel de versiones v1, v2… una por versión generada."""
    ws = _workspace(tmp_path)
    request = fix_origin("need", "DEMO", text=NEED_TEXT) if flow == "need" else _evolve()
    conv = _started(ws, request)
    resume(ws, conv, iterate_answer("Primer cambio ficticio"))
    resume(ws, conv, iterate_answer("Segundo cambio ficticio"))
    assert [v.version for v in conv.versions] == [1, 2, 3]
    assert len({v.fingerprint for v in conv.versions}) == 3


# --- Permisos antes de ejecutar (UI.md §3: `require`) ------------------------------------------


class _SpyGraph:
    """Envuelve el grafo y registra `invoke`/`stream` para comprobar que no se llaman."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph
        self.calls: list[str] = []

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("invoke")
        return self._graph.invoke(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("stream")
        return self._graph.stream(*args, **kwargs)

    def get_state(self, *args: Any, **kwargs: Any) -> Any:
        return self._graph.get_state(*args, **kwargs)


def test_run_start_with_owner_actor_works(tmp_path: Path) -> None:
    """UI.md §3: con el permiso del flujo y siendo la dueña, la conversación arranca."""
    ws = _workspace(tmp_path)
    conv = Conversation(request=_evolve(), user=AF_USER)
    assert run_start(ws, conv, actor=AF_ACTOR) == STREAMED_NODES
    assert conv.error is None
    assert conv.started is True
    assert conv.view is not None and conv.view.version == 1


def test_run_start_with_actor_without_permission_does_not_call_the_graph(tmp_path: Path) -> None:
    """UI.md §3 (error): `require` antes de ejecutar; sin permiso no se llama al grafo ni al LLM."""
    ws = _workspace(tmp_path)
    spy = _SpyGraph(ws.graph)
    ws.graph = spy  # type: ignore[assignment]
    conv = Conversation(request=_evolve(), user=AF_USER)

    assert run_start(ws, conv, actor=QA_ACTOR) == []

    assert conv.error == NO_PERMISSION
    assert conv.view is None
    assert conv.started is True
    assert conv not in ws.conversations  # rechazada: no aparece en la barra lateral
    assert spy.calls == []
    assert _llm(ws.container).calls == []
    _assert_nothing_written(ws.container)


def test_run_start_by_other_person_shows_error(tmp_path: Path) -> None:
    """Seguridad (error): otra persona con el mismo rol no arranca una conversación ajena."""
    ws = _workspace(tmp_path)
    conv = Conversation(request=_evolve(), user=AF_USER)
    other = AF_ACTOR.model_copy(update={"username": "af-otra-demo"})
    assert run_start(ws, conv, actor=other) == []
    assert conv.error == "Esta conversación es de otra persona."
    assert _llm(ws.container).calls == []


def test_resume_with_actor_without_permission_does_not_call_the_graph(tmp_path: Path) -> None:
    """UI.md §3 (error): reanudar sin permiso deja el error, la misma versión y no invoca."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    before = _values(ws, conv)["feedback"]
    calls = len(_llm(ws.container).calls)
    spy = _SpyGraph(ws.graph)
    ws.graph = spy  # type: ignore[assignment]

    resume(ws, conv, iterate_answer("Cambio ficticio no autorizado"), actor=QA_ACTOR)

    assert conv.error == NO_PERMISSION
    assert conv.finished is None
    assert conv.view is not None and conv.view.version == 1
    assert [v.version for v in conv.versions] == [1]
    assert spy.calls == []
    assert len(_llm(ws.container).calls) == calls
    assert _values(ws, conv)["feedback"] == before
    _assert_nothing_written(ws.container)


def test_resume_with_owner_actor_continues(tmp_path: Path) -> None:
    """UI.md §3: la dueña con permiso puede iterar."""
    ws = _workspace(tmp_path)
    conv = _started(ws, _evolve())
    resume(ws, conv, iterate_answer("Cambio ficticio autorizado"), actor=AF_ACTOR)
    assert conv.error is None
    assert conv.view is not None and conv.view.version == 2


# --- Config de la conversación (T-52) ----------------------------------------------------------


def test_conversation_config_thread_id_is_server_generated_and_safe() -> None:
    """T-52 · UI.md §2: `thread_id` generado por el servidor con formato seguro y su dueña."""
    first = Conversation(request=_evolve(), user=AF_USER)
    second = Conversation(request=_evolve(), user=AF_USER)
    for conv in (first, second):
        assert THREAD_ID.fullmatch(conv.thread_id)
        assert conv.config["configurable"]["user"] == AF_USER
        assert conv.thread_id == conv.config["configurable"]["thread_id"]
    assert first.thread_id != second.thread_id


def test_conversation_keeps_explicit_config() -> None:
    """T-52: con `config=` explícito (p. ej. `resume_config`) se respeta tal cual."""
    config = {"configurable": {"thread_id": "hilo-ficticio-7", "user": AF_USER}}
    conv = Conversation(request=_evolve(), user=AF_USER, config=config)
    assert conv.config is config
    assert conv.thread_id == "hilo-ficticio-7"


# --- Retomar una conversación (reopen, T-52 · UI.md §2) ----------------------------------------


def _shared(tmp_path: Path, **overrides: object) -> tuple[Workspace, Any]:
    """Workspace de la app (`require_actor`) y su checkpointer, para abrir otro «proceso»."""
    container = fake_container(tmp_path, require_actor=True, **overrides)
    checkpointer = memory_checkpointer()
    return Workspace(container, build_graph(container, checkpointer)), checkpointer


def _fresh(ws: Workspace, checkpointer: Any) -> Workspace:
    """Otra sesión: mismo contenedor y checkpointer, grafo nuevo y sin conversaciones abiertas."""
    return Workspace(ws.container, build_graph(ws.container, checkpointer), conversations=[])


def _started_by(ws: Workspace, request: StartRequest, actor: Any) -> Conversation:
    conv = Conversation(request=request, user=actor.username)
    assert run_start(ws, conv, actor) == STREAMED_NODES
    assert conv.error is None, conv.error
    assert conv.view is not None
    return conv


def test_reopen_own_conversation_from_new_workspace(tmp_path: Path) -> None:
    """T-52 · UI.md §2: retomar en otra sesión → misma pausa, v1 y v2, request y chat rehechos."""
    ws, checkpointer = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, iterate_answer("Añade un CA de error ficticio"), AF_ACTOR)
    assert conv.view is not None and conv.view.version == 2

    other = _fresh(ws, checkpointer)
    reopened = reopen(other, AF_ACTOR, conv.thread_id)

    assert reopened is not conv
    assert reopened.view is not None
    assert reopened.view.version == conv.view.version
    assert reopened.view.fingerprint == conv.view.fingerprint
    assert [v.version for v in reopened.versions] == [1, 2]
    assert [v.fingerprint for v in reopened.versions] == [v.fingerprint for v in conv.versions]
    request = reopened.request
    assert (request.flow, request.kind, request.key, request.project) == (
        "evolve",
        "story",
        "DEMO-3",
        "DEMO",
    )
    assert reopened.messages[:-1] == [
        ("user", EVOLVE_CHANGE),
        ("user", "Añade un CA de error ficticio"),
    ]
    role, text = reopened.messages[-1]
    assert role == "assistant" and text.startswith("Conversación retomada.")
    assert reopened.started is True and reopened.finished is None
    assert reopened.thread_id == conv.thread_id
    assert other.conversations == [reopened]
    _assert_nothing_written(ws.container)


def test_reopen_then_iterate_with_resume(tmp_path: Path) -> None:
    """T-52: una conversación retomada sigue iterando con `resume` (v3)."""
    ws, checkpointer = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    other = _fresh(ws, checkpointer)
    reopened = reopen(other, AF_ACTOR, conv.thread_id)

    resume(other, reopened, iterate_answer("Cambio ficticio tras retomar"), AF_ACTOR)

    assert reopened.error is None
    assert reopened.view is not None and reopened.view.version == 2
    assert [v.version for v in reopened.versions] == [1, 2]


def test_reopen_then_approve_in_simulation_uses_last_fingerprint(tmp_path: Path) -> None:
    """T-52 · UI.md §5.4: aprobar tras retomar con la huella del último payload (simulación)."""
    ws, checkpointer = _shared(tmp_path, publish_mode="simulation")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, iterate_answer("Cambio ficticio"), AF_ACTOR)
    other = _fresh(ws, checkpointer)
    reopened = reopen(other, AF_ACTOR, conv.thread_id)
    assert reopened.view is not None

    resume(
        other,
        reopened,
        {"decision": "approve", "fingerprint": reopened.view.fingerprint},
        AF_ACTOR,
    )

    assert reopened.error is None
    assert reopened.view is None
    assert reopened.status == "simulated"
    assert reopened.finished == _ENDED["simulated"]
    assert reopened.finished.startswith("Publicación simulada")
    _assert_nothing_written(ws.container)


def test_reopen_qa_conversation_is_tests_flow(tmp_path: Path) -> None:
    """T-52 · UI.md §6.1: una conversación de QA se retoma como «Preparar pruebas»."""
    ws, checkpointer = _shared(tmp_path)
    conv = _started_by(ws, fix_origin("tests", "DEMO", key="DEMO-3"), QA_ACTOR)
    reopened = reopen(_fresh(ws, checkpointer), QA_ACTOR, conv.thread_id)
    assert (reopened.request.flow, reopened.request.kind, reopened.request.key) == (
        "tests",
        "story",
        "DEMO-3",
    )
    assert reopened.request.mode == "qa"
    assert reopened.view is not None


def test_reopen_need_conversation_keeps_its_text(tmp_path: Path) -> None:
    """T-52: una necesidad nueva se retoma con su texto (`origin.text`)."""
    ws, checkpointer = _shared(tmp_path)
    conv = _started_by(ws, fix_origin("need", "DEMO", text=NEED_TEXT), AF_ACTOR)
    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)
    assert (reopened.request.flow, reopened.request.kind) == ("need", "need")
    assert reopened.request.text == NEED_TEXT
    assert reopened.title == conv.title


def test_reopen_after_rejected_answer_shows_error_and_keeps_pause(tmp_path: Path) -> None:
    """T-52 · UI.md §5.3: tras una respuesta rechazada, al retomar se ve el error y la pausa."""
    ws, checkpointer = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, {"decision": "approve", "fingerprint": "0" * 64}, AF_ACTOR)
    assert conv.view is not None and conv.view.error

    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)

    assert reopened.view is not None
    assert reopened.view.error == conv.view.error
    assert reopened.view.version == 1
    assert reopened.finished is None
    assert [v.version for v in reopened.versions] == [1]
    _assert_nothing_written(ws.container)


@pytest.mark.parametrize(
    "thread_id",
    ["hilo-inexistente-ficticio", "../x", "", "a" * 65],
    ids=["inexistente", "ruta", "vacio", "largo"],
)
def test_reopen_unknown_or_invalid_thread_raises_not_found(tmp_path: Path, thread_id: str) -> None:
    """T-52 (seguridad): hilo inexistente o con formato no válido → «No existe esa…»."""
    ws, _ = _shared(tmp_path)
    with pytest.raises(NotFoundError, match=NOT_YOURS):
        reopen(ws, AF_ACTOR, thread_id)
    assert ws.conversations == []


def test_reopen_conversation_of_other_person_raises_not_found(tmp_path: Path) -> None:
    """T-52 (seguridad): nadie retoma la conversación de otra persona (mismo mensaje)."""
    ws, checkpointer = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    other = User(username="af-otra-demo", role="functional")
    fresh = _fresh(ws, checkpointer)
    with pytest.raises(NotFoundError, match=NOT_YOURS):
        reopen(fresh, other, conv.thread_id)
    assert fresh.conversations == []
    # Tampoco si la conversación ya está abierta en esa sesión.
    with pytest.raises(NotFoundError, match=NOT_YOURS):
        reopen(ws, other, conv.thread_id)


def test_reopen_already_open_returns_same_object(tmp_path: Path) -> None:
    """T-52: si ya está abierta en la sesión, se devuelve la misma (con su chat)."""
    ws, _ = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    conv.messages.append(("assistant", "Mensaje ficticio que solo vive en la sesión"))
    assert reopen(ws, AF_ACTOR, conv.thread_id) is conv
    assert ws.conversations == [conv]


def test_reopen_discarded_conversation_is_finished(tmp_path: Path) -> None:
    """T-52 · UI.md §5.3: una conversación descartada se retoma terminada, con sus versiones."""
    ws, checkpointer = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, discard_answer(), AF_ACTOR)

    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)

    assert reopened.view is None
    assert reopened.status == "discarded"
    assert reopened.finished == _ENDED["discarded"]
    assert [v.version for v in reopened.versions] == [1]
    assert not any(role == "assistant" for role, _ in reopened.messages)


def test_reopen_simulated_conversation_is_finished(tmp_path: Path) -> None:
    """T-52 · T-25: tras aprobar en simulación, retomar → terminada con «Publicación simulada…»."""
    ws, checkpointer = _shared(tmp_path, publish_mode="simulation")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, iterate_answer("Cambio ficticio"), AF_ACTOR)
    assert conv.view is not None
    resume(ws, conv, {"decision": "approve", "fingerprint": conv.view.fingerprint}, AF_ACTOR)

    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)

    assert reopened.view is None
    assert reopened.status == ws.container.conversations.get(conv.thread_id).status
    assert reopened.status == "simulated"
    assert reopened.finished == _ENDED["simulated"]
    assert [v.version for v in reopened.versions] == [1, 2]
    _assert_nothing_written(ws.container)


def test_refresh_after_simulated_approval_sets_status_and_finished(tmp_path: Path) -> None:
    """T-52 · T-25: `_refresh` tras aprobar en simulación deja `status` y el texto de fin."""
    ws, _ = _shared(tmp_path, publish_mode="simulation")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    assert conv.view is not None
    ws.graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": conv.view.fingerprint}), conv.config
    )

    _refresh(ws, conv)

    assert conv.view is None
    assert conv.status == "simulated"
    assert conv.finished == "Publicación simulada: no se ha escrito nada en Jira."
    _assert_nothing_written(ws.container)


# --- T-31 · Recibo, aprobación y resultado (UI.md §4.6, §4.7, §5, §6.4, §6.5) ---------------

MEMORY_FAILURE = "El generador de memoria ficticio no responde."
LEDGER_FAILURE = "El registro de aprobaciones ficticio no está disponible."


class _FailingMemoryGenerator:
    """MemoryGenerator que falla siempre (PA-251): la HU ya está publicada cuando se llama."""

    def generate(self, artifact: Artifact) -> Any:
        raise ExternalServiceError(MEMORY_FAILURE, service="llm")


def _approved(ws: Workspace, conv: Conversation, actor: User) -> None:
    assert conv.view is not None
    resume(ws, conv, approve_answer(conv.view), actor)


def test_real_payload_target_is_readable_text(tmp_path: Path) -> None:
    """UI.md §4.6 · T-31: el `target` del payload real de `human_review` se lee como texto."""
    ws, _ = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    assert conv.view is not None
    assert "{" not in conv.view.target
    assert "DEMO-3" in conv.view.target
    assert "proyecto DEMO" in conv.view.target
    assert conv.view.target_info is not None
    assert conv.view.target_info["jira_key"] == "DEMO-3"


def test_approve_answer_after_iterate_uses_last_fingerprint(tmp_path: Path) -> None:
    """UI.md §5.4: tras iterar, `approve_answer` lleva la huella de la última pausa."""
    ws, _ = _shared(tmp_path, publish_mode="simulation")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, iterate_answer("Cambio ficticio antes de aprobar"), AF_ACTOR)
    assert conv.view is not None and conv.view.version == 2
    first, last = conv.versions[0], conv.versions[-1]
    answer = approve_answer(conv.view)
    assert answer["fingerprint"] == last.fingerprint
    assert answer["fingerprint"] != first.fingerprint


def test_approve_with_previous_fingerprint_is_rejected(tmp_path: Path) -> None:
    """UI.md §5.4 (negativa): la huella de una versión anterior ya no vale tras iterar."""
    ws, _ = _shared(tmp_path, publish_mode="simulation")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, iterate_answer("Cambio ficticio"), AF_ACTOR)
    resume(ws, conv, approve_answer(conv.versions[0]), AF_ACTOR)
    assert conv.outcome is None
    assert conv.view is not None and conv.view.error
    assert conv.view.version == 2
    _assert_nothing_written(ws.container)


def test_approve_in_simulation_gives_simulated_outcome(tmp_path: Path) -> None:
    """UI.md §4.7 (simulación) · T-25: resultado simulado y nada escrito en Jira."""
    ws, _ = _shared(tmp_path, publish_mode="simulation")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)
    assert conv.error is None
    assert conv.outcome is not None
    assert conv.outcome.kind == "simulated"
    assert conv.outcome.approved_by == AF_USER
    assert conv.outcome.operations == [
        "Actualizar DEMO-3 con la versión revisada",
        "Añadir a DEMO-3 un comentario con los cambios",  # PA-319
    ]
    assert conv.view is None
    assert conv.finished == _ENDED["simulated"]
    assert conv.status == "simulated"
    assert conv.can_restart is False
    _assert_nothing_written(ws.container)


def test_approve_in_live_gives_published_outcome(tmp_path: Path) -> None:
    """UI.md §4.7 (real) · RF-31: publicado con la clave y la escritura en el fake de Jira."""
    ws, _ = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)
    assert conv.error is None
    assert conv.outcome is not None
    assert conv.outcome.kind == "published"
    assert "DEMO-3" in conv.outcome.published_keys
    assert conv.outcome.errors == []
    assert conv.status == "published"
    assert conv.view is None
    assert conv.finished == "Publicado en Jira."
    assert ("update_story", {"key": "DEMO-3"}) in _tracker(ws.container).writes


def test_approve_qa_suite_in_live_with_failed_case_is_partial(tmp_path: Path) -> None:
    """UI.md §6.5 · RNF-13: un caso que falla → «en parte» con «No se pudo publicar CP-02.»."""
    testmgmt = FakeTestManagement(fail_case_ids={"CP-02"})
    ws, _ = _shared(tmp_path, publish_mode="live", test_management=testmgmt)
    conv = _started_by(ws, fix_origin("tests", "DEMO", key="DEMO-3"), QA_ACTOR)
    _approved(ws, conv, QA_ACTOR)
    assert conv.error is None
    assert conv.outcome is not None
    assert conv.outcome.kind == "partial"
    assert "No se pudo publicar CP-02." in conv.outcome.errors
    assert conv.outcome.published_keys  # CP-01 sí se creó
    assert conv.outcome.story is False
    assert conv.view is None
    assert testmgmt.publish_calls == 1
    assert [case.summary for case in testmgmt.list_cases("DEMO-3")] == [
        "[CP-01] Renovar un préstamo sin reservas"
    ]


def test_memory_failure_after_publishing_is_published_without_memory(tmp_path: Path) -> None:
    """PA-251 · UI.md §4.7: si la memoria falla tras publicar, se dice y no «nada se ha escrito»."""
    ws, _ = _shared(tmp_path, publish_mode="live", memory_generator=_FailingMemoryGenerator())
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)
    assert conv.outcome is not None
    assert conv.outcome.kind == "published_without_memory"
    assert conv.outcome.message == MEMORY_FAILURE
    assert conv.error == MEMORY_FAILURE
    assert conv.finished is not None
    assert "nada se ha escrito" not in conv.finished
    assert conv.can_restart is False
    assert conv.view is None
    assert ("update_story", {"key": "DEMO-3"}) in _tracker(ws.container).writes


def test_approve_with_fake_fingerprint_keeps_pause_with_error(tmp_path: Path) -> None:
    """UI.md §5.3 (negativa): huella falsa → la revisión sigue con `error` y sin resultado."""
    ws, _ = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, {"decision": "approve", "fingerprint": "x"}, AF_ACTOR)
    assert conv.outcome is None
    assert conv.error is None
    assert conv.view is not None
    assert conv.view.error == (
        "La aprobación no corresponde a la versión revisada; vuelve a revisar el artefacto."
    )
    assert conv.finished is None
    _assert_nothing_written(ws.container)


def _ledger_fails(monkeypatch: pytest.MonkeyPatch, container: Container) -> None:
    def failing(*_args: object, **_kwargs: object) -> Any:
        raise ApprovalError(LEDGER_FAILURE)

    monkeypatch.setattr(container.approvals, "record", failing)


def test_approval_error_shows_message_without_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """UI.md §5.3 · §7: `ApprovalError` del registro → su mensaje, sin resultado ni escritura."""
    ws, _ = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _ledger_fails(monkeypatch, ws.container)
    _approved(ws, conv, AF_ACTOR)
    assert conv.error == LEDGER_FAILURE
    assert conv.outcome is None
    _assert_nothing_written(ws.container)


def test_approval_error_closes_conversation_and_offers_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """UI.md §5.3: el registro de aprobaciones falla cerrado → RESTART y «Empezar de nuevo»."""
    ws, _ = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _ledger_fails(monkeypatch, ws.container)
    _approved(ws, conv, AF_ACTOR)
    assert conv.finished == RESTART
    assert conv.can_restart is True
    assert conv.view is None


def test_publish_permission_by_mode() -> None:
    """UI.md §3 · PA-25: aprobar exige PUBLISH_TESTS en QA y PUBLISH_STORY en funcional."""
    qa = Conversation(request=fix_origin("tests", "DEMO", key="DEMO-3"), user=QA_USER)
    functional = Conversation(request=_evolve(), user=AF_USER)
    assert publish_permission(qa) is Permission.PUBLISH_TESTS
    assert publish_permission(functional) is Permission.PUBLISH_STORY


def test_approve_without_publish_permission_does_not_call_the_graph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """UI.md §3 (error): sin el permiso de publicar no se invoca el grafo; la pausa sigue."""
    ws, _ = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    view = conv.view
    # El rol funcional no tiene PUBLISH_TESTS: simula un rol que genera pero no publica.
    monkeypatch.setattr(app_conversation, "publish_permission", lambda _c: Permission.PUBLISH_TESTS)
    spy = _SpyGraph(ws.graph)
    ws.graph = spy  # type: ignore[assignment]

    _approved(ws, conv, AF_ACTOR)

    assert conv.error == NO_PERMISSION
    assert spy.calls == []
    assert conv.view is view
    assert conv.outcome is None and conv.finished is None
    _assert_nothing_written(ws.container)


def test_iterate_does_not_require_publish_permission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """UI.md §3: el permiso de publicar solo se exige al aprobar, no al iterar."""
    ws, _ = _shared(tmp_path)
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    monkeypatch.setattr(app_conversation, "publish_permission", lambda _c: Permission.PUBLISH_TESTS)
    resume(ws, conv, iterate_answer("Cambio ficticio sin publicar"), AF_ACTOR)
    assert conv.error is None
    assert conv.view is not None and conv.view.version == 2


def test_approve_by_actor_with_other_role_is_rejected(tmp_path: Path) -> None:
    """UI.md §3 (error): la dueña con rol QA no aprueba una HU («No tienes permiso…»)."""
    ws, _ = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    spy = _SpyGraph(ws.graph)
    ws.graph = spy  # type: ignore[assignment]
    _approved(ws, conv, User(username=AF_USER, role="qa"))
    assert conv.error == NO_PERMISSION
    assert spy.calls == []
    assert conv.view is not None and conv.outcome is None
    _assert_nothing_written(ws.container)


def test_reopen_approved_simulated_conversation_has_outcome(tmp_path: Path) -> None:
    """T-52 · UI.md §4.7: retomar una conversación aprobada en simulación → resultado simulado."""
    ws, checkpointer = _shared(tmp_path, publish_mode="simulation")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    resume(ws, conv, iterate_answer("Cambio ficticio"), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)
    assert conv.outcome is not None and conv.outcome.version == 2

    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)

    assert reopened.outcome is not None
    assert reopened.outcome.kind == "simulated"
    assert reopened.outcome.version == 2
    assert reopened.outcome.approved_by == AF_USER
    assert reopened.view is None
    assert reopened.finished == _ENDED["simulated"]
    assert reopened.can_restart is False
    _assert_nothing_written(ws.container)


def test_reopen_published_conversation_has_published_outcome(tmp_path: Path) -> None:
    """T-52 · UI.md §4.7: retomar una conversación publicada → resultado publicado."""
    ws, checkpointer = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)

    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)

    assert reopened.outcome is not None
    assert reopened.outcome.kind == "published"
    assert "DEMO-3" in reopened.outcome.published_keys
    assert reopened.status == "published"


class _FailingUpdateTracker(FakeIssueTracker):
    """Jira que falla al actualizar la HU (en `live`, a mitad de `publish`)."""

    def update_story(self, key: str, story: UserStory, comment_md: str) -> None:
        raise PublishError("Jira no ha aceptado la actualización (ficticio).")


def test_publish_failure_in_live_does_not_claim_nothing_was_written(tmp_path: Path) -> None:
    """RNF-13 · UI.md §4.7: si `publish` falla en `live`, no se afirma que Jira esté intacto."""
    ws, _ = _shared(tmp_path, publish_mode="live", issue_tracker=_FailingUpdateTracker())
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)
    assert conv.outcome is None
    assert conv.finished == PUBLISH_INCOMPLETE
    assert "nada se ha escrito" not in conv.finished
    assert conv.can_restart is False
    assert conv.error == "Jira no ha aceptado la actualización (ficticio)."


def test_reopen_after_failed_live_publish_is_not_shown_as_simulated(tmp_path: Path) -> None:
    """UI.md §4.7: un hilo aprobado cuyo `publish` falló no se presenta como «simulado»."""
    ws, checkpointer = _shared(tmp_path, publish_mode="live", issue_tracker=_FailingUpdateTracker())
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)
    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)
    assert reopened.outcome is None
    assert reopened.finished == PUBLISH_INCOMPLETE


def test_reopen_after_memory_failure_is_published_without_memory(tmp_path: Path) -> None:
    """PA-251 · UI.md §4.7: al retomar, una HU publicada sin memoria no dice que la tiene."""
    ws, checkpointer = _shared(
        tmp_path, publish_mode="live", memory_generator=_FailingMemoryGenerator()
    )
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    _approved(ws, conv, AF_ACTOR)
    reopened = reopen(_fresh(ws, checkpointer), AF_ACTOR, conv.thread_id)
    assert reopened.outcome is not None
    assert reopened.outcome.kind == "published_without_memory"
    assert reopened.outcome.message == MEMORY_FAILED


def test_approve_without_actor_fails_closed_without_calling_the_graph(tmp_path: Path) -> None:
    """UI.md §3 · principio 1: aprobar exige saber quién aprueba y su permiso de publicar."""
    ws, _ = _shared(tmp_path, publish_mode="live")
    conv = _started_by(ws, _evolve(), AF_ACTOR)
    assert conv.view is not None
    resume(ws, conv, approve_answer(conv.view))
    assert conv.error == "No tienes permiso para realizar esta acción."
    assert conv.view is not None and conv.outcome is None
    tracker = ws.container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker) and tracker.writes == []


# --- T-28 · QA 1 … QA 3 con el grafo real (UI.md §6.1–6.3, RF-22…RF-27) ----------------------


QA_EXTRA_CASE = TestCase(
    internal_id="CP-03",
    title="Renovar con un socio ficticio en el límite de renovaciones",
    criterion_ids=["CA-01"],
    type=TestCaseType.ALTERNATE,
    preconditions=["Préstamo activo con 1 renovación (ficticio)"],
    steps=[TestStep(action="Pulsar «Renovar»", expected="Vencimiento +21 días")],
    priority=Priority.SHOULD,
)


def _growing_suite_llm() -> FakeLLMProvider:
    """LLM fake: la 1.ª suite es la del dataset; desde la 2.ª añade CP-03 (cubre CA-01)."""
    llm = FakeLLMProvider()
    base = llm.builders[TestSuite]
    calls: list[int] = []

    def build(messages: list[Any]) -> TestSuite:
        calls.append(1)
        suite = base(messages)
        assert isinstance(suite, TestSuite)
        if len(calls) == 1:
            return suite
        return suite.model_copy(update={"cases": [*suite.cases, QA_EXTRA_CASE]})

    llm.builders[TestSuite] = build
    return llm


def _qa_request(types: set[TestCaseType], extras: set[str]) -> StartRequest:
    request = fix_origin("tests", "DEMO", key="DEMO-3", text="DEMO-3")
    return replace(request, extra_feedback=qa_feedback(types, extras))


def test_qa_extra_feedback_reaches_graph_state_and_view_is_suite(tmp_path: Path) -> None:
    """UI.md §6.1–6.2 · RF-22 · T-28: el feedback de QA 1 llega al estado y la vista es la suite."""
    ws, _ = _shared(tmp_path)
    request = _qa_request({TestCaseType.POSITIVE, TestCaseType.EXCEPTION}, {"strategy"})
    conv = _started_by(ws, request, QA_ACTOR)

    feedback = _values(ws, conv)["feedback"]
    assert list(request.extra_feedback) == [
        item for item in feedback if item in request.extra_feedback
    ]
    assert feedback[0] == "Incluye casos: positivos, negativos, de excepción."
    assert "alternos" not in feedback[0]
    assert any(item.startswith("Incluye además: estrategia de pruebas") for item in feedback)
    assert conv.view is not None and conv.view.version == 1
    assert isinstance(conv.view.artifact.content, TestSuite)
    assert summarize(conv.view) == suite_summary(conv.view.artifact.content, 1)
    _assert_nothing_written(ws.container)


def test_qa_iterate_creates_v2_and_case_rows_mark_new_cases(tmp_path: Path) -> None:
    """UI.md §6.3 · T-28: iterar crea la v2; `case_rows` con la v1 marca solo CP-03 como nuevo."""
    ws, _ = _shared(tmp_path, llm=_growing_suite_llm())
    conv = _started_by(ws, _qa_request(set(TestCaseType), {"data", "risks"}), QA_ACTOR)
    resume(ws, conv, iterate_answer("Añade un caso de excepción"), QA_ACTOR)

    assert conv.error is None, conv.error
    assert [v.version for v in conv.versions] == [1, 2]
    v1, v2 = (v.artifact.content for v in conv.versions)
    assert isinstance(v1, TestSuite) and isinstance(v2, TestSuite)
    rows = case_rows(v2, 2, v1)
    assert {row.id: row.new_in for row in rows} == {
        "CP-01": None,
        "CP-02": None,
        "CP-03": "Nuevo en v2",
    }
    assert all(row.new_in is None for row in case_rows(v1, 1, None))
    assert "Añade un caso de excepción" in _values(ws, conv)["feedback"]
    _assert_nothing_written(ws.container)


def test_qa_functional_actor_cannot_start_tests_flow(tmp_path: Path) -> None:
    """UI.md §3 · T-28 (negativa): el analista funcional no puede arrancar una suite."""
    ws, _ = _shared(tmp_path)
    conv = Conversation(request=_qa_request(set(), set()), user=AF_ACTOR.username)
    assert run_start(ws, conv, AF_ACTOR) == []
    assert conv.error == NO_PERMISSION
    assert conv.view is None
    _assert_nothing_written(ws.container)
