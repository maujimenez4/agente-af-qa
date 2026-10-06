"""Mixta 4 · QA 5 · Resultado de la publicación (`docs/specs/UI.md` §4.7 y §6.5; RF-31).

Simulado (la aprobación queda gastada, PA-41), publicado (operaciones hechas y claves), en parte
(errores de RNF-13) o publicado sin memoria (PA-251). *Reintentar solo los fallidos* queda
desactivado: el hilo termina tras `publish` y el grafo no ofrece volver a publicar con la misma
aprobación (PA-153).
"""

import streamlit as st

from app.anim import phase_q
from app.conversation import Conversation
from app.review import Outcome
from app.session import SessionState
from app.text import md_escape, md_lines
from app.views.frame import simulation_notice

RETRY_PENDING = "Disponible cuando el grafo permita volver a publicar con la misma aprobación."


def render(session: SessionState, conv: Conversation, outcome: Outcome) -> None:
    published = outcome.kind in ("published", "published_without_memory")
    phase = 4 if published else 3
    head = st.columns([4, 1])
    head[0].subheader(md_escape(conv.title))
    with head[1]:
        st.html(phase_q(phase, previous=session.previous_phase))
        st.caption(f"Fase {phase} de 4 · {'Publicado' if published else 'Aprobada'}")
    session.previous_phase = phase

    if outcome.kind == "simulated":
        _simulated(outcome)
    elif outcome.kind == "partial":
        _partial(outcome)
    else:
        _published(outcome)
    st.caption(md_escape(f"Versión {outcome.version} aprobada por {outcome.approved_by}."))
    simulation_notice(session)


def _simulated(outcome: Outcome) -> None:
    st.success("Aprobada · simulada", icon=":material/task_alt:")
    st.markdown(
        "**Publicación simulada** · No se ha escrito nada en Jira. Esto es lo que se habría "
        "hecho, y queda en la auditoría:"
    )
    st.markdown(md_lines(outcome.operations))
    st.caption(
        "La aprobación se ha usado en esta simulación. Para publicar de verdad, activa el modo "
        "real y vuelve a revisar y aprobar."
        + (" La memoria se genera al publicar de verdad." if outcome.story else "")
    )


def _published(outcome: Outcome) -> None:
    st.success("Publicado en Jira", icon=":material/task_alt:")
    st.markdown("Estas operaciones ya están en Jira:")
    st.markdown(md_lines(outcome.operations))
    if outcome.published_keys:
        st.markdown(md_escape("Claves: " + ", ".join(outcome.published_keys)))
    if outcome.errors:  # p. ej. vínculos que fallaron (RNF-13), aunque además falle la memoria
        st.markdown("**No se pudo hacer:**")
        st.markdown(md_lines(outcome.errors))
    if outcome.kind == "published_without_memory":
        st.warning(
            "La HU está publicada, pero no se ha podido generar su memoria; no tendrá "
            "prioridad en las próximas propuestas hasta que se regenere (PA-251).",
            icon=":material/warning:",
        )
        if outcome.message:
            st.caption(md_escape(outcome.message))
    elif outcome.story:
        st.caption(
            "La memoria se ha generado e indexado; tendrá prioridad en las próximas propuestas."
        )


def _partial(outcome: Outcome) -> None:
    st.warning("Publicada en parte", icon=":material/warning:")
    if outcome.published_keys:
        st.markdown(md_escape("Hecho en Jira: " + ", ".join(outcome.published_keys)))
    st.markdown("**No se pudo hacer:**")
    st.markdown(md_lines(outcome.errors))
    st.caption(
        "Lo creado se mantiene. Volver a publicar no duplica lo que ya existe en Jira (RNF-13)."
    )
    st.button(
        "Reintentar solo los fallidos",
        key="retry-failed",
        disabled=True,
        help=RETRY_PENDING,
    )
    st.caption(RETRY_PENDING)
