"""Mixta 5 · Revisar la calidad (`docs/specs/UI.md` §4.8, T-48, RF-18): solo lectura.

No pasa por el grafo ni por la aprobación y nada se escribe en Jira. El informe viene del LLM:
se pinta campo a campo con `md_escape` (nunca `to_markdown()` con `st.markdown`), y el `.md`
solo se ofrece para descargar (PA-64).
"""

import streamlit as st

from app.anim import phase_q
from app.conversation import Conversation, message_for
from app.quality import (
    REVIEW_STEPS,
    evolve_request,
    finding_rows,
    invest_rows,
    report_download,
    report_filename,
    review_message,
)
from app.session import SessionState, go
from app.text import md_escape, md_lines
from app.views.frame import simulation_notice
from core.logging import get_logger
from core.quality import QualityReview, QualityReviewer

log = get_logger(__name__)


def render(session: SessionState) -> None:
    request, user, ws = session.request, session.user, session.workspace
    if request is None or user is None or ws is None or request.key is None:
        go(session, "inicio")
        return
    head = st.columns([4, 1])
    head[0].subheader(md_escape(f"Calidad de {request.key} · Revisar la calidad · solo lectura"))
    with head[1]:
        st.html(phase_q(2, previous=session.previous_phase))
        st.caption("Informe · no publica")
    session.previous_phase = 2

    review = session.quality
    if review is None or review.jira_key != request.key:
        review = _run(session, request.key, list(request.excluded_sources))
        if review is None:
            return
        session.quality = review

    chat, panel = st.columns([5, 6], gap="large")
    with chat:
        with st.chat_message("assistant"):
            st.markdown(md_escape(review_message(review)))
            st.markdown(md_escape(review.report.summary))
        st.caption(md_escape(f"Informe generado con {review.provider} · {review.model}"))
    with panel:
        _report(review)
    _footer(session, review, request.project, request.excluded_sources)
    simulation_notice(session)


def _run(session: SessionState, key: str, excluded: list[str]) -> QualityReview | None:
    """Revisión con progreso (dos llamadas al LLM, lento en CPU). Sin reintento automático."""
    ws, user = session.workspace, session.user
    if ws is None or user is None:
        return None
    with st.status("Revisando la calidad…", expanded=True) as status:
        st.markdown("  \n".join(f"· {step}" for step in REVIEW_STEPS))
        try:
            review = QualityReviewer(ws.container).review(user, key, excluded)
        except Exception as exc:  # el mensaje pasa por la lista blanca; el tipo va al log
            status.update(label="No se ha podido revisar la HU", state="error")
            log.warning(
                "error al revisar la calidad",
                user=user.username,
                action="review_quality",
                error_type=type(exc).__name__,
            )
            st.error(md_escape(message_for(exc)))
            cols = st.columns(2)
            if cols[0].button("Reintentar", type="primary", key="quality-retry"):
                st.rerun()
            if cols[1].button("Volver al inicio", key="quality-home"):
                go(session, "inicio", request=None)
            return None
        status.update(label="Informe listo", state="complete", expanded=False)
    return review


def _report(review: QualityReview) -> None:
    st.markdown("**INVEST**")
    for row in invest_rows(review.report):
        with st.container(border=True):
            st.markdown(f"**{md_escape(row.letter)} · {md_escape(row.name)}** · {row.verdict}")
            st.caption(md_escape(row.reason))
    findings = finding_rows(review.report)
    st.markdown(f"**Hallazgos ({len(findings)})**")
    if not findings:
        st.caption("Sin hallazgos.")
    for finding in findings:
        with st.container(border=True):
            st.markdown(f"**{md_escape(finding.kind)}** · {md_escape(finding.target)}")
            st.markdown(md_escape(finding.explanation))
            st.markdown(f"*Propuesta:* {md_escape(finding.proposal)}")
    if review.report.open_questions:
        st.markdown("**Preguntas para negocio**")
        st.markdown(md_lines(review.report.open_questions))


def _footer(
    session: SessionState, review: QualityReview, project: str, excluded: tuple[str, ...]
) -> None:
    cols = st.columns(2)
    cols[0].download_button(
        "Descargar informe",
        data=report_download(review),
        file_name=report_filename(review.jira_key),
        mime="text/markdown",
        key="quality-download",
    )
    user = session.user
    if user is not None and cols[1].button(
        md_escape(f"Evolucionar {review.jira_key} con esto"), type="primary", key="quality-evolve"
    ):
        request = evolve_request(review, project, excluded)
        conv = Conversation(request=request, user=user.username)
        go(session, "generando", pending=conv, current=conv.thread_id, quality=None)
    st.caption(
        "Este flujo no publica en Jira. Evolucionar abre una conversación nueva con estas "
        "mejoras como punto de partida."
    )
