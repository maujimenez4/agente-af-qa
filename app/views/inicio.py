"""Mixta 1 · Inicio (`docs/specs/UI.md` §4.1): flujo, proyecto y origen."""

import streamlit as st

from adapters.errors import AgentError
from app.conversation import message_for
from app.flows import FlowId, default_flow, flow_by_id, flow_cards, shows_flows
from app.origin import fix_origin, mode_of, plan_start, request_from_option
from app.session import SessionState, composer_text, open_origin, show_notices
from app.text import md_escape
from app.views import elegir_jira
from app.views.frame import simulation_notice
from core import assistant
from core.guided_start import GuidedStart, StartOption
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
            f"El rol de administración configura {assistant.ASSISTANT_NAME} y no genera "
            "artefactos. "
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
        _guided_start(session, flow, project, text)
    show_notices(session)
    _choices(session, flow)

    _recent(session, project, flow)
    simulation_notice(session)


def _guided_start(session: SessionState, flow: FlowId, project: str, text: str) -> None:
    """Arranque guiado sin IA (T-53): claves que existen en Jira o HU parecidas por texto."""
    ws, user = session.workspace, session.user
    if ws is None or user is None:
        return
    try:
        proposal = GuidedStart(ws.container).propose(text, project, mode_of(flow))
    except (AgentError, ValueError) as exc:
        st.error(md_escape(message_for(exc)))
        return
    plan = plan_start(flow, proposal, project)
    session.notices = list(plan.notices)
    if proposal.project_changed:  # PA-47: se recuerda como último proyecto usado
        try:
            session.project = ws.container.projects.choose(user.username, proposal.project)
        except (AgentError, ValueError) as exc:
            st.error(md_escape(message_for(exc)))
            return
    if plan.error:
        show_notices(session)
        st.error(md_escape(plan.error))
        session.choices = []
        return
    if plan.chosen is None:  # sin clave: la persona elige entre las HU parecidas
        session.choices = plan.alternatives
        st.rerun()
    try:
        request = request_from_option(flow, plan.chosen, text)
    except ValueError as exc:
        st.error(md_escape(message_for(exc)))
        return
    open_origin(session, request, plan.alternatives)


def _choices(session: SessionState, flow: FlowId) -> None:
    """HU parecidas cuando el flujo necesita una clave y no se ha escrito (sin IA)."""
    if not session.choices:
        return
    st.caption(
        "Búsqueda en Jira por texto · sin IA. No he encontrado una clave; ¿es alguna de estas?"
    )
    for option in session.choices:
        _choice_button(session, flow, option)


def _choice_button(session: SessionState, flow: FlowId, option: StartOption) -> None:
    issue = option.issue
    label = f"{option.label} · {issue.summary[:60]}" if issue else option.label
    if st.button(md_escape(label), key=f"choice-{option.kind}-{option.origin.get('key', '')}"):
        try:
            request = request_from_option(flow, option, composer_text())
        except ValueError as exc:
            st.error(md_escape(message_for(exc)))
            return
        open_origin(session, request)


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
        format_func=lambda key: md_escape(f"{key} · {names[key]}"),
        key="project_select",
    )
    if selected != session.project:
        try:
            session.project = ws.container.projects.choose(user.username, selected)
        except (AgentError, ValueError) as exc:
            st.error(md_escape(message_for(exc)))
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
                st.error(md_escape(message_for(exc)))
            else:
                open_origin(session, request)


def _is_epic(issue_type: str) -> bool:
    return issue_type.strip().lower() in ("epic", "épica")
