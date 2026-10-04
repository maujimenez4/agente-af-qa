"""Marco común (`docs/specs/UI.md` §2): conversaciones, revisiones de calidad (PA-277),
selector de modelo y aviso de prueba."""

import streamlit as st

from adapters.base import User
from adapters.errors import AgentError
from app.conversation import message_for
from app.listing import flow_label, group_by_day, status_label
from app.models import AUTOMATIC, apply_model, model_options
from app.origin import fix_origin
from app.quality import review_item
from app.session import SessionState, clear_composer, go
from app.text import md_escape


def simulation_notice(session: SessionState) -> None:
    if session.workspace and session.workspace.container.publish_mode == "simulation":
        st.warning(
            "Modo de prueba: al aprobar verás lo que se haría en Jira, pero no se escribirá nada.",
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
            go(
                session,
                "inicio",
                current=None,
                request=None,
                pending=None,
                alternatives=[],
                choices=[],
            )
        _conversations(session, user)
        _quality_reviews(session, user)
        st.divider()
        _model_selector(session)


def _conversations(session: SessionState, user: User) -> None:
    """Conversaciones de la persona (T-52), agrupadas por día, para retomarlas."""
    ws = session.workspace
    if ws is None:
        return
    try:
        rows = ws.container.conversations.list_for(user.username)
    except AgentError as exc:
        st.error(md_escape(str(exc)))
        if st.button("Reintentar", key="retry_list"):
            st.rerun()
        return
    if not rows:
        st.caption("Aún no tienes conversaciones.")
        return
    for day, group in group_by_day(rows):
        st.caption(md_escape(day))
        for row in group:
            label = md_escape(f"{row.project_key} · {row.title}")
            details = md_escape(f"{flow_label(row)} · {status_label(row)}")
            if st.button(
                f"{label}  \n{details}",
                key=f"conv-{row.thread_id}",
                width="stretch",
                type="primary" if row.thread_id == session.current else "secondary",
            ):
                go(session, "iterar", current=row.thread_id, pending=None)


def _quality_reviews(session: SessionState, user: User) -> None:
    """Revisiones de calidad de la persona (PA-277): «Informe listo», «En marcha» o «Error».

    Solo el título (flujo y clave) y el estado: nunca texto del informe.
    """
    store = session.quality_store
    if store is None:
        return
    try:
        rows = store.list_for(user.username)
    except AgentError as exc:
        st.error(md_escape(message_for(exc)))
        if st.button("Reintentar", key="retry_quality_list"):
            st.rerun()
        return
    if not rows:
        return
    st.caption("Revisiones de calidad")
    for row in rows:
        title, state = review_item(row)
        if st.button(
            f"{md_escape(title)}  \n{md_escape(state)}",
            key=f"quality-{row.id}",
            width="stretch",
            type="primary" if row.id == session.quality else "secondary",
        ):
            request = fix_origin("review", row.project_key, key=row.issue_key)
            go(session, "calidad", request=request, quality=row.id, current=None, pending=None)


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
        st.error(md_escape(message_for(exc)))
        return
    session.model_label = label


def _role_label(role: str) -> str:
    return {"functional": "Analista funcional", "qa": "QA", "admin": "Administración"}.get(
        role, role
    )
