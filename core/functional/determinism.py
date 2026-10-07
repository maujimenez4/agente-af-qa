"""Llamadas deterministas al LLM (PA-432): la estructuración de una HU de Jira.

La misma HU de Jira debe salir igual cada vez: la llamada que la pasa a la plantilla se hace con
temperatura 0 y una semilla fija. Las demás (HU nueva, evolución, QA) no cambian: ahí la variedad
es útil. El ajuste viaja en una `ContextVar` (como la operación trazada de T-40) y lo lee
`FallbackLLMProvider` mediante `call_options`, inyectado en la composición (`core/factories.py`):
los adaptadores no importan `core/`.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

DETERMINISTIC: Mapping[str, Any] = {"temperature": 0, "seed": 0}

_OPTIONS: ContextVar[Mapping[str, Any] | None] = ContextVar("llm_call_options", default=None)


@contextmanager
def deterministic() -> Iterator[None]:
    """Las llamadas al LLM hechas dentro del bloque van con temperatura 0 y semilla fija."""
    token = _OPTIONS.set(DETERMINISTIC)
    try:
        yield
    finally:
        _OPTIONS.reset(token)


def current_call_options() -> dict[str, Any]:
    """Ajustes de muestreo de la llamada en curso (vacío fuera de `deterministic()`)."""
    return dict(_OPTIONS.get() or {})
