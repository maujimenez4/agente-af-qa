"""Flujo «Revisar la calidad de una HU» (T-48, RF-18): informe sin publicar nada.

Es un flujo propio, de solo lectura (decisión del día 6): no pasa por el grafo, no hay
aprobación ni publicación y nada se escribe en Jira. Pasos:
1. la incidencia de Jira y su contexto (el mismo `gather` que el grafo, con fuentes excluidas);
2. la HU pasada a la plantilla (`StoryWriter.structure`) para tener IDs de CA y RN;
3. el informe (`QualityReport`) con el prompt `review_quality`, validado sin confiar en el LLM:
   seis letras INVEST, hallazgos solo sobre IDs de la HU y citas solo del contexto. Si falla,
   un reintento con los errores y después un error en español.
"""

import json
import time
from dataclasses import dataclass

from adapters.base import Message, TaskType, User
from adapters.errors import AgentError
from core.container import Container
from core.context.service import build_context_service
from core.functional.citations import (
    CitationError,
    allowed_refs_text,
    citation_errors,
    with_real_excerpts,
)
from core.functional.context import StoryContext, escape_data, render_context
from core.functional.writer import PromptLoader, StoryWriter, fill_placeholders
from core.graph.state import normalize_excluded_sources
from core.logging import get_logger
from core.permissions import Permission, require
from core.projects import normalize_issue_key, project_of
from core.rag.prompts import load_prompt
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
        items = []
        for finding in self.report.findings:
            target = f"{finding.target_id}: " if finding.target_id else ""
            items.append(f"{target}{finding.proposal}")
        return items


class QualityReviewer:
    def __init__(self, container: Container, *, prompt_loader: PromptLoader = load_prompt) -> None:
        self.c = container
        self._load = prompt_loader

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
        gathered = build_context_service(self.c, project).gather(origin, issue, excluded=excluded)
        ctx = StoryContext(
            origin_kind="story",
            origin_key=key,
            jira=list(gathered.jira),
            rag=list(gathered.rag),
        )

        origin_only = StoryContext(origin_kind="story", origin_key=key, jira=[issue])
        structured = StoryWriter(self.c.llm, prompt_loader=self._load).structure(origin_only)
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
        sources = review_ctx.sources()
        messages = [
            Message(role="system", content=prompt.text),
            Message(role="user", content=render_context(review_ctx)),
        ]
        result = self.c.llm.generate_structured(messages, QualityReport, TaskType.REVIEW_STORY)
        report, tokens_in, tokens_out = result.content, result.input_tokens, result.output_tokens

        errors = report_errors(report, story, sources)
        if errors:
            feedback = fill_placeholders(
                self._load("quality_retry").text,
                {
                    "errors": "\n".join(f"- {e}" for e in errors),
                    "ids": _ids_text(story),
                    "allowed": allowed_refs_text(sources),
                },
            )
            previous = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
            retry = [
                *messages,
                Message(role="assistant", content=previous),
                Message(role="user", content=feedback),
            ]
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


def report_errors(report: QualityReport, story: UserStory, sources: list) -> list[str]:
    """Problemas del informe; lista vacía si es válido (citas e IDs de la HU)."""
    ids = {c.id for c in story.acceptance_criteria} | {r.id for r in story.business_rules}
    errors = list(citation_errors(report, sources))
    for finding in report.findings:
        if finding.target_id and finding.target_id not in ids:
            errors.append(f"«{finding.target_id}» no es un criterio ni una regla de la HU")
    return errors


def _ids_text(story: UserStory) -> str:
    lines = [f"- {c.id}: {escape_data(c.title)}" for c in story.acceptance_criteria]
    lines += [f"- {r.id}: {escape_data(r.description)}" for r in story.business_rules]
    return "\n".join(lines)
