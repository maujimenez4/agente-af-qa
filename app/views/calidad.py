"""Mixta 5 · Revisar la calidad (`docs/specs/UI.md` §4.8, T-48, RF-18): solo lectura.

No pasa por el grafo ni por la aprobación y nada se escribe en Jira. El informe viene del LLM:
se pinta campo a campo con `md_escape` (nunca `to_markdown()` con `st.markdown`), y el `.md`
solo se ofrece para descargar (PA-64).

PA-277: cada revisión se guarda en `QualityReviewStore` (en marcha → informe listo o error) y la
pantalla pinta lo guardado; la barra lateral la vuelve a abrir tras recargar o reiniciar.
"""

from uuid import uuid4

import streamlit as st

from adapters.errors import AgentError, RateLimitError
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
from app.session import SessionState, go, open_quality
from app.text import md_escape, md_lines
from app.views.frame import simulation_notice
from core.logging import get_logger
from core.projects import project_of
from core.quality import QualityReviewer, QualityReviewStore, StoredQualityReview, new_review
from core.tracing import operation as traced_operation
from schemas.quality import QualityReport

log = get_logger(__name__)

FAILED_CODE = "quality_failed"
RATE_LIMITED_CODE = "rate_limited"
STILL_RUNNING = (
    "Esta revisión sigue en marcha o se interrumpió antes de terminar. Si no avanza, lánzala de "
    "nuevo."
)


def render(session: SessionState) -> None:
    request, user, ws = session.request, session.user, session.workspace
    store = session.quality_store
    if request is None or user is None or ws is None or store is None or request.key is None:
        go(session, "inicio")
        return
    head = st.columns([4, 1])
    head[0].subheader(md_escape(f"Calidad de {request.key} · Revisar la calidad · solo lectura"))
    with head[1]:
        st.html(phase_q(2, previous=session.previous_phase))
        st.caption("Informe · no publica")
    session.previous_phase = 2

    try:
        review = open_quality(session)
    except AgentError as exc:
        st.error(md_escape(message_for(exc)))
        if st.button("Reintentar", key="quality-reload"):
            st.rerun()
        return
    if review is None or review.issue_key != request.key:
        review = _run(session, store, request.key, list(request.excluded_sources))
        if review is None:
            return
        session.quality = review.id

    if review.state == "running":
        st.info(STILL_RUNNING)
        _retry_actions(session)
        return
    if review.state == "error" or review.report is None:
        st.error(md_escape(review.error_message or message_for(Exception())))
        _retry_actions(session)
        return
    report = review.report
    chat, panel = st.columns([5, 6], gap="large")
    with chat:
        with st.chat_message("assistant"):
            st.markdown(md_escape(review_message(review.issue_key, report)))
            st.markdown(md_escape(report.summary))
        if review.model:
            st.caption(md_escape(f"Informe generado con {review.model}"))
    with panel:
        _report(report)
    _footer(session, review, report, request.project, request.excluded_sources)
    simulation_notice(session)


def _run(
    session: SessionState, store: QualityReviewStore, key: str, excluded: list[str]
) -> StoredQualityReview | None:
    """Revisión con progreso (dos llamadas al LLM, lento en CPU). Sin reintento automático.

    Se guarda en marcha antes de llamar al modelo y después con el informe o el error; la
    pantalla abre lo guardado (PA-277).
    """
    ws, user = session.workspace, session.user
    if ws is None or user is None:
        return None
    review_id = str(uuid4())
    try:
        store.create(new_review(review_id, user.username, key))
    except AgentError as exc:
        _show_failure(session, exc)
        return None
    with st.status("Revisando la calidad…", expanded=True) as status:
        st.markdown("  \n".join(f"· {step}" for step in REVIEW_STEPS))
        try:
            with traced_operation(  # T-40
                ws.container.tracer,
                "revisar_calidad",
                session_id=review_id,
                user_id=user.username,
                mode="functional",
                flow="review",
                project=project_of(key),
            ):
                result = QualityReviewer(ws.container).review(user, key, excluded)
        except Exception as exc:  # el mensaje pasa por la lista blanca; el tipo va al log
            status.update(label="No se ha podido revisar la HU", state="error")
            log.warning(
                "error al revisar la calidad",
                user=user.username,
                action="review_quality",
                artifact_id=review_id,
                error_type=type(exc).__name__,
            )
            _record_failure(store, review_id, user.username, exc)
            session.quality = review_id  # una recarga muestra el error, no vuelve a revisar
            _show_failure(session, exc)
            return None
        status.update(label="Informe listo", state="complete", expanded=False)
    try:
        store.finish(review_id, result)
        return store.get(review_id)
    except AgentError as exc:
        _show_failure(session, exc)
        return None


def _record_failure(
    store: QualityReviewStore, review_id: str, username: str, exc: Exception
) -> None:
    """Guarda el error con el mensaje de la lista blanca (nunca el texto interno)."""
    retry_after = exc.retry_after if isinstance(exc, RateLimitError) else None
    code = RATE_LIMITED_CODE if isinstance(exc, RateLimitError) else FAILED_CODE
    try:
        store.fail(review_id, code, message_for(exc), retry_after)
    except AgentError as error:
        log.warning(
            "no se guardó el error de la revisión",
            user=username,
            action="review_quality",
            artifact_id=review_id,
            error_type=type(error).__name__,
        )


def _show_failure(session: SessionState, exc: Exception) -> None:
    st.error(md_escape(message_for(exc)))
    _retry_actions(session)


def _retry_actions(session: SessionState) -> None:
    cols = st.columns(2)
    if cols[0].button("Reintentar", type="primary", key="quality-retry"):
        go(session, "calidad", quality=None)
    if cols[1].button("Volver al inicio", key="quality-home"):
        go(session, "inicio", request=None, quality=None)


def _report(report: QualityReport) -> None:
    st.markdown("**INVEST**")
    for row in invest_rows(report):
        with st.container(border=True):
            st.markdown(f"**{md_escape(row.letter)} · {md_escape(row.name)}** · {row.verdict}")
            st.caption(md_escape(row.reason))
    findings = finding_rows(report)
    st.markdown(f"**Hallazgos ({len(findings)})**")
    if not findings:
        st.caption("Sin hallazgos.")
    for finding in findings:
        with st.container(border=True):
            st.markdown(f"**{md_escape(finding.kind)}** · {md_escape(finding.target)}")
            st.markdown(md_escape(finding.explanation))
            st.markdown(f"*Propuesta:* {md_escape(finding.proposal)}")
    if report.open_questions:
        st.markdown("**Preguntas para negocio**")
        st.markdown(md_lines(report.open_questions))


def _footer(
    session: SessionState,
    review: StoredQualityReview,
    report: QualityReport,
    project: str,
    excluded: tuple[str, ...],
) -> None:
    key = review.issue_key
    cols = st.columns(2)
    cols[0].download_button(
        "Descargar informe",
        data=report_download(key, report),
        file_name=report_filename(key),
        mime="text/markdown",
        key="quality-download",
    )
    user = session.user
    if user is not None and cols[1].button(
        md_escape(f"Evolucionar {key} con esto"), type="primary", key="quality-evolve"
    ):
        request = evolve_request(key, report, project, excluded)
        conv = Conversation(request=request, user=user.username)
        go(session, "generando", pending=conv, current=conv.thread_id, quality=None)
    st.caption(
        "Este flujo no publica en Jira. Evolucionar abre una conversación nueva con estas "
        "mejoras como punto de partida."
    )
