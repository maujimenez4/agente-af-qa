"""Generación de la suite de QA de una HU estructurada (RF-22 a RF-25, RF-27).

`TestWriter` depende solo del protocolo `LLMProvider`. La entrada es una `UserStory` ya
estructurada (la conversión desde Jira es de la sesión principal) y la salida, una `TestSuite`.
Si la suite no cubre la HU, cita fuentes no recibidas o trae datos que parecen personales, se
reintenta una vez con el error; si persiste, se lanza `CoverageError` o `CitationError`.

PA-331: al iterar, la suite actual va al prompt como datos (`<suite_actual>`) junto al feedback,
y los casos que no cambian conservan su ID por código (`keep_case_ids`), sin depender del modelo.
La última petición se repite en un mensaje final corto (`prompts/tests_iterate.md`): los modelos
pequeños atienden mucho más al último mensaje. Si no cabe en la ventana: primero se recorta el
contexto (RAG y HU relacionadas); después la suite entra parcial (sin estrategia, datos ni
fuentes), luego resumida (con aviso en el prompt y en el log) y, si ni así cabe,
`ContextOverflowError`.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from adapters.base import LLMProvider, Message, StructuredResult, TaskType
from adapters.errors import ExternalServiceError
from core.context.budget import (
    ContextOverflowError,
    PromptLimits,
    default_prompt_limits,
    estimate_messages,
)
from core.functional.citations import (
    CitationError,
    allowed_refs_text,
    citation_errors,
    repair_citations,
    with_real_excerpts,
    without_forced_citations,
)
from core.functional.context import CitableSource, StoryContext, render_context
from core.functional.writer import PromptLoader, fill_placeholders, fit_context
from core.logging import get_logger
from core.qa.validation import (
    CoverageError,
    blocking_errors,
    missing_criteria,
    personal_data_errors,
    suite_errors,
)
from core.rag.prompts import load_prompt
from core.text import escape_data  # PA-227
from schemas.test_case import TestCase, TestSuite
from schemas.user_story import UserStory

log = get_logger(__name__)


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
    previous_summarized: bool = False  # PA-331: la suite anterior no cabía y entró resumida
    previous_partial: bool = False  # PA-331: entró sin estrategia, datos ni fuentes
    # PA-426: CA que siguen sin caso tras el reintento dirigido; la suite pasa a revisión con el
    # aviso (`uncovered`) y el grafo no deja aprobarla hasta que se cubran.
    uncovered_criteria: tuple[str, ...] = ()
    targeted_retry: bool = False  # PA-426: se pidió el caso de los CA que faltaban


MAX_CASES_PER_MISSING = 3  # PA-426: casos del reintento dirigido que se aceptan por CA


class MissingCases(BaseModel):
    """PA-426: salida del reintento dirigido: solo los casos nuevos."""

    __test__ = False

    cases: list[TestCase] = Field(min_length=1)


# T-54: HU aprobada en simulación (sin clave de Jira). No tiene forma de clave, así que nunca se
# confunde con una incidencia real; publicar sus casos se rechaza en el grafo.
UNPUBLISHED_STORY_KEY = "SIN-CLAVE"


class TestWriter:
    __test__ = False  # evita que pytest la tome por una clase de pruebas

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

    def generate(
        self,
        story: UserStory,
        ctx: StoryContext | None = None,
        *,
        unpublished: bool = False,
        previous_suite: TestSuite | None = None,
    ) -> SuiteDraft:
        """`unpublished`: HU encadenada sin clave (T-54); la suite lleva `UNPUBLISHED_STORY_KEY`.

        `previous_suite`: al iterar, la suite actual; la nueva aplica el feedback sobre ella
        (PA-331).
        """
        base = ctx or StoryContext(origin_kind="story", origin_key=story.jira_key)
        # La clave de origen solo identifica a la HU si el origen es una historia (no una épica).
        origin_story_key = base.origin_key if base.origin_kind == "story" else None
        story_key = story.jira_key or origin_story_key
        if not story_key and unpublished:
            story_key = UNPUBLISHED_STORY_KEY
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
        blocks = previous_blocks(previous_suite)
        request = self._request(ctx, previous_suite)
        ctx, messages, level = self._fit(  # PA-114: nunca se desborda la ventana en silencio
            ctx,
            blocks,
            lambda c, block: [
                Message(role="system", content=prompt.text),
                Message(role="user", content=_user_message(c, block)),
                *request,
            ],
            action="generate_tests",
        )
        sources = ctx.sources()
        result = self._llm.generate_structured(messages, TestSuite, TaskType.GENERATE_TESTS)
        suite = keep_case_ids(_cited(_with_key(result.content, story_key), sources), previous_suite)
        input_tokens, output_tokens = result.input_tokens, result.output_tokens

        # PA-426: si lo único que falla es que faltan CA, no se regenera la suite entera.
        if blocking_errors(suite, story, sources):
            retry_text = self._load("tests_retry").text
            suite_json = json.dumps(suite.model_dump(mode="json"), ensure_ascii=False)
            first = suite

            def retry_messages(c: StoryContext, block: str) -> list[Message]:
                # Las fuentes permitidas y los errores, del contexto que de verdad se envía.
                allowed = c.sources()
                feedback = fill_placeholders(
                    retry_text,
                    {
                        # Ya son seguros: las citas llegan escapadas, los IDs siguen un patrón
                        # y las claves sospechosas no se muestran.
                        "errors": "\n".join(f"- {e}" for e in suite_errors(first, story, allowed)),
                        "ids": _ids_text(story),
                        "allowed": allowed_refs_text(allowed),
                    },
                )
                return [
                    Message(role="system", content=prompt.text),
                    Message(role="user", content=_user_message(c, block)),
                    *request,
                    Message(role="assistant", content=suite_json),
                    Message(role="user", content=feedback),
                ]

            # PA-114: el reintento de cobertura es el mensaje más largo; pasa por la guarda.
            ctx, retry, level = self._fit(
                ctx, blocks[level:], retry_messages, action="generate_tests_retry", start=level
            )
            sources = ctx.sources()
            result = self._llm.generate_structured(retry, TestSuite, TaskType.GENERATE_TESTS)
            suite = keep_case_ids(
                _cited(_with_key(result.content, story_key), sources), previous_suite
            )
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            if citation_errors(suite, sources):
                problem = (
                    "no cita ninguna de las fuentes del contexto"
                    if not suite.sources
                    else "cita fuentes que no están en el contexto recibido"
                )
                raise CitationError(
                    f"La suite {problem}. Vuelve a generarla o revisa las fuentes disponibles."
                )
            if blocking_errors(suite, story, sources):
                raise CoverageError(
                    "La suite de pruebas no cubre la HU: algún criterio no tiene casos, "
                    "faltan casos positivos o negativos, se referencian CA/RN inexistentes "
                    "o hay datos que parecen personales. Vuelve a generarla."
                )
        targeted = False
        if missing := missing_criteria(suite, story):
            filled = self._fill_missing(suite, story, missing, sources)
            if filled is not None:
                suite, extra = filled
                targeted = True
                input_tokens += extra.input_tokens
                output_tokens += extra.output_tokens
            if missing := missing_criteria(suite, story):
                log.warning(
                    "suite con criterios sin caso: pasa a revisión con el aviso",
                    action="generate_tests",
                    criteria=missing,  # solo IDs (CA-NN)
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
            previous_summarized=level >= SUMMARY_LEVEL,
            previous_partial=level == PARTIAL_LEVEL,
            uncovered_criteria=tuple(missing),
            targeted_retry=targeted,
        )

    def _fill_missing(
        self,
        suite: TestSuite,
        story: UserStory,
        missing: list[str],
        sources: list[CitableSource],
    ) -> tuple[TestSuite, StructuredResult[MissingCases]] | None:
        """PA-426: reintento dirigido. Pide solo los casos de los CA que faltan y los añade a la
        suite, numerados a continuación. `None` si no se pudo (no cabe o el proveedor falla): la
        suite sigue a revisión con el aviso, sin perder el trabajo."""
        prompt = self._load("tests_missing")
        messages = [
            Message(role="system", content=prompt.text),
            Message(role="user", content=_missing_data(suite, story, missing)),
        ]
        if estimate_messages(messages) > self.limits.available(TaskType.GENERATE_TESTS):
            log.warning("reintento dirigido omitido: no cabe", action="generate_tests_missing")
            return None
        try:
            result = self._llm.generate_structured(messages, MissingCases, TaskType.GENERATE_TESTS)
        except ExternalServiceError as exc:  # la cancelación (otro AgentError) sí se propaga
            log.warning(
                "reintento dirigido sin respuesta",
                action="generate_tests_missing",
                error=type(exc).__name__,
            )
            return None
        accepted = [c for c in result.content.cases if _acceptable(c, suite, story, missing)]
        accepted = accepted[: MAX_CASES_PER_MISSING * len(missing)]  # tope de casos añadidos
        merged = _append_cases(suite, accepted)
        # Se valida la suite completa: si algo fallara al fusionar, se queda la de antes.
        if blocking_errors(merged, story, sources):
            log.warning("reintento dirigido descartado", action="generate_tests_missing")
            return suite, result
        return merged, result

    def _request(self, ctx: StoryContext, previous: TestSuite | None) -> list[Message]:
        """PA-331: al iterar, la última petición repetida al final (como dato, escapada)."""
        if previous is None or not ctx.feedback:
            return []
        template = self._load("tests_iterate").text
        text = fill_placeholders(template, {"request": escape_data(ctx.feedback[-1])})
        return [Message(role="user", content=text)]

    def _fit(
        self,
        ctx: StoryContext,
        blocks: list[str],
        build: Callable[[StoryContext, str], list[Message]],
        *,
        action: str,
        start: int = 0,
    ) -> tuple[StoryContext, list[Message], int]:
        """Mensajes que caben, probando la suite anterior completa, parcial y resumida.

        Devuelve el contexto recortado, los mensajes y el escalón usado (0 completa, 1 parcial,
        2 resumida).
        Si ni resumida cabe, `ContextOverflowError` (nunca un recorte en silencio).
        """
        error: ContextOverflowError | None = None
        for offset, block in enumerate(blocks):
            try:
                fitted, messages = fit_context(
                    ctx,
                    lambda c, b=block: build(c, b),
                    self.limits,
                    TaskType.GENERATE_TESTS,
                    action=action,
                )
            except ContextOverflowError as exc:
                error = exc
                continue
            level = start + offset
            if level == PARTIAL_LEVEL:
                log.info("suite anterior sin estrategia, datos ni fuentes: no cabía", action=action)
            elif level >= SUMMARY_LEVEL:
                log.warning("suite anterior resumida: no cabía entera", action=action)
            return fitted, messages, level
        if error is None:  # `blocks` nunca está vacío
            raise ValueError("Sin bloques de suite anterior.")
        raise error


# --- Suite anterior (PA-331) ------------------------------------------------------------------

# Escalones de la suite anterior; qué hacer con cada uno lo dice `prompts/generate_tests.md`.
PARTIAL_LEVEL = 1  # sin estrategia, datos ni fuentes (el modelo los vuelve a escribir)
SUMMARY_LEVEL = 2  # solo lo esencial de cada caso
_SUMMARY_FIELDS = ("internal_id", "title", "type", "criterion_ids", "rule_ids", "priority")


def previous_blocks(previous: TestSuite | None) -> list[str]:
    """Los bloques `<suite_actual>` en orden de preferencia: completo, parcial y resumido (o
    ninguno, en la primera generación)."""
    if previous is None:
        return [""]
    full = json.dumps(previous.model_dump(mode="json"), ensure_ascii=False)
    partial = json.dumps(
        previous.model_dump(mode="json", include={"story_jira_key", "cases"}), ensure_ascii=False
    )
    summary = {
        "story_jira_key": previous.story_jira_key,
        "cases": [
            case.model_dump(mode="json", include=set(_SUMMARY_FIELDS)) for case in previous.cases
        ],
    }
    short = json.dumps(summary, ensure_ascii=False)
    return [
        f"<suite_actual>\n{escape_data(full)}\n</suite_actual>",
        f'<suite_actual parcial="si">\n{escape_data(partial)}\n</suite_actual>',
        f'<suite_actual resumida="si">\n{escape_data(short)}\n</suite_actual>',
    ]


def _user_message(ctx: StoryContext, block: str) -> str:
    rendered = render_context(ctx)
    return f"{rendered}\n\n{block}" if block else rendered


def keep_case_ids(suite: TestSuite, previous: TestSuite | None) -> TestSuite:
    """Los casos idénticos a uno de la versión anterior (salvo el ID) recuperan su ID; los demás
    conservan el suyo si queda libre o reciben el siguiente número. Sin depender del modelo."""
    if previous is None:
        return suite
    old: dict[str, list[str]] = {}
    for case in previous.cases:
        old.setdefault(_signature(case), []).append(case.internal_id)
    kept = [ids.pop(0) if (ids := old.get(_signature(case))) else None for case in suite.cases]
    used = {case_id for case_id in kept if case_id}
    numbers = [_number(c.internal_id) for c in (*previous.cases, *suite.cases)]
    next_number = max(numbers, default=0) + 1
    cases: list[TestCase] = []
    for case, case_id in zip(suite.cases, kept, strict=True):
        if case_id is None:
            if case.internal_id in used:
                case_id, next_number = f"CP-{next_number:02d}", next_number + 1
            else:
                case_id = case.internal_id
        used.add(case_id)
        changed = case_id != case.internal_id
        cases.append(case.model_copy(update={"internal_id": case_id}) if changed else case)
    return suite.model_copy(update={"cases": cases})


def _signature(case: TestCase) -> str:
    return json.dumps(
        case.model_dump(mode="json", exclude={"internal_id"}), ensure_ascii=False, sort_keys=True
    )


def _number(case_id: str) -> int:
    match = re.fullmatch(r"CP-(\d+)", case_id)
    return int(match.group(1)) if match else 0


# --- Reintento dirigido (PA-426) ---------------------------------------------------------------


def _missing_data(suite: TestSuite, story: UserStory, missing: list[str]) -> str:
    """Datos del reintento dirigido: el texto de los CA que faltan, las RN y los IDs usados."""
    wanted = [c for c in story.acceptance_criteria if c.id in missing]
    criteria = "\n".join(
        escape_data(
            f"- {c.id}: {c.title}. Dado {'; '.join(c.given)}. Cuando {'; '.join(c.when)}. "
            f"Entonces {'; '.join(c.then)}."
        )
        for c in wanted
    )
    rules = "\n".join(f"- {r.id}: {escape_data(r.description)}" for r in story.business_rules)
    used = ", ".join(case.internal_id for case in suite.cases)
    return (
        f"<criterios_sin_caso>\n{criteria}\n</criterios_sin_caso>\n\n"
        f"<reglas>\n{rules or '—'}\n</reglas>\n\n"
        f"<ids_usados>\n{used}\n</ids_usados>"
    )


def _acceptable(case: TestCase, suite: TestSuite, story: UserStory, missing: list[str]) -> bool:
    """Solo casos que verifican algún CA de los que faltan, sin IDs inventados ni datos que
    parecen personales (el resto de la suite ya se validó)."""
    criteria = {c.id for c in story.acceptance_criteria}
    rules = {r.id for r in story.business_rules}
    if not set(case.criterion_ids) <= criteria or not set(case.rule_ids) <= rules:
        return False
    if not set(case.criterion_ids) & set(missing):
        return False
    alone = suite.model_copy(
        update={
            "cases": [case],
            "synthetic_data": [],
            "risks": [],
            "dependencies": [],
            "impact_areas": [],
            "strategy_md": "",
        }
    )
    return not personal_data_errors(alone)


def _append_cases(suite: TestSuite, cases: list[TestCase]) -> TestSuite:
    """Añade los casos al final, numerados a continuación por código (sin fiarse del modelo)."""
    next_number = max((_number(c.internal_id) for c in suite.cases), default=0) + 1
    added = []
    for offset, case in enumerate(cases):
        added.append(case.model_copy(update={"internal_id": f"CP-{next_number + offset:02d}"}))
    return suite.model_copy(update={"cases": [*suite.cases, *added]})


def _cited(suite: TestSuite, sources: list[CitableSource]) -> TestSuite:
    """Citas sin inventar (sin fuentes, ninguna) y reparadas sin LLM si es inequívoco (PA-281)."""
    return repair_citations(without_forced_citations(suite, sources), sources)[0]


def _with_key(suite: TestSuite, story_key: str) -> TestSuite:
    return suite.model_copy(update={"story_jira_key": story_key})


def _ids_text(story: UserStory) -> str:
    lines = [f"- {c.id}: {escape_data(c.title)}" for c in story.acceptance_criteria]
    lines += [f"- {r.id}: {escape_data(r.description)}" for r in story.business_rules]
    return "\n".join(lines)
