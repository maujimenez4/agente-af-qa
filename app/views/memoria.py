"""Memoria (T-33, RF-36/RF-38): las memorias de las HU publicadas, solo lectura.

Lista con buscador y filtro por proyecto, y el detalle por secciones. Las memorias las escribió el
LLM: se pintan campo a campo con `md_escape` (nunca el `.md` con `st.markdown`), y el `.md` solo se
ofrece para descargar. Nada llama al LLM ni escribe en Jira.
"""

import streamlit as st

from adapters.errors import AgentError
from app.conversation import message_for
from app.session import SessionState, go
from app.text import md_escape, md_lines
from core import assistant
from core.memory.reader import MAX_QUERY_CHARS, MemoryDocument, MemoryReader, MemorySummary
from core.permissions import Permission, can

EMPTY = "Aún no hay memorias. Se generan al publicar una HU en Jira (modo real)."
NO_MATCH = "Ninguna memoria coincide con la búsqueda."
ALL_PROJECTS = "Todos los proyectos"
SECTIONS = (
    ("Alcance", "scope"),
    ("Reglas de negocio", "business_rules"),
    ("Decisiones", "decisions"),
    ("Dependencias", "dependencies"),
    ("Cambios", "changes"),
    ("Criterios de aceptación", "acceptance_criteria"),
    ("Referencias", "references"),
)


def render(session: SessionState) -> None:
    user, ws = session.user, session.workspace
    if user is None or ws is None or not can(user, Permission.VIEW_MEMORY):
        go(session, "inicio")
        return
    st.subheader("Memoria")
    st.caption(
        f"Resúmenes de las HU publicadas que {assistant.ASSISTANT_NAME} reutiliza como contexto"
        " · lectura"
    )
    container = ws.container
    reader = MemoryReader(container.memory_dir, container.vector_store)
    try:
        visible = [project.key for project in container.issue_tracker.list_projects()]
        if session.memory is not None:
            _detail(session, reader.get(session.memory, visible))
            return
        _list(session, reader, visible)
    except AgentError as exc:
        st.error(md_escape(message_for(exc)))
        if st.button("Reintentar", key="memory-retry"):
            st.rerun()


def _list(session: SessionState, reader: MemoryReader, visible: list[str]) -> None:
    filters = st.columns([3, 1])
    query = filters[0].text_input(
        "Buscar", max_chars=MAX_QUERY_CHARS, placeholder="Clave o texto", key="memory-q"
    )
    choice = filters[1].selectbox("Proyecto", [ALL_PROJECTS, *visible], key="memory-project")
    project = None if choice == ALL_PROJECTS else choice
    rows = reader.summaries(visible, project=project, query=query)
    if not rows:
        st.info(NO_MATCH if query.strip() or project else EMPTY)
        return
    for row in rows:
        if st.button(
            f"{md_escape(row.key)} · {md_escape(row.title)}  \n{md_escape(_details(row))}",
            key=f"memory-{row.key}",
            width="stretch",
        ):
            go(session, "memoria", memory=row.key)


def _details(row: MemorySummary) -> str:
    indexed = "Indexada en el RAG" if row.indexed else "No indexada"
    return f"v{row.version} · actualizada el {row.updated_at:%d/%m/%Y %H:%M} UTC · {indexed}"


def _detail(session: SessionState, document: MemoryDocument | None) -> None:
    if st.button("Volver a la lista", key="memory-back", icon=":material/arrow_back:"):
        go(session, "memoria", memory=None)
    if document is None:
        st.warning("No existe esa memoria o no la puedes ver.")
        return
    summary, memory = document.summary, document.memory
    st.markdown(f"#### {md_escape(summary.key)} · {md_escape(summary.title)}")
    st.caption(md_escape(_details(summary)))
    st.markdown("**Objetivo**")
    st.markdown(md_escape(memory.objective or "—"))
    for title, name in SECTIONS:
        value = getattr(memory, name)
        st.markdown(f"**{title}**")
        if isinstance(value, str):
            st.markdown(md_escape(value or "—"))
        else:
            st.markdown(md_lines(value) if value else "—")
    st.download_button(
        "Descargar .md",
        data=document.markdown,
        file_name=f"memoria-{summary.key}.md",
        mime="text/markdown",
        key="memory-download",
        icon=":material/download:",
    )
