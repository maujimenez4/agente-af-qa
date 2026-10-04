"""Generación, evolución y revisión de HU con salida estructurada y citas (RF-15 a RF-18, RF-21).

`StoryWriter` depende solo del protocolo `LLMProvider`. Los prompts se cargan de
`prompts/<tarea>.md`. Si la propuesta cita fuentes que no estaban en el contexto, se reintenta
una vez indicando el error; si persiste, se lanza `CitationError` (RNF-14).
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from adapters.base import LLMProvider, Message, TaskType
from core.functional.citations import (
    CitationError,
    allowed_refs_text,
    citation_errors,
    repair_citations,
    with_real_excerpts,
    without_forced_citations,
)
from core.functional.context import StoryContext, render_context
from core.rag.prompts import Prompt, load_prompt
from schemas.user_story import UserStory

PromptLoader = Callable[[str], Prompt]


@dataclass(frozen=True)
class StoryDraft:
    """HU propuesta con la trazabilidad de la llamada (`Artifact.model_used`/`prompt_version`)."""

    story: UserStory
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int


class StoryWriter:
    def __init__(self, llm: LLMProvider, *, prompt_loader: PromptLoader = load_prompt) -> None:
        self._llm = llm
        self._load = prompt_loader

    def generate(self, ctx: StoryContext) -> StoryDraft:
        """HU nueva a partir de una necesidad o una épica (RF-15, RF-16, RF-17)."""
        draft = self._run(ctx, "generate_story", TaskType.GENERATE_STORY)
        # Una HU nueva aún no existe en Jira: se descarta cualquier clave que proponga el LLM.
        story = draft.story.model_copy(update={"jira_key": None})
        return replace(draft, story=story)

    def evolve(self, ctx: StoryContext) -> StoryDraft:
        """Nueva versión de una HU existente, con `changes_from_previous`."""
        previous = _require_previous(ctx, "evolucionar")
        draft = self._run(ctx, "evolve_story", TaskType.EVOLVE_STORY)
        return _keep_identity(draft, previous, _story_key(ctx))

    def structure(self, ctx: StoryContext) -> StoryDraft:
        """Versión de partida: la incidencia de Jira pasada a la plantilla, sin cambios (PA-30).

        Se compara con ella la evolución (diff por campo, RF-05, RNF-16). Usa la cadena de
        modelos de `evolve_story`: es la misma HU y el mismo tipo de trabajo.
        """
        if ctx.origin_kind != "story" or not ctx.origin_key:
            raise ValueError("Solo se estructura una HU que ya existe en Jira.")
        draft = self._run(ctx, "structure_story", TaskType.EVOLVE_STORY)
        story = draft.story.model_copy(
            update={"jira_key": ctx.origin_key, "changes_from_previous": []}
        )
        return replace(draft, story=story)

    def review(self, ctx: StoryContext) -> StoryDraft:
        """HU mejorada con ambigüedades, huecos e INVEST señalados (RF-18)."""
        previous = _require_previous(ctx, "revisar")
        draft = self._run(ctx, "review_story", TaskType.REVIEW_STORY)
        return _keep_identity(draft, previous, _story_key(ctx))

    def _run(self, ctx: StoryContext, prompt_name: str, task: TaskType) -> StoryDraft:
        prompt = self._load(prompt_name)
        sources = ctx.sources()
        messages = [
            Message(role="system", content=prompt.text),
            Message(role="user", content=render_context(ctx)),
        ]
        result = self._llm.generate_structured(messages, UserStory, task)
        story, input_tokens, output_tokens = (
            repair_citations(without_forced_citations(result.content, sources), sources)[0],
            result.input_tokens,
            result.output_tokens,
        )

        errors = citation_errors(story, sources)
        if errors:
            retry = self._load("citation_retry").text
            feedback = fill_placeholders(
                retry,
                {
                    "errors": "\n".join(f"- {e}" for e in errors),
                    "allowed": allowed_refs_text(sources),
                },
            )
            story_json = json.dumps(story.model_dump(mode="json"), ensure_ascii=False)
            retry_messages = [
                *messages,
                Message(role="assistant", content=story_json),
                Message(role="user", content=feedback),
            ]
            result = self._llm.generate_structured(retry_messages, UserStory, task)
            story = repair_citations(without_forced_citations(result.content, sources), sources)[0]
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            if citation_errors(story, sources):
                problem = (
                    "no cita ninguna de las fuentes del contexto"
                    if not story.sources
                    else "cita fuentes que no están en el contexto recibido"
                )
                raise CitationError(
                    f"La propuesta {problem}. Vuelve a generarla o revisa las fuentes disponibles."
                )
        return StoryDraft(
            story=with_real_excerpts(story, sources),
            provider=result.provider,
            model=result.model,
            prompt_version=prompt.version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def fill_placeholders(template: str, values: dict[str, str]) -> str:
    """Sustituye `{nombre}` en una sola pasada: los valores nunca se reinterpretan."""
    if not values:
        return template
    pattern = re.compile("|".join(re.escape("{" + name + "}") for name in values))
    return pattern.sub(lambda match: values[match.group(0)[1:-1]], template)


def _story_key(ctx: StoryContext) -> str | None:
    """La clave de origen solo identifica a la HU si el origen es una historia (no una épica)."""
    return ctx.origin_key if ctx.origin_kind == "story" else None


def _require_previous(ctx: StoryContext, verb: str) -> UserStory:
    if ctx.previous is None:
        raise ValueError(f"Para {verb} una HU hace falta la HU actual en el contexto.")
    return ctx.previous


def _keep_identity(draft: StoryDraft, previous: UserStory, origin_key: str | None) -> StoryDraft:
    """La HU evolucionada o revisada conserva su clave de Jira y su ID interno."""
    story = draft.story.model_copy(
        update={
            "jira_key": previous.jira_key or origin_key,
            "internal_id": previous.internal_id or draft.story.internal_id,
        }
    )
    return StoryDraft(
        story=story,
        provider=draft.provider,
        model=draft.model,
        prompt_version=draft.prompt_version,
        input_tokens=draft.input_tokens,
        output_tokens=draft.output_tokens,
    )
