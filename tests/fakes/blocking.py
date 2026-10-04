"""Fakes que se quedan esperando en una llamada concreta hasta que la prueba los suelta (PA-314).

Sirven para probar operaciones en segundo plano (`fake_runtime(..., run_inline=False)`): la
prueba arma la `Gate`, lanza la operación, espera a que la llamada llegue (`wait_hits`) y actúa
(p. ej. cancelar) antes de soltarla (`release`). Todas las esperas tienen tiempo máximo: una
prueba que falla nunca deja la suite colgada. Sin red ni servicios reales; datos ficticios.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from adapters.base import IssueDetail, Message, StructuredResult, TaskType
from schemas.user_story import UserStory
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider

DEFAULT_WAIT = 10.0  # segundos: tope de cualquier espera de las pruebas


class Gate:
    """Bloquea las llamadas que pasan por ella mientras está armada.

    `arm(skip, count)`: deja pasar `skip` llamadas y bloquea las `count` siguientes hasta
    `release()` (o hasta `timeout`, para no colgar nunca la suite).
    """

    def __init__(self, timeout: float = DEFAULT_WAIT) -> None:
        self.timeout = timeout
        self.hits = 0  # llamadas que han llegado a la puerta y se han quedado esperando
        self.timed_out = False
        self._skip = 0
        self._count = 0
        self._open = threading.Event()
        self._open.set()
        self._cond = threading.Condition()

    def arm(self, *, skip: int = 0, count: int = 1) -> None:
        with self._cond:
            self._skip, self._count, self.hits = skip, count, 0
            self._open.clear()

    def passing(self) -> None:
        """Lo llama el fake al empezar la llamada vigilada."""
        with self._cond:
            if self._count <= 0:
                return
            if self._skip > 0:
                self._skip -= 1
                return
            self._count -= 1
            self.hits += 1
            self._cond.notify_all()
        if not self._open.wait(self.timeout):
            self.timed_out = True

    def wait_hits(self, n: int = 1, timeout: float = DEFAULT_WAIT) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: self.hits >= n, timeout=timeout)

    def release(self) -> None:
        with self._cond:
            self._count = 0
        self._open.set()


def wait_until(predicate: Any, timeout: float = DEFAULT_WAIT, step: float = 0.01) -> bool:
    """Sondeo con tiempo máximo (no usa el candado del registro de runs)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


@dataclass
class BlockingLLM(FakeLLMProvider):
    """`FakeLLMProvider` cuyas llamadas estructuradas con `schema` en `blocked` esperan a `gate`.

    La llamada se registra en `calls` cuando termina (como el fake base), así que una llamada
    bloqueada solo cuenta al soltarla.
    """

    gate: Gate = field(default_factory=Gate)
    blocked: tuple[type[BaseModel], ...] = (UserStory,)
    started: list[str] = field(default_factory=list)  # esquemas de las llamadas empezadas

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        self.started.append(schema.__name__)
        if schema in self.blocked:
            self.gate.passing()
        return super().generate_structured(messages, schema, task)


class BlockingIssueTracker(FakeIssueTracker):
    """`FakeIssueTracker` cuyo `get_issue` (lectura) o `update_story` (escritura) espera."""

    def __init__(self) -> None:
        super().__init__()
        self.read_gate = Gate()
        self.write_gate = Gate()

    def get_issue(self, key: str) -> IssueDetail:
        self.read_gate.passing()
        return super().get_issue(key)

    def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None:
        self.write_gate.passing()
        super().update_story(key, story, diff_comment_md)


@dataclass
class BlockingEmbeddings(FakeEmbeddingProvider):
    """`FakeEmbeddingProvider` cuyo `embed` espera (bloquea `retrieve_context`)."""

    gate: Gate = field(default_factory=Gate)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.gate.passing()
        return super().embed(texts)
