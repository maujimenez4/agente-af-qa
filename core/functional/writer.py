"""Generación, evolución y revisión de HU con salida estructurada y citas (RF-15 a RF-18, RF-21).

`StoryWriter` depende solo del protocolo `LLMProvider`. Los prompts se cargan de
`prompts/<tarea>.md`. Si la propuesta cita fuentes que no estaban en el contexto, se reintenta
una vez indicando el error; si persiste, se lanza `CitationError` (RNF-14). Si lleva textos que
parecen datos personales reales o secretos, se reintenta una vez y, si persisten, se lanza
`SensitiveDataError` antes de la revisión humana (PA-452, principio 3).
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from adapters.base import LLMProvider, Message, StructuredResult, TaskType
from adapters.errors import AgentError
from core.context.budget import PromptLimits, default_prompt_limits, fit_messages
from core.functional.citations import (
    CitationError,
    allowed_refs_text,
    citation_errors,
    repair_citations,
    with_real_excerpts,
    without_forced_citations,
)
from core.functional.context import CitableSource, StoryContext, render_context
from core.functional.determinism import deterministic
from core.functional.literal_criteria import literal_criteria
from core.personal_data import looks_like_secret, personal_data_kind
from core.rag.prompts import Prompt, load_prompt
from schemas.user_story import UserStory

PromptLoader = Callable[[str], Prompt]

# Campos de la HU que no son texto libre: identificadores, prioridad y citas (las fuentes y sus
# extractos los pone el agente desde el contexto, no el modelo).
_NOT_FREE_TEXT = frozenset({"internal_id", "jira_key", "priority", "sources", "id"})
SENSITIVE_MESSAGE = (
    "La propuesta contiene textos que parecen datos personales reales o secretos y no se pueden "
    "publicar en Jira: {fields}. Vuelve a generarla o revisa la HU de origen."
)


class SensitiveDataError(AgentError):
    """La HU sigue con datos que parecen personales o secretos tras el reintento (PA-452)."""


def story_texts(story: UserStory) -> list[tuple[str, str]]:
    """Cada texto libre de la HU con su campo («description», «acceptance_criteria[0].then[1]»)."""
    texts: list[tuple[str, str]] = []

    def walk(value: object, where: str) -> None:
        if isinstance(value, str):
            texts.append((where, value))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in _NOT_FREE_TEXT:
                    walk(item, f"{where}.{key}" if where else key)

    walk(story.model_dump(mode="json"), "")
    return texts


def sensitive_errors(story: UserStory) -> list[str]:
    """Campos de la HU que parecen llevar un dato personal real o un secreto (PA-452), sin el
    valor: el mensaje va al modelo en el reintento y a la persona en el error."""
    errors: list[str] = []
    for where, text in story_texts(story):
        if kind := personal_data_kind(text):
            errors.append(f"{where} parece un {kind} real; usa una descripción o un valor ficticio")
        elif looks_like_secret(text):
            errors.append(f"{where} parece contener un secreto; describe lo que es sin copiarlo")
    return errors


def _fields(errors: list[str]) -> str:
    """Los campos afectados, sin repetir y como mucho ocho, para el mensaje de error."""
    names = list(dict.fromkeys(error.split(" ", 1)[0] for error in errors))
    return ", ".join(names[:8]) + ("…" if len(names) > 8 else "")


@dataclass(frozen=True)
class StoryDraft:
    """HU propuesta con la trazabilidad de la llamada (`Artifact.model_used`/`prompt_version`)."""

    story: UserStory
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int


def trim_context(ctx: StoryContext, rag: int, related: int) -> StoryContext:
    """El contexto con los `rag` primeros fragmentos y las `related` primeras HU relacionadas.

    La HU de origen (la primera de Jira si el origen es una HU o una épica), la HU previa y el
    feedback se conservan siempre (PA-114).
    """
    keep = _origin_count(ctx)
    return replace(ctx, rag=list(ctx.rag[:rag]), jira=list(ctx.jira[: keep + related]))


def fit_context(
    ctx: StoryContext,
    build: Callable[[StoryContext], list[Message]],
    limits: PromptLimits,
    task: TaskType,
    *,
    action: str,
) -> tuple[StoryContext, list[Message]]:
    """Contexto recortado y sus mensajes, que caben en la ventana del modelo (PA-114).

    Quita primero los últimos fragmentos del RAG y después las últimas HU relacionadas; si ni
    así cabe, `ContextOverflowError`. Lo comparten la HU, la suite (`core/qa`) y la calidad.
    """
    fitted = [ctx]  # solo el último contexto construido, el de los mensajes devueltos

    def build_trimmed(rag: int, related: int) -> list[Message]:
        fitted[0] = trim_context(ctx, rag, related)
        return build(fitted[0])

    related = len(ctx.jira) - _origin_count(ctx)
    messages, _ = fit_messages(build_trimmed, len(ctx.rag), related, limits, task, action=action)
    return fitted[0], messages


def _origin_count(ctx: StoryContext) -> int:
    return 1 if ctx.origin_kind in ("story", "epic") and ctx.jira else 0


class StoryWriter:
    def __init__(
        self,
        llm: LLMProvider,
        *,
        prompt_loader: PromptLoader = load_prompt,
        limits: PromptLimits | None = None,
    ) -> None:
        self._llm = llm
        self._load = prompt_loader
        self._limits = limits  # PA-114; sin valor, los de la configuración de la aplicación

    @property
    def limits(self) -> PromptLimits:
        if self._limits is None:
            self._limits = default_prompt_limits()
        return self._limits

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
        with deterministic():  # PA-432: la misma HU sale igual cada vez
            draft = self._run(ctx, "structure_story", TaskType.EVOLVE_STORY)
        update: dict[str, object] = {"jira_key": ctx.origin_key, "changes_from_previous": []}
        # PA-432: si la HU trae sus CA y RN con formato, se usan tal cual (todos o ninguno).
        origin = next((i for i in ctx.jira if i.key == ctx.origin_key), None)
        if origin is not None and (literal := literal_criteria(origin.description_text)):
            update["acceptance_criteria"], update["business_rules"] = literal
        story = draft.story.model_copy(update=update)
        return replace(draft, story=story)

    def review(self, ctx: StoryContext) -> StoryDraft:
        """HU mejorada con ambigüedades, huecos e INVEST señalados (RF-18)."""
        previous = _require_previous(ctx, "revisar")
        draft = self._run(ctx, "review_story", TaskType.REVIEW_STORY)
        return _keep_identity(draft, previous, _story_key(ctx))

    def _run(self, ctx: StoryContext, prompt_name: str, task: TaskType) -> StoryDraft:
        prompt = self._load(prompt_name)
        ctx, messages = fit_context(  # PA-114: nunca se desborda la ventana en silencio
            ctx,
            lambda c: [
                Message(role="system", content=prompt.text),
                Message(role="user", content=render_context(c)),
            ],
            self.limits,
            task,
            action=prompt_name,
        )
        sources = ctx.sources()
        result = self._llm.generate_structured(messages, UserStory, task)
        story, input_tokens, output_tokens = (
            repair_citations(without_forced_citations(result.content, sources), sources)[0],
            result.input_tokens,
            result.output_tokens,
        )

        errors = citation_errors(story, sources)
        if errors:
            retry = self._load("citation_retry").text
            story_json = json.dumps(story.model_dump(mode="json"), ensure_ascii=False)
            first = story

            def retry_messages(c: StoryContext) -> list[Message]:
                # Las fuentes permitidas y los errores, del contexto que de verdad se envía.
                allowed = c.sources()
                feedback = fill_placeholders(
                    retry,
                    {
                        "errors": "\n".join(f"- {e}" for e in citation_errors(first, allowed)),
                        "allowed": allowed_refs_text(allowed),
                    },
                )
                return [
                    Message(role="system", content=prompt.text),
                    Message(role="user", content=render_context(c)),
                    Message(role="assistant", content=story_json),
                    Message(role="user", content=feedback),
                ]

            # PA-114: el reintento es el mensaje más largo; también pasa por la guarda.
            ctx, messages = fit_context(
                ctx, retry_messages, self.limits, task, action=f"{prompt_name}_retry"
            )
            sources = ctx.sources()
            result = self._llm.generate_structured(messages, UserStory, task)
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
        story, sources, ctx, tokens = self._without_sensitive_data(
            story, sources, ctx, prompt, prompt_name, task
        )
        if tokens is not None:
            result = tokens
            input_tokens += tokens.input_tokens
            output_tokens += tokens.output_tokens
        return StoryDraft(
            story=with_real_excerpts(story, sources),
            provider=result.provider,
            model=result.model,
            prompt_version=prompt.version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _without_sensitive_data(
        self,
        story: UserStory,
        sources: list[CitableSource],
        ctx: StoryContext,
        prompt: Prompt,
        prompt_name: str,
        task: TaskType,
    ) -> tuple[UserStory, list[CitableSource], StoryContext, StructuredResult[UserStory] | None]:
        """PA-452: sin datos que parezcan personales ni secretos en la HU, que acabaría en Jira.

        Un reintento indicando los campos (nunca los valores); si persisten, `SensitiveDataError`
        antes de la revisión humana. Devuelve la HU, sus fuentes, el contexto y la llamada del
        reintento (`None` si no hizo falta).
        """
        errors = sensitive_errors(story)
        if not errors:
            return story, sources, ctx, None
        retry = self._load("story_retry").text
        story_json = json.dumps(story.model_dump(mode="json"), ensure_ascii=False)

        def retry_messages(c: StoryContext) -> list[Message]:
            feedback = fill_placeholders(
                retry,
                {
                    "errors": "\n".join(f"- {e}" for e in errors),
                    "allowed": allowed_refs_text(c.sources()),
                },
            )
            return [
                Message(role="system", content=prompt.text),
                Message(role="user", content=render_context(c)),
                Message(role="assistant", content=story_json),
                Message(role="user", content=feedback),
            ]

        # PA-114: el reintento también pasa por la guarda de la ventana.
        ctx, messages = fit_context(
            ctx, retry_messages, self.limits, task, action=f"{prompt_name}_sensitive_retry"
        )
        sources = ctx.sources()
        result = self._llm.generate_structured(messages, UserStory, task)
        story = repair_citations(without_forced_citations(result.content, sources), sources)[0]
        if citation_errors(story, sources):
            raise CitationError(
                "La propuesta cita fuentes que no están en el contexto recibido. Vuelve a "
                "generarla o revisa las fuentes disponibles."
            )
        if still := sensitive_errors(story):
            raise SensitiveDataError(SENSITIVE_MESSAGE.format(fields=_fields(still)))
        return story, sources, ctx, result


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
