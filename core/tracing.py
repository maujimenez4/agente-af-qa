"""Trazas de las operaciones del agente (T-40, RNF-24, DT-09).

Cada operación (crear, iterar, aprobar, reintentar, QA, revisión de calidad, ejecución) es una
traza con un paso por nodo del grafo, una *generation* por intento de la cadena de proveedores y
un paso por búsqueda del RAG. El núcleo solo conoce el `Protocol` `Tracer`; la implementación con
el SDK de Langfuse está en `adapters/observability/langfuse.py` y la composición, en
`core/factories.py` (`Container.tracer`, `NullTracer` sin claves).

La operación en curso vive en una `ContextVar` (como `cancellation()` y `capture_fallbacks()`),
que LangGraph propaga a los hilos de los nodos: el router, el vector store y `load_prompt` la
encuentran sin tocar los nodos.

Contenido (`LANGFUSE_CAPTURE_CONTENT`): sin el interruptor, aquí nunca se pone `input` ni
`output`, solo metadatos de una lista blanca (modelo, tarea, nodo, tokens, latencia, tipo de
error, ids y puntuaciones). El adaptador enmascara además los secretos de todo lo que sale.

Robustez: una traza nunca rompe ni retrasa la operación. Toda llamada al trazador va dentro de
`_safe`, que captura cualquier error y lo registra (solo el tipo, una vez por tipo).
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphBubbleUp
from pydantic import BaseModel

from adapters.base import (
    Chunk,
    LLMResult,
    Message,
    RetrievedChunk,
    StructuredResult,
    TaskType,
    VectorStore,
)
from core.logging import SecretMasker, get_logger

log = get_logger(__name__)

SpanKind = Literal["span", "generation", "retriever"]
Level = Literal["DEFAULT", "WARNING", "ERROR"]
PAUSED = "pausado para revisión"
FREE_COST = {"total": 0.0}  # D-14: solo modelos gratuitos


class Span(Protocol):
    """Un paso de la traza (la propia traza, un nodo, una llamada al modelo o una búsqueda)."""

    def child(
        self,
        name: str,
        *,
        kind: SpanKind = "span",
        input: Any = None,
        metadata: Mapping[str, Any] | None = None,
        model: str | None = None,
    ) -> "Span": ...

    def end(
        self,
        *,
        output: Any = None,
        metadata: Mapping[str, Any] | None = None,
        level: Level | None = None,
        status: str | None = None,
        usage: Mapping[str, int] | None = None,
        cost: Mapping[str, float] | None = None,
    ) -> None: ...


class Tracer(Protocol):
    """Destino de las trazas. `enabled` falso: no se crea nada (sin claves, `NullTracer`)."""

    @property
    def enabled(self) -> bool: ...

    @property
    def capture_content(self) -> bool: ...

    def start_trace(
        self,
        name: str,
        *,
        session_id: str | None,
        user_id: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, Any],
    ) -> Span: ...

    def flush(self) -> None:
        """Envía lo pendiente sin bloquear a quien llama."""
        ...

    def shutdown(self) -> None:
        """Al cerrar el proceso: envía lo pendiente con un tope de tiempo."""
        ...


class NullTracer:
    """Sin Langfuse configurado: no hace nada y no llama a la red."""

    enabled = False
    capture_content = False

    def start_trace(self, name: str, **_kwargs: Any) -> Span:
        raise RuntimeError("NullTracer no crea trazas")  # nunca se llama: `enabled` es falso

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


def secret_mask(secrets: Iterable[str]) -> Callable[[Any], Any]:
    """Enmascarado de las trazas: el mismo de los logs (`SecretMasker` de `core/logging`), con
    los valores secretos de la configuración, los patrones de token y las claves sensibles."""
    masker = SecretMasker(secrets)

    def mask(data: Any) -> Any:
        return masker(None, "trace", {"valor": data})["valor"]

    return mask


# --- Robustez ----------------------------------------------------------------------------------

_WARNED: set[str] = set()


def _safe[T](action: str, call: Callable[[], T]) -> T | None:
    """Ejecuta una llamada al trazador; si falla, `None` y un aviso por tipo de error."""
    try:
        return call()
    except Exception as exc:
        kind = f"{action}:{type(exc).__name__}"
        if kind not in _WARNED:
            _WARNED.add(kind)
            log.warning("traza no registrada", action=action, error=type(exc).__name__)
        return None


# --- Operación en curso ------------------------------------------------------------------------


@dataclass
class Operation:
    """La traza de una operación y su paso actual (el nodo del grafo que se ejecuta)."""

    tracer: Tracer
    root: Span
    step: Span | None = None
    prompt: tuple[str, str] | None = None  # último prompt cargado: nombre y versión
    _steps: dict[UUID, tuple[Span, Span | None]] = field(default_factory=dict)

    @property
    def capture(self) -> bool:
        return bool(self.tracer.capture_content)

    def parent(self) -> Span:
        return self.step or self.root

    def prompt_metadata(self) -> dict[str, str]:
        if self.prompt is None:
            return {}
        return {"prompt": self.prompt[0], "prompt_version": self.prompt[1]}


_CURRENT: ContextVar[Operation | None] = ContextVar("trace_operation", default=None)


def current_operation() -> Operation | None:
    return _CURRENT.get()


# Nombre de la traza de cada operación (las de la API y la UI usan estos identificadores).
OPERATION_NAMES = {
    "start": "crear",
    "iterate": "iterar",
    "approve": "aprobar",
    "retry": "reintentar",
    "edit": "editar",
    "discard": "descartar",
    "save": "guardar",  # registro de la ejecución
}


def operation_name(operation: str | None) -> str:
    return OPERATION_NAMES.get(operation or "", operation or "operacion")


def operation_tags(
    *, mode: str | None = None, flow: str | None = None, project: str | None = None
) -> list[str]:
    """Etiquetas de la traza: modo, flujo y proyecto (los que se conozcan)."""
    pairs = (("modo", mode), ("flujo", flow), ("proyecto", project))
    return [f"{name}:{value}" for name, value in pairs if value]


@contextmanager
def operation(
    tracer: Tracer,
    name: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    mode: str | None = None,
    flow: str | None = None,
    project: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Operation | None]:
    """Traza de una operación: `session_id` es la conversación y `user_id`, la persona.

    Con el trazador desactivado (o si no se puede crear la traza) entrega `None` y no hace nada.
    Los errores de la operación se propagan sin cambios; en la traza solo queda su tipo.
    """
    if not getattr(tracer, "enabled", False):
        yield None
        return
    root = _safe(
        "trace_start",
        lambda: tracer.start_trace(
            name,
            session_id=session_id,
            user_id=user_id,
            tags=operation_tags(mode=mode, flow=flow, project=project),
            metadata={"operacion": name, **(metadata or {})},
        ),
    )
    if root is None:
        yield None
        return
    op = Operation(tracer, root)
    token = _CURRENT.set(op)
    failure: str | None = None
    level: Level = "ERROR"
    try:
        yield op
    except BaseException as exc:
        failure = type(exc).__name__
        if not isinstance(exc, Exception):  # p. ej. la UI abandona el progreso (GeneratorExit)
            level = "WARNING"
        raise
    finally:
        _safe("trace_context", lambda: _CURRENT.reset(token))
        if failure is None:
            _safe("trace_end", lambda: root.end())
        else:
            _safe("trace_end", lambda: root.end(level=level, status=failure))
        _safe("trace_flush", tracer.flush)


def note_prompt(name: str, version: str) -> None:
    """`load_prompt` anota el prompt en la operación en curso; sin operación no hace nada."""
    op = _CURRENT.get()
    if op is not None:
        op.prompt = (name, version)


# --- Pasos del grafo ---------------------------------------------------------------------------


class GraphStepHandler(BaseCallbackHandler):
    """Un paso por nodo real del grafo (no los internos de LangGraph), con su duración y su
    estado. La pausa de `human_review` (interrupción) queda como «pausado», no como error.

    Va en `config["callbacks"]` donde se invoca el grafo (`with_trace_callbacks`).
    """

    raise_error = False
    run_inline = True  # en el hilo del nodo: el paso está abierto mientras el nodo trabaja

    def __init__(self, op: Operation) -> None:
        self._op = op

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if not isinstance(node, str) or node.startswith("__") or kwargs.get("name") != node:
            return
        op = self._op
        span = _safe(
            "trace_step",
            lambda: op.root.child(
                node, metadata={"nodo": node, "paso": (metadata or {}).get("langgraph_step")}
            ),
        )
        if span is None:
            return
        op._steps[run_id] = (span, op.step)
        op.step, op.prompt = span, None

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._close(run_id, metadata={"estado": "ok", **_node_metadata(outputs)})

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if isinstance(error, GraphBubbleUp):  # `interrupt()`: espera la revisión humana
            self._close(run_id, metadata={"estado": "pausado"}, status=PAUSED)
        else:
            self._close(
                run_id,
                metadata={"estado": "error", "error": type(error).__name__},
                level="ERROR",
                status=type(error).__name__,
            )

    def _close(self, run_id: UUID, **fields: Any) -> None:
        entry = self._op._steps.pop(run_id, None)
        if entry is None:
            return
        span, previous = entry
        self._op.step = previous
        _safe("trace_step", lambda: span.end(**fields))


def _node_metadata(outputs: Any) -> dict[str, Any]:
    """Solo referencias del resultado de un nodo: los campos que cambia y, si hay artefacto,
    su versión, su estado y la versión del prompt. Nunca contenido."""
    if not isinstance(outputs, Mapping):
        return {}
    found: dict[str, Any] = {"campos": sorted(str(k) for k in outputs)}
    artifact = outputs.get("artifact")
    for name in ("version", "prompt_version", "status"):
        value = getattr(artifact, name, None)
        if value is not None:
            found[f"artefacto_{name}"] = str(getattr(value, "value", value))
    return found


def with_trace_callbacks(config: Any, op: Operation | None) -> Any:
    """`config` del grafo con el manejador de pasos añadido (igual si no hay operación)."""
    if op is None:
        return config
    callbacks = [*(config or {}).get("callbacks", []), GraphStepHandler(op)]
    return {**(config or {}), "callbacks": callbacks}


# --- Llamadas al modelo ------------------------------------------------------------------------


class _Attempt:
    """Una *generation*: un intento de un proveedor de la cadena."""

    def __init__(self, op: Operation, span: Span) -> None:
        self._op = op
        self._span = span

    def succeeded(self, result: LLMResult | StructuredResult) -> None:
        output = _result_text(result) if self._op.capture else None
        _safe(
            "trace_generation",
            lambda: self._span.end(
                output=output,
                metadata={"estado": "ok", "latencia_ms": result.latency_ms},
                usage={"input": result.input_tokens, "output": result.output_tokens},
                cost=FREE_COST,
            ),
        )

    def failed(
        self, reason: str, error: str, input_tokens: int, output_tokens: int, latency_ms: int
    ) -> None:
        _safe(
            "trace_generation",
            lambda: self._span.end(
                metadata={
                    "estado": "fallido",
                    "motivo": reason,
                    "error": error,
                    "latencia_ms": latency_ms,
                },
                level="ERROR",
                status=f"{reason}: {error}",
                usage={"input": input_tokens, "output": output_tokens},
                cost=FREE_COST,
            ),
        )


class LLMTraceObserver:
    """Observador de `FallbackLLMProvider`: cada intento es una *generation* de la operación en
    curso, hija del paso actual. Sin operación no hace nada."""

    def attempt(
        self, task: TaskType, provider: str, model: str | None, messages: list[Message]
    ) -> _Attempt | None:
        op = _CURRENT.get()
        if op is None:
            return None
        payload = [{"role": m.role, "content": m.content} for m in messages] if op.capture else None
        parent = op.parent()
        span = _safe(
            "trace_generation",
            lambda: parent.child(
                f"llm · {task.value}",
                kind="generation",
                input=payload,
                model=model,
                metadata={
                    "tarea": task.value,
                    "proveedor": provider,
                    "modelo": model,
                    **op.prompt_metadata(),
                },
            ),
        )
        return None if span is None else _Attempt(op, span)


def _result_text(result: LLMResult | StructuredResult) -> Any:
    content = result.content
    return content.model_dump(mode="json") if isinstance(content, BaseModel) else content


# --- Recuperación del RAG ----------------------------------------------------------------------


class TracingVectorStore:
    """`VectorStore` que deja un paso por búsqueda en la operación en curso: `k`, filtros, ids y
    puntuaciones; la consulta y el texto de los fragmentos, solo con el interruptor."""

    def __init__(self, inner: VectorStore) -> None:
        self._inner = inner

    def upsert(self, chunks: list[Chunk]) -> None:
        self._inner.upsert(chunks)

    def delete_by_document(self, document_id: str) -> None:
        self._inner.delete_by_document(document_id)

    def replace_document(self, document_id: str, chunks: list[Chunk]) -> None:
        self._inner.replace_document(document_id, chunks)

    def has_document(self, document_id: str) -> bool:
        return self._inner.has_document(document_id)

    def search(
        self,
        query_vector: list[float],
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
        memory_boost: float = 1.0,
    ) -> list[RetrievedChunk]:
        op = _CURRENT.get()
        span = None
        if op is not None:
            parent = op.parent()
            span = _safe(
                "trace_retrieval",
                lambda: parent.child(
                    "rag · buscar",
                    kind="retriever",
                    input={"consulta": query_text} if op.capture else None,
                    metadata={"k": k, "filtros": dict(filters or {}), "memory_boost": memory_boost},
                ),
            )
        try:
            results = self._inner.search(query_vector, query_text, k, filters, memory_boost)
        except Exception as exc:
            if span is not None:
                error = type(exc).__name__
                _safe("trace_retrieval", lambda: span.end(level="ERROR", status=error))
            raise
        if span is not None and op is not None:
            _safe("trace_retrieval", lambda: span.end(**_retrieval_fields(results, op.capture)))
        return results


def _retrieval_fields(results: list[RetrievedChunk], capture: bool) -> dict[str, Any]:
    found = [
        {"id": r.chunk.id, "documento": r.chunk.document_id, "puntuacion": round(r.score, 4)}
        for r in results
    ]
    output = [{"id": r.chunk.id, "texto": r.chunk.content} for r in results] if capture else None
    return {"output": output, "metadata": {"fragmentos": found, "devueltos": len(results)}}
