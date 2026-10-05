"""Registrar la ejecución de las pruebas desde la API (T-47 · QA 6, UI.md §6.6).

La API solo arranca y reanuda el grafo de ejecución (`core/graph/execution.py`): guardar el
borrador, aprobar con la huella o descartar. Solo su nodo `publish` escribe en Jira, y solo con la
aprobación vigente guardada en el servidor. Cada registro es de su dueña: el 404 es el mismo si no
existe o es de otra persona.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any

from langgraph.types import Command

from adapters.base import User
from adapters.errors import NotFoundError
from api.errors import ApiError, to_api_error
from api.models import (
    ExecutionCaseOut,
    ExecutionOut,
    ExecutionOutcome,
    ExecutionResultOut,
    ExecutionResultsIn,
    ExecutionState,
)
from api.runtime import Run, Runtime, Workspace
from api.service import pending_payload
from core.conversations import THREAD_ID, new_conversation_config
from core.graph.execution import KIND, initial_execution_state
from core.permissions import Permission, require
from core.tracing import Operation, operation_name, with_trace_callbacks
from core.tracing import operation as traced_operation

NOT_YOURS = "No existe ese registro o no es tuyo."
CANNOT_CONTINUE = "Este registro no puede continuar. Empieza uno nuevo; nada se ha escrito en Jira."
PERMISSION = Permission.PUBLISH_TESTS  # UI.md §3: registrar la ejecución es del rol QA
NOT_IN_REVIEW_EXECUTION = ApiError(
    409,
    "not_in_review",
    "El registro no está en revisión (se está registrando, ya se registró o se descartó).",
)


def _graph(ws: Workspace) -> Any:
    if ws.execution_graph is None:
        raise ApiError(
            503, "service_unavailable", "El registro de la ejecución no está disponible."
        )
    return ws.execution_graph


def _config(thread_id: str, user: User) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "user": user.username}}


def create(rt: Runtime, ws: Workspace, user: User, story_key: str) -> str:
    """Abre un registro: lee los casos de la HU en Jira y pausa con el recibo vacío."""
    require(user, PERMISSION)
    config = new_conversation_config(user.username)
    thread_id = str(config["configurable"]["thread_id"])  # type: ignore[index]
    with _traced(ws, user, thread_id, "start", story_key) as trace:
        _graph(ws).invoke(
            initial_execution_state(user.username, story_key), with_trace_callbacks(config, trace)
        )
    return thread_id


def _traced(
    ws: Workspace, user: User, thread_id: str, operation: str, story_key: str | None = None
) -> AbstractContextManager[Operation | None]:
    """T-40: traza de una operación del registro de la ejecución."""
    project = story_key.split("-", 1)[0] if story_key else None
    return traced_operation(
        ws.container.tracer,
        f"ejecucion · {operation_name(operation)}",
        session_id=thread_id,
        user_id=user.username,
        mode="qa",
        flow="execution",
        project=project,
    )


def _snapshot(ws: Workspace, user: User, thread_id: str) -> Any:
    """Estado del registro si es de `user`; `NotFoundError` idéntico en cualquier otro caso."""
    if not THREAD_ID.fullmatch(thread_id or ""):
        raise NotFoundError(NOT_YOURS, service="ejecuciones")
    snapshot = _graph(ws).get_state(_config(thread_id, user))
    values = snapshot.values or {}
    if values.get("kind") != KIND or values.get("user") != user.username:
        raise NotFoundError(NOT_YOURS, service="ejecuciones")
    return snapshot


def _run(rt: Runtime, thread_id: str, user: User) -> Run:
    return rt.execution_runs.add(
        Run(
            thread_id=thread_id,
            owner=user.username,
            flow="tests",
            mode="qa",
            project="",
            title="Registro de la ejecución",
        )
    )


def _resume(
    rt: Runtime, ws: Workspace, user: User, thread_id: str, operation: str, answer: dict[str, Any]
) -> None:
    require(user, PERMISSION)
    story_key = (_snapshot(ws, user, thread_id).values or {}).get("story_key")
    run = _run(rt, thread_id, user)
    if run.running or pending_payload(_graph(ws).get_state(_config(thread_id, user))) is None:
        raise NOT_IN_REVIEW_EXECUTION
    if not rt.execution_runs.begin(run, operation):
        raise NOT_IN_REVIEW_EXECUTION
    try:
        with _traced(ws, user, thread_id, operation, story_key) as trace:
            config = with_trace_callbacks(_config(thread_id, user), trace)
            _graph(ws).invoke(Command(resume=answer), config)
    except Exception as exc:
        error = to_api_error(exc)
        rt.execution_runs.finish(run, error.body)
        raise error from None
    rt.execution_runs.finish(run)


def save(rt: Runtime, ws: Workspace, user: User, thread_id: str, body: ExecutionResultsIn) -> None:
    answer = {
        "decision": "save",
        "results": [r.model_dump() for r in body.results],
        "environment": body.environment,
    }
    _resume(rt, ws, user, thread_id, "save", answer)


def approve(rt: Runtime, ws: Workspace, user: User, thread_id: str, fingerprint: str) -> None:
    _resume(rt, ws, user, thread_id, "approve", {"decision": "approve", "fingerprint": fingerprint})


def discard(rt: Runtime, ws: Workspace, user: User, thread_id: str) -> None:
    _resume(rt, ws, user, thread_id, "discard", {"decision": "discard"})


def _state(run: Run | None, values: Mapping[str, Any], in_review: bool) -> ExecutionState:
    if run is not None and run.running:
        return "recording"
    if in_review:
        return "in_review"
    if values.get("decision") == "discard":
        return "discarded"
    if values.get("simulated"):
        return "simulated"
    if values.get("recorded") or values.get("failed"):
        return "partial" if values.get("failed") else "recorded"
    return "error"


def describe(rt: Runtime, ws: Workspace, user: User, thread_id: str) -> ExecutionOut:
    require(user, PERMISSION)
    snapshot = _snapshot(ws, user, thread_id)
    values: Mapping[str, Any] = snapshot.values or {}
    payload = pending_payload(snapshot)
    run = rt.execution_runs.get(thread_id)
    state = _state(run, values, payload is not None)
    error = run.error if run is not None and run.error is not None else None
    if state == "error" and error is None:
        error = ApiError(409, "restart", CANNOT_CONTINUE).body
    outcome = None
    if state in ("simulated", "recorded", "partial"):
        outcome = ExecutionOutcome(
            recorded=list(values.get("recorded") or []),
            failed=list(values.get("failed") or []),
            errors=list(values.get("errors") or []),
            approved_by=str(values.get("user")),
            approved_at=values.get("approved_at"),
            simulated=bool(values.get("simulated")),
        )
    source = payload or values
    return ExecutionOut(
        id=thread_id,
        story_key=str(values.get("story_key")),
        project=str(values.get("project")),
        state=state,
        cases=[ExecutionCaseOut(**c) for c in source.get("cases") or []],
        results=[ExecutionResultOut(**r) for r in source.get("results") or []],
        environment=str(source.get("environment") or ""),
        plan=[dict(op) for op in (payload or {}).get("plan") or []],
        fingerprint=(payload or {}).get("fingerprint"),
        review_error=(payload or {}).get("error"),
        outcome=outcome,
        error=error,
    )
