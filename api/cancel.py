"""Detener una generación en curso (PA-314), sin matar hilos.

Cada operación de una conversación tiene su propia señal (`Run.cancel`, un `threading.Event` que
`RunRegistry.begin` renueva). `_run_graph` la fija en un `ContextVar` mientras recorre el grafo, en
el hilo de esa operación: otra conversación que se genere a la vez tiene la suya.

Se comprueba en dos puntos:
- antes de cada llamada al LLM (`CancellableLLM`): un paso con varias llamadas (estructurar,
  evolucionar, analizar el impacto) se corta al terminar la que está en curso, que no se puede
  interrumpir;
- entre nodos (`_run_graph`): no se empieza el siguiente paso.

Nunca afecta a aprobar ni a publicar: esa operación no se puede cancelar (409).
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType
from adapters.errors import AgentError

CANCELLED_MESSAGE = (
    "Generación detenida a petición tuya. Puedes reintentarla o descartar la conversación."
)

_SIGNAL: ContextVar[threading.Event | None] = ContextVar("generation_cancel", default=None)


class GenerationCancelledError(AgentError):
    """La persona detuvo la generación; mensaje en español para la UI."""

    def __init__(self) -> None:
        super().__init__(CANCELLED_MESSAGE)


@contextmanager
def cancellation(signal: threading.Event) -> Iterator[None]:
    """Las llamadas al LLM hechas dentro del bloque (en este hilo) respetan `signal`."""
    token = _SIGNAL.set(signal)
    try:
        yield
    finally:
        _SIGNAL.reset(token)


def raise_if_cancelled() -> None:
    signal = _SIGNAL.get()
    if signal is not None and signal.is_set():
        raise GenerationCancelledError


class CancellableLLM:
    """`LLMProvider` que no empieza una llamada si la operación en curso se ha cancelado."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        raise_if_cancelled()
        return self._inner.generate(messages, task)

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        raise_if_cancelled()
        return self._inner.generate_structured(messages, schema, task)

    def __getattr__(self, name: str) -> Any:  # el resto (p. ej. `tokens_today`), tal cual
        return getattr(self._inner, name)
