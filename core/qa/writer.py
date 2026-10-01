"""Generación de la suite de QA de una HU estructurada (RF-22 a RF-25, RF-27).

`TestWriter` depende solo del protocolo `LLMProvider`. La entrada es una `UserStory` ya
estructurada (la conversión desde Jira es de la sesión principal) y la salida, una `TestSuite`.
Si la suite no cubre la HU, cita fuentes no recibidas o trae datos que parecen personales, se
reintenta una vez con el error; si persiste, se lanza `CoverageError` o `CitationError`.
"""

import json
from dataclasses import dataclass, field

from adapters.base import LLMProvider, Message, TaskType
from core.functional.citations import (
    CitationError,
    allowed_refs_text,
    citation_errors,
    with_real_excerpts,
)
from core.functional.context import StoryContext, escape_data, render_context
from core.functional.writer import PromptLoader, fill_placeholders
from core.qa.validation import CoverageError, suite_errors
from core.rag.prompts import load_prompt
from schemas.test_case import TestSuite
from schemas.user_story import UserStory


@dataclass(frozen=True)
class SuiteDraft:
    """Suite propuesta con la trazabilidad de la llamada; `coverage_md` es la matriz (RF-24)."""

    suite: TestSuite
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    coverage_md: str = field(default="")


class TestWriter:
    __test__ = False  # evita que pytest la tome por una clase de pruebas

    def __init__(self, llm: LLMProvider, *, prompt_loader: PromptLoader = load_prompt) -> None:
        self._llm = llm
        self._load = prompt_loader

    def generate(self, story: UserStory, ctx: StoryContext | None = None) -> SuiteDraft:
        base = ctx or StoryContext(origin_kind="story", origin_key=story.jira_key)
        # La clave de origen solo identifica a la HU si el origen es una historia (no una épica).
        origin_story_key = base.origin_key if base.origin_kind == "story" else None
        story_key = story.jira_key or origin_story_key
        if not story_key:
            raise ValueError(
                "La HU no tiene clave de Jira: publícala antes de generar sus pruebas."
            )
        ctx = StoryContext(
            origin_kind="story",
            origin_key=story_key,
            need=base.need,
            jira=base.jira,
            rag=base.rag,
            previous=story,
            feedback=base.feedback,
        )
        prompt = self._load("generate_tests")
        sources = ctx.sources()
        messages = [
            Message(role="system", content=prompt.text),
            Message(role="user", content=render_context(ctx)),
        ]
        result = self._llm.generate_structured(messages, TestSuite, TaskType.GENERATE_TESTS)
        suite = _with_key(result.content, story_key)
        input_tokens, output_tokens = result.input_tokens, result.output_tokens

        errors = suite_errors(suite, story, sources)
        if errors:
            feedback = fill_placeholders(
                self._load("tests_retry").text,
                {
                    # Ya son seguros: las citas llegan escapadas, los IDs siguen un patrón y
                    # las claves sospechosas no se muestran.
                    "errors": "\n".join(f"- {e}" for e in errors),
                    "ids": _ids_text(story),
                    "allowed": allowed_refs_text(sources),
                },
            )
            suite_json = json.dumps(suite.model_dump(mode="json"), ensure_ascii=False)
            retry_messages = [
                *messages,
                Message(role="assistant", content=suite_json),
                Message(role="user", content=feedback),
            ]
            result = self._llm.generate_structured(
                retry_messages, TestSuite, TaskType.GENERATE_TESTS
            )
            suite = _with_key(result.content, story_key)
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            if citation_errors(suite, sources):
                raise CitationError(
                    "La suite cita fuentes que no están en el contexto recibido. "
                    "Vuelve a generarla o revisa las fuentes disponibles."
                )
            if suite_errors(suite, story, sources):
                raise CoverageError(
                    "La suite de pruebas no cubre la HU: algún criterio no tiene casos, "
                    "faltan casos positivos o negativos, se referencian CA/RN inexistentes "
                    "o hay datos que parecen personales. Vuelve a generarla."
                )
        suite = with_real_excerpts(suite, sources)
        return SuiteDraft(
            suite=suite,
            provider=result.provider,
            model=result.model,
            prompt_version=prompt.version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            coverage_md=suite.coverage_md(),
        )


def _with_key(suite: TestSuite, story_key: str) -> TestSuite:
    return suite.model_copy(update={"story_jira_key": story_key})


def _ids_text(story: UserStory) -> str:
    lines = [f"- {c.id}: {escape_data(c.title)}" for c in story.acceptance_criteria]
    lines += [f"- {r.id}: {escape_data(r.description)}" for r in story.business_rules]
    return "\n".join(lines)
