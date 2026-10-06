"""API real (FastAPI) sobre los dobles de prueba, solo para desarrollo del frontend.

`APP_ENV=development uv run python -m tests.fakes.serve_api [--port 8100] [--delay 1.5]`

- Sin `.env`, sin PostgreSQL, sin Jira ni LLM reales: `fake_runtime` con `api_settings()`
  (`Settings(_env_file=None)`) y los usuarios ficticios de `tests/fakes/dataset.py`.
- Las operaciones largas van en segundo plano (`run_inline=False`), como en la app: el SSE avanza
  paso a paso. `--delay` añade una pausa a cada llamada al LLM falso para ver el progreso y poder
  probar «Detener» y «Reintentar»; la cancelación sigue pasando por `CancellableLLM`, porque el
  retardo envuelve el LLM del contenedor antes de que `fake_runtime` lo envuelva a su vez.
  La pausa no se interrumpe: «Detener» se nota al empezar la siguiente llamada (hasta `--delay` s).
- Escucha solo en `127.0.0.1` y se niega a arrancar si `APP_ENV` no es `development`.
- No lee el `.env`, pero sí las variables de entorno del shell (p. ej. `API_*`): lánzalo sin
  credenciales en el entorno. `APP_ENV` y `JIRA_PUBLISH_MODE` se fijan por código.
- Siempre en simulación: nada se escribe en ningún Jira.
"""

import argparse
import os
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType
from api.app import create_app
from core.usage import UsageCall
from tests.fakes.api import api_settings, fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider

HOST = "127.0.0.1"  # nunca otra interfaz: es un servidor de pruebas
DEFAULT_PORT = 8100
DEFAULT_DELAY_S = 1.5
NOT_DEVELOPMENT = (
    "serve_api solo arranca con APP_ENV=development (es un servidor de pruebas con usuarios "
    "ficticios)."
)


class InMemoryUsage:
    """`UsageQueries` en memoria: el anillo de consumo de la web («Consumo de tokens de hoy»)."""

    def __init__(self) -> None:
        self._calls: list[UsageCall] = []
        self._lock = threading.Lock()

    def record(self, task: TaskType, result: LLMResult | StructuredResult[BaseModel]) -> None:
        call = UsageCall(
            at=datetime.now(UTC),
            task=task.value,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            est_cost=Decimal(0),
            latency_ms=result.latency_ms,
            artifact_id=None,
        )
        with self._lock:
            self._calls.append(call)

    def calls(
        self, since: datetime | None = None, until: datetime | None = None, limit: int | None = None
    ) -> list[UsageCall]:
        with self._lock:
            rows = [
                c
                for c in reversed(self._calls)
                if (since is None or c.at >= since) and (until is None or c.at < until)
            ]
        return rows[:limit] if limit is not None else rows


class DelayedLLM:
    """`LLMProvider` que espera `delay_s` antes de cada llamada y anota su consumo en `usage`."""

    def __init__(
        self, inner: LLMProvider, delay_s: float, usage: InMemoryUsage | None = None
    ) -> None:
        self._inner = inner
        self._delay_s = delay_s
        self._usage = usage

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        time.sleep(self._delay_s)
        result = self._inner.generate(messages, task)
        if self._usage is not None:
            self._usage.record(task, result)
        return result

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        time.sleep(self._delay_s)
        result = self._inner.generate_structured(messages, schema, task)
        if self._usage is not None:
            self._usage.record(task, result)  # type: ignore[arg-type]
        return result


def build_app(memory_dir: Path, delay_s: float = DEFAULT_DELAY_S) -> FastAPI:
    """La app FastAPI real con el runtime de los fakes, en simulación y en segundo plano."""
    usage = InMemoryUsage()
    container = fake_container(
        memory_dir,
        require_actor=True,
        publish_mode="simulation",
        llm=DelayedLLM(FakeLLMProvider(), max(0.0, delay_s), usage),
    )
    settings = api_settings()
    runtime = fake_runtime(memory_dir, container=container, settings=settings, run_inline=False)
    runtime.usage = usage  # GET /settings/usage: el anillo de consumo de la web
    return create_app(runtime_instance=runtime, settings=settings)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="API real sobre los dobles de prueba (desarrollo)."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY_S, help="segundos por llamada al LLM falso"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("APP_ENV") != "development":
        print(NOT_DEVELOPMENT, file=sys.stderr)
        return 2
    args = parse_args(argv)
    memory_dir = Path(tempfile.mkdtemp(prefix="serve-api-"))
    app = build_app(memory_dir, args.delay)
    print(
        f"API con dobles de prueba en http://{HOST}:{args.port}/api/v1 "
        f"(retardo del LLM: {args.delay} s). Usuarios: los de tests/fakes/dataset.py.",
        file=sys.stderr,
    )
    uvicorn.run(app, host=HOST, port=args.port, workers=1, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
