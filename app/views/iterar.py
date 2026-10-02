"""Mixta 3 · Iterar (`docs/specs/UI.md` §4.5): chat, versiones, pestañas, editar y descartar.

*Revisar y aprobar* abre el recibo (T-31); tras aprobar, esta pantalla muestra el resultado
(Mixta 4). Los CA y RN cambiados frente a la versión de partida llevan «Cambiado en vN» o
«Nueva» (PA-73). El contenido del artefacto viene del LLM y se muestra siempre escapado.
"""

import streamlit as st

from app.anim import phase_q, typing_q
from app.conversation import Conversation, message_for, resume
from app.editing import LIST_FIELDS, STEP_FIELDS, TEXT_FIELDS, form_to_content, story_to_form
from app.progress import phase_label, phase_of
from app.review import (
    ReviewView,
    change_marks,
    describe_operation,
    discard_answer,
    edit_answer,
    iterate_answer,
    summarize,
)
from app.session import SessionState, current_conversation, go
from app.text import md_escape, md_lines
from app.views import resultado
from app.views.frame import simulation_notice
from schemas.user_story import UserStory

MULTILINE_FIELDS = frozenset({"description", "business_goal"})  # conservan los saltos de línea


def render(session: SessionState) -> None:
    conv = current_conversation(session)
    if conv is None or session.workspace is None:
        go(session, "inicio", current=None)  # el aviso de `current_conversation` se ve allí
        return
    if conv.outcome is not None:  # aprobada: Mixta 4 · QA 5
        resultado.render(session, conv, conv.outcome)
        return
    view = conv.view
    phase = phase_of(view.artifact.status if view else None)
    head = st.columns([4, 1])
    head[0].subheader(md_escape(conv.title))
    with head[1]:
        st.html(phase_q(phase, previous=session.previous_phase))
        st.caption(phase_label(phase))
    session.previous_phase = phase

    if conv.error:
        st.error(md_escape(conv.error))
    if view and view.error and not st.session_state.get(f"editing-{conv.thread_id}"):
        st.error(md_escape(view.error))  # con el editor abierto se muestra junto a él
    if conv.finished:
        st.info(md_escape(conv.finished))
    if conv.can_restart:
        _restart(session, conv)

    chat, panel = st.columns([5, 6], gap="large")
    with chat:
        _chat(session, conv)
    with panel:
        if conv.versions:
            _panel(session, conv)
    simulation_notice(session)


def _restart(session: SessionState, conv: Conversation) -> None:
    """«Empezar de nuevo» (UI.md §5): conversación nueva con el mismo origen; el hilo no vuelve."""
    if session.user is None:
        return
    if st.button("Empezar de nuevo", type="primary", key=f"restart-{conv.thread_id}"):
        new = Conversation(request=conv.request, user=session.user.username)
        go(session, "generando", pending=new, current=new.thread_id)


# --- Conversación ------------------------------------------------------------------------------


def _chat(session: SessionState, conv: Conversation) -> None:
    if conv.request.text:
        with st.chat_message("user"):
            st.markdown(md_escape(conv.request.text))
    for role, text in conv.messages:
        with st.chat_message(role):
            st.markdown(md_escape(text))
    if conv.finished or conv.view is None or session.workspace is None:
        return
    suggestions = ["Añade un criterio de error", "Revisa INVEST", "Busca la fuente de los CA"]
    cols = st.columns(len(suggestions))
    for col, suggestion in zip(cols, suggestions, strict=True):
        if col.button(suggestion, key=f"sugg-{suggestion}"):
            _iterate(session, conv, suggestion)
    message = st.chat_input("Pide un cambio a la propuesta", key=f"chat-{conv.thread_id}")
    if message:
        _iterate(session, conv, message)


def _iterate(session: SessionState, conv: Conversation, message: str) -> None:
    ws = session.workspace
    if ws is None:
        return
    try:
        answer = iterate_answer(message)
    except ValueError as exc:
        st.error(md_escape(message_for(exc)))
        return
    conv.messages.append(("user", answer["feedback"]))
    typing = st.empty()
    typing.html(typing_q())
    before = conv.view.version if conv.view else 0
    resume(ws, conv, answer, session.user)
    typing.empty()
    if conv.view and conv.view.version != before:
        conv.messages.append(("assistant", summarize(conv.view)))
    st.rerun()


# --- Panel de la propuesta ---------------------------------------------------------------------


def _panel(session: SessionState, conv: Conversation) -> None:
    labels = [f"v{v.version}" for v in conv.versions]
    # La clave incluye el número de versiones: con una versión nueva el selector vuelve a la
    # última (en 1.64 la radio conserva el valor guardado aunque cambien las opciones).
    chosen = st.radio(
        "Versión",
        labels,
        index=len(labels) - 1,
        horizontal=True,
        key=f"ver-{conv.thread_id}-{len(labels)}",
    )
    view = conv.versions[labels.index(chosen)]
    latest = view is conv.versions[-1]
    st.caption(
        md_escape(
            f"{view.target} · {view.artifact.model_used or 'modelo sin registrar'}"
            + ("" if latest else " · versión anterior, solo lectura")
        )
    )
    story = view.artifact.content
    if not isinstance(story, UserStory):
        st.info("La vista de una suite de pruebas llegará con T-28.")
        return
    impact = view.impact
    tabs = st.tabs(
        [
            "Propuesta",
            f"Cambios ({len(impact.diffs) if impact else 0})",
            f"Impacto ({len(impact.affected) if impact else 0})",
            f"Fuentes ({len(story.sources)})",
        ]
    )
    with tabs[0]:
        _story(story, change_marks(view))
    with tabs[1]:
        _changes(view)
    with tabs[2]:
        _impact(view)
    with tabs[3]:
        _sources(conv, story)
    if latest and not conv.finished:
        _actions(session, conv, view, story)


def _story(story: UserStory, marks: dict[str, str]) -> None:
    st.markdown(f"#### {md_escape(story.title)}")
    st.markdown(
        f"**Como** {md_escape(story.role)}, **quiero** {md_escape(story.action)} "
        f"**para** {md_escape(story.benefit)}"
    )
    if story.description:
        st.markdown(md_escape(story.description))
    st.markdown("**Criterios de aceptación**")
    for ca in story.acceptance_criteria:
        with st.container(border=True):
            st.markdown(f"**{md_escape(ca.id)} · {md_escape(ca.title)}**")
            if ca.id in marks:
                st.caption(md_escape(marks[ca.id]))
            for step, label in STEP_FIELDS:
                for line in getattr(ca, step):
                    st.markdown(f"*{label}* {md_escape(line)}")
    if story.business_rules:
        st.markdown("**Reglas de negocio**")
        st.markdown(
            md_lines(
                [
                    f"{rn.id} · {rn.description}" + (f" · {marks[rn.id]}" if rn.id in marks else "")
                    for rn in story.business_rules
                ]
            )
        )
    if story.open_questions:
        st.markdown("**Preguntas abiertas**")
        st.markdown(md_lines(story.open_questions))


def _changes(view: ReviewView) -> None:
    if not view.impact or not view.impact.diffs:
        st.caption("Sin cambios frente a la versión de partida.")
        return
    for diff in view.impact.diffs:
        with st.container(border=True):
            st.markdown(f"**{md_escape(diff.field)}**")
            st.markdown(f"Antes: {md_escape(diff.before) if diff.before else '*(no existía)*'}")
            st.markdown(f"Después: {md_escape(diff.after) if diff.after else '*(eliminado)*'}")


def _impact(view: ReviewView) -> None:
    if not view.impact or not view.impact.affected:
        st.caption("No se han detectado otras HU afectadas.")
    else:
        for item in view.impact.affected:
            st.markdown(f"**{md_escape(item.jira_key)}** · {md_escape(item.reason)}")
    if view.impact and view.impact.regression_notes:
        st.markdown("**Notas de regresión**")
        st.markdown(md_lines(view.impact.regression_notes))
    if view.plan:
        st.markdown("**Qué se haría en Jira al aprobar**")
        st.markdown(md_lines([describe_operation(op) for op in view.plan]))


def _sources(conv: Conversation, story: UserStory) -> None:
    """Fuentes citadas (solo lectura): las desmarcadas se eligieron antes de generar (Mixta 2)."""
    if conv.request.excluded_sources:
        st.caption(
            md_escape("Excluidas antes de generar: " + ", ".join(conv.request.excluded_sources))
        )
    if not story.sources:
        st.caption("La propuesta no cita fuentes.")
        return
    for source in story.sources:
        st.markdown(md_escape(f"{source.ref} · {source.kind}"))
        if source.excerpt:
            st.caption(md_escape(source.excerpt))


# --- Acciones ----------------------------------------------------------------------------------


def _actions(session: SessionState, conv: Conversation, view: ReviewView, story: UserStory) -> None:
    ws = session.workspace
    if ws is None:
        return
    cols = st.columns(3)
    editing_key = f"editing-{conv.thread_id}"
    if cols[0].button("Editar a mano", key="edit"):
        st.session_state[editing_key] = True
    if cols[1].button("Descartar", key="discard"):
        resume(ws, conv, discard_answer(), session.user)
        st.rerun()
    if cols[2].button("Revisar y aprobar", key="approve", type="primary"):
        go(session, "recibo")
    if st.session_state.get(editing_key):
        _editor(session, conv, view, story, editing_key)


def _editor(
    session: SessionState, conv: Conversation, view: ReviewView, story: UserStory, flag: str
) -> None:
    ws = session.workspace
    if ws is None:
        return
    if view.error:  # la edición anterior se rechazó: el motivo junto al editor (UI.md §5)
        st.error(md_escape(view.error))
    initial = story_to_form(story)
    prefix = f"ed-{conv.thread_id}-{view.version}"
    with st.form(prefix):
        form: dict[str, object] = {}
        for name, label in TEXT_FIELDS:
            widget = st.text_area if name in MULTILINE_FIELDS else st.text_input
            form[name] = widget(label, value=initial[name], key=f"{prefix}-{name}")
        for name, label in LIST_FIELDS:
            form[name] = st.text_area(
                f"{label} (una por línea)", value=initial[name], key=f"{prefix}-{name}"
            )
        criteria = []
        for ca in initial["criteria"]:
            ca_key = f"{prefix}-{ca['id']}"
            st.markdown(f"**{md_escape(ca['id'])}**")
            edited = {
                "id": ca["id"],
                "title": st.text_input("Título", value=ca["title"], key=f"{ca_key}-title"),
            }
            for step, label in STEP_FIELDS:
                edited[step] = st.text_area(
                    f"{label} (una por línea)", value=ca[step], key=f"{ca_key}-{step}"
                )
            criteria.append(edited)
        form["criteria"] = criteria
        form["rules"] = [
            {
                "id": rn["id"],
                "description": st.text_input(
                    rn["id"], value=rn["description"], key=f"{prefix}-{rn['id']}"
                ),
            }
            for rn in initial["rules"]
        ]
        save = st.form_submit_button("Guardar como versión nueva", type="primary")
        cancel = st.form_submit_button("Cancelar")
    if cancel:
        st.session_state[flag] = False
        st.rerun()
    if not save:
        return
    try:
        content = form_to_content(story, form)
    except ValueError as exc:
        st.error(md_escape(message_for(exc)))
        return
    resume(ws, conv, edit_answer(view, content), session.user)
    accepted = conv.error is None and conv.view is not None and not conv.view.error
    if accepted and conv.view is not None:
        st.session_state[flag] = False
        saved = f"He guardado tu edición como versión {conv.view.version}."
        conv.messages.append(("assistant", saved))
    st.rerun()
