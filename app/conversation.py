"""Conversaciones de la UI sobre el grafo (Mixta 2b y 3; `docs/specs/UI.md` §4.4 y §4.5).

Una conversación = un `thread_id`, que genera siempre el servidor (`new_conversation_config`) o
se retoma solo por su dueña (`resume_config`, T-52). Sin Streamlit: se prueba con el grafo real
y los fakes. El estado vive en el checkpointer; aquí solo está lo que la UI pinta.
"""

from collections.abc import Iterator
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
from app.review import ReviewView, pending_from_state, summarize
from core.approvals import ApprovalError
from core.container import Container
from core.conversations import new_conversation_config, resume_config
from core.graph.nodes import ReviewRejectedError
from core.logging import get_logger
from core.permissions import require

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


def _after_failure(ws: Workspace, conv: Conversation) -> None:
    """Tras un fallo al reanudar, la vista refleja el hilo real (no la pausa anterior).

    Si ya no hay revisión pendiente (p. ej. falló `generate` o el registro de aprobaciones,
    que falla cerrado), la conversación se cierra y la UI ofrece empezar de nuevo (UI.md §5).
    """
    try:
        view = pending_from_state(ws.graph.get_state(conv.config))
    except Exception:  # sin estado legible: se trata como hilo no recuperable
        view = None
    _record_view(conv, view)
    if view is None:
        conv.finished = RESTART


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
        for update in ws.graph.stream(state, conv.config, stream_mode="updates"):
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
    if actor is not None:
        try:
            authorize(actor, conv)
        except AgentError as exc:
            _fail(conv, exc)
            return
    try:
        ws.graph.invoke(Command(resume=answer), conv.config)
        _refresh(ws, conv)
    except Exception as exc:  # se muestra el mensaje; el tipo va al log
        _fail(conv, exc)
        _after_failure(ws, conv)
        return
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
    _remember(ws, conv)
    return conv
