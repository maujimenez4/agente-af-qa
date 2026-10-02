"""Composición de la sesión de Streamlit y acceso a su estado.

La UI compone **solo** con `build_app_container`, `build_checkpointer` y `build_graph` (nunca
instancia adaptadores). Un router de modelos por sesión para el selector (RF-42). El
checkpointer de PostgreSQL (T-52) se crea una sola vez por proceso, porque abre un pool, y lo
comparten todas las sesiones: las conversaciones sobreviven a un reinicio de la app.
"""

import time
from dataclasses import dataclass, field
from typing import Any, cast

import streamlit as st
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import ValidationError

from adapters.base import User
from adapters.errors import AgentError
from adapters.llm.router import ModelRouter
from app.conversation import Conversation, Workspace, message_for, reopen
from app.flows import FlowId
from app.origin import StartRequest
from app.text import md_escape
from core.config import AppConfig, ConfigError, build_config
from core.factories import (
    build_app_container,
    build_checkpointer,
    build_handoffs,
    model_router,
)
from core.graph import build_graph
from core.guided_start import StartOption
from core.handoff import HandoffStore
from core.logging import get_logger
from core.quality import QualityReview

log = get_logger(__name__)

_KEY = "agente"
INVALID_CONFIG = "La configuración no es válida: revisa los valores del `.env`."
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 300
LOGIN_LOCKED = "Demasiados intentos fallidos. Espera unos minutos antes de volver a intentarlo."


@dataclass
class SessionState:
    """Todo lo que la UI guarda en `st.session_state` para una persona."""

    config: AppConfig | None = None
    router: ModelRouter | None = None
    workspace: Workspace | None = None
    compose_error: str | None = None
    user: User | None = None
    screen: str = "inicio"
    flow: FlowId | None = None
    project: str | None = None
    request: StartRequest | None = None  # origen fijado en Mixta 2, antes de generar
    alternatives: list[StartOption] = field(default_factory=list)  # HU parecidas (T-53)
    choices: list[StartOption] = field(default_factory=list)  # HU para elegir en Mixta 1
    notices: list[str] = field(default_factory=list)  # avisos para la pantalla siguiente
    current: str | None = None  # thread_id de la conversación abierta
    pending: Conversation | None = None  # conversación por arrancar (Mixta 2b)
    quality: QualityReview | None = None  # informe de «Revisar la calidad» (Mixta 5)
    model_label: str | None = None
    previous_phase: int | None = None
    failed_logins: int = 0
    login_locked_until: float = 0.0


def state() -> SessionState:
    if _KEY not in st.session_state:
        st.session_state[_KEY] = SessionState()
    return cast(SessionState, st.session_state[_KEY])


@st.cache_resource(show_spinner=False)
def shared_checkpointer(_config: AppConfig) -> BaseCheckpointSaver:
    """Checkpointer de PostgreSQL, uno por proceso (abre un pool). Un fallo no se cachea."""
    return build_checkpointer(_config)


@st.cache_resource(show_spinner=False)
def shared_handoffs(_config: AppConfig) -> HandoffStore:
    """Entregas de HU a QA (T-54, PA-268), un almacén por proceso como el checkpointer."""
    return build_handoffs(_config)


def compose(session: SessionState) -> None:
    """Compone contenedor y grafo una vez por sesión; deja el error en español si falla."""
    if session.workspace is not None or session.compose_error is not None:
        return
    try:
        config = build_config()
        router = model_router(config)
        container = build_app_container(config, router=router)
        graph = build_graph(
            container,
            checkpointer=shared_checkpointer(config),
            handoffs=shared_handoffs(config),  # T-54 (PA-268): QA encadenada
        )
    except (ConfigError, AgentError, ValidationError) as exc:
        # Un ValidationError (p. ej. un valor no válido en `.env`) incluiría el valor recibido.
        session.compose_error = INVALID_CONFIG if isinstance(exc, ValidationError) else str(exc)
        log.warning("no se pudo componer la app", action="compose", error_type=type(exc).__name__)
        return
    session.config, session.router = config, router
    session.workspace = Workspace(container=container, graph=graph)


def retry_compose(session: SessionState) -> None:
    """*Reintentar* tras un fallo al arrancar (p. ej. PostgreSQL caído, UI.md §7)."""
    session.compose_error = None
    st.rerun()


# --- Inicio de sesión ---------------------------------------------------------------------------


def login_locked(session: SessionState, now: float | None = None) -> bool:
    """Tras `MAX_LOGIN_ATTEMPTS` fallos seguidos, el formulario se bloquea un rato."""
    return (now if now is not None else time.monotonic()) < session.login_locked_until


def record_login_failure(session: SessionState, now: float | None = None) -> None:
    session.failed_logins += 1
    if session.failed_logins >= MAX_LOGIN_ATTEMPTS:
        session.failed_logins = 0
        session.login_locked_until = (now if now is not None else time.monotonic()) + (
            LOGIN_LOCK_SECONDS
        )


def record_login_success(session: SessionState, user: User) -> None:
    session.failed_logins = 0
    session.login_locked_until = 0.0
    session.user = user


# --- Conversaciones ---------------------------------------------------------------------------


def current_conversation(session: SessionState) -> Conversation | None:
    """La conversación abierta; si no está en la sesión, se retoma del checkpointer (T-52).

    Si no se puede retomar (ajena, inexistente o el almacén falla), deja el aviso y None.
    """
    ws, user = session.workspace, session.user
    if ws is None or user is None or session.current is None:
        return None
    try:
        return reopen(ws, user, session.current)
    except Exception as exc:  # el mensaje se filtra con la lista blanca; el tipo va al log
        session.notices.append(message_for(exc))
        session.current = None
        log.warning(
            "no se pudo retomar la conversación",
            user=user.username,
            action="resume_conversation",
            error_type=type(exc).__name__,
        )
        return None


def show_notices(session: SessionState) -> None:
    """Pinta los avisos pendientes (escapados) y los vacía."""
    for notice in session.notices:
        st.warning(md_escape(notice), icon=":material/info:")
    session.notices = []


COMPOSER_KEYS = ("start_text", "restrictions")  # textos que no pasan a otra conversación


def clear_composer() -> None:
    for key in COMPOSER_KEYS:
        st.session_state.pop(key, None)


def composer_text() -> str:
    """Lo escrito en el cuadro de Mixta 1 (la necesidad), para no perderlo al elegir en Jira."""
    return str(st.session_state.get("start_text", ""))


def open_origin(
    session: SessionState,
    request: StartRequest,
    alternatives: list[StartOption] | None = None,
) -> None:
    """Fija el origen: recuerda el proyecto como último usado (T-50) y abre Mixta 2."""
    if session.workspace is None or session.user is None:
        return
    try:
        project = session.workspace.container.projects.choose(
            session.user.username, request.project
        )
    except (AgentError, ValueError) as exc:
        st.error(md_escape(message_for(exc)))
        return
    go(
        session,
        "origen",
        request=request,
        project=project,
        alternatives=list(alternatives or []),
        choices=[],
    )


def go(session: SessionState, screen: str, **changes: Any) -> None:
    """Cambia de pantalla y vuelve a pintar."""
    session.screen = screen
    for name, value in changes.items():
        setattr(session, name, value)
    st.rerun()
