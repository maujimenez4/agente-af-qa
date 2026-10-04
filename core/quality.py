"""Flujo «Revisar la calidad de una HU» (T-48, RF-18): informe sin publicar nada.

Es un flujo propio, de solo lectura (decisión del día 6): no pasa por el grafo, no hay
aprobación ni publicación y nada se escribe en Jira. Pasos:
1. la incidencia de Jira y su contexto (el mismo `gather` que el grafo, con fuentes excluidas);
2. la HU pasada a la plantilla (`StoryWriter.structure`) para tener IDs de CA y RN;
3. el informe (`QualityReport`) con el prompt `review_quality`, validado sin confiar en el LLM:
   seis letras INVEST, hallazgos solo sobre IDs de la HU y citas solo del contexto. Si falla,
   un reintento con los errores y después un error en español.

Las revisiones se guardan (PA-272, PA-103) en `quality_reviews` (migración `0006`) con
`QualityReviewStore`: estado, informe validado y error en la forma común; nunca la HU ni los
prompts. Así sobreviven a un reinicio y aparecen en la lista de la persona («Informe listo»).
"""

import json
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from adapters.base import Message, TaskType, User
from adapters.errors import AgentError, ExternalServiceError
from core.container import Container
from core.context.budget import PromptLimits, default_prompt_limits
from core.context.service import build_context_service, is_story
from core.functional.citations import (
    CitationError,
    allowed_refs_text,
    citation_errors,
    with_real_excerpts,
)
from core.functional.context import StoryContext, render_context
from core.functional.writer import PromptLoader, StoryWriter, fill_placeholders, fit_context
from core.graph.state import normalize_excluded_sources
from core.logging import get_logger
from core.permissions import Permission, require
from core.projects import normalize_issue_key, project_of
from core.rag.prompts import load_prompt
from core.text import escape_data
from schemas.quality import QualityReport
from schemas.user_story import UserStory

log = get_logger("core.quality")
# Provisional (UI.md §3): revisar la calidad es del analista funcional, como generar una HU.
REVIEW_PERMISSION = Permission.GENERATE_STORY


class QualityReviewError(AgentError):
    """El informe no es válido tras el reintento; mensaje en español para la UI."""


@dataclass(frozen=True)
class QualityReview:
    """Resultado del flujo: el informe y la HU revisada (estructurada desde Jira)."""

    jira_key: str
    report: QualityReport
    story: UserStory
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int

    def evolve_feedback(self) -> list[str]:
        """Feedback inicial para «Evolucionar con esto» (`initial_state(..., feedback=...)`)."""
        return evolve_feedback_of(self.report)


def evolve_feedback_of(report: QualityReport) -> list[str]:
    """Una línea por hallazgo, con el ID afectado: el feedback de «Evolucionar con esto»."""
    items = []
    for finding in report.findings:
        target = f"{finding.target_id}: " if finding.target_id else ""
        items.append(f"{target}{finding.proposal}")
    return items


class QualityReviewer:
    def __init__(self, container: Container, *, prompt_loader: PromptLoader = load_prompt) -> None:
        self.c = container
        self._load = prompt_loader

    @property
    def limits(self) -> PromptLimits:
        """Ventana y topes de salida de la configuración del contenedor (PA-114)."""
        if self.c.config is not None:
            return PromptLimits.from_config(self.c.config)
        return default_prompt_limits()

    def review(
        self, user: User, issue_key: str, excluded_sources: list[str] | None = None
    ) -> QualityReview:
        """Informe de calidad de la HU `issue_key`, sin escribir nada en Jira."""
        require(user, REVIEW_PERMISSION)
        started = time.perf_counter()
        key = normalize_issue_key(issue_key)
        project = project_of(key)
        origin = {"kind": "story", "key": key, "project": project}
        excluded = normalize_excluded_sources(excluded_sources, key)  # mismas reglas que el grafo
        issue = self.c.issue_tracker.get_issue(key)
        if not is_story(issue.issue_type):  # PA-222: antes de llamar al LLM
            raise QualityReviewError(
                f"{key} es de tipo «{issue.issue_type[:40]}»: la revisión de calidad solo se hace "
                "sobre historias de usuario."
            )
        gathered = build_context_service(self.c, project).gather(origin, issue, excluded=excluded)
        ctx = StoryContext(
            origin_kind="story",
            origin_key=key,
            jira=list(gathered.jira),
            rag=list(gathered.rag),
        )

        origin_only = StoryContext(origin_kind="story", origin_key=key, jira=[issue])
        writer = StoryWriter(self.c.llm, prompt_loader=self._load, limits=self.limits)
        structured = writer.structure(origin_only)
        story = structured.story
        report, provider, model, version, tokens_in, tokens_out = self._report(ctx, story)
        log.info(
            "calidad revisada",
            user=user.username,
            action="review_quality",
            model=f"{provider}/{model}",
            findings=len(report.findings),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return QualityReview(
            jira_key=key,
            report=report,
            story=story,
            provider=provider,
            model=model,
            prompt_version=version,
            input_tokens=structured.input_tokens + tokens_in,
            output_tokens=structured.output_tokens + tokens_out,
        )

    def _report(
        self, ctx: StoryContext, story: UserStory
    ) -> tuple[QualityReport, str, str, str, int, int]:
        prompt = self._load("review_quality")
        review_ctx = StoryContext(
            origin_kind="story",
            origin_key=ctx.origin_key,
            jira=ctx.jira,
            rag=ctx.rag,
            previous=story,
        )
        review_ctx, messages = fit_context(  # PA-114: nunca se desborda la ventana en silencio
            review_ctx,
            lambda c: [
                Message(role="system", content=prompt.text),
                Message(role="user", content=render_context(c)),
            ],
            self.limits,
            TaskType.REVIEW_STORY,
            action="review_quality",
        )
        sources = review_ctx.sources()
        result = self.c.llm.generate_structured(messages, QualityReport, TaskType.REVIEW_STORY)
        report, tokens_in, tokens_out = result.content, result.input_tokens, result.output_tokens

        errors = report_errors(report, story, sources)
        if errors:
            retry_text = self._load("quality_retry").text
            previous = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
            first = report

            def retry_messages(c: StoryContext) -> list[Message]:
                # Las fuentes permitidas y los errores, del contexto que de verdad se envía.
                allowed = c.sources()
                feedback = fill_placeholders(
                    retry_text,
                    {
                        "errors": "\n".join(f"- {e}" for e in report_errors(first, story, allowed)),
                        "ids": _ids_text(story),
                        "allowed": allowed_refs_text(allowed),
                    },
                )
                return [
                    Message(role="system", content=prompt.text),
                    Message(role="user", content=render_context(c)),
                    Message(role="assistant", content=previous),
                    Message(role="user", content=feedback),
                ]

            # PA-114: el reintento es el mensaje más largo; también pasa por la guarda.
            review_ctx, retry = fit_context(
                review_ctx,
                retry_messages,
                self.limits,
                TaskType.REVIEW_STORY,
                action="review_quality_retry",
            )
            sources = review_ctx.sources()
            result = self.c.llm.generate_structured(retry, QualityReport, TaskType.REVIEW_STORY)
            report = result.content
            tokens_in += result.input_tokens
            tokens_out += result.output_tokens
            if citation_errors(report, sources):
                raise CitationError(
                    "El informe cita fuentes que no están en el contexto recibido. "
                    "Vuelve a revisar la HU o revisa las fuentes disponibles."
                )
            if report_errors(report, story, sources):
                raise QualityReviewError(
                    "El informe de calidad señala criterios o reglas que no existen en la HU. "
                    "Vuelve a revisarla."
                )
        report = with_real_excerpts(report, sources)
        return report, result.provider, result.model, prompt.version, tokens_in, tokens_out


_TRACE_ID = re.compile(r"\b(?:CA|RN)-\d+\b")  # IDs citados en el texto libre (PA-222)


def report_errors(report: QualityReport, story: UserStory, sources: list) -> list[str]:
    """Problemas del informe; lista vacía si es válido (citas e IDs de la HU)."""
    ids = {c.id for c in story.acceptance_criteria} | {r.id for r in story.business_rules}
    errors = list(citation_errors(report, sources))
    for finding in report.findings:
        if finding.target_id and finding.target_id not in ids:
            errors.append(f"«{finding.target_id}» no es un criterio ni una regla de la HU")
    # PA-222: los CA y RN citados en el texto libre también deben existir en la HU.
    texts = [report.summary, *report.open_questions]
    texts += [t for f in report.findings for t in (f.explanation, f.proposal)]
    cited = dict.fromkeys(m.group(0) for text in texts for m in _TRACE_ID.finditer(text))
    unknown = [i for i in cited if i not in ids]
    errors += [f"«{i}» se cita en el informe pero no existe en la HU" for i in unknown]
    return errors


def _ids_text(story: UserStory) -> str:
    lines = [f"- {c.id}: {escape_data(c.title)}" for c in story.acceptance_criteria]
    lines += [f"- {r.id}: {escape_data(r.description)}" for r in story.business_rules]
    return "\n".join(lines)


# --- Revisiones guardadas (PA-272, PA-103) -------------------------------------------------------

SERVICE = "postgres"
MAX_REVIEWS_PER_PERSON = 20  # cada persona conserva sus revisiones más recientes
INTERRUPTED = "La revisión se interrumpió al reiniciar el servidor; vuelve a lanzarla."

QualityState = Literal["running", "done", "error"]


@dataclass(frozen=True)
class StoredQualityReview:
    """Una revisión lanzada por una persona: estado, informe y error (nunca la HU ni prompts)."""

    id: str
    username: str
    issue_key: str
    created_at: datetime
    updated_at: datetime
    state: QualityState = "running"
    report: QualityReport | None = None
    model: str | None = None
    prompt_version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error_code: str | None = None
    error_message: str | None = None
    retry_after: float | None = None

    @property
    def project_key(self) -> str:
        return project_of(self.issue_key)

    @property
    def title(self) -> str:
        """Solo el flujo y la clave, como las conversaciones: nunca texto del informe."""
        return f"Revisar la calidad de {self.issue_key}"

    def evolve_feedback(self) -> list[str]:
        return evolve_feedback_of(self.report) if self.report else []


def new_review(review_id: str, username: str, issue_key: str) -> StoredQualityReview:
    now = datetime.now(UTC)
    return StoredQualityReview(
        id=review_id, username=username, issue_key=issue_key, created_at=now, updated_at=now
    )


class QualityReviewStore(Protocol):
    def create(self, review: StoredQualityReview) -> None:
        """Guarda una revisión en marcha; la persona conserva las `MAX_REVIEWS_PER_PERSON`."""
        ...

    def finish(self, review_id: str, result: QualityReview) -> None: ...

    def fail(
        self, review_id: str, code: str, message: str, retry_after: float | None = None
    ) -> None: ...

    def get(self, review_id: str) -> StoredQualityReview | None: ...

    def list_for(
        self, username: str, limit: int = MAX_REVIEWS_PER_PERSON
    ) -> list[StoredQualityReview]:
        """Las revisiones de la persona, de la más reciente a la más antigua."""
        ...

    def interrupt_running(self) -> int:
        """Al arrancar (un solo proceso): las que estaban en marcha pasan a error."""
        ...


class InMemoryQualityReviewStore:
    def __init__(self) -> None:
        self.rows: dict[str, StoredQualityReview] = {}
        self._lock = threading.Lock()

    def create(self, review: StoredQualityReview) -> None:
        with self._lock:
            self.rows[review.id] = review
            # Orden de inserción: dos revisiones seguidas pueden tener la misma marca de tiempo.
            mine = [r for r in self.rows.values() if r.username == review.username]
            for old in mine[:-MAX_REVIEWS_PER_PERSON]:  # en SQL, por `created_at`
                del self.rows[old.id]

    def finish(self, review_id: str, result: QualityReview) -> None:
        self._update(review_id, **_result_fields(result))

    def fail(
        self, review_id: str, code: str, message: str, retry_after: float | None = None
    ) -> None:
        self._update(
            review_id,
            state="error",
            error_code=code,
            error_message=message,
            retry_after=retry_after,
        )

    def get(self, review_id: str) -> StoredQualityReview | None:
        return self.rows.get(review_id)

    def list_for(
        self, username: str, limit: int = MAX_REVIEWS_PER_PERSON
    ) -> list[StoredQualityReview]:
        mine = [r for r in self.rows.values() if r.username == username]
        return sorted(mine, key=lambda r: r.updated_at, reverse=True)[:limit]

    def interrupt_running(self) -> int:
        running = [r.id for r in self.rows.values() if r.state == "running"]
        for review_id in running:
            self.fail(review_id, "operation_failed", INTERRUPTED)
        return len(running)

    def _update(self, review_id: str, **changes: object) -> None:
        with self._lock:
            if (row := self.rows.get(review_id)) is not None:
                self.rows[review_id] = replace(row, updated_at=datetime.now(UTC), **changes)  # type: ignore[arg-type]


_METADATA = sa.MetaData()
QUALITY_REVIEWS = sa.Table(
    "quality_reviews",
    _METADATA,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("username", sa.String, nullable=False),
    sa.Column("issue_key", sa.String, nullable=False),
    sa.Column("project_key", sa.String, nullable=False),
    sa.Column("state", sa.String, nullable=False),
    sa.Column("report", postgresql.JSONB),
    sa.Column("model", sa.String),
    sa.Column("prompt_version", sa.String),
    sa.Column("input_tokens", sa.Integer, nullable=False),
    sa.Column("output_tokens", sa.Integer, nullable=False),
    sa.Column("error_code", sa.String),
    sa.Column("error_message", sa.String),
    sa.Column("retry_after", sa.Float),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


class SqlQualityReviewStore:
    """`quality_reviews` (migración `0006`) con SQLAlchemy Core."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlQualityReviewStore":
        return cls(sa.create_engine(url, pool_pre_ping=True, hide_parameters=True))

    def create(self, review: StoredQualityReview) -> None:
        table = QUALITY_REVIEWS
        keep = (
            sa.select(table.c.id)
            .where(table.c.username == review.username)
            .order_by(table.c.created_at.desc())
            .limit(MAX_REVIEWS_PER_PERSON)
        )
        self._run(
            [
                table.insert().values(
                    id=_uuid(review.id),
                    username=review.username,
                    issue_key=review.issue_key,
                    project_key=review.project_key,
                    state=review.state,
                    input_tokens=0,
                    output_tokens=0,
                    created_at=review.created_at,
                    updated_at=review.updated_at,
                ),
                table.delete().where(
                    table.c.username == review.username, table.c.id.not_in(keep.scalar_subquery())
                ),
            ],
            "guardar la revisión de calidad",
        )

    def finish(self, review_id: str, result: QualityReview) -> None:
        fields = _result_fields(result)
        fields["report"] = result.report.model_dump(mode="json")
        self._update(review_id, fields)

    def fail(
        self, review_id: str, code: str, message: str, retry_after: float | None = None
    ) -> None:
        self._update(
            review_id,
            {
                "state": "error",
                "error_code": code,
                "error_message": message,
                "retry_after": retry_after,
            },
        )

    def get(self, review_id: str) -> StoredQualityReview | None:
        try:
            uid = _uuid(review_id)
        except ValueError:
            return None
        rows = self._fetch(sa.select(QUALITY_REVIEWS).where(QUALITY_REVIEWS.c.id == uid))
        return rows[0] if rows else None

    def list_for(
        self, username: str, limit: int = MAX_REVIEWS_PER_PERSON
    ) -> list[StoredQualityReview]:
        table = QUALITY_REVIEWS
        query = (
            sa.select(table)
            .where(table.c.username == username)
            .order_by(table.c.updated_at.desc())
            .limit(limit)
        )
        return self._fetch(query)

    def interrupt_running(self) -> int:
        table = QUALITY_REVIEWS
        statement = (
            table.update()
            .where(table.c.state == "running")
            .values(
                state="error",
                error_code="operation_failed",
                error_message=INTERRUPTED,
                updated_at=datetime.now(UTC),
            )
        )
        try:
            with self._engine.begin() as conn:
                return conn.execute(statement).rowcount
        except sa.exc.SQLAlchemyError:
            raise ExternalServiceError(
                "No se pudieron revisar las revisiones de calidad en marcha.", service=SERVICE
            ) from None

    def _update(self, review_id: str, values: dict[str, object]) -> None:
        try:
            uid = _uuid(review_id)
        except ValueError:
            # Los ids los genera el servidor: uno que no es uuid no existe.
            raise ExternalServiceError(
                "No se pudo guardar la revisión de calidad.", service=SERVICE
            ) from None
        statement = (
            QUALITY_REVIEWS.update()
            .where(QUALITY_REVIEWS.c.id == uid)
            .values(updated_at=datetime.now(UTC), **values)
        )
        self._run([statement], "guardar la revisión de calidad")

    def _run(self, statements: list[sa.Executable], verb: str) -> None:
        try:
            with self._engine.begin() as conn:
                for statement in statements:
                    conn.execute(statement)
        except sa.exc.SQLAlchemyError:
            raise ExternalServiceError(f"No se pudo {verb}.", service=SERVICE) from None

    def _fetch(self, query: sa.Select) -> list[StoredQualityReview]:
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(query).mappings().all()
            return [_from_row(row) for row in rows]
        except sa.exc.SQLAlchemyError:
            raise ExternalServiceError(
                "No se pudieron leer las revisiones de calidad.", service=SERVICE
            ) from None
        except (ValueError, ValidationError, TypeError, AttributeError, KeyError):
            # Fila dañada: falla cerrado sin mostrar su contenido.
            raise ExternalServiceError(
                "Una revisión de calidad guardada no es válida.", service=SERVICE
            ) from None


def _result_fields(result: QualityReview) -> dict[str, object]:
    return {
        "state": "done",
        "report": result.report,
        "model": f"{result.provider}/{result.model}",
        "prompt_version": result.prompt_version,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def _uuid(value: str) -> UUID:
    return UUID(str(value))


def _from_row(row: object) -> StoredQualityReview:
    data = dict(row)  # type: ignore[call-overload]
    report = data.pop("report")
    data.pop("project_key", None)  # se deduce de la clave
    data["id"] = str(data["id"])
    for name in ("created_at", "updated_at"):
        if data[name].tzinfo is None:  # SQLite no guarda la zona: se escribe en UTC
            data[name] = data[name].replace(tzinfo=UTC)
    return StoredQualityReview(
        report=QualityReport.model_validate(report) if report is not None else None, **data
    )
