"""Pruebas de adapters/llm/fallback.py (T-10 · RF-43, RF-44, RNF-27, RNF-28).

Los eslabones de la cadena son `tests.fakes.llm.FakeLLMProvider`; no hay llamadas reales.
"""

import dataclasses
import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from adapters.base import LLMProvider, Message, TaskType
from adapters.errors import (
    AuthenticationError,
    ExternalServiceError,
    RateLimitError,
)
from adapters.llm.fallback import (
    FallbackEvent,
    FallbackLLMProvider,
    capture_fallbacks,
    fallback_reason,
)
from adapters.llm.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderTimeoutError,
    StructuredOutputError,
)
from adapters.llm.usage import InMemoryUsageRecorder, UsageRecord, usage_scope
from schemas.user_story import UserStory
from tests.fakes.llm import FakeLLMProvider
from tests.unit.test_llm_openai_compatible import (
    BODY_MARKER,
    FAKE_KEY,
    TEST_PROMPTS,
    VALID_ANSWER,
    Answer,
    FakeServer,
    bad_request,
    make_client,
)
from tests.unit.test_llm_openai_compatible import completion as oa_completion
from tests.unit.test_llm_openai_compatible import error_response as oa_error

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


# --- T-32 · Cadena con proveedores OpenAI-compatibles (RNF-12, RNF-27, PA-16) ---------------


@dataclass
class Link:
    """Eslabón real (OpenAICompatibleProvider) sobre un servidor falso."""

    provider: OpenAICompatibleProvider
    server: FakeServer
    sleeps: list[float]


def _link(name: str, model: str, *replies: Any, **kwargs: Any) -> Link:
    server = FakeServer(list(replies))
    sleeps: list[float] = []
    provider = OpenAICompatibleProvider(
        name, model, make_client(server), prompts=TEST_PROMPTS, sleep=sleeps.append, **kwargs
    )
    return Link(provider, server, sleeps)


def _timeout() -> httpx.ReadTimeout:
    return httpx.ReadTimeout("tiempo agotado (ficticio)")


def test_chain_uses_next_provider_when_first_times_out() -> None:
    """CA-2 · RNF-12: un tiempo agotado no se reintenta con el mismo proveedor: pasa al siguiente
    y el evento lleva el motivo «tiempo_espera»."""
    first = _link("a", "ma", _timeout())
    second = _link("b", "mb", oa_completion("respuesta ficticia"))

    with capture_fallbacks() as events:
        result = _fixed_chain(first.provider, second.provider).generate(MESSAGES, TASK)

    assert (result.provider, result.content) == ("b", "respuesta ficticia")
    assert len(first.server.requests) == 1  # sin bucle de reintentos
    assert first.sleeps == []
    assert [(e.provider, e.model, e.reason) for e in events] == [("a", "ma", "tiempo_espera")]


def test_chain_raises_spanish_external_error_when_all_time_out() -> None:
    """CA-2: si todos agotan el tiempo → ExternalServiceError en español de la cadena."""
    links = [_link("a", "ma", _timeout()), _link("b", "mb", _timeout())]

    with capture_fallbacks() as events, pytest.raises(ExternalServiceError) as info:
        _fixed_chain(*(link.provider for link in links)).generate(MESSAGES, TASK)

    assert not isinstance(info.value, RateLimitError | ProviderTimeoutError)
    assert "Todos los proveedores" in str(info.value)
    assert "generate_story" in str(info.value)
    assert all(len(link.server.requests) == 1 for link in links)
    assert [e.reason for e in events] == ["tiempo_espera", "tiempo_espera"]


def test_chain_moves_on_without_sleeping_when_retry_after_exceeds_max_wait() -> None:
    """CA-1 · RNF-27: retry-after > max_wait_s → RateLimitError inmediato y siguiente proveedor."""
    first = _link("a", "ma", oa_error(429, {"retry-after": "120"}), max_wait_s=20.0)
    second = _link("b", "mb", oa_completion("ok"))

    with capture_fallbacks() as events:
        result = _fixed_chain(first.provider, second.provider).generate(MESSAGES, TASK)

    assert result.provider == "b"
    assert first.sleeps == []
    assert len(first.server.requests) == 1
    assert [(e.provider, e.reason) for e in events] == [("a", "limite")]


def test_chain_uses_next_provider_when_generic_400_in_structured() -> None:
    """CA-3 · PA-16: en la cadena, un 400 genérico pasa al siguiente proveedor (motivo «error»)
    sin probar el modo JSON en el primero."""
    first = _link("a", "ma", bad_request("context length exceeded", "messages"))
    second = _link("b", "mb", oa_completion(VALID_ANSWER))

    with capture_fallbacks() as events:
        result = _fixed_chain(first.provider, second.provider).generate_structured(
            MESSAGES, Answer, TASK
        )

    assert result.provider == "b"
    assert result.content.score == 7
    assert len(first.server.requests) == 1
    assert [(e.provider, e.reason) for e in events] == [("a", "error")]


# --- T-32 · capture_fallbacks y FallbackEvent (PA-67) --------------------------------------


def _failing_chain() -> FallbackLLMProvider:
    return _fixed_chain(
        FakeLLMProvider(provider="a", model="ma", error=RateLimitError("Límite.", "a")),
        FakeLLMProvider(provider="b", model="mb", error=ProviderTimeoutError("Tiempo.", "b")),
        FakeLLMProvider(provider="c", model="mc", error=ExternalServiceError("Caído.", "c")),
        FakeLLMProvider(provider="d", model="md"),
    )


def test_capture_fallbacks_collects_events_in_order_when_providers_fail() -> None:
    """CA-4 · PA-67: se recogen los eventos en orden con proveedor, modelo, motivo y tarea."""
    with capture_fallbacks() as events:
        result = _failing_chain().generate(MESSAGES, TASK)

    assert result.provider == "d"
    assert [(e.provider, e.model, e.reason) for e in events] == [
        ("a", "ma", "limite"),
        ("b", "mb", "tiempo_espera"),
        ("c", "mc", "error"),
    ]
    assert all(e.task == TASK for e in events)
    assert all(e.at.tzinfo is not None for e in events)


def test_capture_fallbacks_is_empty_when_first_provider_answers() -> None:
    """CA-4 (límite): sin cambios de proveedor no hay eventos."""
    with capture_fallbacks() as events:
        _fixed_chain(FakeLLMProvider(provider="a")).generate(MESSAGES, TASK)

    assert events == []


def test_capture_fallbacks_records_event_of_last_provider_when_chain_exhausted() -> None:
    """CA-4: si se agota la cadena, cada eslabón fallido deja su evento."""
    chain = _fixed_chain(
        FakeLLMProvider(provider="a", error=RateLimitError("Límite.", "a")),
        FakeLLMProvider(provider="b", error=RateLimitError("Límite.", "b")),
    )
    with capture_fallbacks() as events, pytest.raises(RateLimitError):
        chain.generate(MESSAGES, TASK)

    assert [e.provider for e in events] == ["a", "b"]


def test_capture_fallbacks_collects_nothing_when_call_is_outside_block() -> None:
    """CA-4: las llamadas hechas fuera del bloque no se recogen."""
    chain = _failing_chain()
    chain.generate(MESSAGES, TASK)  # fuera de cualquier bloque: no debe fallar

    with capture_fallbacks() as events:
        pass
    chain.generate(MESSAGES, TASK)  # tras cerrar el bloque

    assert events == []


def test_capture_fallbacks_isolates_nested_blocks() -> None:
    """CA-4: un bloque anidado recoge solo lo suyo y el exterior sigue recogiendo al volver."""
    single_failure = _fixed_chain(
        FakeLLMProvider(provider="x", error=ExternalServiceError("Caído.", "x")),
        FakeLLMProvider(provider="y"),
    )
    with capture_fallbacks() as outer:
        single_failure.generate(MESSAGES, TASK)
        with capture_fallbacks() as inner:
            _failing_chain().generate(MESSAGES, TASK)
        single_failure.generate(MESSAGES, TASK)

    assert [e.provider for e in inner] == ["a", "b", "c"]
    assert [e.provider for e in outer] == ["x", "x"]


def test_capture_fallbacks_restores_previous_block_when_exception() -> None:
    """CA-4: si el bloque interior termina con excepción, se restaura el exterior."""
    with capture_fallbacks() as outer:
        with pytest.raises(RuntimeError), capture_fallbacks():
            raise RuntimeError("fallo ficticio")
        _failing_chain().generate(MESSAGES, TASK)

    assert len(outer) == 3


def test_capture_fallbacks_isolates_threads() -> None:
    """CA-4: otro hilo (otra sesión) no ve los eventos del hilo principal ni al revés."""
    seen_in_thread: list[list[FallbackEvent]] = []
    errors: list[BaseException] = []

    def other_session() -> None:
        try:
            with capture_fallbacks() as thread_events:
                _fixed_chain(
                    FakeLLMProvider(provider="hilo", error=RateLimitError("Límite.", "hilo")),
                    FakeLLMProvider(provider="ok"),
                ).generate(MESSAGES, TASK)
            _failing_chain().generate(MESSAGES, TASK)  # fuera de su bloque
            seen_in_thread.append(thread_events)
        except BaseException as exc:  # pragma: no cover - se informa abajo
            errors.append(exc)

    with capture_fallbacks() as main_events:
        thread = threading.Thread(target=other_session)
        thread.start()
        thread.join(timeout=10)
        _fixed_chain(
            FakeLLMProvider(provider="principal", error=RateLimitError("Límite.", "p")),
            FakeLLMProvider(provider="ok"),
        ).generate(MESSAGES, TASK)

    assert errors == []
    assert [e.provider for e in seen_in_thread[0]] == ["hilo"]
    assert [e.provider for e in main_events] == ["principal"]


def test_capture_fallbacks_ignores_calls_from_thread_without_block() -> None:
    """CA-4: un hilo sin bloque propio no escribe en la lista del hilo principal."""
    with capture_fallbacks() as main_events:
        thread = threading.Thread(target=lambda: _failing_chain().generate(MESSAGES, TASK))
        thread.start()
        thread.join(timeout=10)

    assert main_events == []


@pytest.mark.parametrize(
    ("reason", "fragment"),
    [
        ("limite", "límite de uso"),
        ("tiempo_espera", "no ha respondido a tiempo"),
        ("error", "ha fallado"),
    ],
)
def test_fallback_event_message_is_spanish_when_built(reason: Any, fragment: str) -> None:
    """CA-4 · PA-67: el aviso para la UI está en español y nombra al proveedor."""
    event = FallbackEvent(TASK, "proveedor-ficticio", "modelo-ficticio", reason)

    assert fragment in event.message
    assert event.message.startswith("proveedor-ficticio ")
    assert event.message.endswith(".")
    assert "siguiente" not in event.message  # vale también para el último de la cadena


def test_fallback_event_message_omits_internal_details_when_error_has_them() -> None:
    """CA-4 · RNF-02: el aviso no incluye el texto de la excepción, la tarea interna ni la clave."""
    marker = "MARCADOR-INTERNO-NO-MOSTRAR test-key https://llm.example/v1"
    chain = _fixed_chain(
        FakeLLMProvider(provider="a", model="ma", error=ExternalServiceError(marker, "a")),
        FakeLLMProvider(provider="b"),
    )
    with capture_fallbacks() as events:
        chain.generate(MESSAGES, TASK)

    message = events[0].message
    for forbidden in ("MARCADOR-INTERNO", "test-key", "llm.example", TASK.value, "Exception"):
        assert forbidden not in message


def test_fallback_event_is_immutable() -> None:
    """CA-4: los eventos son inmutables (frozen)."""
    event = FallbackEvent(TASK, "a", "ma", "error")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.provider = "otro"  # type: ignore[misc]


def test_structured_output_error_creates_no_event_nor_fallback() -> None:
    """CA-4 · RNF-28: una salida estructurada inválida no genera evento ni respaldo."""
    error = StructuredOutputError("Salida no válida (ficticio).", service="a")
    second = FakeLLMProvider(provider="b")

    with capture_fallbacks() as events, pytest.raises(StructuredOutputError):
        _fixed_chain(FakeLLMProvider(provider="a", error=error), second).generate_structured(
            MESSAGES, UserStory, TASK
        )

    assert events == []
    assert second.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RateLimitError("Límite.", "a", retry_after=3.0), "limite"),
        (ProviderTimeoutError("Tiempo.", "a"), "tiempo_espera"),
        (AuthenticationError("Clave.", "a"), "error"),
        (ExternalServiceError("Caído.", "a"), "error"),
    ],
    ids=["rate_limit", "timeout", "auth", "external"],
)
def test_fallback_reason_maps_error_type(error: ExternalServiceError, expected: str) -> None:
    """CA-4 · PA-67: el motivo se deduce del tipo de error."""
    assert fallback_reason(error) == expected


# --- T-32 · Registro de uso con artefacto (RF-43) ------------------------------------------


def test_usage_record_carries_artifact_id_when_inside_scope() -> None:
    """CA-5 · RF-43: dentro de usage_scope el registro lleva el artifact_id del bloque."""
    recorder = InMemoryUsageRecorder()
    fallback = FallbackLLMProvider(lambda _task: [FakeLLMProvider()], recorder)
    artifact_id = uuid4()

    with usage_scope(artifact_id=artifact_id):
        fallback.generate(MESSAGES, TASK)
        fallback.generate_structured(MESSAGES, UserStory, TASK)

    assert [r.artifact_id for r in recorder.records] == [artifact_id, artifact_id]


def test_usage_record_has_no_artifact_id_when_outside_scope() -> None:
    """CA-5: fuera de usage_scope el registro lleva artifact_id None, también tras el bloque."""
    recorder = InMemoryUsageRecorder()
    fallback = FallbackLLMProvider(lambda _task: [FakeLLMProvider()], recorder)

    fallback.generate(MESSAGES, TASK)
    with usage_scope(artifact_id=uuid4()):
        pass
    fallback.generate(MESSAGES, TASK)

    assert [r.artifact_id for r in recorder.records] == [None, None]


def test_usage_scope_restores_artifact_id_after_exception() -> None:
    """CA-5: si el bloque lanza, el artifact_id se restaura igualmente."""
    recorder = InMemoryUsageRecorder()
    fallback = FallbackLLMProvider(lambda _task: [FakeLLMProvider()], recorder)
    outer = uuid4()

    with usage_scope(artifact_id=outer):
        with pytest.raises(RuntimeError), usage_scope(artifact_id=uuid4()):
            raise RuntimeError("fallo ficticio")
        fallback.generate(MESSAGES, TASK)
    fallback.generate(MESSAGES, TASK)

    assert [r.artifact_id for r in recorder.records] == [outer, None]


@dataclass
class BrokenRecorder:
    """UsageRecorder cuya base de datos falla en `record` o en `tokens_since`."""

    fail_on: str
    records: list[UsageRecord] = field(default_factory=list)

    def _error(self) -> Exception:
        return sa.exc.OperationalError(
            "INSERT INTO llm_usage MARCADOR-SQL-NO-MOSTRAR",
            {"secret": "test-key"},
            Exception("conexión rechazada MARCADOR-SQL-NO-MOSTRAR"),
        )

    def record(self, usage: UsageRecord) -> None:
        if self.fail_on == "record":
            raise self._error()
        self.records.append(usage)

    def tokens_since(self, since: datetime) -> int:
        if self.fail_on == "tokens_since":
            raise self._error()
        return 0


@pytest.mark.parametrize(
    ("fail_on", "event"),
    [("record", "llm_usage_not_recorded"), ("tokens_since", "llm_usage_not_read")],
)
def test_generate_returns_result_and_warns_when_usage_store_fails(fail_on: str, event: str) -> None:
    """CA-5 · RNF-12: si el registro de uso o el consumo diario fallan, la respuesta se devuelve
    y se registra un aviso (`llm_usage_not_recorded` o `llm_usage_not_read`) sin el mensaje."""
    recorder = BrokenRecorder(fail_on)
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", model="ma")],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs:
        result = fallback.generate(MESSAGES, TASK)

    assert result.provider == "a"
    warnings = [entry for entry in logs if entry["event"] == event]
    assert len(warnings) == 1
    assert warnings[0]["error"] == "OperationalError"
    assert warnings[0]["log_level"] == "warning"
    text = json.dumps(logs, ensure_ascii=False, default=str)
    assert "MARCADOR-SQL-NO-MOSTRAR" not in text
    assert "test-key" not in text


def test_structured_returns_result_when_usage_store_fails() -> None:
    """CA-5 · RNF-12: lo mismo en generate_structured."""
    fallback = FallbackLLMProvider(lambda _task: [FakeLLMProvider()], BrokenRecorder("record"))

    result = fallback.generate_structured(MESSAGES, UserStory, TASK)

    assert isinstance(result.content, UserStory)


# --- T-32 · Logs de la cadena (RNF-02) -----------------------------------------------------


def test_chain_logs_omit_message_content_and_error_text() -> None:
    """CA-10 · RNF-02: los eventos de fallback.py no llevan el contenido de los mensajes, el
    texto de los errores ni la clave."""
    secret_messages = [Message(role="user", content="CONTENIDO-PRIVADO-FICTICIO")]
    chain = _fixed_chain(
        FakeLLMProvider(
            provider="a", error=ExternalServiceError("ERROR-INTERNO test-key", service="a")
        ),
        FakeLLMProvider(provider="b"),
    )

    with capture_logs() as logs:
        chain.generate(secret_messages, TASK)

    events = [entry["event"] for entry in logs]
    assert events == ["llm_provider_failed", "llm_call"]
    failed = logs[0]
    assert failed["error"] == "ExternalServiceError"
    assert failed["reason"] == "error"
    text = json.dumps(logs, ensure_ascii=False, default=str)
    for forbidden in ("CONTENIDO-PRIVADO-FICTICIO", "ERROR-INTERNO", "test-key", "Respuesta"):
        assert forbidden not in text


def test_chain_logs_omit_content_with_real_provider_when_timeout() -> None:
    """CA-10 · RNF-02: con proveedores reales sobre MockTransport, ni la clave ni el cuerpo
    llegan a los logs."""
    first = _link("a", "ma", oa_error(500))
    second = _link("b", "mb", oa_completion("RESPUESTA-PRIVADA-FICTICIA"))

    with capture_logs() as logs:
        _fixed_chain(first.provider, second.provider).generate(MESSAGES, TASK)

    text = json.dumps(logs, ensure_ascii=False, default=str)
    for forbidden in (FAKE_KEY, BODY_MARKER, "RESPUESTA-PRIVADA-FICTICIA", MESSAGES[0].content):
        assert forbidden not in text


# --- PA-145 · Aviso de consumo diario también tras un fallo con tokens gastados ------------


def _failure(spent: tuple[int, int], cls: type[ExternalServiceError] = ExternalServiceError) -> Any:
    """Error de proveedor que ya había consumido tokens (como los marca openai_compatible)."""
    error = cls("Fallo ficticio del proveedor.", service="a")
    error.spent_tokens = spent  # type: ignore[attr-defined]
    return error


def _budget_warnings(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in logs if entry["event"] == "llm_daily_budget_warning"]


def test_daily_warning_is_logged_when_failed_call_spent_tokens_over_threshold() -> None:
    """PA-145 · RNF-27: si la llamada falla tras consumir tokens, se registran y, si el
    consumo del día supera el umbral, se avisa aunque no haya respuesta."""
    recorder = InMemoryUsageRecorder()
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", model="ma", error=_failure((70, 40)))],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs, pytest.raises(ExternalServiceError):
        fallback.generate(MESSAGES, TASK)

    assert [r.total_tokens for r in recorder.records] == [110]
    (warning,) = _budget_warnings(logs)
    assert warning["tokens_today"] == 110
    assert warning["threshold"] == 100
    assert warning["log_level"] == "warning"


def test_daily_warning_is_logged_when_structured_output_error_spent_tokens() -> None:
    """PA-145: también con `StructuredOutputError` (no hay respaldo, pero sí consumo)."""
    recorder = SpyRecorder(total=500)
    error = _failure((30, 20), StructuredOutputError)
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", error=error)],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs, pytest.raises(StructuredOutputError):
        fallback.generate_structured(MESSAGES, UserStory, TASK)

    assert len(recorder.records) == 1
    assert len(_budget_warnings(logs)) == 1


def test_daily_warning_is_logged_per_recorded_attempt_when_chain_falls_back() -> None:
    """PA-145: un fallo con tokens y la respuesta del siguiente proveedor avisan cada uno
    tras registrar su consumo."""
    recorder = SpyRecorder(total=1_000)
    fallback = FallbackLLMProvider(
        lambda _task: [
            FakeLLMProvider(provider="a", error=_failure((10, 5))),
            FakeLLMProvider(provider="b"),
        ],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs:
        result = fallback.generate(MESSAGES, TASK)

    assert result.provider == "b"
    assert [r.provider for r in recorder.records] == ["a", "b"]
    assert len(_budget_warnings(logs)) == 2


def test_daily_warning_is_not_logged_when_failed_call_stays_below_threshold() -> None:
    """PA-145 (límite): por debajo del umbral, el fallo se registra pero no se avisa."""
    recorder = InMemoryUsageRecorder()
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", error=_failure((50, 49)))],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs, pytest.raises(ExternalServiceError):
        fallback.generate(MESSAGES, TASK)

    assert [r.total_tokens for r in recorder.records] == [99]
    assert _budget_warnings(logs) == []


def test_daily_warning_is_logged_when_failed_call_reaches_threshold_exactly() -> None:
    """PA-145 (límite): llegar exactamente al umbral ya avisa (`>=`)."""
    recorder = InMemoryUsageRecorder()
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", error=_failure((50, 50)))],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs, pytest.raises(ExternalServiceError):
        fallback.generate(MESSAGES, TASK)

    assert len(_budget_warnings(logs)) == 1


def test_daily_usage_is_not_read_when_failed_call_spent_no_tokens() -> None:
    """PA-145 (negativo): un fallo sin tokens consumidos no se registra ni consulta el día."""
    recorder = SpyRecorder(total=10_000)
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", error=_failure((0, 0)))],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs, pytest.raises(ExternalServiceError):
        fallback.generate(MESSAGES, TASK)

    assert recorder.records == []
    assert recorder.since_calls == []
    assert _budget_warnings(logs) == []


def test_daily_usage_is_not_read_when_failed_call_and_no_threshold() -> None:
    """PA-145 (negativo): sin umbral configurado no se consulta el consumo del día."""
    recorder = SpyRecorder(total=10_000)
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", error=_failure((70, 40)))], recorder
    )

    with capture_logs() as logs, pytest.raises(ExternalServiceError):
        fallback.generate(MESSAGES, TASK)

    assert len(recorder.records) == 1
    assert recorder.since_calls == []
    assert _budget_warnings(logs) == []


def test_failed_call_logs_usage_not_read_and_no_warning_when_daily_read_fails() -> None:
    """PA-145 · RNF-12 (error): si leer el consumo del día falla tras registrar el fallo, se
    registra `llm_usage_not_read`, no hay aviso diario y se propaga el error del proveedor."""
    recorder = BrokenRecorder("tokens_since")
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", model="ma", error=_failure((70, 40)))],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs, pytest.raises(ExternalServiceError) as info:
        fallback.generate(MESSAGES, TASK)

    assert not isinstance(info.value.__cause__, sa.exc.OperationalError)
    assert len(recorder.records) == 1
    (not_read,) = [entry for entry in logs if entry["event"] == "llm_usage_not_read"]
    assert not_read["error"] == "OperationalError"
    assert not_read["model"] == "ma"
    assert not_read["task"] == TASK.value
    assert _budget_warnings(logs) == []
    text = json.dumps(logs, ensure_ascii=False, default=str)
    assert "MARCADOR-SQL-NO-MOSTRAR" not in text
    assert "test-key" not in text


def test_failed_call_logs_not_recorded_and_skips_daily_check_when_record_fails() -> None:
    """PA-145 · RNF-12 (error): si el registro del fallo falla, `llm_usage_not_recorded`, sin
    leer el consumo del día ni avisar."""

    @dataclass
    class FailingRecordSpy(BrokenRecorder):
        since_calls: list[datetime] = field(default_factory=list)

        def tokens_since(self, since: datetime) -> int:
            self.since_calls.append(since)
            return 10_000

    recorder = FailingRecordSpy("record")
    fallback = FallbackLLMProvider(
        lambda _task: [FakeLLMProvider(provider="a", model="ma", error=_failure((70, 40)))],
        recorder,
        daily_token_warning=100,
    )

    with capture_logs() as logs, pytest.raises(ExternalServiceError):
        fallback.generate(MESSAGES, TASK)

    events = [entry["event"] for entry in logs]
    assert events.count("llm_usage_not_recorded") == 1
    assert "llm_usage_not_read" not in events
    assert recorder.since_calls == []
    assert _budget_warnings(logs) == []
