"""Pruebas de la guarda de la ventana de contexto (PA-114).

Cubren `core/context/budget.py` (`estimate_messages`, `PromptLimits`, `default_prompt_limits`,
`fit_messages`, `check_messages`, `ContextOverflowError`) y su uso en `StoryWriter`,
`TestWriter`, `QualityReviewer`, `LLMMemoryGenerator` e `ImpactAnalyzer`, siempre contra
`FakeLLMProvider` (sin LLM real). Datos 100 % sintéticos (Villaficticia, claves DEMO-N).
"""

import dataclasses
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel
from structlog.testing import capture_logs

import core.config
from adapters.base import Chunk, IssueDetail, Message, RetrievedChunk, TaskType
from adapters.errors import AgentError
from core.config import AppConfig, ConfigError, Settings, load_models_config
from core.container import Container
from core.context.budget import (
    CHARS_PER_TOKEN,
    DEFAULT_CONTEXT_WINDOW,
    MESSAGE_OVERHEAD_TOKENS,
    SAFETY_TOKENS,
    ContextOverflowError,
    FitReport,
    PromptLimits,
    check_messages,
    default_prompt_limits,
    estimate_messages,
    estimate_tokens,
    fit_messages,
)
from core.functional.context import StoryContext, render_context
from core.functional.writer import StoryWriter, trim_context
from core.impact.analysis import ImpactAnalyzer
from core.memory.generator import LLMMemoryGenerator
from core.qa.writer import TestWriter
from core.quality import QualityReviewer
from core.rag.prompts import Prompt
from core.text import escape_data
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem
from schemas.memory import Memory
from schemas.quality import QualityFinding, QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider, renewal_quality_report, renewal_test_suite
from tests.fixtures import MODELS_FIXTURE

ROOT = Path(__file__).resolve().parents[2]
AF = dataset.DEMO_USERS["af-demo"][1]
FILLER = "Texto ficticio de relleno sobre préstamos de Villaficticia. "
INSTRUCTIONS_MARK = "INSTRUCCIONES-MARCADOR-PA114"
FEEDBACK_MARK = "FEEDBACK-MARCADOR-PA114"
CONTENT_MARK = "CONTENIDO-MARCADOR-ZZZ"
RAG_DOCS = ("DOC-71", "DOC-72", "DOC-73", "DOC-74")
RELATED_KEYS = ("DEMO-21", "DEMO-22")
BIG = 10**6  # ventana holgada: nada se recorta

PROMPTS = {
    name: f"{INSTRUCTIONS_MARK} {name}: instrucciones ficticias de la tarea. " + FILLER * 3
    for name in (
        "generate_story",
        "evolve_story",
        "structure_story",
        "generate_tests",
        "review_quality",
    )
}
PROMPTS["citation_retry"] = "Corrige las citas.\n{errors}\nPermitidas:\n{allowed}"
PROMPTS["tests_retry"] = "Corrige la suite.\n{errors}\nIDs:\n{ids}\nPermitidas:\n{allowed}"
PROMPTS["quality_retry"] = "Corrige el informe.\n{errors}\nIDs:\n{ids}\nPermitidas:\n{allowed}"


# --- utilidades --------------------------------------------------------------------------


def loader(name: str) -> Prompt:
    return Prompt(name=name, version="prueba-1", text=PROMPTS[name])


def limits_for(available: int, task: TaskType, output: int = 500) -> PromptLimits:
    """Límites cuyo `available(task)` es exactamente `available`."""
    return PromptLimits(available + output + SAFETY_TOKENS, {task: output})


def rag_hit(doc_id: str, repeat: int = 10) -> RetrievedChunk:
    document_id = f"uuid-ficticio-{doc_id.lower()}"
    chunk = Chunk(
        id=f"{document_id}-0",
        document_id=document_id,
        ordinal=0,
        content=f"RAG-MARCADOR-{doc_id} " + FILLER * repeat,
        metadata={"doc_id": doc_id, "date": "2026-04-20", "category": "normativa"},
    )
    return RetrievedChunk(
        chunk=chunk, score=0.8, source=SourceRef(kind="rag", ref=document_id, excerpt="ficticio")
    )


def related_issue(key: str) -> IssueDetail:
    return IssueDetail(
        key=key,
        summary=f"HU relacionada ficticia {key}",
        issue_type="Story",
        status="Por hacer",
        description_text=f"JIRA-MARCADOR-{key} " + FILLER * 5,
    )


def full_ctx(kind: str = "story", *, rag_repeat: int = 10, origin: IssueDetail | None = None):
    """Contexto con origen, 2 HU relacionadas, 4 fragmentos del RAG, HU previa y feedback."""
    if origin is None:
        origin = dataset.STORIES["DEMO-3"] if kind == "story" else dataset.EPIC
    return StoryContext(
        origin_kind=kind,  # type: ignore[arg-type]
        origin_key=origin.key,
        need="Renovar préstamos desde la web (necesidad ficticia)." if kind != "story" else "",
        jira=[origin, *(related_issue(k) for k in RELATED_KEYS)],
        rag=[rag_hit(d, rag_repeat) for d in RAG_DOCS],
        previous=dataset.renewal_story(),
        feedback=[f"{FEEDBACK_MARK}: acortar el plazo de aviso (ficticio)."],
    )


def story_messages(prompt_name: str, ctx: StoryContext) -> list[Message]:
    return [
        Message(role="system", content=PROMPTS[prompt_name]),
        Message(role="user", content=render_context(ctx)),
    ]


def sent(llm: FakeLLMProvider, index: int = 0) -> list[Message]:
    return llm.calls[index]["messages"]


def user_text(messages: list[Message]) -> str:
    return "\n".join(m.content for m in messages if m.role == "user")


def source_count(messages: list[Message]) -> int:
    return messages[1].content.count("<fuente ")


def trim_events(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in logs if "dropped_rag" in e]


class Sequence:
    """Builder que devuelve las respuestas en orden (la última se repite)."""

    def __init__(self, *responses: BaseModel) -> None:
        self.responses = list(responses)
        self.count = 0

    def __call__(self, _messages: list[Message]) -> BaseModel:
        response = self.responses[min(self.count, len(self.responses) - 1)]
        self.count += 1
        return response


def story_citing(*refs: tuple[str, str]) -> UserStory:
    sources = [SourceRef(kind=k, ref=r, excerpt="inventado") for k, r in refs]  # type: ignore[arg-type]
    return dataset.renewal_story(jira_key=None).model_copy(update={"sources": sources})


def app_config(limits: PromptLimits) -> AppConfig:
    """AppConfig de prueba: el fixture (PA-458) con los límites de PA-114 sustituidos.

    PA-443: sin los límites propios de cada proveedor, para que valgan los globales (los
    límites por proveedor se prueban en `test_mixed_models.py`).
    """
    models = load_models_config(MODELS_FIXTURE)
    new_limits = models.limits.model_copy(
        update={
            "context_window": limits.context_window,
            "max_output_tokens": dict(limits.max_output_tokens),
        }
    )
    providers = {
        name: provider.model_copy(update={"limits": None})
        for name, provider in models.providers.items()
    }
    models = models.model_copy(update={"limits": new_limits, "providers": providers})
    return AppConfig(Settings(_env_file=None), models)  # type: ignore[call-arg]


# --- 1. estimate_messages y PromptLimits.available -----------------------------------------


def test_estimate_messages_sums_all_messages_plus_overhead() -> None:
    """PA-114 · criterio 1: estima el mensaje completo, con el sobrecoste por mensaje."""
    messages = [
        Message(role="system", content="a" * 30),
        Message(role="user", content="b" * 31),
        Message(role="assistant", content="c" * 2),
        Message(role="user", content=""),
    ]

    expected = 10 + 11 + 1 + 0 + 4 * MESSAGE_OVERHEAD_TOKENS
    assert estimate_messages(messages) == expected


def test_estimate_messages_empty_list_is_zero() -> None:
    """PA-114 · criterio 1 (límite): sin mensajes, 0 tokens."""
    assert estimate_messages([]) == 0


def test_available_subtracts_output_cap_and_safety_margin() -> None:
    """PA-114 · criterio 1: available = ventana − tope de salida de la tarea − SAFETY_TOKENS."""
    limits = PromptLimits(8192, {TaskType.EVOLVE_STORY: 2500})

    assert limits.available(TaskType.EVOLVE_STORY) == 8192 - 2500 - SAFETY_TOKENS


def test_available_without_task_cap_uses_zero_output() -> None:
    """PA-114 · criterio 1: una tarea sin tope de salida descuenta 0."""
    limits = PromptLimits(8192, {TaskType.EVOLVE_STORY: 2500})

    assert limits.available(TaskType.NL_TO_JQL) == 8192 - SAFETY_TOKENS
    assert PromptLimits().available(TaskType.GENERATE_STORY) == DEFAULT_CONTEXT_WINDOW - 256


# --- 2. fit_messages y check_messages --------------------------------------------------------

PART_CHARS = 30  # 10 tokens por parte


def make_build(
    n_rag: int, n_related: int, base_chars: int = 300
) -> tuple[Callable[[int, int], list[Message]], list[tuple[int, int]]]:
    """`build(rag, related)` sintético que registra con qué recuentos se le llama."""
    calls: list[tuple[int, int]] = []
    rag = [f"R{i}{CONTENT_MARK}".ljust(PART_CHARS, "r") for i in range(n_rag)]
    related = [f"J{i}{CONTENT_MARK}".ljust(PART_CHARS, "j") for i in range(n_related)]

    def build(r: int, j: int) -> list[Message]:
        calls.append((r, j))
        return [
            Message(role="system", content="s" * base_chars),
            Message(role="user", content="".join(related[:j]) + "".join(rag[:r])),
        ]

    return build, calls


def full_estimate(n_rag: int, n_related: int) -> int:
    build, _ = make_build(n_rag, n_related)
    return estimate_messages(build(n_rag, n_related))


def test_fit_messages_exact_fit_drops_nothing() -> None:
    """PA-114 · criterio 2 (límite): estimado == available no recorta nada."""
    build, calls = make_build(3, 2)
    limits = limits_for(full_estimate(3, 2), TaskType.GENERATE_STORY)

    with capture_logs() as logs:
        messages, report = fit_messages(build, 3, 2, limits, TaskType.GENERATE_STORY, action="t")

    assert report == FitReport(full_estimate(3, 2), full_estimate(3, 2), 0, 0)
    assert estimate_messages(messages) == limits.available(TaskType.GENERATE_STORY)
    assert calls == [(3, 2)]
    assert trim_events(logs) == []


def test_fit_messages_one_token_over_drops_last_rag_chunk_first() -> None:
    """PA-114 · criterio 2: con un token de más se quita primero el último fragmento del RAG."""
    build, calls = make_build(3, 2)
    limits = limits_for(full_estimate(3, 2) - 1, TaskType.GENERATE_STORY)

    messages, report = fit_messages(build, 3, 2, limits, TaskType.GENERATE_STORY, action="t")

    assert (report.dropped_rag, report.dropped_jira) == (1, 0)
    assert calls[-1] == (2, 2)
    assert "R2" not in messages[1].content and "R1" in messages[1].content
    assert estimate_messages(messages) <= limits.available(TaskType.GENERATE_STORY)


def test_fit_messages_without_rag_drops_last_related_story() -> None:
    """PA-114 · criterio 2: sin RAG se quitan las últimas HU relacionadas."""
    build, calls = make_build(0, 3)
    limits = limits_for(full_estimate(0, 3) - 1, TaskType.GENERATE_STORY)

    messages, report = fit_messages(build, 0, 3, limits, TaskType.GENERATE_STORY, action="t")

    assert (report.dropped_rag, report.dropped_jira) == (0, 1)
    assert calls[-1] == (0, 2)
    assert "J2" not in messages[1].content and "J1" in messages[1].content


def test_fit_messages_empties_rag_before_touching_related() -> None:
    """PA-114 · criterio 2: todo el RAG sale antes que la primera HU relacionada."""
    build, calls = make_build(3, 2)
    target = estimate_messages(make_build(3, 2)[0](0, 1))
    limits = limits_for(target, TaskType.GENERATE_STORY)

    _, report = fit_messages(build, 3, 2, limits, TaskType.GENERATE_STORY, action="t")

    assert (report.dropped_rag, report.dropped_jira) == (3, 1)
    assert calls == [(3, 2), (2, 2), (1, 2), (0, 2), (0, 1)]


def test_fit_messages_raises_overflow_when_base_does_not_fit() -> None:
    """PA-114 · criterio 2 (error): ni sin fuentes cabe → ContextOverflowError en español."""
    build, calls = make_build(2, 2)
    base = estimate_messages(make_build(2, 2)[0](0, 0))
    limits = limits_for(base - 1, TaskType.GENERATE_STORY)

    with pytest.raises(ContextOverflowError) as info:
        fit_messages(build, 2, 2, limits, TaskType.GENERATE_STORY, action="t")

    message = str(info.value)
    assert "ventana" in message
    assert str(limits.context_window) in message
    assert isinstance(info.value, AgentError)
    assert calls[-1] == (0, 0)


def test_fit_messages_logs_only_counts_never_content() -> None:
    """PA-114 · criterio 2: el log de recorte lleva recuentos y nunca contenido."""
    build, _ = make_build(3, 2)
    target = estimate_messages(make_build(3, 2)[0](0, 1))
    limits = limits_for(target, TaskType.GENERATE_STORY)

    with capture_logs() as logs:
        fit_messages(build, 3, 2, limits, TaskType.GENERATE_STORY, action="accion_prueba")

    (event,) = trim_events(logs)
    assert event["dropped_rag"] == 3
    assert event["dropped_jira"] == 1
    assert event["estimated_tokens"] == target
    assert event["available_tokens"] == target
    assert event["action"] == "accion_prueba"
    assert CONTENT_MARK not in repr(logs)


def test_fit_messages_overflow_log_has_no_content() -> None:
    """PA-114 · criterio 2: el aviso de desbordamiento tampoco lleva contenido."""
    build, _ = make_build(2, 1)
    limits = limits_for(10, TaskType.GENERATE_STORY)

    with capture_logs() as logs, pytest.raises(ContextOverflowError):
        fit_messages(build, 2, 1, limits, TaskType.GENERATE_STORY, action="t")

    assert any(e.get("log_level") == "warning" for e in logs)
    assert CONTENT_MARK not in repr(logs)


def test_check_messages_returns_messages_when_they_fit() -> None:
    """PA-114 · criterio 7 (base): sin recorte, devuelve los mismos mensajes si caben."""
    messages = [Message(role="user", content="x" * 300)]
    limits = limits_for(estimate_messages(messages), TaskType.ANALYZE_IMPACT)

    assert check_messages(messages, limits, TaskType.ANALYZE_IMPACT, action="t") == messages


def test_check_messages_raises_when_one_token_over() -> None:
    """PA-114 · criterio 7 (límite): un token de más y no hay nada que recortar → error."""
    messages = [Message(role="user", content="x" * 300)]
    limits = limits_for(estimate_messages(messages) - 1, TaskType.ANALYZE_IMPACT)

    with pytest.raises(ContextOverflowError):
        check_messages(messages, limits, TaskType.ANALYZE_IMPACT, action="t")


# --- 3. default_prompt_limits y PromptLimits.from_config --------------------------------------


def test_default_prompt_limits_falls_back_on_config_error(monkeypatch) -> None:
    """PA-114 · criterio 3: si get_config lanza ConfigError, valores por defecto (8192)."""

    def broken() -> AppConfig:
        raise ConfigError("Configuración ficticia rota.")

    monkeypatch.setattr(core.config, "get_config", broken)

    with capture_logs() as logs:
        limits = default_prompt_limits()

    assert limits.context_window == 8192
    assert dict(limits.max_output_tokens) == {}
    # Reserva de salida conservadora: la guarda no es más permisiva que con la configuración.
    assert limits.available(TaskType.GENERATE_STORY) == 8192 - 2500 - SAFETY_TOKENS
    [warning] = [e for e in logs if e.get("action") == "context_limits"]
    assert warning["error"] == "ConfigError"
    assert "ficticia rota" not in repr(logs)  # sin el mensaje de la excepción


def test_default_prompt_limits_uses_app_config_when_available(monkeypatch) -> None:
    """PA-114 · criterio 3: con configuración, los límites salen de ella."""
    config = app_config(PromptLimits(4096, {TaskType.GENERATE_STORY: 1000}))
    monkeypatch.setattr(core.config, "get_config", lambda: config)

    limits = default_prompt_limits()

    assert limits.context_window == 4096
    assert limits.max_output_tokens[TaskType.GENERATE_STORY] == 1000


def test_prompt_limits_from_config_reads_window_and_output_caps() -> None:
    """PA-114 · criterio 3: from_config lee context_window y max_output_tokens."""
    config = app_config(
        PromptLimits(6000, {TaskType.EVOLVE_STORY: 1500, TaskType.ANALYZE_IMPACT: 300})
    )

    limits = PromptLimits.from_config(config)

    assert limits.context_window == 6000
    assert dict(limits.max_output_tokens) == {
        TaskType.EVOLVE_STORY: 1500,
        TaskType.ANALYZE_IMPACT: 300,
    }
    assert limits.available(TaskType.EVOLVE_STORY) == 6000 - 1500 - SAFETY_TOKENS


# --- 4. StoryWriter: recorte y desbordamiento ---------------------------------------------------

STORY_CASES = [
    ("generate", "epic", "generate_story", TaskType.GENERATE_STORY),
    ("evolve", "story", "evolve_story", TaskType.EVOLVE_STORY),
]


@pytest.mark.parametrize(("method", "kind", "prompt_name", "task"), STORY_CASES)
def test_story_writer_trims_rag_then_related_and_fits_window(
    method: str, kind: str, prompt_name: str, task: TaskType
) -> None:
    """PA-114 · criterio 4: lo enviado cabe; sale todo el RAG y después la última HU relacionada;
    origen, HU previa, feedback e instrucciones se conservan."""
    ctx = full_ctx(kind)
    target = estimate_messages(story_messages(prompt_name, trim_context(ctx, 0, 1)))
    limits = limits_for(target, task)
    llm = FakeLLMProvider()

    with capture_logs() as logs:
        getattr(StoryWriter(llm, prompt_loader=loader, limits=limits), method)(ctx)

    assert len(llm.calls) == 1
    messages = sent(llm)
    assert estimate_messages(messages) <= limits.available(task)
    assert messages[0].content == PROMPTS[prompt_name]
    text = user_text(messages)
    assert f'<fuente ref="{ctx.jira[0].key}"' in text
    assert f'<fuente ref="{RELATED_KEYS[0]}"' in text
    assert f'<fuente ref="{RELATED_KEYS[1]}"' not in text
    assert all(f"RAG-MARCADOR-{doc}" not in text for doc in RAG_DOCS)
    assert "<hu_actual>" in text and escape_data(ctx.previous.title) in text
    assert FEEDBACK_MARK in text
    (event,) = trim_events(logs)
    assert (event["dropped_rag"], event["dropped_jira"]) == (4, 1)


def test_story_writer_drops_last_rag_chunks_first() -> None:
    """PA-114 · criterio 4: con poco recorte salen los últimos fragmentos y ninguna HU."""
    ctx = full_ctx("story")
    target = estimate_messages(story_messages("evolve_story", trim_context(ctx, 2, 2)))
    llm = FakeLLMProvider()

    StoryWriter(llm, prompt_loader=loader, limits=limits_for(target, TaskType.EVOLVE_STORY)).evolve(
        ctx
    )

    text = user_text(sent(llm))
    assert "RAG-MARCADOR-DOC-71" in text and "RAG-MARCADOR-DOC-72" in text
    assert "RAG-MARCADOR-DOC-73" not in text and "RAG-MARCADOR-DOC-74" not in text
    assert all(f'<fuente ref="{k}"' in text for k in RELATED_KEYS)


def test_story_writer_without_trimming_sends_everything() -> None:
    """PA-114 · criterio 4 (límite): si cabe justo, se envía el contexto completo."""
    ctx = full_ctx("story")
    target = estimate_messages(story_messages("evolve_story", ctx))
    llm = FakeLLMProvider()

    StoryWriter(llm, prompt_loader=loader, limits=limits_for(target, TaskType.EVOLVE_STORY)).evolve(
        ctx
    )

    assert sent(llm) == story_messages("evolve_story", ctx)


def test_story_writer_huge_instructions_raise_without_calling_llm() -> None:
    """PA-114 · criterio 4 (error): instrucciones enormes → ContextOverflowError, sin LLM."""
    llm = FakeLLMProvider()

    def huge_loader(name: str) -> Prompt:
        return Prompt(name=name, version="prueba-1", text=PROMPTS[name] + "x" * 30_000)

    writer = StoryWriter(llm, prompt_loader=huge_loader, limits=PromptLimits(8192))

    with pytest.raises(ContextOverflowError, match="ventana"):
        writer.evolve(full_ctx("story"))
    assert llm.calls == []


def test_story_writer_huge_origin_is_never_trimmed_and_raises() -> None:
    """PA-114 · criterio 4 (error): el origen nunca se recorta; si es enorme, error sin LLM."""
    origin = dataset.STORIES["DEMO-3"].model_copy(
        update={"description_text": "Descripción ficticia enorme. " * 2000}
    )
    llm = FakeLLMProvider()
    writer = StoryWriter(llm, prompt_loader=loader, limits=PromptLimits(8192))

    with pytest.raises(ContextOverflowError):
        writer.evolve(full_ctx("story", origin=origin))
    assert llm.calls == []


# --- 5. StoryWriter: el reintento de citas también se recorta -----------------------------


def first_call_estimate(ctx: StoryContext) -> int:
    llm = FakeLLMProvider(builders={UserStory: Sequence(story_citing(("jira", "DEMO-3")))})
    StoryWriter(llm, prompt_loader=loader, limits=PromptLimits(BIG)).evolve(ctx)
    return estimate_messages(sent(llm))


def test_story_writer_citation_retry_is_trimmed_to_fit() -> None:
    """PA-114 · criterio 5: la primera llamada cabe entera; el reintento se recorta y cabe."""
    ctx = full_ctx("story", rag_repeat=30)
    first = first_call_estimate(ctx)
    limits = limits_for(first + 2, TaskType.EVOLVE_STORY)
    builder = Sequence(story_citing(("rag", "DOC-99")), story_citing(("jira", "DEMO-3")))
    llm = FakeLLMProvider(builders={UserStory: builder})

    with capture_logs() as logs:
        StoryWriter(llm, prompt_loader=loader, limits=limits).evolve(ctx)

    assert len(llm.calls) == 2
    first_sent, retry_sent = sent(llm, 0), sent(llm, 1)
    assert estimate_messages(first_sent) == first
    assert len(retry_sent) == 4 and retry_sent[2].role == "assistant"
    assert estimate_messages(retry_sent) <= limits.available(TaskType.EVOLVE_STORY)
    assert source_count(retry_sent) < source_count(first_sent)
    assert [e["action"] for e in trim_events(logs)] == ["evolve_story_retry"]
    # Lo que nunca se recorta sigue en el reintento.
    assert retry_sent[0].content == PROMPTS["evolve_story"]
    assert '<fuente ref="DEMO-3"' in retry_sent[1].content
    assert FEEDBACK_MARK in retry_sent[1].content


def test_story_writer_citation_retry_overflow_raises() -> None:
    """PA-114 · criterio 5 (error): si el reintento no cabe ni recortando, ContextOverflowError."""
    ctx = dataclasses.replace(full_ctx("story"), rag=[rag_hit("DOC-71", 0)])
    first = first_call_estimate(ctx)
    limits = limits_for(first, TaskType.EVOLVE_STORY)
    builder = Sequence(story_citing(("rag", "DOC-99")), story_citing(("jira", "DEMO-3")))
    llm = FakeLLMProvider(builders={UserStory: builder})

    with pytest.raises(ContextOverflowError):
        StoryWriter(llm, prompt_loader=loader, limits=limits).evolve(ctx)
    assert len(llm.calls) == 1


# --- 6. TestWriter y QualityReviewer ------------------------------------------------------------


def suite_ctx(rag_repeat: int = 10) -> StoryContext:
    """Contexto para la suite: TestWriter pone la HU como `previous` y conserva el feedback."""
    ctx = full_ctx("story", rag_repeat=rag_repeat)
    return dataclasses.replace(ctx, previous=None)


def suite_messages(ctx: StoryContext, story: UserStory) -> list[Message]:
    internal = dataclasses.replace(ctx, previous=story)
    return story_messages("generate_tests", internal)


def citing_suite(cases: int | None = None) -> TestSuite:
    suite = renewal_test_suite().model_copy(
        update={"sources": [SourceRef(kind="jira", ref="DEMO-3")]}
    )
    return suite if cases is None else suite.model_copy(update={"cases": suite.cases[:cases]})


def test_test_writer_trims_rag_then_related_and_fits_window() -> None:
    """PA-114 · criterio 6: la suite recorta RAG y HU relacionadas y cabe en la ventana."""
    story = dataset.renewal_story()
    ctx = suite_ctx()
    target = estimate_messages(suite_messages(trim_context(ctx, 0, 1), story))
    limits = limits_for(target, TaskType.GENERATE_TESTS)
    llm = FakeLLMProvider()

    TestWriter(llm, prompt_loader=loader, limits=limits).generate(story, ctx)

    messages = sent(llm)
    assert estimate_messages(messages) <= limits.available(TaskType.GENERATE_TESTS)
    text = user_text(messages)
    assert all(f"RAG-MARCADOR-{doc}" not in text for doc in RAG_DOCS)
    assert f'<fuente ref="{RELATED_KEYS[0]}"' in text
    assert f'<fuente ref="{RELATED_KEYS[1]}"' not in text
    assert '<fuente ref="DEMO-3"' in text and "<hu_actual>" in text and FEEDBACK_MARK in text
    assert messages[0].content == PROMPTS["generate_tests"]


def test_test_writer_overflow_raises_without_calling_llm() -> None:
    """PA-114 · criterio 6 (error): si la suite no cabe ni recortando, error sin LLM."""
    llm = FakeLLMProvider()
    limits = limits_for(50, TaskType.GENERATE_TESTS)

    with pytest.raises(ContextOverflowError):
        TestWriter(llm, prompt_loader=loader, limits=limits).generate(
            dataset.renewal_story(), suite_ctx()
        )
    assert llm.calls == []


def test_test_writer_coverage_retry_is_trimmed_to_fit() -> None:
    """PA-114 · criterio 6: el reintento de cobertura también pasa por la guarda."""
    story = dataset.renewal_story()
    ctx = suite_ctx(rag_repeat=30)
    first = estimate_messages(suite_messages(ctx, story))
    limits = limits_for(first + 2, TaskType.GENERATE_TESTS)
    llm = FakeLLMProvider(builders={TestSuite: Sequence(citing_suite(1), citing_suite())})

    TestWriter(llm, prompt_loader=loader, limits=limits).generate(story, ctx)

    assert len(llm.calls) == 2
    first_sent, retry_sent = sent(llm, 0), sent(llm, 1)
    assert estimate_messages(first_sent) == first
    assert retry_sent[2].role == "assistant"
    assert estimate_messages(retry_sent) <= limits.available(TaskType.GENERATE_TESTS)
    assert source_count(retry_sent) < source_count(first_sent)


def test_test_writer_coverage_retry_overflow_raises() -> None:
    """PA-114 · criterio 6 (error): reintento de cobertura que no cabe → error tras 1 llamada."""
    story = dataset.renewal_story()
    base = suite_ctx()
    # Solo el origen y un fragmento corto: lo recortable es menor que lo que añade el reintento.
    ctx = dataclasses.replace(base, jira=base.jira[:1], rag=[rag_hit("DOC-71", 0)])
    limits = limits_for(estimate_messages(suite_messages(ctx, story)), TaskType.GENERATE_TESTS)
    llm = FakeLLMProvider(builders={TestSuite: Sequence(citing_suite(1), citing_suite())})

    with pytest.raises(ContextOverflowError):
        TestWriter(llm, prompt_loader=loader, limits=limits).generate(story, ctx)
    assert len(llm.calls) == 1


def quality_container(tmp_path: Path, limits: PromptLimits, llm: FakeLLMProvider) -> Container:
    container = fake_container(tmp_path / "memoria", llm=llm)
    return dataclasses.replace(container, config=app_config(limits))


def quality_messages(ctx: StoryContext, story: UserStory) -> list[Message]:
    internal = StoryContext(
        origin_kind="story", origin_key=ctx.origin_key, jira=ctx.jira, rag=ctx.rag, previous=story
    )
    return story_messages("review_quality", internal)


def quality_ctx(rag_repeat: int = 10) -> StoryContext:
    ctx = full_ctx("story", rag_repeat=rag_repeat)
    return dataclasses.replace(ctx, previous=None, feedback=[])


def cited_report(**update: Any) -> QualityReport:
    return renewal_quality_report().model_copy(
        update={"sources": [SourceRef(kind="jira", ref="DEMO-3")], **update}
    )


def test_quality_reviewer_limits_come_from_container_config(tmp_path: Path) -> None:
    """PA-114 · criterio 6: QualityReviewer toma los límites de container.config."""
    limits = PromptLimits(5000, {TaskType.REVIEW_STORY: 700})
    container = quality_container(tmp_path, limits, FakeLLMProvider())

    reviewer_limits = QualityReviewer(container).limits
    assert reviewer_limits.context_window == limits.context_window
    assert dict(reviewer_limits.max_output_tokens) == dict(limits.max_output_tokens)
    # PA-443: lleva la configuración de modelos para los límites por proveedor de la cadena.
    assert reviewer_limits.models is container.config.models  # type: ignore[union-attr]
    for task in (TaskType.REVIEW_STORY, TaskType.EVOLVE_STORY):
        assert reviewer_limits.available(task) == limits.available(task)


def test_quality_reviewer_trims_rag_then_related_and_fits_window(tmp_path: Path) -> None:
    """PA-114 · criterio 6: la revisión de calidad recorta y cabe en la ventana."""
    story = dataset.renewal_story()
    ctx = quality_ctx()
    target = estimate_messages(quality_messages(trim_context(ctx, 0, 1), story))
    limits = limits_for(target, TaskType.REVIEW_STORY)
    llm = FakeLLMProvider()
    reviewer = QualityReviewer(quality_container(tmp_path, limits, llm), prompt_loader=loader)

    reviewer._report(ctx, story)

    messages = sent(llm)
    assert estimate_messages(messages) <= limits.available(TaskType.REVIEW_STORY)
    text = user_text(messages)
    assert all(f"RAG-MARCADOR-{doc}" not in text for doc in RAG_DOCS)
    assert f'<fuente ref="{RELATED_KEYS[0]}"' in text
    assert f'<fuente ref="{RELATED_KEYS[1]}"' not in text
    assert '<fuente ref="DEMO-3"' in text and "<hu_actual>" in text


def test_quality_reviewer_retry_is_trimmed_to_fit(tmp_path: Path) -> None:
    """PA-114 · criterio 6: el reintento del informe también se recorta y cabe."""
    story = dataset.renewal_story()
    ctx = quality_ctx(rag_repeat=30)
    first = estimate_messages(quality_messages(ctx, story))
    limits = limits_for(first + 2, TaskType.REVIEW_STORY)
    bad = QualityFinding(
        kind="ambiguity", target_id="CA-99", explanation="Ficticio.", proposal="Ficticia."
    )
    llm = FakeLLMProvider(
        builders={QualityReport: Sequence(cited_report(findings=[bad]), cited_report())}
    )
    reviewer = QualityReviewer(quality_container(tmp_path, limits, llm), prompt_loader=loader)

    reviewer._report(ctx, story)

    assert len(llm.calls) == 2
    first_sent, retry_sent = sent(llm, 0), sent(llm, 1)
    assert estimate_messages(first_sent) == first
    assert estimate_messages(retry_sent) <= limits.available(TaskType.REVIEW_STORY)
    assert source_count(retry_sent) < source_count(first_sent)


def test_quality_review_overflow_raises_without_calling_llm(tmp_path: Path) -> None:
    """PA-114 · criterio 6 (error): ventana mínima → ContextOverflowError sin llamar al LLM."""
    llm = FakeLLMProvider()
    # Sin topes de salida: estructurar (EVOLVE_STORY) y revisar (REVIEW_STORY) disponen de 20.
    container = quality_container(tmp_path, PromptLimits(SAFETY_TOKENS + 20, {}), llm)

    with pytest.raises(ContextOverflowError):
        QualityReviewer(container, prompt_loader=loader).review(AF, "DEMO-3")
    assert llm.calls == []


# --- 7. LLMMemoryGenerator e ImpactAnalyzer ---------------------------------------------------

MEMORY_SOURCES = [SourceRef(kind="rag", ref="doc-reglamento"), SourceRef(kind="jira", ref="DEMO-2")]


def memory_artifact() -> Artifact:
    return Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.PUBLISHED,
        version=1,
        origin_key="DEMO-3",
        content=dataset.renewal_story().model_copy(update={"sources": MEMORY_SOURCES}),
        created_by="af-demo",
    )


def valid_memory(**update: Any) -> Memory:
    base = Memory(
        artifact_type=ArtifactType.USER_STORY,
        jira_key="DEMO-3",
        version=1,
        objective="Reducir las visitas al mostrador por renovaciones.",
        scope="Incluye la renovación web; excluye materiales audiovisuales.",
        business_rules=["RN-01: Máximo 2 renovaciones.", "RN-02: Sin reservas pendientes."],
        decisions=[],
        dependencies=["DEMO-2"],
        changes=[],
        acceptance_criteria=["CA-01: Renovación permitida.", "CA-02: Rechazada con reservas."],
        references=["doc-reglamento"],
    )
    return base.model_copy(update=update)


def memory_first_estimate(artifact: Artifact) -> int:
    llm = FakeLLMProvider(builders={Memory: Sequence(valid_memory())})
    LLMMemoryGenerator(llm, limits=PromptLimits(BIG)).generate(artifact)
    return estimate_messages(sent(llm))


def test_memory_generator_fits_exactly_without_trimming() -> None:
    """PA-114 · criterio 7 (límite): si el mensaje cabe justo, se llama al LLM sin cambios."""
    artifact = memory_artifact()
    first = memory_first_estimate(artifact)
    llm = FakeLLMProvider(builders={Memory: Sequence(valid_memory())})

    LLMMemoryGenerator(llm, limits=limits_for(first, TaskType.SYNTHESIZE_MEMORY)).generate(artifact)

    assert len(llm.calls) == 1
    assert estimate_messages(sent(llm)) == first


def test_memory_generator_overflow_raises_without_calling_llm() -> None:
    """PA-114 · criterio 7 (error): la memoria no cabe → ContextOverflowError sin LLM."""
    artifact = memory_artifact()
    first = memory_first_estimate(artifact)
    llm = FakeLLMProvider(builders={Memory: Sequence(valid_memory())})
    generator = LLMMemoryGenerator(llm, limits=limits_for(first - 1, TaskType.SYNTHESIZE_MEMORY))

    with pytest.raises(ContextOverflowError):
        generator.generate(artifact)
    assert llm.calls == []


def test_memory_generator_retry_overflow_raises() -> None:
    """PA-114 · criterio 7 (error): el reintento, más largo, no cabe → error tras 1 llamada."""
    artifact = memory_artifact()
    first = memory_first_estimate(artifact)
    builder = Sequence(valid_memory(acceptance_criteria=["CA-01: Renovación."]), valid_memory())
    llm = FakeLLMProvider(builders={Memory: builder})
    generator = LLMMemoryGenerator(llm, limits=limits_for(first, TaskType.SYNTHESIZE_MEMORY))

    with pytest.raises(ContextOverflowError):
        generator.generate(artifact)
    assert len(llm.calls) == 1


IMPACT_JIRA: list[IssueDetail] = [
    dataset.STORIES["DEMO-3"],
    dataset.EPIC,
    dataset.STORIES["DEMO-2"],
    dataset.STORIES["DEMO-4"],
]


def impact_answer(key: str = "DEMO-2") -> ImpactAnalysis:
    return ImpactAnalysis(
        diffs=[],
        affected=[ImpactItem(jira_key=key, reason="Motivo ficticio.", kind="story")],
        regression_notes=[],
    )


def run_impact(llm: FakeLLMProvider, limits: PromptLimits) -> ImpactAnalysis:
    story = dataset.renewal_story().model_copy(update={"title": "Renovar desde la app"})
    return ImpactAnalyzer(llm, limits=limits).analyze(
        story, IMPACT_JIRA, baseline=dataset.renewal_story(), origin_key="DEMO-3"
    )


def impact_first_estimate() -> int:
    llm = FakeLLMProvider(builders={ImpactAnalysis: Sequence(impact_answer())})
    run_impact(llm, PromptLimits(BIG))
    return estimate_messages(sent(llm))


def test_impact_analyzer_fits_exactly_without_trimming() -> None:
    """PA-114 · criterio 7 (límite): el análisis cabe justo y se llama una vez."""
    first = impact_first_estimate()
    llm = FakeLLMProvider(builders={ImpactAnalysis: Sequence(impact_answer())})

    run_impact(llm, limits_for(first, TaskType.ANALYZE_IMPACT))

    assert len(llm.calls) == 1
    assert estimate_messages(sent(llm)) == first


def test_impact_analyzer_overflow_raises_without_calling_llm() -> None:
    """PA-114 · criterio 7 (error): el análisis no cabe → ContextOverflowError sin LLM."""
    first = impact_first_estimate()
    llm = FakeLLMProvider(builders={ImpactAnalysis: Sequence(impact_answer())})

    with pytest.raises(ContextOverflowError):
        run_impact(llm, limits_for(first - 1, TaskType.ANALYZE_IMPACT))
    assert llm.calls == []


def test_impact_analyzer_retry_overflow_raises() -> None:
    """PA-114 · criterio 7 (error): el reintento por claves inventadas no cabe → error."""
    first = impact_first_estimate()
    builder = Sequence(impact_answer("DEMO-99"), impact_answer())
    llm = FakeLLMProvider(builders={ImpactAnalysis: builder})

    with pytest.raises(ContextOverflowError):
        run_impact(llm, limits_for(first, TaskType.ANALYZE_IMPACT))
    assert len(llm.calls) == 1


# --- 8. Medición: /3 no se queda corto en español --------------------------------------------

# docs/pruebas/E2E-local-2026-10-02.md §6.1 (tokenizador real de qwen3, evolución de AFQP-3).
MEASURED = [
    ("instrucciones", 2260, 674),
    ("contexto Jira + RAG", 17_537, 5498),
    ("HU previa y feedback", 3856, 1278),
    ("total", 23_653, 7434),
]
MEASURED_CHARS_PER_TOKEN = 3.19  # contexto en español (la fila más grande del prompt)
CORPUS_DOCS = (
    "data/seed/corpus/documentacion/DOC-08-modulo-prestamo-digital.md",
    "data/seed/corpus/documentacion/DOC-10-modulo-notificaciones.md",
)


@pytest.mark.parametrize(("part", "chars", "real_tokens"), MEASURED)
def test_estimate_tokens_is_not_below_measured_real_tokens(
    part: str, chars: int, real_tokens: int
) -> None:
    """PA-114 · criterio 8: con /3 la estimación cubre los tokens reales medidos."""
    assert CHARS_PER_TOKEN == 3
    assert estimate_tokens("x" * chars) >= real_tokens, part


@pytest.mark.parametrize("relative", CORPUS_DOCS)
def test_estimate_tokens_on_corpus_exceeds_measured_spanish_ratio(relative: str) -> None:
    """PA-114 · criterio 8: en documentos reales del corpus, /3 supera la proporción medida."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert len(text) > 1000

    assert estimate_tokens(text) > math.ceil(len(text) / MEASURED_CHARS_PER_TOKEN)


# --- PA-228: el grafo pasa los límites del contenedor a los escritores ---------------------


def test_graph_nodes_pass_container_limits_to_writers(tmp_path, monkeypatch) -> None:
    """PA-228: con configuración, el grafo construye los límites desde el contenedor y no
    recurre a `get_config()`."""
    import core.graph.nodes as nodes_module
    from core.graph.nodes import GraphNodes
    from tests.fakes.container import fake_container

    config = app_config(PromptLimits(12_345, {TaskType.EVOLVE_STORY: 111}))
    nodes = GraphNodes(fake_container(tmp_path, config=config))

    def unexpected() -> PromptLimits:
        raise AssertionError("no debería usarse get_config() con un contenedor configurado")

    monkeypatch.setattr(nodes_module, "default_prompt_limits", unexpected)
    limits = nodes._limits()
    assert limits.context_window == 12_345
    assert limits.available(TaskType.EVOLVE_STORY) == 12_345 - 111 - SAFETY_TOKENS


def test_graph_nodes_fall_back_to_default_limits_without_config(tmp_path) -> None:
    """PA-228: sin configuración en el contenedor (pruebas), los límites por defecto."""
    from core.graph.nodes import GraphNodes
    from tests.fakes.container import fake_container

    nodes = GraphNodes(fake_container(tmp_path))
    assert nodes._limits().context_window > 0


def test_graph_nodes_construct_every_writer_with_limits() -> None:
    """PA-228: los cinco sitios del grafo que crean escritores les pasan `limits`."""
    from core.config import ROOT_DIR

    source = (ROOT_DIR / "core" / "graph" / "nodes.py").read_text(encoding="utf-8")
    for writer in ("StoryWriter", "TestWriter", "ImpactAnalyzer"):
        assert f"{writer}(self.c.llm)" not in source
    assert source.count("limits=self._limits()") == 5
