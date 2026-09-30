"""Cadena de respaldo de proveedores LLM por tarea (RF-44, RNF-27).

Recorre la cadena de la tarea en orden: si un proveedor alcanza su límite (429) o falla, pasa al
siguiente. Una salida estructurada inválida no provoca respaldo: se informa al usuario (RNF-28).
Cada llamada correcta se registra en `llm_usage` (RF-43).
"""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType
from adapters.errors import ExternalServiceError, RateLimitError
from adapters.llm.openai_compatible import StructuredOutputError
from adapters.llm.usage import UsageRecord, UsageRecorder

log = structlog.get_logger(__name__)

ChainResolver = Callable[[TaskType], Sequence[LLMProvider]]


class FallbackLLMProvider:
    """Implementa `LLMProvider` delegando en la cadena ordenada de cada tarea."""

    def __init__(
        self,
        chain_for: ChainResolver,
        recorder: UsageRecorder | None = None,
        *,
        daily_token_warning: int | None = None,
    ) -> None:
        self._chain_for = chain_for
        self._recorder = recorder
        self._daily_token_warning = daily_token_warning

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        return self._run(task, lambda provider: provider.generate(messages, task))

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        return self._run(
            task, lambda provider: provider.generate_structured(messages, schema, task)
        )

    def tokens_today(self) -> int:
        """Tokens consumidos desde el inicio del día (UTC), para el aviso de la UI (RNF-27)."""
        if self._recorder is None:
            return 0
        start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return self._recorder.tokens_since(start_of_day)

    def _run[R: LLMResult | StructuredResult](
        self, task: TaskType, call: Callable[[LLMProvider], R]
    ) -> R:
        chain = list(self._chain_for(task))
        if not chain:
            raise ExternalServiceError(
                f"No hay ningún proveedor LLM disponible para la tarea «{task.value}». "
                "Revisa las claves configuradas y config/models.yaml."
            )
        failures: list[ExternalServiceError] = []
        for provider in chain:
            name = getattr(provider, "provider", type(provider).__name__)
            model = getattr(provider, "model", None)
            start = time.monotonic()
            try:
                result = call(provider)
            except StructuredOutputError:
                raise
            except ExternalServiceError as exc:
                log.warning(
                    "llm_provider_failed",
                    action="llm_call",
                    task=task.value,
                    provider=name,
                    model=model,
                    error=type(exc).__name__,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
                failures.append(exc)
                continue
            self._record(task, result)
            return result
        raise _chain_error(task, failures)

    def _record(self, task: TaskType, result: LLMResult | StructuredResult) -> None:
        log.info(
            "llm_call",
            action="llm_call",
            task=task.value,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=result.latency_ms,
        )
        if self._recorder is None:
            return
        self._recorder.record(
            UsageRecord(
                task=task,
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
            )
        )
        if self._daily_token_warning is not None:
            used = self.tokens_today()
            if used >= self._daily_token_warning:
                log.warning(
                    "llm_daily_budget_warning",
                    action="llm_call",
                    tokens_today=used,
                    threshold=self._daily_token_warning,
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
