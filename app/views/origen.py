"""Mixta 2 · Origen fijado (`docs/specs/UI.md` §4.3): operación fijada y restricciones."""

import streamlit as st

from app.anim import phase_q
from app.conversation import Conversation
from app.origin import find_issue_key, fix_origin, with_restrictions
from app.session import SessionState, clear_composer, go
from app.text import md_escape
from app.views.frame import simulation_notice


def render(session: SessionState) -> None:
    request, user = session.request, session.user
    if request is None or user is None or session.workspace is None:
        go(session, "inicio")
        return
    head = st.columns([4, 1])
    title = request.text.splitlines()[0][:80] if request.text else request.describe()
    head[0].subheader(md_escape(title))
    with head[1]:
        st.html(phase_q(1))
        st.caption("Fase 1 de 4 · Contexto")

    if request.text:
        with st.chat_message("user"):
            st.markdown(md_escape(request.text))

    similar = (
        find_issue_key(request.text, prefer_project=request.project)
        if request.kind == "need"
        else None
    )
    if similar:
        with st.chat_message("assistant"):
            st.markdown(
                f"He reconocido la clave **{md_escape(similar)}** en tu texto. "
                "¿La evolucionamos o creamos una HU nueva?"
            )
            cols = st.columns(2)
            if cols[0].button(f"Evolucionar {similar}", type="primary", key="evolve_similar"):
                try:
                    session.request = fix_origin(
                        "evolve", request.project, key=similar, text=request.text
                    )
                except ValueError as exc:
                    st.error(md_escape(str(exc)))
                else:
                    st.rerun()
            cols[1].caption("O sigue abajo para crear una HU nueva con este texto.")
    elif request.kind == "need":
        st.caption(
            "Buscar en Jira una HU parecida por texto (sin IA) estará disponible pronto (T-53)."
        )

    st.info(
        f"**Operación fijada: {md_escape(request.describe())}**  \n"
        "No cambia durante la conversación; es lo único que se podrá aprobar y publicar.",
        icon=":material/lock:",
    )
    if st.button("Cambiar la operación", key="change_op"):
        go(session, "inicio", request=None)

    restrictions = st.text_area(
        "Restricciones (opcional)",
        placeholder="Por ejemplo: mismas reglas que en la web.",
        key="restrictions",
    )
    st.caption(
        "Las fuentes que se usarán se podrán revisar y desmarcar en la pestaña *Fuentes* tras "
        "la primera versión. La vista previa antes de generar llegará con T-53."
    )
    if st.button("Generar propuesta", type="primary", key="generate"):
        conv = Conversation(request=with_restrictions(request, restrictions), user=user.username)
        clear_composer()
        go(session, "generando", current=conv.thread_id, pending=conv)
    st.caption("Una llamada al modelo. Después itera conversando.")
    simulation_notice(session)
