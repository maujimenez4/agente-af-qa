"""Composición de la sesión de Streamlit y acceso a su estado.

La UI compone **solo** con `build_app_container` y `build_graph` (nunca instancia adaptadores).
Un router de modelos por sesión para el selector (RF-42). El checkpointer es en memoria: las
conversaciones se pierden al reiniciar la app (T-52).
"""

from dataclasses import dataclass
from typing import Any, cast

import streamlit as st
from pydantic import ValidationError

from adapters.base import User
from adapters.errors import AgentError
from adapters.llm.router import ModelRouter
from app.conversation import Conversation, Workspace
from app.flows import FlowId
from app.origin import StartRequest
from app.text import md_escape
from core.config import AppConfig, ConfigError, build_config
from core.factories import build_app_container, model_router
from core.graph import build_graph, memory_checkpointer
from core.logging import get_logger

log = get_logger(__name__)

_KEY = "agente"
INVALID_CONFIG = "La configuración no es válida: revisa los valores del `.env`."


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
    current: str | None = None  # thread_id de la conversación abierta
    pending: Conversation | None = None  # conversación por arrancar (Mixta 2b)
    model_label: str | None = None
    previous_phase: int | None = None


def state() -> SessionState:
    if _KEY not in st.session_state:
        st.session_state[_KEY] = SessionState()
    return cast(SessionState, st.session_state[_KEY])


def compose(session: SessionState) -> None:
    """Compone contenedor y grafo una vez por sesión; deja el error en español si falla."""
    if session.workspace is not None or session.compose_error is not None:
        return
    try:
        config = build_config()
        router = model_router(config)
        container = build_app_container(config, router=router)
        graph = build_graph(container, memory_checkpointer())
    except (ConfigError, AgentError, ValidationError) as exc:
        # Un ValidationError (p. ej. un valor no válido en `.env`) incluiría el valor recibido.
        session.compose_error = INVALID_CONFIG if isinstance(exc, ValidationError) else str(exc)
        log.warning("no se pudo componer la app", action="compose", error_type=type(exc).__name__)
        return
    session.config, session.router = config, router
    session.workspace = Workspace(container=container, graph=graph)


def current_conversation(session: SessionState) -> Conversation | None:
    if session.workspace is None or session.current is None:
        return None
    return next(
        (c for c in session.workspace.conversations if c.thread_id == session.current), None
    )


COMPOSER_KEYS = ("start_text", "restrictions")  # textos que no pasan a otra conversación


def clear_composer() -> None:
    for key in COMPOSER_KEYS:
        st.session_state.pop(key, None)


def composer_text() -> str:
    """Lo escrito en el cuadro de Mixta 1 (la necesidad), para no perderlo al elegir en Jira."""
    return str(st.session_state.get("start_text", ""))


def open_origin(session: SessionState, request: StartRequest) -> None:
    """Fija el origen: recuerda el proyecto como último usado (T-50) y abre Mixta 2."""
    if session.workspace is None or session.user is None:
        return
    try:
        project = session.workspace.container.projects.choose(
            session.user.username, request.project
        )
    except (AgentError, ValueError) as exc:
        st.error(md_escape(str(exc)))
        return
    go(session, "origen", request=request, project=project)


def go(session: SessionState, screen: str, **changes: Any) -> None:
    """Cambia de pantalla y vuelve a pintar."""
    session.screen = screen
    for name, value in changes.items():
        setattr(session, name, value)
    st.rerun()
