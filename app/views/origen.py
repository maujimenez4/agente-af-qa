"""Mixta 2 · Origen fijado (`docs/specs/UI.md` §4.3): HU parecida, operación, restricciones y
panel «Antes de generar» con las fuentes que se pueden desmarcar (T-53, T-51).

En el flujo de QA es QA 1 (§6.1, T-28): HU de origen reconocida, tipos de caso (RF-22) y
extras, que van como primer feedback (decisión del día 6).
"""

from dataclasses import replace

import streamlit as st

from adapters.errors import AgentError
from app.anim import phase_q
from app.conversation import Conversation, message_for
from app.origin import (
    StartRequest,
    preview_origin,
    request_from_option,
    with_excluded,
    with_restrictions,
)
from app.qa import CASE_TYPES, EXTRAS, REQUIRED_TYPES, qa_feedback
from app.session import SessionState, clear_composer, go, show_notices
from app.sources import describe_card, excluded_refs, issue_card, source_label
from app.text import md_escape
from app.views.frame import simulation_notice
from core.guided_start import GuidedStart, SourcePreview, StartOption


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
    show_notices(session)

    chat, panel = st.columns([5, 6], gap="large")
    with chat:
        if request.text:
            with st.chat_message("user"):
                st.markdown(md_escape(request.text))
        _similar(session, request)
        if request.flow == "tests":
            _qa_origin(session, request)
        st.info(
            f"**Operación fijada: {md_escape(request.describe())}**  \n"
            "No cambia durante la conversación; es lo único que se podrá aprobar y publicar.",
            icon=":material/lock:",
        )
        if request.flow == "tests" and request.key:
            st.caption(
                md_escape(
                    f"Los casos serán subtareas de {request.key} con la etiqueta «caso-prueba»; "
                    "la estrategia y la matriz, adjuntos."
                )
            )
    with panel:
        _before_generating(session, request, user.username)
    simulation_notice(session)


def _similar(session: SessionState, request: StartRequest) -> None:
    """Tarjetas «HU parecida» (T-53, búsqueda por texto sin IA) con su épica y nº de CA y RN."""
    if not session.alternatives:
        return
    with st.chat_message("assistant"):
        st.caption("Búsqueda en Jira por texto · sin IA")
        for option in session.alternatives:
            _option_card(session, request, option)


def _option_card(session: SessionState, request: StartRequest, option: StartOption) -> None:
    ws = session.workspace
    key = option.origin.get("key")
    if ws is None or key is None:
        return
    with st.container(border=True):
        try:
            card = issue_card(ws.container.issue_tracker.get_issue(key))  # PA-56
        except AgentError:
            summary = option.issue.summary if option.issue else ""
            st.markdown(f"**{md_escape(key)}** · {md_escape(summary)}")
        else:
            st.markdown(f"**{md_escape(card.key)}** · {md_escape(card.summary)}")
            st.caption(md_escape(describe_card(card)))
        cols = st.columns(2)
        if cols[0].button(md_escape(option.label), type="primary", key=f"alt-{key}"):
            try:
                chosen = request_from_option(request.flow, option, request.text)
            except ValueError as exc:
                st.error(md_escape(message_for(exc)))
                return
            go(session, "origen", request=chosen, alternatives=[])
        if request.kind == "need" and cols[1].button("Crear HU nueva", key=f"new-{key}"):
            go(session, "origen", alternatives=[])


def _qa_origin(session: SessionState, request: StartRequest) -> None:
    """QA 1: «Clave reconocida en Jira · sin IA» con la épica y el nº de CA y RN de la HU."""
    ws = session.workspace
    if ws is None or request.key is None:
        return
    with st.chat_message("assistant"):
        st.caption("Clave reconocida en Jira · sin IA")
        try:
            card = issue_card(ws.container.issue_tracker.get_issue(request.key))
        except AgentError as exc:
            st.error(md_escape(message_for(exc)))
            return
        st.markdown(f"**{md_escape(card.key)}** · {md_escape(card.summary)}")
        st.caption(md_escape(describe_card(card)))
        st.caption("El modo QA parte siempre de una HU existente.")


def _qa_options() -> tuple[str, ...]:
    """Casillas de tipos de caso (RF-22) e «Incluir además»; devuelve el primer feedback."""
    st.markdown("**Tipos de caso**")
    types = set()
    for kind, label in CASE_TYPES:
        required = kind in REQUIRED_TYPES
        if st.checkbox(label, value=True, disabled=required, key=f"qa-type-{kind.value}"):
            types.add(kind)
    st.caption("Positivos y negativos son obligatorios: la suite necesita al menos uno de cada.")
    st.markdown("**Incluir además**")
    extras = {key for key, label in EXTRAS if st.checkbox(label, value=True, key=f"qa-{key}")}
    return qa_feedback(types, extras)


def _before_generating(session: SessionState, request: StartRequest, username: str) -> None:
    st.markdown("**Antes de generar**")
    st.markdown(f"**Operación** · {md_escape(request.describe())}")
    st.caption("Se puede cambiar solo antes de generar.")
    if st.button("Cambiar", key="change_op"):
        go(session, "inicio", request=None, alternatives=[])
    if request.flow == "review":  # Mixta 5: solo lectura, sin restricciones ni conversación
        excluded = _sources(session, request)
        if st.button("Revisar la calidad", type="primary", key="review"):
            clear_composer()
            go(session, "calidad", request=with_excluded(request, excluded), quality=None)
        st.caption("Dos llamadas al modelo. No cambia nada en Jira.")
        return
    if request.flow == "tests":  # QA 1: tipos de caso y extras en lugar de restricciones
        feedback = _qa_options()
        excluded = _sources(session, request)
        if st.button("Generar la suite", type="primary", key="generate"):
            final = with_excluded(replace(request, extra_feedback=feedback), excluded)
            conv = Conversation(request=final, user=username)
            clear_composer()
            go(session, "generando", current=conv.thread_id, pending=conv)
        st.caption("Una llamada al modelo. Después itera conversando.")
        return
    restrictions = st.text_area(
        "Restricciones (opcional)",
        placeholder="Por ejemplo: mismas reglas que en la web.",
        key="restrictions",
    )
    excluded = _sources(session, request)
    if st.button("Generar propuesta", type="primary", key="generate"):
        final = with_excluded(with_restrictions(request, restrictions), excluded)
        conv = Conversation(request=final, user=username)
        clear_composer()
        go(session, "generando", current=conv.thread_id, pending=conv)
    st.caption("Una llamada al modelo. Después itera conversando.")


def _preview(session: SessionState, request: StartRequest) -> list[SourcePreview] | None:
    """Vista previa de las fuentes, una vez por origen (mismo `gather` que el grafo, sin LLM)."""
    ws = session.workspace
    if ws is None:
        return None
    cache_key = f"preview-{hash(request)}"  # proyecto, origen, texto y exclusiones
    if cache_key not in st.session_state:
        try:
            origin = preview_origin(request)
            st.session_state[cache_key] = GuidedStart(ws.container).preview_sources(
                origin, list(request.excluded_sources)
            )
        except (AgentError, ValueError) as exc:
            st.error(md_escape(message_for(exc)))
            st.caption("Puedes generar igualmente; se usarán todas las fuentes.")
            return None
    return list(st.session_state[cache_key])


def _sources(session: SessionState, request: StartRequest) -> list[str]:
    """Casillas de las fuentes; devuelve las desmarcadas (`excluded_sources`)."""
    sources = _preview(session, request)
    if not sources:
        if sources is not None:
            st.caption("No se han encontrado fuentes para este origen.")
        return []
    st.markdown(f"**Fuentes ({len(sources)})**")
    checked: dict[str, bool] = {}
    for source in sources:
        checked[source.ref] = st.checkbox(
            md_escape(source_label(source)),
            value=True,
            disabled=source.required,
            key=f"src-{request.key or request.project}-{source.ref}",
        )
        if not checked[source.ref]:
            st.caption("No influirá en la propuesta.")
    return excluded_refs(sources, checked)
