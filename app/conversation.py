"""Conversaciones de la UI sobre el grafo (Mixta 2b y 3; `docs/specs/UI.md` §4.4 y §4.5).

Una conversación = un `thread_id`. Sin Streamlit: se prueba con el grafo real y los fakes.
Las conversaciones viven en el checkpointer en memoria y se pierden al reiniciar (T-52).
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import ValidationError

from adapters.base import User
from adapters.errors import AgentError, AuthenticationError
from app.flows import flow_by_id
from app.origin import StartRequest, build_initial_state
from app.progress import nodes_in_update
from app.review import ReviewView, pending_from_state
from core.container import Container
from core.logging import get_logger
from core.permissions import require

log = get_logger(__name__)

ChatMessage = tuple[str, str]  # (rol «user» | «assistant», texto)
UNEXPECTED = "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
# Su texto lleva estructura interna o contenido no fiable (p. ej. `input_value` de pydantic).
INTERNAL_VALUE_ERRORS = (ValidationError, json.JSONDecodeError, UnicodeError)


@dataclass
class Conversation:
    """Estado de la UI de una conversación (no es el estado del grafo)."""

    request: StartRequest
    user: str
    thread_id: str = field(default_factory=lambda: f"conv-{uuid4()}")
    view: ReviewView | None = None  # última pausa de human_review
    versions: list[ReviewView] = field(default_factory=list)  # una por versión generada
    messages: list[ChatMessage] = field(default_factory=list)
    finished: str | None = None  # motivo si la conversación ya no admite cambios
    error: str | None = None  # último error al llamar al grafo
    started: bool = False  # ya se lanzó `start` (evita relanzarlo en otra ejecución)

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.thread_id}}

    @property
    def title(self) -> str:
        if self.request.text:
            return self.request.text.splitlines()[0][:60]
        return self.request.describe()


@dataclass
class Workspace:
    """Contenedor y grafo compuestos para la sesión de una persona."""

    container: Container
    graph: CompiledStateGraph
    conversations: list[Conversation] = field(default_factory=list)


def message_for(exc: Exception) -> str:
    """Mensaje para la UI: el de las excepciones del dominio (en español) o uno genérico.

    `ApprovalError` es subclase de `ValueError` (no de `AgentError`), igual que los errores de
    validación de `initial_state` y de las claves escritas.
    """
    if isinstance(exc, INTERNAL_VALUE_ERRORS):  # subclases de ValueError con detalle interno
        return UNEXPECTED
    if isinstance(exc, AgentError | ValueError):
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


def _refresh(ws: Workspace, conv: Conversation) -> None:
    view = pending_from_state(ws.graph.get_state(conv.config))
    _record_view(conv, view)
    if view is None and conv.finished is None:
        conv.finished = "La conversación ha terminado."


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
    if conv not in ws.conversations:
        ws.conversations.insert(0, conv)
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
        conv.finished = "Has descartado la propuesta. Nada se ha escrito en Jira."
