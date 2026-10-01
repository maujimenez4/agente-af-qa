"""Mixta 2b · Generando (`docs/specs/UI.md` §4.4): progreso por nodos del grafo (PA-66)."""

import streamlit as st

from app.anim import phase_q
from app.conversation import Conversation, start
from app.progress import STEPS, completed_steps
from app.review import summarize
from app.session import SessionState, go
from app.text import md_escape
from app.views.frame import simulation_notice

INTERRUPTED = "La generación se interrumpió antes de terminar. Puedes reintentarla."


def render(session: SessionState) -> None:
    conv, ws = session.pending, session.workspace
    if conv is None or ws is None:
        go(session, "iterar" if session.current else "inicio")
        return
    st.subheader(md_escape(conv.title))
    st.html(phase_q(2, previous=1))
    st.caption("Fase 2 de 4 · Generar")
    simulation_notice(session)

    if not conv.started:  # una sola vez: otra ejecución de la página no vuelve a llamar al LLM
        _run(session, conv)
        return
    _failed(session, conv, conv.error or INTERRUPTED)


def _run(session: SessionState, conv: Conversation) -> None:
    ws = session.workspace
    if ws is None:
        return
    done: list[str] = []
    with st.status("Generando la propuesta…", expanded=True) as status:
        placeholder = st.empty()
        placeholder.markdown(_steps_md(0))
        for node in start(ws, conv, session.user):
            done.append(node)
            placeholder.markdown(_steps_md(completed_steps(done)))
        if conv.error or conv.view is None:
            status.update(label="No se ha podido generar la propuesta", state="error")
        else:
            status.update(label="Propuesta lista", state="complete")
    st.caption("Las citas se comprueban antes de mostrar la propuesta; suele tardar menos de 30 s.")
    if conv.error or conv.view is None:
        _failed(session, conv, conv.error or INTERRUPTED)
        return
    conv.messages.append(("assistant", summarize(conv.view)))
    go(session, "iterar", pending=None, current=conv.thread_id)


def _failed(session: SessionState, conv: Conversation, message: str) -> None:
    st.error(md_escape(message))
    cols = st.columns(2)
    if cols[0].button("Reintentar", type="primary", key=f"retry-{conv.thread_id}"):
        retry = Conversation(request=conv.request, user=conv.user)
        go(session, "generando", pending=retry, current=retry.thread_id)
    if cols[1].button("Volver al inicio", key=f"home-{conv.thread_id}"):
        go(session, "inicio", pending=None, current=None)


def _steps_md(completed: int) -> str:
    lines = []
    for index, step in enumerate(STEPS):
        mark = "✓" if index < completed else ("…" if index == completed else "·")
        lines.append(f"{mark} {step.label}")
    return "  \n".join(lines)
