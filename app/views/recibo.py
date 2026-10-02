"""Recibo de aprobación (`docs/specs/UI.md` §4.6 y §6.4; contrato §5; RF-31, RNF-16).

Es la revisión humana: una casilla por operación del `plan` del payload de `human_review`.
*Aprobar y publicar* solo se activa con todas marcadas (ayuda visual: la garantía es la huella
en el grafo) y devuelve exactamente la huella del último payload. Todo texto del artefacto y de
Jira se muestra escapado.
"""

import streamlit as st

from adapters.base import User
from app.anim import phase_q
from app.conversation import Conversation, message_for, publish_permission, resume
from app.review import (
    ReviewView,
    approve_answer,
    discard_answer,
    iterate_answer,
    receipt_items,
    receipt_progress,
    source_count,
)
from app.session import SessionState, current_conversation, go
from app.text import md_escape
from app.views.frame import simulation_notice
from core.permissions import can


def render(session: SessionState) -> None:
    conv = current_conversation(session)
    ws, user = session.workspace, session.user
    if conv is None or ws is None or user is None or conv.view is None or conv.finished:
        go(session, "iterar" if conv is not None else "inicio")
        return
    view = conv.view
    head = st.columns([4, 1])
    head[0].subheader(md_escape(f"{conv.title} · versión {view.version} lista para revisar"))
    with head[1]:
        st.html(phase_q(3, previous=session.previous_phase))
        st.caption("Fase 3 de 4 · Revisión")
    session.previous_phase = 3
    if conv.error:
        st.error(md_escape(conv.error))
    if view.error:  # respuesta rechazada (huella, decisión): la revisión sigue abierta
        st.error(md_escape(view.error))

    approved = _receipt(session, conv, view)
    st.caption(
        f"Generado con IA a partir de {source_count(view)} fuentes. "
        "Revisa cada operación antes de aprobar."
    )
    allowed = can(user, publish_permission(conv))
    cols = st.columns(3)
    if cols[0].button("Descartar", key="receipt-discard"):
        resume(ws, conv, discard_answer(), user)
        go(session, "iterar")
    if cols[1].button("Volver a la propuesta", key="receipt-back"):
        go(session, "iterar")
    if cols[2].button(
        "Aprobar y publicar",
        type="primary",
        key="receipt-approve",
        disabled=not (approved and allowed),
        help=None if allowed else "No tienes permiso para realizar esta acción.",
    ):
        with st.spinner("Publicando…"):
            resume(ws, conv, approve_answer(view), user)
        go(session, "iterar" if conv.view is None else "recibo")

    _regenerate(session, conv, user)
    _history(conv)
    st.caption("Al publicar quedará registrado quién aprobó, cuándo y qué claves se crearon.")
    simulation_notice(session)


def _receipt(session: SessionState, conv: Conversation, view: ReviewView) -> bool:
    """Casillas «Qué se hará en Jira»; True si están todas marcadas."""
    st.markdown("**Qué se hará en Jira**")
    st.caption(md_escape(view.target))
    items = receipt_items(view)
    checked: dict[str, bool] = {}
    for item in items:
        # La clave lleva la huella: con una versión nueva las casillas empiezan sin marcar.
        checked[item.id] = st.checkbox(
            md_escape(item.text), key=f"rcpt-{conv.thread_id}-{view.fingerprint[:16]}-{item.id}"
        )
        if item.detail:
            st.caption(md_escape(item.detail))
    done, complete = receipt_progress(items, checked)
    if not items:
        st.warning("La propuesta no tiene operaciones que publicar.")
    st.markdown("**Todo revisado**" if complete else f"{done} de {len(items)} revisadas")
    return complete


def _regenerate(session: SessionState, conv: Conversation, user: User) -> None:
    """*Volver a generar*: una petición de cambio (`iterate`) y de vuelta a la propuesta."""
    ws = session.workspace
    if ws is None:
        return
    with st.expander("Volver a generar"):
        text = st.text_area("Qué quieres cambiar", key=f"receipt-iterate-{conv.thread_id}")
        if st.button("Volver a generar", key="receipt-regenerate"):
            try:
                answer = iterate_answer(text)
            except ValueError as exc:
                st.error(md_escape(message_for(exc)))
                return
            conv.messages.append(("user", answer["feedback"]))
            with st.spinner("Escribiendo la respuesta…"):
                resume(ws, conv, answer, user)
            go(session, "iterar")


def _history(conv: Conversation) -> None:
    """Historial de la versión: modelo, versión del prompt (nunca su texto) y quién itera."""
    with st.expander(f"Historial ({len(conv.versions)} versiones)"):
        for version in conv.versions:
            artifact = version.artifact
            parts = [
                f"v{version.version}",
                artifact.model_used or "modelo sin registrar",
                f"prompt v{artifact.prompt_version}" if artifact.prompt_version else "",
                conv.user,
            ]
            st.markdown(md_escape(" · ".join(part for part in parts if part)))
