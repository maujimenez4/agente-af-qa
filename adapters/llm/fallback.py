"""Cadena de respaldo de proveedores LLM por tarea (RF-44, RNF-27).

Recorre la cadena de la tarea en orden: si un proveedor alcanza su límite (429) o falla, pasa al
siguiente. Una salida estructurada inválida no provoca respaldo: se informa al usuario (RNF-28).
Cada llamada correcta se registra en `llm_usage` (RF-43); si el registro falla, la respuesta
no se pierde (RNF-12).

Cada cambio de proveedor genera un `FallbackEvent` con su motivo (PA-67). La UI lo recoge
envolviendo la invocación en `capture_fallbacks()`, que usa una `ContextVar`: cada sesión ve
solo sus eventos.

T-40: un `AttemptObserver` opcional ve cada intento de la cadena (las trazas de Langfuse los
muestran como *generations*, también los fallidos). Si el observador falla, la llamada sigue.
"""

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import structlog
from pydantic import BaseModel

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType
from adapters.errors import ExternalServiceError, RateLimitError
from adapters.llm.openai_compatible import (
    ProviderTimeoutError,
    StructuredOutputError,
    spent_tokens,
)
from adapters.llm.usage import UsageRecord, UsageRecorder, current_artifact_id

log = structlog.get_logger(__name__)

ChainResolver = Callable[[TaskType], Sequence[LLMProvider]]
FallbackReason = Literal["limite", "tiempo_espera", "error"]

INVALID_OUTPUT = "salida_no_valida"


class AttemptRecord(Protocol):
    """Un intento observado: termina bien (con el resultado) o falla (solo métricas)."""

    def succeeded(self, result: LLMResult | StructuredResult) -> None: ...
    def failed(
        self, reason: str, error: str, input_tokens: int, output_tokens: int, latency_ms: int
    ) -> None: ...


class AttemptObserver(Protocol):
    """T-40: observa cada intento de un proveedor de la cadena (p. ej. para las trazas)."""

    def attempt(
        self, task: TaskType, provider: str, model: str | None, messages: list[Message]
    ) -> AttemptRecord | None: ...


_REASON_TEXT: dict[FallbackReason, str] = {
    "limite": "ha alcanzado su límite de uso",
    "tiempo_espera": "no ha respondido a tiempo",
    "error": "ha fallado",
}


@dataclass(frozen=True)
class FallbackEvent:
    """Un proveedor de la cadena falló y se pasó al siguiente (o se agotó la cadena)."""

    task: TaskType
    provider: str
    model: str | None
    reason: FallbackReason
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def message(self) -> str:
        """Aviso en español para la UI, sin datos internos.

        No afirma que haya otro modelo: si la cadena se agota, la UI muestra además el error
        final de la llamada.
        """
        return f"{self.provider} {_REASON_TEXT[self.reason]}."


_EVENTS: ContextVar[list[FallbackEvent] | None] = ContextVar("llm_fallback_events", default=None)


@contextmanager
def capture_fallbacks() -> Iterator[list[FallbackEvent]]:
    """Recoge los cambios de proveedor de las llamadas hechas dentro del bloque (PA-67)."""
    events: list[FallbackEvent] = []
    token = _EVENTS.set(events)
    try:
        yield events
    finally:
        _EVENTS.reset(token)


def fallback_reason(exc: ExternalServiceError) -> FallbackReason:
    if isinstance(exc, RateLimitError):
        return "limite"
    if isinstance(exc, ProviderTimeoutError):
        return "tiempo_espera"
    return "error"


class FallbackLLMProvider:
    """Implementa `LLMProvider` delegando en la cadena ordenada de cada tarea."""

    def __init__(
        self,
        chain_for: ChainResolver,
        recorder: UsageRecorder | None = None,
        *,
        daily_token_warning: int | None = None,
        observer: AttemptObserver | None = None,
        call_options: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self._chain_for = chain_for
        self._recorder = recorder
        self._daily_token_warning = daily_token_warning
        self._observer = observer
        # PA-432: ajustes de muestreo de la llamada en curso (p. ej. temperatura 0 al
        # estructurar una HU); los aplica el proveedor que tenga `with_options`.
        self._call_options = call_options

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        return self._run(task, lambda provider: provider.generate(messages, task), messages)

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        return self._run(
            task, lambda provider: provider.generate_structured(messages, schema, task), messages
        )

    def tokens_today(self) -> int:
        """Tokens consumidos desde el inicio del día (UTC), para el aviso de la UI (RNF-27)."""
        if self._recorder is None:
            return 0
        start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return self._recorder.tokens_since(start_of_day)

    def _run[R: LLMResult | StructuredResult](
        self, task: TaskType, call: Callable[[LLMProvider], R], messages: list[Message]
    ) -> R:
        chain = list(self._chain_for(task))
        if not chain:
            raise ExternalServiceError(
                f"No hay ningún proveedor LLM disponible para la tarea «{task.value}». "
                "Revisa las claves configuradas y config/models.yaml."
            )
        failures: list[ExternalServiceError] = []
        options = self._options()
        for provider in chain:
            if options and hasattr(provider, "with_options"):
                provider = provider.with_options(**options)
            name = getattr(provider, "provider", type(provider).__name__)
            model = getattr(provider, "model", None)
            start = time.monotonic()
            attempt = self._observe(task, name, model, messages)
            try:
                result = call(provider)
            except StructuredOutputError as exc:
                self._record_spent(task, name, model, exc, start)
                _attempt_failed(attempt, INVALID_OUTPUT, exc, start)
                raise
            except ExternalServiceError as exc:
                self._record_spent(task, name, model, exc, start)
                reason = fallback_reason(exc)
                _attempt_failed(attempt, reason, exc, start)
                log.warning(
                    "llm_provider_failed",
                    action="llm_call",
                    task=task.value,
                    provider=name,
                    model=model,
                    error=type(exc).__name__,
                    reason=reason,
                    artifact_id=current_artifact_id(),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
                if (events := _EVENTS.get()) is not None:
                    events.append(FallbackEvent(task, name, model, reason))
                failures.append(exc)
                continue
            except Exception as exc:  # error no previsto: queda en la traza y se propaga igual
                _attempt_failed(attempt, "error", exc, start)
                raise
            self._record(task, result)
            _attempt_succeeded(attempt, result)
            return result
        raise _chain_error(task, failures)

    def _options(self) -> dict[str, Any]:
        if self._call_options is None:
            return {}
        try:
            return dict(self._call_options() or {})
        except Exception as exc:  # PA-432: sin ajustes, la llamada sigue igual
            log.warning("llm_call_options_failed", action="llm_call", error=type(exc).__name__)
            return {}

    def _observe(
        self, task: TaskType, provider: str, model: str | None, messages: list[Message]
    ) -> AttemptRecord | None:
        observer = self._observer
        if observer is None:
            return None
        return _quietly(lambda: observer.attempt(task, provider, model, messages))

    def _record_spent(
        self,
        task: TaskType,
        provider: str,
        model: str | None,
        exc: BaseException,
        start: float,
    ) -> None:
        """PA-191: registra los tokens que un proveedor consumió antes de fallar (RF-43)."""
        input_tokens, output_tokens = spent_tokens(exc)
        if self._recorder is None or input_tokens + output_tokens == 0:
            return
        try:
            self._recorder.record(
                UsageRecord(
                    task=task,
                    provider=provider,
                    model=model or "",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    artifact_id=current_artifact_id(),
                )
            )
        except Exception as error:  # el registro no puede tapar el error del proveedor
            log.warning(
                "llm_usage_not_recorded",
                action="llm_call",
                task=task.value,
                model=model,
                artifact_id=current_artifact_id(),
                error=type(error).__name__,
            )
            return
        self._check_daily_budget(task, model)  # PA-145: también tras registrar un fallo

    def _record(self, task: TaskType, result: LLMResult | StructuredResult) -> None:
        log.info(
            "llm_call",
            action="llm_call",
            task=task.value,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            artifact_id=current_artifact_id(),  # PA-194: campos de log de CLAUDE.md
            duration_ms=result.latency_ms,
        )
        if self._recorder is None:
            return
        try:
            self._recorder.record(
                UsageRecord(
                    task=task,
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    latency_ms=result.latency_ms,
                    artifact_id=current_artifact_id(),
                )
            )
        except Exception as exc:  # el registro no puede tumbar la respuesta (RNF-12)
            self._warn_usage("llm_usage_not_recorded", task, result.model, exc)
            return
        self._check_daily_budget(task, result.model)

    def _check_daily_budget(self, task: TaskType, model: str | None) -> None:
        """Aviso de consumo diario (RNF-27) tras registrar tokens, sean de una llamada correcta
        o de una que falló (PA-145). Nunca tumba la llamada (RNF-12)."""
        if self._daily_token_warning is None:
            return
        try:
            used = self.tokens_today()
        except Exception as exc:  # el aviso diario tampoco (RNF-12)
            self._warn_usage("llm_usage_not_read", task, model, exc)
            return
        if used >= self._daily_token_warning:
            log.warning(
                "llm_daily_budget_warning",
                action="llm_call",
                tokens_today=used,
                threshold=self._daily_token_warning,
            )

    @staticmethod
    def _warn_usage(event: str, task: TaskType, model: str | None, exc: Exception) -> None:
        log.warning(
            event, action="llm_call", task=task.value, model=model, error=type(exc).__name__
        )


def _quietly[T](call: Callable[[], T] | None) -> T | None:
    """T-40: el observador nunca tumba ni cambia la llamada al LLM."""
    if call is None:
        return None
    try:
        return call()
    except Exception as exc:
        log.warning("llm_attempt_not_observed", action="llm_call", error=type(exc).__name__)
        return None


def _attempt_succeeded(attempt: AttemptRecord | None, result: LLMResult | StructuredResult) -> None:
    if attempt is not None:
        _quietly(lambda: attempt.succeeded(result))


def _attempt_failed(
    attempt: AttemptRecord | None, reason: str, exc: BaseException, start: float
) -> None:
    if attempt is None:
        return
    input_tokens, output_tokens = spent_tokens(exc)
    latency_ms = int((time.monotonic() - start) * 1000)
    _quietly(
        lambda: attempt.failed(reason, type(exc).__name__, input_tokens, output_tokens, latency_ms)
    )


def _chain_error(task: TaskType, failures: list[ExternalServiceError]) -> ExternalServiceError:
    if failures and all(isinstance(f, RateLimitError) for f in failures):
        waits = [f.retry_after for f in failures if isinstance(f, RateLimitError) and f.retry_after]
        return RateLimitError(
            f"Todos los proveedores de la tarea «{task.value}» han alcanzado su límite de uso. "
            "Espera unos minutos o elige otro modelo.",
            retry_after=min(waits) if waits else None,
        )
    return ExternalServiceError(
        f"Todos los proveedores de la tarea «{task.value}» han fallado. "
        "Revisa las conexiones en Administración o elige otro modelo."
    )
