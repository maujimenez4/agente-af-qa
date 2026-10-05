"""`Tracer` sobre el SDK de Langfuse 4 (T-40, RNF-24, DT-09). Lo compone `core/factories.py`.

OpenTelemetry: el SDK de Langfuse funciona sobre él y, si no se le da un proveedor, registra el
suyo como global y exporta también los spans de otras bibliotecas (`gen_ai.*`, el SDK de MCP…).
Aquí se le da un `TracerProvider` **propio** (el global no se toca) y solo se exportan los spans
del propio SDK (`is_langfuse_span`): nada ajeno sale hacia Langfuse Cloud.

Contenido y secretos: el interruptor `LANGFUSE_CAPTURE_CONTENT` se aplica en el núcleo y se
vuelve a aplicar aquí (sin él, `input` y `output` nunca salen). Todo lo que sale pasa por `mask`,
que la composición construye con el enmascarado de `core/logging` (`SecretMasker`, los mismos
secretos que los logs); también va como función `mask` del cliente, como última red para la
entrada, la salida y los metadatos. Como todo adaptador, no importa `core/` (SPEC-00 §2).

Sin espera: registrar solo encola (el envío va en el hilo del `BatchSpanProcessor`), el cliente
tiene un tiempo límite y `flush` se lanza en segundo plano. `shutdown` espera como mucho
`flush_timeout_s`.
"""

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

import structlog
from langfuse import Langfuse, propagate_attributes
from langfuse.span_filter import is_langfuse_span
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter
from pydantic import SecretStr

log = structlog.get_logger(__name__)

SpanKind = Literal["span", "generation", "retriever"]  # los de `core.tracing`
Level = Literal["DEFAULT", "WARNING", "ERROR"]
Masker = Callable[[Any], Any]

TIMEOUT_S = 3
FLUSH_TIMEOUT_S = 2.0


class _LangfuseSpan:
    """Un paso de la traza; sus hijos llevan los mismos atributos de traza (sesión, usuario)."""

    def __init__(self, tracer: "LangfuseTracer", observation: Any, trace: Mapping[str, Any]):
        self._tracer = tracer
        self._observation = observation
        self._trace = trace

    def child(
        self,
        name: str,
        *,
        kind: SpanKind = "span",
        input: Any = None,
        metadata: Mapping[str, Any] | None = None,
        model: str | None = None,
    ) -> "_LangfuseSpan":
        tracer = self._tracer
        with propagate_attributes(**self._trace):
            observation = self._observation.start_observation(
                name=name,
                as_type=kind,
                input=tracer.content(input),
                metadata=tracer.mask(dict(metadata or {})),
                model=model,
            )
        return _LangfuseSpan(tracer, observation, self._trace)

    def end(
        self,
        *,
        output: Any = None,
        metadata: Mapping[str, Any] | None = None,
        level: Level | None = None,
        status: str | None = None,
        usage: Mapping[str, int] | None = None,
        cost: Mapping[str, float] | None = None,
    ) -> None:
        tracer = self._tracer
        fields: dict[str, Any] = {}
        if (content := tracer.content(output)) is not None:
            fields["output"] = content
        if metadata:
            fields["metadata"] = tracer.mask(dict(metadata))
        if level is not None:
            fields["level"] = level
        if status is not None:
            fields["status_message"] = tracer.mask(status)
        if usage is not None:
            fields["usage_details"] = dict(usage)
        if cost is not None:
            fields["cost_details"] = dict(cost)
        if fields:
            self._observation.update(**fields)
        self._observation.end()


class LangfuseTracer:
    """Trazas en Langfuse Cloud. Solo se crea con las dos claves (`core/factories.build_tracer`)."""

    enabled = True

    def __init__(
        self,
        *,
        public_key: SecretStr,
        secret_key: SecretStr,
        host: str,
        capture_content: bool = False,
        mask: Masker,
        timeout_s: int = TIMEOUT_S,
        flush_timeout_s: float = FLUSH_TIMEOUT_S,
        span_exporter: SpanExporter | None = None,
    ) -> None:
        self.capture_content = capture_content
        self._masker = mask
        self._flush_timeout_s = flush_timeout_s
        self._flushing = threading.Lock()
        self.provider = TracerProvider()  # propio: nunca el proveedor global de OpenTelemetry
        self._client = Langfuse(
            public_key=public_key.get_secret_value(),
            secret_key=secret_key.get_secret_value(),
            base_url=host,
            timeout=timeout_s,
            tracer_provider=self.provider,
            should_export_span=is_langfuse_span,
            mask=self._mask_hook,
            span_exporter=span_exporter,
        )

    # --- Contenido y enmascarado ---------------------------------------------------------------

    def mask(self, data: Any) -> Any:
        """Los secretos de la configuración y los patrones de token, como en los logs."""
        return self._masker(data)

    def content(self, data: Any) -> Any:
        """Entrada o salida: solo con el interruptor activado, y enmascarada."""
        if data is None or not self.capture_content:
            return None
        return self.mask(data)

    def _mask_hook(self, *, data: Any, **_kwargs: Any) -> Any:
        return self.mask(data)

    # --- Tracer ---------------------------------------------------------------------------------

    def start_trace(
        self,
        name: str,
        *,
        session_id: str | None,
        user_id: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, Any],
    ) -> _LangfuseSpan:
        trace: dict[str, Any] = {"trace_name": name, "tags": list(tags)}
        if session_id:
            trace["session_id"] = session_id
        if user_id:
            trace["user_id"] = user_id
        with propagate_attributes(**trace):
            observation = self._client.start_observation(
                name=name, as_type="span", metadata=self.mask(dict(metadata))
            )
        return _LangfuseSpan(self, observation, trace)

    def flush(self) -> None:
        """En segundo plano; si ya hay un envío en marcha, no se lanza otro."""
        if not self._flushing.acquire(blocking=False):
            return

        def run() -> None:
            try:
                self._client.flush()
            except Exception as exc:  # el envío nunca afecta a la operación
                log.warning("trazas no enviadas", action="trace_flush", error=type(exc).__name__)
            finally:
                self._flushing.release()

        threading.Thread(target=run, name="langfuse-flush", daemon=True).start()

    def shutdown(self) -> None:
        """Envía lo pendiente y cierra; espera como mucho `flush_timeout_s`."""
        worker = threading.Thread(
            target=self._shutdown_quietly, name="langfuse-shutdown", daemon=True
        )
        worker.start()
        worker.join(self._flush_timeout_s)

    def _shutdown_quietly(self) -> None:
        try:
            self._client.shutdown()
        except Exception as exc:
            log.warning("trazas no enviadas", action="trace_shutdown", error=type(exc).__name__)
