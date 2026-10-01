"""Mixta 1 · Inicio (`docs/specs/UI.md` §4.1): flujo, proyecto y origen."""

import streamlit as st

from adapters.errors import AgentError
from app.flows import FlowId, default_flow, flow_by_id, flow_cards, shows_flows
from app.origin import fix_origin
from app.session import SessionState, composer_text, open_origin
from app.text import md_escape
from app.views import elegir_jira
from app.views.frame import simulation_notice
from core.permissions import can
from core.projects import normalize_project_key

MAX_RECENT = 5


def render(session: SessionState) -> None:
    user = session.user
    if user is None or session.workspace is None:
        return
    st.title("¿En qué trabajamos hoy?")
    st.caption(
        "Elige qué hacemos y de qué partimos. Después lo mejoramos conversando. "
        "Nada se publica en Jira sin tu aprobación."
    )
    if not shows_flows(user):
        st.info(
            "El rol de administración configura el agente y no genera artefactos. "
            "Ajustes estará disponible en T-29 e Historial en T-45."
        )
        return

    flow = _flow_cards(session)
    project = _project_selector(session)
    if flow is None or project is None:
        simulation_notice(session)
        return

    text = st.text_area(
        "Qué necesitas", placeholder=flow_by_id(flow).placeholder, height=110, key="start_text"
    )
    cols = st.columns([1, 1, 3])
    if cols[0].button("Elegir en Jira", key="pick_jira"):
        elegir_jira.open_dialog(session, flow)
    if cols[1].button("Continuar", type="primary", key="continue"):
        try:
            request = fix_origin(flow, project, text=text)
        except ValueError as exc:
            st.error(md_escape(str(exc)))
        else:
            open_origin(session, request)

    _recent(session, project, flow)
    simulation_notice(session)


def _flow_cards(session: SessionState) -> FlowId | None:
    cards = flow_cards(session.user)
    current = session.flow if any(c.enabled and c.flow.id == session.flow for c in cards) else None
    current = current or default_flow(session.user)
    session.flow = current
    cols = st.columns(2)
    for index, card in enumerate(cards):
        label = f"{'● ' if card.flow.id == current else ''}{card.flow.label}"
        with cols[index % 2]:
            if st.button(
                label,
                key=f"flow-{card.flow.id}",
                disabled=not card.enabled,
                help=card.hint,
                width="stretch",
                type="primary" if card.flow.id == current else "secondary",
            ):
                session.flow = card.flow.id
                st.rerun()
            st.caption(card.hint)
    return current


def _project_selector(session: SessionState) -> str | None:
    """Todos los proyectos que ve la conexión, con el último usado preseleccionado (T-50)."""
    user, ws = session.user, session.workspace
    if user is None or ws is None:
        return None
    try:
        choice = ws.container.projects.available(user.username)
    except AgentError as exc:
        st.error(md_escape(str(exc)))
        return None
    if not choice.projects:
        st.warning("La conexión con Jira no ve ningún proyecto.")
        return None
    keys = [p.key for p in choice.projects]
    names = {p.key: p.name for p in choice.projects}
    current = session.project if session.project in keys else choice.preselected
    index = keys.index(current) if current in keys else 0
    selected = st.selectbox(
        "Proyecto de Jira",
        keys,
        index=index,
        format_func=lambda key: f"{key} · {names[key]}",
        key="project_select",
    )
    if selected != session.project:
        try:
            session.project = ws.container.projects.choose(user.username, selected)
        except (AgentError, ValueError) as exc:
            st.error(md_escape(str(exc)))
            return None
    return session.project


def _recent(session: SessionState, project: str, flow: FlowId) -> None:
    """Recientes del proyecto: incidencias actualizadas hace poco (solo lectura)."""
    ws, user = session.workspace, session.user
    if ws is None or user is None or not can(user, flow_by_id(flow).permission):
        return
    try:
        recent = ws.container.issue_tracker.search(
            f'project = "{normalize_project_key(project)}" ORDER BY updated DESC',
            limit=MAX_RECENT,
        )
    except (AgentError, ValueError):
        return
    if flow != "need":  # solo una necesidad nueva puede partir de una épica
        recent = [issue for issue in recent if not _is_epic(issue.issue_type)]
    if not recent:
        return
    st.caption(f"Recientes en {md_escape(project)}")
    cols = st.columns(min(len(recent), MAX_RECENT))
    for col, issue in zip(cols, recent, strict=False):
        is_epic = _is_epic(issue.issue_type)
        if col.button(
            md_escape(f"{issue.key} · {issue.summary[:40]}"),
            key=f"recent-{issue.key}",
            help=md_escape(issue.issue_type),
        ):
            try:
                request = fix_origin(
                    flow,
                    project,
                    key=issue.key,
                    kind="epic" if is_epic else "story",
                    text=composer_text(),  # la necesidad escrita no se pierde (B3)
                )
            except ValueError as exc:
                st.error(md_escape(str(exc)))
            else:
                open_origin(session, request)


def _is_epic(issue_type: str) -> bool:
    return issue_type.strip().lower() in ("epic", "épica")
