"""Marco común (`docs/specs/UI.md` §2): conversaciones, selector de modelo y aviso de prueba."""

import streamlit as st

from app.models import AUTOMATIC, apply_model, model_options
from app.session import SessionState, clear_composer, go
from app.text import md_escape


def simulation_notice(session: SessionState) -> None:
    if session.workspace and session.workspace.container.publish_mode == "simulation":
        st.warning(
            "Modo de prueba: al aprobar verás lo que se haría en Jira, "
            "pero no se escribirá nada.",
            icon=":material/info:",
        )


def sidebar(session: SessionState) -> None:
    user = session.user
    if user is None or session.workspace is None:
        return
    with st.sidebar:
        st.markdown(f"**{md_escape(user.username)}** · {md_escape(_role_label(user.role))}")
        if st.button("Cerrar sesión", key="logout"):
            st.session_state.clear()
            st.rerun()
        st.divider()
        if st.button("Nueva conversación", key="new_conv", width="stretch"):
            clear_composer()
            go(session, "inicio", current=None, request=None, pending=None)
        conversations = session.workspace.conversations
        if conversations:
            st.caption("Conversaciones")
        for conv in conversations:
            status = conv.finished or (f"Versión {conv.view.version}" if conv.view else "")
            label = md_escape(f"{conv.request.project} · {conv.title}")
            if st.button(label, key=f"conv-{conv.thread_id}", help=status or None):
                go(session, "iterar", current=conv.thread_id)
        st.caption(
            "Las conversaciones se guardan solo mientras la app está abierta; "
            "retomarlas después llegará con T-52."
        )
        st.divider()
        _model_selector(session)


def _model_selector(session: SessionState) -> None:
    if session.config is None or session.router is None:
        return
    options = model_options(session.config)
    labels = [option.label for option in options]
    current = session.model_label if session.model_label in labels else AUTOMATIC
    label = st.selectbox("Modelo", labels, index=labels.index(current), key="model")
    if label == session.model_label:
        return
    choice = next(option.choice for option in options if option.label == label)
    try:
        apply_model(session.router, choice)
    except ValueError as exc:
        st.error(md_escape(str(exc)))
        return
    session.model_label = label


def _role_label(role: str) -> str:
    return {"functional": "Analista funcional", "qa": "QA", "admin": "Administración"}.get(
        role, role
    )
