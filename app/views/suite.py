"""QA 3 · Iterar la suite (`docs/specs/UI.md` §6.3, T-28): pestañas Casos, Cobertura, Datos y
riesgos y Estrategia.

La suite viene del LLM: los textos van escapados con `md_escape` o en widgets de texto plano
(`st.code` para el Gherkin, `st.text` para la estrategia, `st.dataframe` para las tablas). La
matriz sale de `TestSuite.coverage()`, no del Markdown del adjunto. *Editar a mano* una suite
queda fuera de T-28 (PA-158): se itera conversando.
"""

import streamlit as st

from app.conversation import Conversation, resume
from app.qa import (
    COVERAGE_BADGE,
    attachment_names,
    case_rows,
    coverage_rows,
    data_rows,
)
from app.review import ReviewView, discard_answer
from app.session import SessionState, go
from app.text import md_escape, md_lines
from schemas.test_case import TestSuite


def render_panel(
    session: SessionState,
    conv: Conversation,
    view: ReviewView,
    previous: ReviewView | None,
    *,
    latest: bool,
) -> None:
    suite = view.artifact.content
    if not isinstance(suite, TestSuite):
        return
    st.success(COVERAGE_BADGE, icon=":material/task_alt:")
    before = previous.artifact.content if previous is not None else None
    rows = case_rows(suite, view.version, before if isinstance(before, TestSuite) else None)
    matrix_name, strategy_name = attachment_names(suite.story_jira_key)
    tabs = st.tabs([f"Casos ({len(rows)})", "Cobertura", "Datos y riesgos", "Estrategia"])
    with tabs[0]:
        for row in rows:
            with st.container(border=True):
                head = f"**{md_escape(row.id)} · {md_escape(row.title)}**"
                if row.new_in:
                    head += f" · {md_escape(row.new_in)}"
                st.markdown(head)
                st.caption(md_escape(f"{row.type} · prioridad {row.priority} · {row.verifies}"))
                if row.preconditions:
                    st.markdown("*Precondiciones*")
                    st.markdown(md_lines(row.preconditions))
                st.dataframe(
                    [
                        {"Acción": action, "Datos": data, "Resultado esperado": expected}
                        for action, data, expected in row.steps
                    ],
                    hide_index=True,
                )
                if row.gherkin:
                    with st.expander("Gherkin"):
                        st.code(row.gherkin, language="gherkin")
    with tabs[1]:
        st.dataframe(coverage_rows(suite), hide_index=True)
        st.caption(
            md_escape(
                f"Se adjunta como {matrix_name}. Cada CA y cada RN tiene al menos un caso; si no "
                "fuera así, la suite no se podría aprobar."
            )
        )
    with tabs[2]:
        data = data_rows(suite)
        st.markdown("**Datos sintéticos** (identificadores ficticios)")
        if data:
            st.dataframe(data, hide_index=True)
        else:
            st.caption("La suite no trae datos sintéticos.")
        for title, items in (
            ("Riesgos", suite.risks),
            ("Dependencias", suite.dependencies),
            ("Áreas de impacto", suite.impact_areas),
        ):
            if items:
                st.markdown(f"**{title}**")
                st.markdown(md_lines(items))
    with tabs[3]:
        st.text(suite.strategy_md)  # texto plano: el Markdown del LLM no se interpreta
        st.caption(md_escape(f"Se adjunta como {strategy_name}."))
    if latest and not conv.finished:
        _actions(session, conv)


def _actions(session: SessionState, conv: Conversation) -> None:
    ws = session.workspace
    if ws is None:
        return
    cols = st.columns(3)
    cols[0].button(
        "Editar a mano",
        key="edit-suite",
        disabled=True,
        help="Editar a mano una suite llegará más adelante (PA-158); pide los cambios en el chat.",
    )
    if cols[1].button("Descartar", key="discard"):
        resume(ws, conv, discard_answer(), session.user)
        st.rerun()
    if cols[2].button("Revisar y aprobar", key="approve", type="primary"):
        go(session, "recibo")
