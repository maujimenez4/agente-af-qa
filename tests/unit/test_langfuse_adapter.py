"""Adaptador `LangfuseTracer` (T-40 · RNF-24 · DT-09) sobre el SDK real de Langfuse, sin red.

Se inyecta un `InMemorySpanExporter` (lo que se exportaría a Langfuse Cloud queda en memoria) y
el host apunta a un puerto cerrado de la propia máquina. El SDK comparte recursos por clave
pública: cada prueba usa una clave ficticia distinta y cierra el cliente al final.
"""

import json
import os
import threading
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel, SecretStr
from structlog.testing import capture_logs

from adapters.base import Chunk, Message, TaskType
from adapters.errors import RateLimitError
from adapters.llm.fallback import FallbackLLMProvider
from adapters.observability.langfuse import LangfuseTracer
from core import tracing
from core.config import Settings
from core.tracing import (
    GraphStepHandler,
    LLMTraceObserver,
    TracingVectorStore,
    operation,
    secret_mask,
)
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.vector_store import FakeVectorStore

OFFLINE_HOST = "http://127.0.0.1:9"  # puerto cerrado: nunca sale nada de la máquina
FICTITIOUS_GROQ = "valorficticio-groq-5b1d8e4a"  # sin forma de token: solo lo tapa la config
INPUT_ATTR = "langfuse.observation.input"
OUTPUT_ATTR = "langfuse.observation.output"
MESSAGES = [
    Message(role="system", content="Sistema ficticio."),
    Message(role="user", content=f"Petición ficticia con {FICTITIOUS_GROQ} dentro."),
]


class Answer(BaseModel):
    text: str


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        groq_api_key=SecretStr(FICTITIOUS_GROQ),
        langfuse_public_key=SecretStr("pk-lf-ficticia-config"),
        langfuse_secret_key=SecretStr("sk-lf-ficticia-config"),
    )


@pytest.fixture(autouse=True)
def no_langfuse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """El SDK lee variables `LANGFUSE_*`: ninguna del entorno de quien ejecuta las pruebas."""
    for name in list(os.environ):
        if name.upper().startswith("LANGFUSE_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(tracing, "_WARNED", set())


class Offline:
    """Un `LangfuseTracer` real con exportador en memoria y su cierre al final."""

    def __init__(self, *, capture_content: bool, flush_timeout_s: float = 2.0) -> None:
        self.exporter = InMemorySpanExporter()
        self.tracer = LangfuseTracer(
            public_key=SecretStr(f"pk-lf-ficticia-{uuid4()}"),
            secret_key=SecretStr("sk-lf-ficticia"),
            host=OFFLINE_HOST,
            capture_content=capture_content,
            mask=secret_mask(_settings().secret_values()),
            timeout_s=1,
            flush_timeout_s=flush_timeout_s,
            span_exporter=self.exporter,
        )
        self.client = self.tracer._client

    def spans(self) -> list[ReadableSpan]:
        self.client.flush()  # síncrono, solo hacia el exportador en memoria
        return list(self.exporter.get_finished_spans())

    def by_name(self) -> dict[str, ReadableSpan]:
        return {s.name: s for s in self.spans()}

    def close(self) -> None:
        self.tracer._client = self.client
        self.client.shutdown()


@pytest.fixture
def offline() -> Iterator[Offline]:
    o = Offline(capture_content=False)
    yield o
    o.close()


@pytest.fixture
def capturing() -> Iterator[Offline]:
    o = Offline(capture_content=True)
    yield o
    o.close()


def _attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def _store() -> tuple[FakeVectorStore, list[float]]:
    embeddings = FakeEmbeddingProvider()
    store = FakeVectorStore()
    text = f"Fragmento ficticio de préstamos con {FICTITIOUS_GROQ}."
    (vector,) = embeddings.embed([text])
    store.upsert(
        [
            Chunk(
                id="DOC-1-0",
                document_id="DOC-1",
                ordinal=0,
                section="Sección ficticia",
                content=text,
                embedding=vector,
                metadata={"category": "negocio"},
            )
        ]
    )
    (query,) = embeddings.embed(["préstamos"])
    return store, query


def _full_operation(tracer: LangfuseTracer) -> None:
    """Operación como la de la API: paso de nodo, búsqueda del RAG y dos intentos del LLM."""
    first = FakeLLMProvider(
        provider="ollama",
        model="modelo-ficticio-a",
        error=RateLimitError("Límite ficticio.", "llm", 1),
    )
    second = FakeLLMProvider(provider="ollama", model="modelo-ficticio-b")
    for llm in (first, second):
        llm.builders[Answer] = lambda _m: Answer(text=f"Salida ficticia {FICTITIOUS_GROQ}")
    chain = FallbackLLMProvider(lambda _t: [first, second], observer=LLMTraceObserver())
    store, query = _store()
    with operation(
        tracer,
        "crear",
        session_id="conv-ficticia-9",
        user_id="af-demo",
        mode="functional",
        flow="need",
        project="DEMO",
    ) as op:
        assert op is not None
        handler = GraphStepHandler(op)
        run_id = uuid4()
        handler.on_chain_start(
            {}, {}, run_id=run_id, metadata={"langgraph_node": "generate"}, name="generate"
        )
        TracingVectorStore(store).search(query, f"consulta {FICTITIOUS_GROQ}", 1)
        chain.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
        handler.on_chain_end({"artifact": None}, run_id=run_id)


# --- Criterio 6: OpenTelemetry propio ----------------------------------------------------------


def test_constructing_tracer_does_not_touch_global_provider() -> None:
    """Criterio 6: el proveedor global de OpenTelemetry sigue siendo el mismo objeto."""
    before = otel_trace.get_tracer_provider()
    o = Offline(capture_content=False)
    try:
        after = otel_trace.get_tracer_provider()
        assert after is before and type(after) is type(before)
        assert isinstance(o.tracer.provider, TracerProvider)
        assert o.tracer.provider is not before
    finally:
        o.close()
    assert otel_trace.get_tracer_provider() is before


def test_foreign_scope_spans_are_not_exported(offline: Offline) -> None:
    """Criterio 6: un span de otro ámbito en el mismo proveedor (p. ej. el SDK de MCP) no sale,
    ni suelto ni dentro de una traza de Langfuse."""
    foreign = offline.tracer.provider.get_tracer("mcp-ficticio")
    with foreign.start_as_current_span("ajeno-suelto"):
        pass
    root = offline.tracer.start_trace(
        "crear", session_id=None, user_id=None, tags=[], metadata={"operacion": "crear"}
    )
    with foreign.start_as_current_span("ajeno-anidado"):
        pass
    root.end()
    names = [s.name for s in offline.spans()]
    assert names == ["crear"]
    assert all(s.instrumentation_scope.name == "langfuse-sdk" for s in offline.spans())


def test_global_provider_spans_are_not_exported(offline: Offline) -> None:
    """Criterio 6: un span creado con el proveedor global tampoco llega al exportador."""
    with otel_trace.get_tracer("biblioteca-ficticia").start_as_current_span("ajeno-global"):
        pass
    assert offline.spans() == []


# --- Traza: atributos ---------------------------------------------------------------------------


def test_trace_attributes_reach_every_span(offline: Offline) -> None:
    """Criterio 2: sesión, persona, nombre y etiquetas en la raíz y en todos sus hijos."""
    _full_operation(offline.tracer)
    spans = offline.spans()
    assert {s.name for s in spans} == {"crear", "generate", "rag · buscar", "llm · generate_story"}
    for span in spans:
        attrs = _attrs(span)
        assert attrs["session.id"] == "conv-ficticia-9"
        assert attrs["user.id"] == "af-demo"
        assert attrs["langfuse.trace.name"] == "crear"
        assert tuple(attrs["langfuse.trace.tags"]) == (
            "modo:functional",
            "flujo:need",
            "proyecto:DEMO",
        )


def test_generations_carry_model_usage_cost_and_error_level(offline: Offline) -> None:
    """Criterio 3: la generation fallida en ERROR con su motivo; la buena con tokens y coste 0."""
    _full_operation(offline.tracer)
    generations = [
        _attrs(s)
        for s in offline.spans()
        if _attrs(s).get("langfuse.observation.type") == "generation"
    ]
    failed = next(a for a in generations if a.get("langfuse.observation.level") == "ERROR")
    ok = next(a for a in generations if a is not failed)
    assert failed["langfuse.observation.model.name"] == "modelo-ficticio-a"
    assert failed["langfuse.observation.metadata.motivo"] == "limite"
    assert failed["langfuse.observation.status_message"] == "limite: RateLimitError"
    assert ok["langfuse.observation.model.name"] == "modelo-ficticio-b"
    assert '"input"' in ok["langfuse.observation.usage_details"]
    assert ok["langfuse.observation.cost_details"] == '{"total": 0.0}'


def test_retriever_span_type(offline: Offline) -> None:
    """Criterio 2: la búsqueda del RAG es un paso de tipo retriever."""
    _full_operation(offline.tracer)
    attrs = _attrs(offline.by_name()["rag · buscar"])
    assert attrs["langfuse.observation.type"] == "retriever"
    assert "DOC-1-0" in attrs["langfuse.observation.metadata.fragmentos"]


# --- Criterio 5: interruptor y enmascarado -----------------------------------------------------


def test_capture_off_exports_no_input_or_output(offline: Offline) -> None:
    """Criterio 5: sin el interruptor, ningún span exportado lleva entrada ni salida."""
    _full_operation(offline.tracer)
    spans = offline.spans()
    assert len(spans) == 5
    for span in spans:
        assert INPUT_ATTR not in _attrs(span) and OUTPUT_ATTR not in _attrs(span)
    exported = repr([_attrs(s) for s in spans])
    assert "Petición ficticia" not in exported and "Fragmento ficticio" not in exported
    assert FICTITIOUS_GROQ not in exported


def test_capture_off_adapter_drops_content_even_if_core_sends_it(offline: Offline) -> None:
    """Criterio 5: el adaptador vuelve a aplicar el interruptor (segunda barrera)."""
    root = offline.tracer.start_trace(
        "crear", session_id=None, user_id=None, tags=[], metadata={"operacion": "crear"}
    )
    child = root.child("llm", kind="generation", input=[{"content": "texto-ficticio"}])
    child.end(output="salida-ficticia")
    root.end(output="otra-salida-ficticia")
    for span in offline.spans():
        assert INPUT_ATTR not in _attrs(span) and OUTPUT_ATTR not in _attrs(span)
    assert offline.tracer.content("algo") is None


def test_capture_on_exports_content_with_secrets_masked(capturing: Offline) -> None:
    """Criterio 5: con el interruptor viajan entrada y salida; el secreto de la configuración
    sale como `***` en la entrada, la salida y los metadatos."""
    _full_operation(capturing.tracer)
    spans = capturing.by_name()
    generation = next(
        _attrs(s)
        for s in capturing.spans()
        if _attrs(s).get("langfuse.observation.type") == "generation" and OUTPUT_ATTR in _attrs(s)
    )
    assert json.loads(generation[INPUT_ATTR])[1] == {
        "role": "user",
        "content": "Petición ficticia con *** dentro.",
    }
    assert json.loads(generation[OUTPUT_ATTR]) == {"text": "Salida ficticia ***"}
    retriever = _attrs(spans["rag · buscar"])
    assert json.loads(retriever[INPUT_ATTR]) == {"consulta": "consulta ***"}
    assert json.loads(retriever[OUTPUT_ATTR]) == [
        {"id": "DOC-1-0", "texto": "Fragmento ficticio de préstamos con ***."}
    ]
    assert FICTITIOUS_GROQ not in repr([_attrs(s) for s in capturing.spans()])


def test_capture_on_masks_metadata_status_and_token_patterns(capturing: Offline) -> None:
    """Criterio 5: metadatos, mensaje de estado, claves sensibles y patrones `Bearer …`."""
    bearer = "Bearer abcdefghijklmnop0123"
    root = capturing.tracer.start_trace(
        "crear",
        session_id="conv-ficticia",
        user_id="af-demo",
        tags=[],
        metadata={"operacion": "crear", "nota": f"valor {FICTITIOUS_GROQ}"},
    )
    child = root.child(
        "paso",
        input={"cabecera": bearer},
        metadata={"api_key": "cualquier-valor-ficticio", "otra": bearer},
    )
    child.end(
        output=[FICTITIOUS_GROQ],
        metadata={"detalle": f"fin {FICTITIOUS_GROQ}"},
        level="ERROR",
        status=f"fallo {FICTITIOUS_GROQ}",
    )
    root.end()
    spans = capturing.by_name()
    attrs = _attrs(spans["paso"])
    assert attrs["langfuse.observation.metadata.api_key"] == "***"
    assert attrs["langfuse.observation.metadata.otra"] == "***"
    assert attrs["langfuse.observation.metadata.detalle"] == "fin ***"
    assert attrs["langfuse.observation.status_message"] == "fallo ***"
    assert attrs[INPUT_ATTR] == '{"cabecera": "***"}'
    assert attrs[OUTPUT_ATTR] == '["***"]'
    assert _attrs(spans["crear"])["langfuse.observation.metadata.nota"] == "valor ***"
    exported = repr([_attrs(s) for s in spans.values()])
    assert FICTITIOUS_GROQ not in exported and "abcdefghijklmnop0123" not in exported


def test_client_mask_hook_uses_the_same_masker(offline: Offline) -> None:
    """Criterio 5: la función `mask` del cliente (última red) enmascara igual."""
    masked = offline.tracer._mask_hook(data={"texto": f"x {FICTITIOUS_GROQ}"})
    assert masked == {"texto": "x ***"}


def test_langfuse_keys_from_settings_are_masked_too() -> None:
    """Criterio 5: las propias claves de Langfuse están entre los secretos enmascarados."""
    mask = secret_mask(_settings().secret_values())
    assert mask("pk-lf-ficticia-config y sk-lf-ficticia-config") == "*** y ***"


# --- Criterio 7: sin espera ---------------------------------------------------------------------


class SlowClient:
    """Cliente cuyo `flush` y `shutdown` tardan (Langfuse lento); se puede soltar al final."""

    def __init__(self, wait_s: float = 5.0, fail: bool = False) -> None:
        self.wait_s = wait_s
        self.fail = fail
        self.release = threading.Event()
        self.flushes = 0
        self.shutdowns = 0

    def flush(self) -> None:
        self.flushes += 1
        self.release.wait(self.wait_s)
        if self.fail:
            raise ConnectionError("Langfuse ficticio caído")

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.release.wait(self.wait_s)
        if self.fail:
            raise ConnectionError("Langfuse ficticio caído")


def test_flush_returns_immediately_with_slow_client(offline: Offline) -> None:
    """Criterio 7: con un cliente que tarda 5 s, `flush()` vuelve en < 0,5 s."""
    slow = SlowClient(wait_s=5.0)
    offline.tracer._client = slow
    try:
        begin = time.monotonic()
        offline.tracer.flush()
        assert time.monotonic() - begin < 0.5
    finally:
        slow.release.set()


def test_flush_does_not_start_a_second_send_while_one_is_running(offline: Offline) -> None:
    """Criterio 7: si ya hay un envío en marcha, no se lanza otro."""
    slow = SlowClient(wait_s=5.0)
    offline.tracer._client = slow
    try:
        offline.tracer.flush()
        deadline = time.monotonic() + 2
        while slow.flushes == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        offline.tracer.flush()
        offline.tracer.flush()
        assert slow.flushes == 1
    finally:
        slow.release.set()
    deadline = time.monotonic() + 2
    while offline.tracer._flushing.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not offline.tracer._flushing.locked()  # se libera al terminar


def test_flush_error_is_logged_not_raised(offline: Offline) -> None:
    """Criterio 7: un fallo del envío no llega a quien llama; queda un aviso con el tipo."""
    broken = SlowClient(wait_s=0.0, fail=True)
    offline.tracer._client = broken
    with capture_logs() as logs:
        offline.tracer.flush()
        deadline = time.monotonic() + 2
        while offline.tracer._flushing.locked() or broken.flushes == 0:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        time.sleep(0.05)
    warnings = [e for e in logs if e["event"] == "trazas no enviadas"]
    assert warnings and warnings[0]["error"] == "ConnectionError"
    assert "caído" not in repr(logs)


def test_shutdown_waits_at_most_flush_timeout() -> None:
    """Criterio 7: `shutdown()` vuelve en ≈ `flush_timeout_s` aunque el cliente tarde 5 s."""
    o = Offline(capture_content=False, flush_timeout_s=0.3)
    slow = SlowClient(wait_s=5.0)
    o.tracer._client = slow
    try:
        begin = time.monotonic()
        o.tracer.shutdown()
        elapsed = time.monotonic() - begin
        assert 0.25 <= elapsed < 1.5
        assert slow.shutdowns == 1
    finally:
        slow.release.set()
        o.close()


def test_shutdown_error_is_swallowed() -> None:
    """Criterio 7: un fallo al cerrar no se propaga."""
    o = Offline(capture_content=False, flush_timeout_s=1.0)
    o.tracer._client = SlowClient(wait_s=0.0, fail=True)
    try:
        o.tracer.shutdown()
    finally:
        o.close()


def test_operation_with_real_adapter_is_not_delayed_by_slow_send(offline: Offline) -> None:
    """Criterio 7: una operación completa con Langfuse lento termina sin esperar el envío."""
    slow = SlowClient(wait_s=5.0)
    real = offline.client
    try:
        # Los spans se siguen creando con el cliente real; solo el envío es lento.
        offline.tracer._client = _SpansFromRealClient(real, slow)  # type: ignore[assignment]
        begin = time.monotonic()
        _full_operation(offline.tracer)
        assert time.monotonic() - begin < 1.0
    finally:
        slow.release.set()


class _SpansFromRealClient:
    """Crea los spans con el cliente real y envía con el lento."""

    def __init__(self, real: Any, slow: SlowClient) -> None:
        self._real = real
        self._slow = slow

    def start_observation(self, **kwargs: Any) -> Any:
        return self._real.start_observation(**kwargs)

    def flush(self) -> None:
        self._slow.flush()

    def shutdown(self) -> None:
        self._slow.shutdown()
