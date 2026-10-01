"""Inicio de sesión (RF-45) con `container.auth.authenticate` y límite de intentos por sesión."""

import streamlit as st

from adapters.errors import AgentError
from app.session import (
    LOGIN_LOCKED,
    SessionState,
    login_locked,
    record_login_failure,
    record_login_success,
)
from app.text import md_escape
from core.logging import get_logger

log = get_logger(__name__)


def render(session: SessionState) -> None:
    st.title("Agente de Análisis Funcional y QA")
    st.caption("Inicia sesión para empezar. Nada se publica en Jira sin tu aprobación.")
    if session.workspace is None:
        return
    locked = login_locked(session)
    with st.form("login", clear_on_submit=False):
        username = st.text_input("Usuario", autocomplete="username")
        password = st.text_input("Contraseña", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Entrar", type="primary", disabled=locked)
    if locked:
        st.error(LOGIN_LOCKED)
        return
    if not submitted:
        return
    try:
        user = session.workspace.container.auth.authenticate(username.strip(), password)
    except AgentError as exc:
        st.error(md_escape(str(exc)))
        return
    if user is None:
        record_login_failure(session)
        log.info("login fallido", action="login_failed")
        if login_locked(session):
            st.rerun()  # el formulario se vuelve a pintar ya desactivado, con el aviso
        st.error("Usuario o contraseña incorrectos.")
        return
    log.info("login", user=user.username, action="login")
    record_login_success(session, user)
    st.rerun()
