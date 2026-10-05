"""Doble de `core.tracing.Tracer` (T-40): guarda en memoria las trazas y sus pasos, sin red.

Cada `FakeSpan` conserva lo que el núcleo le pasó (nombre, tipo, entrada, metadatos, modelo) y
lo que añadió al terminar (salida, nivel, estado, uso y coste). `fail=True` hace que toda
llamada falle (Langfuse caído) y `delay_s` que tarde (Langfuse lento).
"""

import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


class TracerDown(RuntimeError):  # noqa: N818 - simula un fallo del SDK, no es de la app
    pass


@dataclass
class FakeSpan:
    tracer: "FakeTracer"
    name: str
    kind: str = "span"
    input: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)  # solo en la raíz
    output: Any = None
    level: str | None = None
    status: str | None = None
    usage: dict[str, int] | None = None
    cost: dict[str, float] | None = None
    ended: bool = False
    children: list["FakeSpan"] = field(default_factory=list)

    def child(
        self,
        name: str,
        *,
        kind: str = "span",
        input: Any = None,
        metadata: Mapping[str, Any] | None = None,
        model: str | None = None,
    ) -> "FakeSpan":
        self.tracer.hit()
        span = FakeSpan(self.tracer, name, kind, input, dict(metadata or {}), model)
        self.children.append(span)
        return span

    def end(
        self,
        *,
        output: Any = None,
        metadata: Mapping[str, Any] | None = None,
        level: str | None = None,
        status: str | None = None,
        usage: Mapping[str, int] | None = None,
        cost: Mapping[str, float] | None = None,
    ) -> None:
        self.tracer.hit()
        self.output = output
        self.metadata.update(metadata or {})
        self.level, self.status = level, status
        self.usage = dict(usage) if usage is not None else None
        self.cost = dict(cost) if cost is not None else None
        self.ended = True

    def walk(self) -> Iterator["FakeSpan"]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class FakeTracer:
    enabled: bool = True
    capture_content: bool = False
    fail: bool = False
    delay_s: float = 0.0
    traces: list[FakeSpan] = field(default_factory=list)
    flushes: int = 0
    shutdowns: int = 0

    def hit(self) -> None:
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail:
            raise TracerDown("Langfuse ficticio no disponible")

    def start_trace(
        self,
        name: str,
        *,
        session_id: str | None,
        user_id: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, Any],
    ) -> FakeSpan:
        self.hit()
        span = FakeSpan(
            self,
            name,
            metadata=dict(metadata),
            trace={"session_id": session_id, "user_id": user_id, "tags": list(tags)},
        )
        self.traces.append(span)
        return span

    def flush(self) -> None:
        self.flushes += 1
        self.hit()

    def shutdown(self) -> None:
        self.shutdowns += 1

    def spans(self, kind: str | None = None) -> list[FakeSpan]:
        found = [s for t in self.traces for s in t.walk()]
        return [s for s in found if kind is None or s.kind == kind]
