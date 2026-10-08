"""Conversaciones de la API sobre el grafo (T-55): crear, retomar, reanudar y describir.

Nada aquí escribe en Jira: la API solo arranca el grafo y lo reanuda con la respuesta de la
persona (`Command(resume=...)`). El único nodo que escribe es `publish`, y solo tras `approve`
con la huella exacta que el grafo ofreció (principio 1). Las comprobaciones de aquí (permiso,
propiedad, estado) son previas; las de verdad siguen en el grafo y en el registro de
aprobaciones.
"""

import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from adapters.base import TaskType, User
from adapters.errors import AgentError, NotFoundError
from adapters.llm.router import ModelChoice
from api.cancel import CANCELLED_MESSAGE, GenerationCancelledError, cancellation
from api.errors import ApiError, to_api_error
from api.models import (
    ConversationCreateIn,
    ConversationOut,
    ConversationState,
    Flow,
    HandoffOut,
    Mode,
    ModelChoiceOut,
    OriginIn,
    ProgressStep,
    PublishOutcome,
    ReviewPayload,
    TaskModelsOut,
    UncoveredRefs,
    VersionOut,
)
from api.runtime import Run, Runtime, Workspace
from core.approvals import ApprovalError, PublishTarget
from core.conversations import (
    NOT_YOURS,
    ConversationSummary,
    conversation_title,
    new_conversation_config,
    resume_config,
)
from core.graph import initial_state
from core.graph.state import Origin, normalize_excluded_sources
from core.handoff import (
    HANDOFF_ID,
    Handoff,
    HandoffError,
    HandoffStore,
    QaStart,
    hand_off,
    list_handoffs,
    load_taken_handoff,
    release_failed_take,
    take_handoff,
)
from core.handoff import NOT_AVAILABLE as HANDOFF_NOT_AVAILABLE
from core.logging import get_logger
from core.permissions import Permission, require
from core.projects import normalize_issue_key, normalize_project_key, project_of
from core.tracing import operation as traced_operation
from core.tracing import operation_name, with_trace_callbacks
from core.usage import DEFAULT_TZ, UsageQueries
from schemas.artifact import Artifact
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

log = get_logger("api.service")

NOT_IN_REVIEW = ApiError(
    409,
    "not_in_review",
    "La conversación no tiene una propuesta en revisión (está generando o ya terminó).",
)
NOT_IN_ERROR = ApiError(
    409,
    "not_in_error",
    "La conversación no está en error: no hay nada que reintentar.",
)
# PA-276: solo se reintentan pasos que no escriben en Jira. Repetir `publish` (o la respuesta de
# `human_review` que lleva a él) podría crear la HU dos veces tras un reinicio: la aprobación
# gastada solo vive en memoria y `create_story` no es idempotente (security-reviewer, PA-153).
RETRYABLE_NODES = frozenset({"load_origin", "retrieve_context", "generate", "memorize"})
NOT_RETRYABLE = ApiError(
    409,
    "not_in_error",
    "El paso que falló es la aprobación o la publicación en Jira y no se reintenta: "
    "empieza una conversación nueva o revisa en Jira lo que llegó a publicarse.",
)
# PA-314: solo se detiene lo que genera; aprobar (publicar y la memoria) nunca se corta.
CANCELLABLE_OPERATIONS = frozenset({"start", "iterate", "retry"})
NOT_GENERATING = ApiError(
    409,
    "not_cancellable",
    "La conversación no está generando: no hay nada que detener.",
)
NOT_CANCELLABLE = ApiError(
    409,
    "not_cancellable",
    "Aprobar y publicar en Jira no se pueden detener: espera a que termine.",
)
CANCELLED = ApiError(409, "cancelled", CANCELLED_MESSAGE)
HANDOFF_RELEASED = ApiError(
    409,
    "handoff_unavailable",
    "La HU volvió a la lista de QA tras el fallo: recógela de nuevo para preparar sus pruebas.",
)
APPROVAL_REJECTED = "La aprobación no corresponde a la versión revisada; empieza de nuevo."
RESTART = "Esta conversación no puede continuar. Empieza una nueva; nada se ha escrito en Jira."
# PA-453: aprobada y sin publicación terminada (p. ej. tras reiniciar la API a mitad); lo que
# llegó a escribirse en Jira consta en la auditoría.
PUBLISH_UNFINISHED = (
    "La publicación no terminó y puede haberse escrito parte en Jira: revisa la HU y la "
    "auditoría antes de empezar una conversación nueva."
)
NEED_TEXT_REQUIRED = "Describe la necesidad antes de continuar."
KEY_REQUIRED = "Escribe la clave de la HU de Jira, por ejemplo DEMO-3."

STEP_LABELS = {
    "load_origin": "Leer el origen en Jira",
    "retrieve_context": "Recuperar el contexto (Jira, documentos y memoria)",
    "generate": "Generar la propuesta, validar las citas y analizar el impacto",
    "publish": "Publicar (o simular la publicación) en Jira",
    "memorize": "Guardar la memoria de la HU publicada",
}
# PA-327: en QA, cada etiqueta dice lo que hace el nodo en ese modo. `memorize` no aparece: en
# QA no hace nada (D-07), así que la lista tiene 4 pasos en vez de 5.
QA_STEP_LABELS = {
    "load_origin": "Recuperar la HU de origen",
    "retrieve_context": "Recuperar el contexto (Jira, documentos y memoria)",
    "generate": "Generar casos y escenarios, validar la cobertura y preparar datos, riesgos y "
    "estrategia",
    "publish": "Publicar (o simular la publicación de) los casos de prueba en Jira",
}
GENERATION_NODES = ("load_origin", "retrieve_context", "generate")
PUBLISH_NODES = ("publish", "memorize")
# Nodos que vuelve a ejecutar cada operación (el resto conserva su estado).
OPERATION_NODES = {
    "start": (*GENERATION_NODES, *PUBLISH_NODES),
    "iterate": ("generate",),
    "approve": PUBLISH_NODES,
}
ENDED = ("approved", "simulated", "published", "discarded")


def retry_nodes(next_nodes: Iterable[str]) -> tuple[str, ...]:
    """Nodos que repite un reintento: desde el que falló hasta el final de su tramo."""
    pending = set(next_nodes)
    for block in (GENERATION_NODES, PUBLISH_NODES):
        for index, node in enumerate(block):
            if node in pending:
                return block[index:]
    return ()


# IDs de criterios y reglas en la descripción de una incidencia (plantilla de HU), sin IA.
_CA_ID = re.compile(r"\bCA-\d+\b")
_RN_ID = re.compile(r"\bRN-\d+\b")


def nodes_in_update(update: object) -> list[str]:
    """Nodos de un evento de `graph.stream(..., stream_mode="updates")` (sin los internos)."""
    if not isinstance(update, dict):
        return []
    return [str(name) for name in update if not str(name).startswith("__")]


def count_test_cases(ws: Workspace, story_key: str) -> int | None:
    """Subtareas CP de la HU en Jira (PA-104); None si no se pudo consultar."""
    try:
        return len(ws.container.test_management.list_cases(story_key))
    except AgentError:
        return None


def published_by_agent(ws: Workspace, story_key: str) -> bool | None:
    """El agente publicó esta HU (tabla `artifacts`, PA-104); None si no hay almacén o falla."""
    check = getattr(ws.container.versions, "published_by_agent", None)
    if check is None:
        return None
    try:
        return bool(check(story_key))
    except AgentError:
        return None


def count_ids(text: str) -> tuple[int, int]:
    """CA y RN distintos que aparecen en `text` (ficha de una incidencia)."""
    return len(set(_CA_ID.findall(text))), len(set(_RN_ID.findall(text)))


# --- Permisos y propiedad -------------------------------------------------------------------


def mode_of(flow: Flow) -> Mode:
    return "qa" if flow == "tests" else "functional"


def flow_of(mode: str, origin_kind: str) -> Flow:
    if mode == "qa":
        return "tests"
    return "evolve" if origin_kind == "story" else "need"


def generate_permission(mode: str) -> Permission:
    return Permission.GENERATE_TESTS if mode == "qa" else Permission.GENERATE_STORY


def publish_permission(mode: str) -> Permission:
    return Permission.PUBLISH_TESTS if mode == "qa" else Permission.PUBLISH_STORY


def _config(thread_id: str, user: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "user": user}}


def open_conversation(
    rt: Runtime, ws: Workspace, user: User, thread_id: str
) -> tuple[dict[str, Any], Run | None, ConversationSummary | None]:
    """Config de una conversación propia; `NotFoundError` idéntico si no existe o no es suya."""
    run = rt.runs.get(thread_id)
    row = ws.container.conversations.get(thread_id)
    if run is not None and row is None:
        # Recién creada: aún no ha llegado a `load_origin`, que la añade a la lista.
        if run.owner != user.username:
            raise NotFoundError(NOT_YOURS, service="conversaciones")
        return _config(thread_id, user.username), run, None
    config = resume_config(ws.container.conversations, user.username, thread_id)
    if run is not None and run.owner != user.username:
        raise NotFoundError(NOT_YOURS, service="conversaciones")
    return config, run, row


# --- Arranque, fuentes y ajustes ------------------------------------------------------------


def preview_origin(o: OriginIn) -> Origin:
    """`Origin` para la vista previa de fuentes; `ValueError` con mensaje para la persona."""
    if o.kind == "need":
        text = (o.text or "").strip()
        if not text:
            raise ValueError(NEED_TEXT_REQUIRED)
        return Origin(kind="need", text=text, project=normalize_project_key(o.project))
    if not o.key:
        raise ValueError(KEY_REQUIRED)
    key = normalize_issue_key(o.key)
    return Origin(kind=o.kind, key=key, project=project_of(key))


def excluded_for(excluded: list[str], origin_key: str | None) -> list[str]:
    """Las mismas reglas que el grafo (T-51): el origen nunca se excluye."""
    return normalize_excluded_sources(excluded, origin_key)


def iterate_answer(feedback: str) -> dict[str, Any]:
    text = feedback.strip()
    if not text:
        raise ValueError("Escribe qué quieres cambiar de la propuesta.")
    return {"decision": "iterate", "feedback": text}


def tokens_today(queries: UsageQueries, now: datetime | None = None) -> int:
    """Tokens de todas las llamadas al LLM desde las 00:00 (hora de `core.usage`)."""
    local_now = (now or datetime.now(UTC)).astimezone(DEFAULT_TZ)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return sum(call.total_tokens for call in queries.calls(since=start))


def task_type(raw: str) -> TaskType:
    try:
        return TaskType(raw)
    except ValueError:
        raise ApiError(404, "not_found", "No existe esa tarea.") from None


def _choice_out(choice: ModelChoice) -> ModelChoiceOut:
    return ModelChoiceOut(provider=choice.provider, model=choice.model)


def task_models(ws: Workspace, task: TaskType) -> TaskModelsOut:
    override = ws.overrides.get(task)
    return TaskModelsOut(
        task=task.value,
        chain=[_choice_out(c) for c in ws.chains.get(task, [])],
        override=_choice_out(override) if override else None,
    )


def set_override(ws: Workspace, task: TaskType, choice: ModelChoice) -> None:
    """Solo modelos de la cadena configurada de esa tarea (D-14, requisito 12)."""
    if choice not in ws.chains.get(task, []):
        raise ApiError(
            422,
            "invalid_request",
            "Ese modelo no está en la cadena de la tarea (config/models.yaml).",
        )
    if ws.router is None:
        raise ApiError(503, "service_unavailable", "El selector de modelo no está disponible.")
    ws.router.set_override(task, choice)  # ValueError si el proveedor no está disponible
    ws.overrides[task] = choice


def clear_override(ws: Workspace, task: TaskType) -> None:
    if ws.router is not None:
        ws.router.clear_override(task)
    ws.overrides.pop(task, None)


# --- Crear ----------------------------------------------------------------------------------


def _origin(body: ConversationCreateIn) -> tuple[Origin, list[str]]:
    """`Origin` del grafo y feedback previo; `ValueError` con mensaje para la persona."""
    o = body.origin
    feedback = list(body.feedback)
    origin = preview_origin(o)
    if o.kind != "need" and o.text and o.text.strip():
        feedback.insert(0, o.text.strip())  # lo pedido junto a la clave, como feedback (T-51)
    return origin, feedback


def create_conversation(rt: Runtime, ws: Workspace, user: User, body: ConversationCreateIn) -> Run:
    mode = mode_of(body.flow)
    require(user, generate_permission(mode))
    origin, feedback = _origin(body)
    project = origin.get("project") or ""
    if project not in {p.key for p in ws.container.issue_tracker.list_projects()}:
        raise NotFoundError(
            f"El proyecto {project} no existe o la conexión no tiene acceso a él.", service="jira"
        )
    state = initial_state(
        user.username, mode, origin, excluded_sources=body.excluded_sources, feedback=feedback
    )
    config = new_conversation_config(user.username)
    thread_id = str(config["configurable"]["thread_id"])  # type: ignore[index]
    run = Run(
        thread_id=thread_id,
        owner=user.username,
        flow=body.flow,
        mode=mode,
        project=project,
        title=conversation_title(mode, origin["kind"], origin.get("key"), project),
    )
    rt.runs.add(run)
    rt.runs.begin(run, "start")
    rt.submit(lambda: _run_graph(rt, ws, run, state, config))
    return run


def _handoff_store(rt: Runtime) -> HandoffStore:
    if rt.handoffs is None:
        raise ApiError(503, "service_unavailable", "La entrega de HU a QA no está disponible.")
    return rt.handoffs


def handoff_out(handoff: Handoff) -> HandoffOut:
    return HandoffOut(
        id=handoff.id,
        title=handoff.title,
        project=handoff.project_key,
        story_key=handoff.story_key,
        version=handoff.version,
        from_user=handoff.from_user,
        created_at=handoff.created_at,
    )


def pass_to_qa(rt: Runtime, ws: Workspace, user: User, thread_id: str) -> HandoffOut:
    """«Pasar a QA» (T-54): la HU sale del servidor (checkpointer, lista y registro)."""
    # Permiso y propiedad primero: lo ajeno da el mismo 404 aunque esté generando.
    require(user, Permission.GENERATE_STORY)
    _cfg, run, _row = open_conversation(rt, ws, user, thread_id)
    if run is not None and run.running:
        raise NOT_IN_REVIEW
    handoff = hand_off(ws.container, ws.graph, _handoff_store(rt), user, thread_id)
    return handoff_out(handoff)


def pending_handoffs(rt: Runtime, ws: Workspace, user: User) -> list[HandoffOut]:
    """HU pendientes de QA, solo de los proyectos que ve la conexión."""
    require(user, Permission.GENERATE_TESTS)
    projects = {p.key for p in ws.container.issue_tracker.list_projects()}
    return [handoff_out(h) for h in list_handoffs(_handoff_store(rt), user, projects)]


def take(rt: Runtime, ws: Workspace, user: User, handoff_id: str) -> Run:
    """Recoge la HU (una sola persona) y arranca su conversación de QA en segundo plano."""
    require(user, Permission.GENERATE_TESTS)
    store = _handoff_store(rt)
    # Defensa en profundidad: solo entregas de proyectos que ve la conexión (como la lista).
    found = store.get(handoff_id) if HANDOFF_ID.fullmatch(handoff_id or "") else None
    if found is not None:
        visible = {p.key for p in ws.container.issue_tracker.list_projects()}
        if found.project_key not in visible:
            raise HandoffError(HANDOFF_NOT_AVAILABLE)
    start = take_handoff(store, user, handoff_id)
    thread_id = str(start.config["configurable"]["thread_id"])  # type: ignore[index]
    handoff = start.handoff
    run = Run(
        thread_id=thread_id,
        owner=user.username,
        flow="tests",
        mode="qa",
        project=handoff.project_key,
        title=conversation_title("qa", "story", handoff.story_key, handoff.project_key),
    )
    rt.runs.add(run)
    rt.runs.begin(run, "start")
    rt.submit(lambda: _run_taken(rt, ws, run, start, store))
    return run


def _run_taken(rt: Runtime, ws: Workspace, run: Run, start: QaStart, store: HandoffStore) -> None:
    """Genera la suite de la HU recogida; si falla antes de la primera versión, la HU vuelve a
    la lista de QA (PA-113) en lugar de quedar bloqueada en una conversación con error."""
    _run_graph(
        rt,
        ws,
        run,
        start.state,
        start.config,
        on_error=lambda: _release_if_unstarted(ws, store, start.handoff.id, run, start.config),
    )


def _release_if_unstarted(
    ws: Workspace, store: HandoffStore, handoff_id: str, run: Run, config: Any
) -> None:
    """PA-113: sin primera versión, la entrega vuelve a la lista de QA. Se llama **antes** de
    dar el run por terminado (PA-276), así nadie puede reintentar el hilo con la entrega aún
    recogida."""
    try:
        artifact = (ws.graph.get_state(config).values or {}).get("artifact")
        if artifact is None:
            release_failed_take(store, handoff_id, run.owner, run.thread_id)
    except Exception as exc:  # la entrega queda recogida: solo se registra el tipo
        log.warning(
            "entrega sin devolver tras un fallo",
            user=run.owner,
            action="release_handoff",
            error_type=type(exc).__name__,
        )


def retry(rt: Runtime, ws: Workspace, user: User, thread_id: str) -> Run:
    """PA-276: retoma una conversación en error desde su último checkpoint (`stream(None)`).

    El nodo que falló se repite; lo anterior (contexto, versiones aprobadas…) no. Propiedad y
    permiso como el resto; 409 si no está en error o si lo que falló es aprobar o publicar
    (`RETRYABLE_NODES`). En QA encadenada, si la entrega ya volvió a la lista (PA-113), no se
    reintenta: hay que recogerla de nuevo.
    """
    config, run, row = open_conversation(rt, ws, user, thread_id)
    run = _ensure_run(rt, row, run)
    require(user, generate_permission(row.mode if row else run.mode))
    if run.running:
        raise NOT_IN_ERROR
    snapshot = ws.graph.get_state(config)
    in_review = pending_payload(snapshot) is not None
    pending = "publish" in (snapshot.next or ())
    if _state(run, row, in_review, pending) != "error" or not snapshot.next:
        raise NOT_IN_ERROR
    if not set(snapshot.next) <= RETRYABLE_NODES:
        raise NOT_RETRYABLE
    handoff_id = (snapshot.values or {}).get("handoff_id")
    on_error = None
    if handoff_id is not None:
        store = _handoff_store(rt)
        try:
            load_taken_handoff(store, handoff_id, user.username, thread_id)
        except HandoffError:
            raise HANDOFF_RELEASED from None
        on_error = lambda: _release_if_unstarted(ws, store, handoff_id, run, config)  # noqa: E731
    if not rt.runs.begin(run, "retry", retry_nodes(snapshot.next)):
        raise NOT_IN_ERROR
    rt.submit(lambda: _run_graph(rt, ws, run, None, config, on_error=on_error))
    return run


# --- Reanudar -------------------------------------------------------------------------------


def _run_graph(
    rt: Runtime,
    ws: Workspace,
    run: Run,
    graph_input: Any,
    config: Any,
    *,
    on_error: Callable[[], None] | None = None,
) -> None:
    """Ejecuta el grafo hasta la siguiente pausa o el final, anotando cada nodo terminado.

    `on_error` se ejecuta si falla, **antes** de marcar el run como terminado (PA-276).
    """
    started = time.perf_counter()
    # PA-314: la señal de ESTA operación, tomada una sola vez; aprobar (publicar) no la respeta
    # nunca, aunque alguien la active por una carrera con una generación que acaba de terminar.
    signal = run.cancel if run.operation in CANCELLABLE_OPERATIONS else threading.Event()
    try:
        with (
            cancellation(signal),  # en este hilo
            traced_operation(  # T-40: una traza por operación, con un paso por nodo
                ws.container.tracer,
                operation_name(run.operation),
                session_id=run.thread_id,
                user_id=run.owner,
                mode=run.mode,
                flow=run.flow,
                project=run.project,
            ) as trace,
        ):
            config = with_trace_callbacks(config, trace)
            for update in ws.graph.stream(graph_input, config, stream_mode="updates"):
                finished = nodes_in_update(update)
                labels = step_labels(run.mode)
                for node in finished:
                    if node in labels:
                        rt.runs.node_done(run, node)
                if signal.is_set() and _stops_after(finished):
                    raise GenerationCancelledError
        rt.runs.finish(run)
    except Exception as exc:  # el mensaje pasa por la lista blanca; el tipo va al log
        if on_error is not None:
            on_error()
        body = (
            CANCELLED.body if isinstance(exc, GenerationCancelledError) else to_api_error(exc).body
        )
        rt.runs.finish(run, body)
        log.warning(
            "error en la operación",
            user=run.owner,
            action=run.operation,
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
    else:
        log.info(
            "operación terminada",
            user=run.owner,
            action=run.operation,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )


def _stops_after(finished: list[str]) -> bool:
    """PA-314: ¿se detiene tras estos nodos? Se decide por el nodo que acaba de terminar y no
    por el checkpoint: LangGraph emite la actualización antes de guardarlo, y leerlo ahí puede
    dar el paso anterior. Tras `generate` lo siguiente es `human_review`, que solo pausa con la
    propuesta ya generada: se deja correr (queda en revisión, no en un callejón sin salida).
    Tras `load_origin`, `retrieve_context` o `human_review` (al iterar) se para antes del
    siguiente paso, que queda pendiente y se puede reintentar con `/retry`."""
    return bool(finished) and "generate" not in finished


def cancel(rt: Runtime, ws: Workspace, user: User, thread_id: str) -> Run:
    """PA-314: pide detener la generación en curso; se para al terminar la llamada al LLM o el
    paso en curso, sin empezar el siguiente. Nunca escribe en Jira."""
    _config, run, row = open_conversation(rt, ws, user, thread_id)
    run = _ensure_run(rt, row, run)
    require(user, generate_permission(row.mode if row else run.mode))
    outcome = rt.runs.request_cancel(run, CANCELLABLE_OPERATIONS)
    if outcome == "idle":
        raise NOT_GENERATING
    if outcome == "operation":
        raise NOT_CANCELLABLE
    log.info("generación detenida a petición", user=user.username, action="cancel")
    return run


def _ensure_run(rt: Runtime, row: ConversationSummary | None, run: Run | None) -> Run:
    if run is not None:
        return run
    if row is None:
        raise NotFoundError(NOT_YOURS, service="conversaciones")
    run = Run(
        thread_id=row.thread_id,
        owner=row.username,
        flow=flow_of(row.mode, row.origin_kind),
        mode=row.mode,
        project=row.project_key,
        title=row.title,
    )
    return rt.runs.add(run)


def _pending(ws: Workspace, config: Any) -> tuple[dict[str, Any], Mapping[str, Any]]:
    """Valores del hilo y la pausa de `human_review`; 409 si no hay propuesta en revisión."""
    snapshot = ws.graph.get_state(config)
    payload = pending_payload(snapshot)
    if payload is None:
        raise NOT_IN_REVIEW
    return dict(snapshot.values or {}), payload


def resume(
    rt: Runtime,
    ws: Workspace,
    user: User,
    thread_id: str,
    operation: str,
    answer: dict[str, Any],
) -> Run:
    """Reanuda la revisión: `iterate` y `approve` en segundo plano; `edit` y `discard` aquí."""
    config, run, row = open_conversation(rt, ws, user, thread_id)
    run = _ensure_run(rt, row, run)
    mode = row.mode if row else run.mode
    permission = publish_permission(mode) if operation == "approve" else generate_permission(mode)
    require(user, permission)
    if run.running:
        raise NOT_IN_REVIEW
    values, payload = _pending(ws, config)
    if operation == "approve" and answer.get("fingerprint") == payload.get("fingerprint"):
        _check_offered(ws, values, config)
    if not rt.runs.begin(run, operation):
        raise NOT_IN_REVIEW
    if operation in ("iterate", "approve"):
        rt.submit(lambda: _run_graph(rt, ws, run, Command(resume=answer), config))
    else:
        _run_graph(rt, ws, run, Command(resume=answer), config)
    return run


def _check_offered(ws: Workspace, values: Mapping[str, Any], config: Any) -> None:
    """El registro de aprobaciones aceptará esta versión; si no, 409 antes de reanudar."""
    artifact = values.get("artifact")
    origin = values.get("origin") or {}
    if not isinstance(artifact, Artifact):
        raise NOT_IN_REVIEW
    target = PublishTarget(
        mode=str(values.get("mode")),
        origin_kind=str(origin.get("kind")),
        origin_key=origin.get("key"),
        project_key=origin.get("project") or "",
        user=str(values.get("user")),
        thread_id=str(config["configurable"]["thread_id"]),
    )
    try:
        offered = ws.container.approvals.is_offered(artifact, target)
    except ApprovalError as exc:  # registro dañado: falla cerrado con su mensaje para la UI
        raise ApiError(409, "approval_rejected", str(exc)) from None
    if not offered:
        raise ApiError(409, "approval_rejected", APPROVAL_REJECTED)


# --- Describir ------------------------------------------------------------------------------


def _interrupt_values(snapshot: Any) -> list[Mapping[str, Any]]:
    return [
        i.value
        for task in getattr(snapshot, "tasks", ()) or ()
        for i in getattr(task, "interrupts", ()) or ()
        if isinstance(getattr(i, "value", None), Mapping)
    ]


def pending_payload(snapshot: Any) -> Mapping[str, Any] | None:
    """La pausa pendiente de `human_review` (última interrupción de las tareas del hilo)."""
    values = _interrupt_values(snapshot)
    return values[-1] if values else None


def _versions(history: Iterable[Any]) -> tuple[list[VersionOut], list[dict[str, str]]]:
    """Una versión por cada pausa distinta (la más antigua da la fecha) y el último plan."""
    by_version: dict[int, VersionOut] = {}
    plans: dict[int, list[dict[str, str]]] = {}
    for snapshot in history:  # de la más reciente a la más antigua
        payload = pending_payload(snapshot)
        if payload is None:
            continue
        version = int(payload["version"])
        values = snapshot.values or {}
        by_version[version] = VersionOut(
            version=version,
            artifact=Artifact.model_validate(payload["artifact"]),
            created_at=_parse_time(getattr(snapshot, "created_at", None)),
            edited=values.get("decision") == "edit",
        )
        plans.setdefault(version, [dict(op) for op in payload.get("plan") or []])
    ordered = [by_version[v] for v in sorted(by_version)]
    last_plan = plans[max(plans)] if plans else []
    return ordered, last_plan


def _parse_time(raw: object) -> datetime:
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.now(UTC)


def _state(
    run: Run | None,
    row: ConversationSummary | None,
    in_review: bool,
    publish_pending: bool = False,
) -> ConversationState:
    if run is not None and run.running:
        return "generating"
    if run is not None and run.error is not None:
        return "error"
    if in_review:
        return "in_review"
    if row is not None and row.status == "approved" and publish_pending:
        # PA-453: aprobada y con `publish` aún pendiente en el grafo, sin operación en curso: la
        # publicación no terminó (falló o se interrumpió, p. ej. al reiniciar la API). Una suite
        # publicada en parte sí terminó `publish` y sigue `approved` con sus fallos (PA-324).
        return "error"
    if row is not None and row.status in ENDED:
        return row.status  # type: ignore[return-value]
    return "error"


def step_labels(mode: str | None) -> dict[str, str]:
    """PA-327: los pasos que se muestran y su texto, según el modo."""
    return QA_STEP_LABELS if mode == "qa" else STEP_LABELS


def _progress(
    state: ConversationState, run: Run | None, values: Mapping[str, Any], mode: str
) -> list[ProgressStep]:
    labels = step_labels(mode)
    done: set[str] = set()
    if values.get("artifact") is not None:
        done.update(GENERATION_NODES)
    if state in ("simulated", "published"):
        done.update(PUBLISH_NODES)
    running_node = None
    if run is not None and run.running:
        rerun = (
            run.rerun if run.operation == "retry" else OPERATION_NODES.get(run.operation or "", ())
        )
        if run.operation == "retry" and rerun:
            # Lo anterior al nodo que falló ya se hizo y no se repite (`stream(None)`).
            ordered = (*GENERATION_NODES, *PUBLISH_NODES)
            done.update(ordered[: ordered.index(rerun[0])])
        done -= set(rerun)
        done.update(run.nodes)
        running_node = next((n for n in rerun if n not in run.nodes and n in labels), None)
    return [
        ProgressStep(
            node=node,  # type: ignore[arg-type]
            label=label,
            state="done" if node in done else "running" if node == running_node else "pending",
        )
        for node, label in labels.items()
    ]


def _result(
    ws: Workspace,
    state: ConversationState,
    row: ConversationSummary | None,
    values: Mapping[str, Any],
    plan: list[dict[str, str]],
) -> PublishOutcome | None:
    errors = list(values.get("errors") or [])
    keys = list(values.get("published_keys") or [])
    if state not in ("simulated", "published") and not (errors or keys):
        return None
    if row is None:
        return None
    failed_ids: list[str] = []
    artifact = values.get("artifact")
    if isinstance(artifact, Artifact) and errors:
        failed_ids = _failed_ids(ws, artifact)
    return PublishOutcome(
        simulated=row.status == "simulated",
        plan=plan,
        approved_by=str(values.get("user") or row.username),
        approved_at=row.updated_at,
        published_keys=keys,
        errors=errors,
        failed_ids=failed_ids,
    )


def _failed_ids(ws: Workspace, artifact: Artifact) -> list[str]:
    """CP o adjuntos que fallaron, de la última publicación en la auditoría (RNF-13)."""
    try:
        entries = ws.container.audit.entries(artifact.id)
    except Exception as exc:  # la auditoría es secundaria para pintar el resultado
        # PA-244: queda rastro del tipo (nunca el mensaje, que podría llevar datos).
        log.warning(
            "fallidos no leídos de la auditoría",
            action="read_failed_ids",
            artifact_id=str(artifact.id),
            error_type=type(exc).__name__,
        )
        return []
    for entry in reversed(entries):
        if entry.action == "publish":
            return [str(i) for i in entry.detail.get("failed_ids") or []]
    return []


def describe(
    ws: Workspace,
    config: Any,
    run: Run | None,
    row: ConversationSummary | None,
    handoffs: HandoffStore | None,
) -> ConversationOut:
    snapshot = ws.graph.get_state(config)
    values: Mapping[str, Any] = snapshot.values or {}
    payload = pending_payload(snapshot)
    versions, plan = _versions(ws.graph.get_state_history(config))
    publish_pending = "publish" in (snapshot.next or ())
    state = _state(run, row, payload is not None, publish_pending)
    origin = values.get("origin") or {}
    mode = str(values.get("mode") or (row.mode if row else run.mode if run else "functional"))
    kind = str(origin.get("kind") or (row.origin_kind if row else "need"))
    project = str(origin.get("project") or (row.project_key if row else run.project if run else ""))
    error = run.error if run is not None else None
    if state == "error" and error is None:
        unfinished = row is not None and row.status == "approved" and publish_pending
        error = ApiError(409, "restart", PUBLISH_UNFINISHED if unfinished else RESTART).body
    updated = [t for t in (row.updated_at if row else None, run.updated_at if run else None) if t]
    return ConversationOut(
        id=str(config["configurable"]["thread_id"]),
        title=row.title if row else run.title if run else "Conversación",
        project=project,
        flow=run.flow if run else flow_of(mode, kind),
        mode=mode,  # type: ignore[arg-type]
        state=state,
        progress=_progress(state, run, values, mode),
        review=_review(ws, handoffs, config, payload, mode, values)
        if payload and state == "in_review"
        else None,
        versions=versions,
        feedback=[str(f) for f in values.get("feedback") or []],
        result=_result(ws, state, row, values, plan),
        error=error,
        updated_at=max(updated) if updated else datetime.now(UTC),
        cancel_requested=bool(run and run.running and run.cancel.is_set()),
        jira_baseline=_jira_baseline(ws, mode, kind, state, values),
    )


def _review(
    ws: Workspace,
    handoffs: HandoffStore | None,
    config: Any,
    payload: Mapping[str, Any],
    mode: str,
    values: Mapping[str, Any],
) -> ReviewPayload:
    """La revisión; en QA, con la matriz de cobertura y lo no cubierto (PA-326), sin LLM."""
    review = ReviewPayload.model_validate(dict(payload))
    suite = review.artifact.content
    if mode != "qa" or not isinstance(suite, TestSuite):
        return review
    configurable = config["configurable"]
    # La persona de la sesión (`open_conversation` ya comprobó que es la dueña), no la del estado.
    requester = str(configurable.get("user") or "")
    story = _source_story(
        ws, handoffs, review.artifact, values, str(configurable["thread_id"]), requester
    )
    return review.model_copy(
        update={
            "coverage_md": suite.coverage_md(),
            "uncovered": _uncovered(suite, story) if story is not None else None,
        }
    )


def _source_story(
    ws: Workspace,
    handoffs: HandoffStore | None,
    artifact: Artifact,
    values: Mapping[str, Any],
    thread_id: str,
    requester: str,
) -> UserStory | None:
    """La HU de origen que el grafo ya cargó, o `None` si no se puede saber sin el LLM.

    QA encadenada: la HU aprobada de la entrega, con las mismas comprobaciones que el grafo
    (recogida por esta persona y en este hilo; nunca la de otra entrega). Desde Jira: la versión
    de partida que `generate` estructuró y guardó (PA-61).
    """
    try:
        if handoff_id := values.get("handoff_id"):
            return load_taken_handoff(handoffs, str(handoff_id), requester, thread_id).story
        saved = (ws.container.state_store.load(str(artifact.id)) or {}).get("baseline")
        return UserStory.model_validate(saved) if saved else None
    except Exception as exc:  # solo informativo: sin HU de origen, `uncovered` es «no se sabe»
        log.warning("HU de origen sin leer", action="uncovered", error_type=type(exc).__name__)
        return None


def _uncovered(suite: TestSuite, story: UserStory) -> UncoveredRefs:
    covered = suite.coverage()
    return UncoveredRefs(
        criteria=[c.id for c in story.acceptance_criteria if not covered.get(c.id)],
        rules=[r.id for r in story.business_rules if not covered.get(r.id)],
    )


def _jira_baseline(
    ws: Workspace, mode: str, kind: str, state: str, values: Mapping[str, Any]
) -> UserStory | None:
    """PA-316: la versión de partida que el grafo ya guardó (`state["baseline"]`), sin LLM."""
    artifact = values.get("artifact")
    if mode != "functional" or kind != "story" or not isinstance(artifact, Artifact):
        return None
    if state not in ("generating", "in_review", "error"):
        return None  # terminada (aprobada, simulada, publicada o descartada): ya no se itera
    try:
        saved = (ws.container.state_store.load(str(artifact.id)) or {}).get("baseline")
        return UserStory.model_validate(saved) if saved else None
    except Exception:  # solo informativo: si no se puede leer, el frontend no la muestra
        log.warning("versión de Jira sin leer", action="jira_baseline")
        return None


def conversation_out(rt: Runtime, ws: Workspace, user: User, thread_id: str) -> ConversationOut:
    config, run, row = open_conversation(rt, ws, user, thread_id)
    if row is None and run is not None:
        row = ws.container.conversations.get(thread_id)
    return describe(ws, config, run, row, rt.handoffs)
