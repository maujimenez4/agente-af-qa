"""Conversaciones de la UI sobre el grafo (Mixta 2b y 3; `docs/specs/UI.md` §4.4 y §4.5).

Una conversación = un `thread_id`, que genera siempre el servidor (`new_conversation_config`) o
se retoma solo por su dueña (`resume_config`, T-52). Sin Streamlit: se prueba con el grafo real
y los fakes. El estado vive en el checkpointer; aquí solo está lo que la UI pinta.
"""

from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.base import User
from adapters.errors import AgentError, AuthenticationError, NotFoundError
from app.flows import flow_by_id
from app.origin import StartRequest, build_initial_state, request_from_state
from app.progress import nodes_in_update
from app.review import Outcome, ReviewView, outcome_from_state, pending_from_state, summarize
from core.approvals import ApprovalError
from core.container import Container
from core.conversations import new_conversation_config, resume_config
from core.graph.nodes import ReviewRejectedError
from core.logging import get_logger
from core.permissions import Permission, require
from core.tracing import operation as traced_operation
from core.tracing import operation_name, with_trace_callbacks

log = get_logger(__name__)

ChatMessage = tuple[str, str]  # (rol «user» | «assistant», texto)
UNEXPECTED = "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
# Errores cuyo mensaje se escribe para la UI (en español, sin datos internos).
SAFE_ERRORS: tuple[type[Exception], ...] = (AgentError, ReviewRejectedError, ApprovalError)
# Módulos cuyos `ValueError` llevan un mensaje para la UI (validación de lo que se escribe).
# Se mira el último frame Python: un builtin de C (p. ej. `int(x)`) llamado desde uno de estos
# módulos pasaría con su mensaje, así que en ellos solo se lanzan `ValueError` escritos a mano.
SAFE_VALUE_ERROR_MODULES = frozenset(
    {
        "core.projects",
        "core.graph.state",
        "app.origin",
        "app.editing",
        "app.review",
        "adapters.llm.router",
    }
)
_ENDED = {
    "approved": "La propuesta está aprobada.",
    "simulated": "Publicación simulada: no se ha escrito nada en Jira.",
    "published": "La propuesta está publicada en Jira.",
    "discarded": "Has descartado la propuesta. Nada se ha escrito en Jira.",
}


@dataclass
class Conversation:
    """Estado de la UI de una conversación (no es el estado del grafo).

    `config` la da el servidor: `new_conversation_config` al crearla (por defecto) o
    `resume_config` al retomarla (`reopen`). Nunca se construye con un `thread_id` de fuera.
    """

    request: StartRequest
    user: str
    config: dict[str, Any] = field(default_factory=dict)
    view: ReviewView | None = None  # última pausa de human_review
    versions: list[ReviewView] = field(default_factory=list)  # una por versión generada
    messages: list[ChatMessage] = field(default_factory=list)
    finished: str | None = None  # motivo si la conversación ya no admite cambios
    error: str | None = None  # último error al llamar al grafo
    started: bool = False  # ya se lanzó `start` (evita relanzarlo en otra ejecución)
    status: str | None = None  # estado de la lista de conversaciones (T-52) al terminar
    outcome: Outcome | None = None  # resultado de la publicación (Mixta 4 · QA 5, T-31)
    can_restart: bool = False  # el hilo no se recupera: se ofrece «Empezar de nuevo»

    def __post_init__(self) -> None:
        if not self.config:
            self.config = new_conversation_config(self.user)

    @property
    def thread_id(self) -> str:
        return str(self.config["configurable"]["thread_id"])

    @property
    def title(self) -> str:
        if self.request.text:
            return self.request.text.splitlines()[0][:60]
        return self.request.describe()


@dataclass
class Workspace:
    """Contenedor y grafo compuestos para la sesión de una persona.

    `conversations` son las abiertas en esta sesión (con su chat); la lista completa de la
    persona sale de `container.conversations.list_for` (T-52).
    """

    container: Container
    graph: CompiledStateGraph
    conversations: list[Conversation] = field(default_factory=list)


def _raised_in(exc: BaseException) -> str:
    """Módulo del código Python que lanzó la excepción (último frame del traceback)."""
    tb: TracebackType | None = exc.__traceback__
    module = ""
    while tb is not None:
        module = str(tb.tb_frame.f_globals.get("__name__", ""))
        tb = tb.tb_next
    return module


def message_for(exc: Exception) -> str:
    """Mensaje para la UI con lista blanca; cualquier otro error da `UNEXPECTED`.

    Se muestran los errores del dominio (`AgentError`), la respuesta rechazada de la revisión
    (`ReviewRejectedError`), el registro de aprobaciones (`ApprovalError`) y los `ValueError`
    exactos (no subclases como los de pydantic o json) lanzados por la validación de
    `core/projects`, `core/graph/state`, `app/origin`, `app/editing` (edición a mano),
    `app/review` (petición de cambio) y `adapters/llm/router` (selector de modelo).
    """
    if isinstance(exc, SAFE_ERRORS):
        return str(exc) or UNEXPECTED
    if type(exc) is ValueError and _raised_in(exc) in SAFE_VALUE_ERROR_MODULES:
        return str(exc) or UNEXPECTED
    return UNEXPECTED


def _fail(conv: Conversation, exc: Exception) -> None:
    conv.error = message_for(exc)
    log.warning(
        "error en la conversación",
        user=conv.user,
        action="graph_call",
        error_type=type(exc).__name__,
    )


def _record_view(conv: Conversation, view: ReviewView | None) -> None:
    conv.view = view
    if view is None:
        return
    if conv.versions and conv.versions[-1].version == view.version:
        conv.versions[-1] = view  # misma versión: payload con un `error` nuevo
    else:
        conv.versions.append(view)


def _ended_status(ws: Workspace, conv: Conversation) -> str | None:
    try:
        row = ws.container.conversations.get(conv.thread_id)
    except AgentError:  # la lista es secundaria (T-52): sin ella no se sabe el motivo
        return None
    return row.status if row is not None and row.username == conv.user else None


def _refresh(ws: Workspace, conv: Conversation) -> None:
    view = pending_from_state(ws.graph.get_state(conv.config))
    _record_view(conv, view)
    if view is None and conv.finished is None:
        conv.status = _ended_status(ws, conv)
        conv.finished = _ENDED.get(conv.status or "", "La conversación ha terminado.")


RESTART = "Esta conversación no puede continuar. Empieza una nueva; nada se ha escrito en Jira."
# Tras aprobar en `live`, un fallo no permite afirmar que Jira esté intacto (RNF-13).
PUBLISH_INCOMPLETE = (
    "La publicación no se ha completado. Revisa en Jira y en la auditoría qué se ha hecho "
    "antes de volver a intentarlo."
)
MEMORY_FAILED = "No se ha podido generar la memoria de la HU."


def _after_failure(ws: Workspace, conv: Conversation) -> None:
    """Tras un fallo al reanudar, la vista refleja el hilo real (no la pausa anterior).

    Si ya no hay revisión pendiente (p. ej. falló `generate` o el registro de aprobaciones,
    que falla cerrado), la conversación se cierra y la UI ofrece empezar de nuevo (UI.md §5).
    """
    try:
        view = pending_from_state(ws.graph.get_state(conv.config))
    except Exception as exc:  # sin estado legible: se trata como hilo no recuperable
        # PA-244: queda rastro del tipo (nunca el mensaje, que podría llevar datos).
        log.warning(
            "estado del hilo no legible tras un fallo",
            user=conv.user,
            action="after_failure",
            error_type=type(exc).__name__,
        )
        view = None
    _record_view(conv, view)
    if view is None:
        conv.finished = RESTART
        conv.can_restart = True


_OUTCOME_TEXT = {
    "simulated": _ENDED["simulated"],
    "published": "Publicado en Jira.",
    "partial": "Publicada en parte: algunas operaciones no se han podido hacer en Jira.",
    "published_without_memory": (
        "Publicado en Jira, pero no se ha podido generar la memoria de la HU."
    ),
}


def _settle_approval(
    ws: Workspace, conv: Conversation, approved: ReviewView, failure: str | None
) -> bool:
    """Tras aprobar, deja el resultado de la publicación (T-31); False si no hay resultado.

    Si la reanudación falló después de publicar (p. ej. la memoria, PA-251), el resultado lo
    dice en lugar de «nada se ha escrito en Jira».
    """
    try:
        values = ws.graph.get_state(conv.config).values or {}
    except Exception as exc:  # sin estado legible: no se puede afirmar nada sobre Jira
        # PA-244: queda rastro del tipo (nunca el mensaje, que podría llevar datos).
        log.warning(
            "estado del hilo no legible tras aprobar",
            user=conv.user,
            action="settle_approval",
            error_type=type(exc).__name__,
        )
        return False
    outcome = outcome_from_state(values, approved, conv.user, failure=failure)
    if outcome is None:
        return False
    # Tras `publish` solo viene `memorize`: un fallo con la HU publicada es de la memoria. Si
    # se añade otro nodo detrás de `publish`, hay que mirar qué tarea falló (`_reopen_outcome`).
    if failure is not None and outcome.kind != "published_without_memory":
        return False  # el fallo fue antes de terminar de publicar: lo decide `_after_failure`
    conv.outcome = outcome
    conv.status = _ended_status(ws, conv)
    conv.view = None
    conv.error = None if failure is None else conv.error
    conv.finished = _OUTCOME_TEXT[outcome.kind]
    return True


def publish_permission(conv: Conversation) -> Permission:
    """Permiso de aprobar y publicar del flujo (UI.md §3; complementa la aprobación, PA-25)."""
    return Permission.PUBLISH_TESTS if conv.request.mode == "qa" else Permission.PUBLISH_STORY


def authorize(actor: User | None, conv: Conversation) -> None:
    """`require` antes de ejecutar (UI.md §3): el permiso del flujo de la conversación.

    Lanza `AuthenticationError` («No tienes permiso…») si el rol no puede usar el flujo o si la
    persona no es la dueña de la conversación.
    """
    require(actor, flow_by_id(conv.request.flow).permission)
    if actor is not None and actor.username != conv.user:
        raise AuthenticationError("Esta conversación es de otra persona.")


def _remember(ws: Workspace, conv: Conversation) -> None:
    if conv not in ws.conversations:
        ws.conversations.insert(0, conv)


def _traced(ws: Workspace, conv: Conversation, operation: str) -> Any:
    """T-40: traza de una operación de la conversación (crear, iterar, aprobar…)."""
    return traced_operation(
        ws.container.tracer,
        operation_name(operation),
        session_id=conv.thread_id,
        user_id=conv.user,
        mode=conv.request.mode,
        flow=conv.request.flow,
        project=conv.request.project,
    )


def find_open(ws: Workspace, thread_id: str) -> Conversation | None:
    return next((c for c in ws.conversations if c.thread_id == thread_id), None)


def start(ws: Workspace, conv: Conversation, actor: User | None = None) -> Iterator[str]:
    """Arranca el grafo con `stream` y devuelve cada nodo al terminar (Mixta 2b).

    Con `actor`, comprueba antes el permiso del flujo (la UI siempre lo pasa).
    """
    conv.error = None
    conv.started = True
    if actor is not None:
        try:
            authorize(actor, conv)
        except AgentError as exc:  # rechazada: no aparece en la lista de conversaciones
            _fail(conv, exc)
            return
    _remember(ws, conv)
    try:
        state = build_initial_state(conv.user, conv.request)
        # Se cierra siempre aquí: un `stream` abandonado lo cerraría la recogida de basura en
        # cualquier hilo y su executor puede bloquearse esperando a otros hilos.
        with (
            _traced(ws, conv, "start") as trace,  # T-40: una traza con un paso por nodo
            closing(
                ws.graph.stream(
                    state, with_trace_callbacks(conv.config, trace), stream_mode="updates"
                )
            ) as updates,
        ):
            for update in updates:
                yield from nodes_in_update(update)
        _refresh(ws, conv)
    except Exception as exc:  # se muestra el mensaje; el tipo va al log
        _fail(conv, exc)


def run_start(ws: Workspace, conv: Conversation, actor: User | None = None) -> list[str]:
    """`start` sin progreso intermedio (pruebas y reintentos)."""
    return list(start(ws, conv, actor))


def resume(
    ws: Workspace, conv: Conversation, answer: dict[str, Any], actor: User | None = None
) -> None:
    """Reanuda `human_review` con la respuesta de la persona y lee la nueva pausa."""
    if conv.view is None or conv.finished:
        conv.error = "No hay ninguna propuesta en revisión."
        return
    conv.error = None
    approving = answer.get("decision") == "approve"
    if approving and actor is None:  # aprobar exige saber quién aprueba y su permiso
        conv.error = "No tienes permiso para realizar esta acción."
        return
    if actor is not None:
        try:
            authorize(actor, conv)
            if approving:
                require(actor, publish_permission(conv))
        except AgentError as exc:
            _fail(conv, exc)
            return
    reviewed = conv.view
    try:
        with _traced(ws, conv, str(answer.get("decision") or "")) as trace:
            ws.graph.invoke(Command(resume=answer), with_trace_callbacks(conv.config, trace))
    except Exception as exc:  # se muestra el mensaje; el tipo va al log
        _fail(conv, exc)
        if not (approving and _settle_approval(ws, conv, reviewed, conv.error)):
            _after_failure(ws, conv)
            if (
                approving
                and conv.view is None
                and ws.container.publish_mode == "live"
                and not isinstance(exc, ApprovalError)  # falla antes de publicar
            ):
                conv.finished = PUBLISH_INCOMPLETE
                conv.can_restart = False
        return
    if approving and _settle_approval(ws, conv, reviewed, None):
        return
    _refresh(ws, conv)
    if answer.get("decision") == "discard":
        conv.finished = _ENDED["discarded"]


def _history_views(ws: Workspace, config: dict[str, Any]) -> list[ReviewView]:
    """Una vista por versión, de la pausa más reciente de cada una (el historial va al revés)."""
    by_version: dict[int, ReviewView] = {}
    for snapshot in ws.graph.get_state_history(config):
        view = pending_from_state(snapshot)
        if view is not None:
            by_version.setdefault(view.version, view)
    return [by_version[v] for v in sorted(by_version)]


def reopen(ws: Workspace, actor: User, thread_id: str) -> Conversation:
    """Retoma una conversación propia desde el checkpointer (T-52, UI.md §2).

    `NotFoundError` («No existe esa conversación o no es tuya.») si no es de `actor`. La pausa
    pendiente se lee de las interrupciones de las tareas, no de `next`; las versiones, del
    historial del hilo. El chat se rehace con las peticiones de cambio (`feedback`) y un
    resumen de la última versión: el checkpoint no guarda los mensajes del asistente.
    """
    if (opened := find_open(ws, thread_id)) is not None and opened.user == actor.username:
        return opened
    config = resume_config(ws.container.conversations, actor.username, thread_id)
    snapshot = ws.graph.get_state(config)
    values = snapshot.values or {}
    if "origin" not in values:  # la fila existe pero el hilo no llegó a guardar su estado
        raise NotFoundError(RESTART, service="conversaciones")
    request = request_from_state(
        values["origin"], values.get("mode", "functional"), list(values.get("excluded_sources", []))
    )
    conv = Conversation(request=request, user=actor.username, config=config, started=True)
    authorize(actor, conv)
    conv.versions = _history_views(ws, config)
    conv.messages = [("user", text) for text in values.get("feedback") or []]
    view = pending_from_state(snapshot)
    conv.view = view
    if view is not None:
        conv.messages.append(("assistant", f"Conversación retomada. {summarize(view)}"))
    else:
        conv.status = _ended_status(ws, conv)
        conv.finished = _ENDED.get(conv.status or "", RESTART)
        conv.can_restart = conv.status not in _ENDED
        if values.get("decision") == "approve":  # sin resultado claro, no se afirma nada
            conv.finished, conv.can_restart = PUBLISH_INCOMPLETE, False
            if conv.versions:
                _reopen_outcome(conv, snapshot, values)
    _remember(ws, conv)
    return conv


def _reopen_outcome(conv: Conversation, snapshot: Any, values: dict[str, Any]) -> None:
    """Resultado de una conversación aprobada al retomarla.

    «Simulado» solo si la lista lo confirma (`publish` en simulación); un hilo aprobado cuyo
    `publish` falló no se presenta como simulado. Si `memorize` falló tras publicar (PA-251),
    se dice que la HU está publicada sin memoria.
    """
    memory_failed = any(
        getattr(task, "name", "") == "memorize" and getattr(task, "error", None) is not None
        for task in getattr(snapshot, "tasks", ())
    )
    outcome = outcome_from_state(
        values, conv.versions[-1], conv.user, failure=MEMORY_FAILED if memory_failed else None
    )
    if outcome is None:
        return
    if outcome.kind == "simulated" and conv.status != "simulated":
        conv.finished = PUBLISH_INCOMPLETE
        conv.can_restart = False
        return
    conv.outcome = outcome
    conv.finished = _OUTCOME_TEXT[outcome.kind]
