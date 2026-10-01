"""Mixta 1b · Elegir en Jira (`docs/specs/UI.md` §4.2): proyecto → épica → HU.

Solo lectura: `list_projects`, `list_epics`, `list_children` y `get_issue` para una clave.
"""

import streamlit as st

from adapters.errors import AgentError
from app.flows import FlowId
from app.origin import fix_origin
from app.session import SessionState, composer_text, open_origin
from app.text import md_escape
from core.projects import normalize_issue_key


def open_dialog(session: SessionState, flow: FlowId) -> None:
    _dialog(session, flow)


@st.dialog("Elegir en Jira", width="large")
def _dialog(session: SessionState, flow: FlowId) -> None:
    ws, user = session.workspace, session.user
    if ws is None or user is None:
        return
    tracker = ws.container.issue_tracker
    typed = st.text_input("Buscar por clave", placeholder="Por ejemplo DEMO-3", key="pick_key")
    if typed.strip():
        _by_key(session, flow, typed)
        return
    try:
        projects = tracker.list_projects()
        project_col, epic_col, story_col = st.columns(3)
        with project_col:
            st.caption(f"Proyectos que ve la conexión ({len(projects)})")
            project = st.radio(
                "Proyecto",
                [p.key for p in projects],
                index=_index([p.key for p in projects], session.project),
                format_func=lambda key: md_escape(
                    f"{key} · {next(p.name for p in projects if p.key == key)}"
                ),
                label_visibility="collapsed",
                key="pick_project",
            )
        if project is None:
            return
        epics = tracker.list_epics(project)
        with epic_col:
            st.caption(f"Épicas de {md_escape(project)} ({len(epics)})")
            epic = st.radio(
                "Épica",
                [e.key for e in epics],
                format_func=lambda key: md_escape(
                    f"{key} · {next(e.summary for e in epics if e.key == key)}"
                ),
                label_visibility="collapsed",
                key="pick_epic",
            )
            st.caption("Elegir la épica sirve para crear una HU nueva dentro de ella.")
        stories = tracker.list_children(epic) if epic else []
        with story_col:
            st.caption(f"HU de {md_escape(epic or '—')} ({len(stories)})")
            story = st.radio(
                "HU",
                [s.key for s in stories],
                format_func=lambda key: md_escape(
                    f"{key} · {next(s.summary for s in stories if s.key == key)}"
                ),
                label_visibility="collapsed",
                key="pick_story",
            )
    except AgentError as exc:
        st.error(md_escape(str(exc)))
        return

    cols = st.columns(2)
    use_epic = flow == "need" and cols[0].button(
        md_escape(f"Usar la épica {epic}"), key="use_epic", disabled=not epic
    )
    if epic and use_epic:
        _use(session, flow, epic, "epic")
    if story and cols[1].button(md_escape(f"Usar {story}"), type="primary", key="use_story"):
        _use(session, flow, story, "story")


def _by_key(session: SessionState, flow: FlowId, typed: str) -> None:
    ws = session.workspace
    if ws is None:
        return
    try:
        key = normalize_issue_key(typed)
        issue = ws.container.issue_tracker.get_issue(key)
    except (AgentError, ValueError) as exc:
        st.error(md_escape(str(exc)))
        return
    st.markdown(f"**{md_escape(issue.key)}** · {md_escape(issue.summary)}")
    st.caption(md_escape(f"{issue.issue_type} · {issue.status}"))
    kind = "epic" if issue.issue_type.strip().lower() in ("epic", "épica") else "story"
    if st.button(md_escape(f"Usar {issue.key}"), type="primary", key="use_typed"):
        _use(session, flow, issue.key, kind)


def _use(session: SessionState, flow: FlowId, key: str, kind: str) -> None:
    try:
        request = fix_origin(
            flow,
            session.project or key.split("-")[0],
            key=key,
            kind="epic" if kind == "epic" else "story",
            text=composer_text(),  # la necesidad escrita no se pierde (B3)
        )
    except ValueError as exc:
        st.error(md_escape(str(exc)))
        return
    open_origin(session, request)


def _index(keys: list[str], current: str | None) -> int:
    return keys.index(current) if current in keys else 0
