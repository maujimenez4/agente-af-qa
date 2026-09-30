"""Pruebas de adapters/llm/fallback.py (T-10 · RF-43, RF-44, RNF-27, RNF-28).

Los eslabones de la cadena son `tests.fakes.llm.FakeLLMProvider`; no hay llamadas reales.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from adapters.base import LLMProvider, Message, TaskType
from adapters.errors import (
    AuthenticationError,
    ExternalServiceError,
    RateLimitError,
)
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.openai_compatible import StructuredOutputError
from adapters.llm.usage import InMemoryUsageRecorder, UsageRecord
from schemas.user_story import UserStory
from tests.fakes.llm import FakeLLMProvider

MESSAGES = [Message(role="user", content="Genera una HU ficticia de renovación.")]
TASK = TaskType.GENERATE_STORY


def _fixed_chain(*providers: LLMProvider) -> FallbackLLMProvider:
    return FallbackLLMProvider(lambda _task: list(providers))


def _start_of_utc_day() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass
class SpyRecorder:
    """UsageRecorder que registra los argumentos de `tokens_since`."""

    total: int = 0
    records: list[UsageRecord] = field(default_factory=list)
    since_calls: list[datetime] = field(default_factory=list)

    def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    def tokens_since(self, since: datetime) -> int:
        self.since_calls.append(since)
        return self.total


# --- Contrato ------------------------------------------------------------------------------


def test_fallback_satisfies_llm_protocol_when_built() -> None:
    """RF-44: FallbackLLMProvider implementa el protocolo LLMProvider."""
    assert isinstance(_fixed_chain(FakeLLMProvider()), LLMProvider)


# --- Orden de la cadena --------------------------------------------------------------------


def test_generate_uses_first_provider_when_it_answers() -> None:
    """RF-44: se usa el principal si responde y no se llama a los respaldos."""
    first = FakeLLMProvider(provider="a", model="ma")
    second = FakeLLMProvider(provider="b", model="mb")

    result = _fixed_chain(first, second).generate(MESSAGES, TASK)

    assert result.provider == "a"
    assert len(first.calls) == 1
    assert second.calls == []


def test_chain_for_receives_requested_task() -> None:
    """RF-41 · RF-44: la cadena se resuelve para la tarea pedida."""
    asked: list[TaskType] = []

    def chain_for(task: TaskType) -> Sequence[LLMProvider]:
        asked.append(task)
        return [FakeLLMProvider()]

    FallbackLLMProvider(chain_for).generate(MESSAGES, TaskType.NL_TO_JQL)

    assert asked == [TaskType.NL_TO_JQL]


@pytest.mark.parametrize(
    "error",
    [
        RateLimitError("Límite de uso alcanzado (ficticio).", service="a", retry_after=5.0),
        AuthenticationError("Credenciales no válidas (ficticio).", service="a"),
        ExternalServiceError("Servicio no disponible (ficticio).", service="a"),
    ],
    ids=["rate_limit", "authentication", "external"],
)
def test_generate_uses_next_provider_when_first_fails(error: Exception) -> None:
    """RF-44: ante límite de uso, credenciales o fallo externo se pasa al siguiente eslabón."""
    first = FakeLLMProvider(provider="a", model="ma", error=error)
    second = FakeLLMProvider(provider="b", model="mb")

    result = _fixed_chain(first, second).generate(MESSAGES, TASK)

    assert result.provider == "b"
    assert result.model == "mb"
    assert len(first.calls) == 1
    assert len(second.calls) == 1


def test_structured_uses_next_provider_when_first_rate_limited() -> None:
    """RF-44: el respaldo también funciona para salidas estructuradas."""
    first = FakeLLMProvider(provider="a", error=RateLimitError("Límite (ficticio).", "a"))
    second = FakeLLMProvider(provider="b")

    result = _fixed_chain(first, second).generate_structured(MESSAGES, UserStory, TASK)

    assert isinstance(result.content, UserStory)
    assert result.provider == "b"
    assert second.calls[0]["schema"] is UserStory


def test_structured_does_not_fall_back_when_structured_output_error() -> None:
    """RNF-28: una salida inválida tras el reintento se informa; no se prueba otro proveedor."""
    error = StructuredOutputError("Salida estructurada no válida (ficticio).", service="a")
    first = FakeLLMProvider(provider="a", error=error)
    second = FakeLLMProvider(provider="b")

    with pytest.raises(StructuredOutputError):
        _fixed_chain(first, second).generate_structured(MESSAGES, UserStory, TASK)

    assert second.calls == []


# --- Cadena agotada ------------------------------------------------------------------------


def test_generate_raises_external_error_when_chain_empty() -> None:
    """RF-44 (límite): sin proveedores disponibles se informa en español citando la tarea."""
    with pytest.raises(ExternalServiceError) as info:
        FallbackLLMProvider(lambda _task: []).generate(MESSAGES, TASK)

    assert "generate_story" in str(info.value)


def test_structured_raises_external_error_when_chain_empty() -> None:
    """RF-44 (límite): lo mismo para generate_structured."""
    with pytest.raises(ExternalServiceError) as info:
        FallbackLLMProvider(lambda _task: []).generate_structured(
            MESSAGES, UserStory, TaskType.GENERATE_TESTS
        )

    assert "generate_tests" in str(info.value)


def test_generate_raises_rate_limit_with_min_retry_after_when_all_rate_limited() -> None:
    """RNF-27: si todos alcanzan el límite, RateLimitError con el menor retry_after conocido."""
    chain = [
        FakeLLMProvider(provider="a", error=RateLimitError("Límite.", "a", retry_after=30.0)),
        FakeLLMProvider(provider="b", error=RateLimitError("Límite.", "b", retry_after=None)),
        FakeLLMProvider(provider="c", error=RateLimitError("Límite.", "c", retry_after=10.0)),
    ]

    with pytest.raises(RateLimitError) as info:
        _fixed_chain(*chain).generate(MESSAGES, TASK)

    assert info.value.retry_after == 10.0
    assert all(len(p.calls) == 1 for p in chain)


def test_generate_raises_rate_limit_without_retry_after_when_none_known() -> None:
    """RNF-27 (límite): si ningún proveedor indica retry_after, este queda a None."""
    chain = [
        FakeLLMProvider(provider="a", error=RateLimitError("Límite.", "a")),
        FakeLLMProvider(provider="b", error=RateLimitError("Límite.", "b")),
    ]

    with pytest.raises(RateLimitError) as info:
        _fixed_chain(*chain).generate(MESSAGES, TASK)

    assert info.value.retry_after is None


@pytest.mark.parametrize(
    "other",
    [
        ExternalServiceError("Servicio caído (ficticio).", "b"),
        AuthenticationError("Clave no válida (ficticio).", "b"),
    ],
    ids=["external", "authentication"],
)
def test_generate_raises_external_error_when_failures_are_mixed(other: Exception) -> None:
    """RF-44: si falla toda la cadena con errores de distinto tipo → ExternalServiceError."""
    chain = [
        FakeLLMProvider(provider="a", error=RateLimitError("Límite.", "a", retry_after=5.0)),
        FakeLLMProvider(provider="b", error=other),
    ]

    with pytest.raises(ExternalServiceError) as info:
        _fixed_chain(*chain).generate(MESSAGES, TASK)

    assert not isinstance(info.value, RateLimitError)
    assert all(len(p.calls) == 1 for p in chain)


# --- Registro de uso (RF-43) ---------------------------------------------------------------


def test_generate_records_usage_of_answering_provider() -> None:
    """RF-43: tras un éxito se registra el uso con la tarea y el proveedor/modelo que respondió."""
    recorder = InMemoryUsageRecorder()
    first = FakeLLMProvider(provider="a", model="ma", error=RateLimitError("Límite.", "a"))
    second = FakeLLMProvider(provider="b", model="mb")
    fallback = FallbackLLMProvider(lambda _task: [first, second], recorder)

    result = fallback.generate(MESSAGES, TASK)

    assert len(recorder.records) == 1
    usage = recorder.records[0]
    assert usage.task == TASK
    assert usage.provider == "b"
    assert usage.model == "mb"
    assert usage.input_tokens == result.input_tokens
    assert usage.output_tokens == result.output_tokens
    assert usage.latency_ms == result.latency_ms


def test_structured_records_usage_when_ok() -> None:
    """RF-43: las llamadas estructuradas también registran su uso."""
    recorder = InMemoryUsageRecorder()
    fallback = FallbackLLMProvider(lambda _task: [FakeLLMProvider(provider="a")], recorder)

    result = fallback.generate_structured(MESSAGES, UserStory, TaskType.EVOLVE_STORY)

    assert len(recorder.records) == 1
    assert recorder.records[0].task == TaskType.EVOLVE_STORY
    assert recorder.records[0].total_tokens == result.input_tokens + result.output_tokens


def test_generate_does_not_record_usage_when_all_fail() -> None:
    """RF-43: los fallos no registran uso."""
    recorder = InMemoryUsageRecorder()
    failing = FakeLLMProvider(error=ExternalServiceError("Caído (ficticio).", "fake"))
    fallback = FallbackLLMProvider(lambda _task: [failing], recorder)

    with pytest.raises(ExternalServiceError):
        fallback.generate(MESSAGES, TASK)

    assert recorder.records == []


def test_generate_works_without_recorder() -> None:
    """RF-43 (límite): sin recorder la llamada funciona igual."""
    result = FallbackLLMProvider(lambda _task: [FakeLLMProvider()]).generate(MESSAGES, TASK)
    assert result.content


# --- Consumo diario (RNF-27) ---------------------------------------------------------------


def test_tokens_today_returns_zero_without_recorder() -> None:
    """RNF-27 (límite): sin recorder el consumo diario es 0."""
    assert _fixed_chain(FakeLLMProvider()).tokens_today() == 0


def test_tokens_today_queries_recorder_since_start_of_utc_day() -> None:
    """RNF-27: el consumo diario se consulta desde el inicio del día en UTC."""
    recorder = SpyRecorder(total=1234)
    fallback = FallbackLLMProvider(lambda _task: [FakeLLMProvider()], recorder)

    assert fallback.tokens_today() == 1234
    since = recorder.since_calls[-1]
    assert since.utcoffset() == timedelta(0)
    assert since == _start_of_utc_day()


def test_tokens_today_excludes_yesterday_records() -> None:
    """RNF-27: solo cuenta el consumo del día en curso."""
    recorder = InMemoryUsageRecorder()
    yesterday = _start_of_utc_day() - timedelta(seconds=1)
    for at, tokens in ((yesterday, 500), (datetime.now(UTC), 40)):
        recorder.record(
            UsageRecord(
                task=TASK,
                provider="a",
                model="ma",
                input_tokens=tokens,
                output_tokens=0,
                latency_ms=1,
                at=at,
            )
        )
    fallback = FallbackLLMProvider(lambda _task: [FakeLLMProvider()], recorder)

    assert fallback.tokens_today() == 40


def test_generate_still_works_when_daily_warning_exceeded() -> None:
    """RNF-27: superar el umbral diario solo avisa; la llamada no se bloquea."""
    recorder = SpyRecorder(total=10_000)
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a")], recorder, daily_token_warning=100
    )

    result = fallback.generate(MESSAGES, TASK)

    assert result.provider == "a"
    assert len(recorder.records) == 1
