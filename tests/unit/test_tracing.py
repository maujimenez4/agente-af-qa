"""Núcleo de las trazas (T-40 · RNF-24 · DT-09): `core/tracing.py` con `tests/fakes/tracer.py`.

Operación en curso, pasos del grafo, *generations* de la cadena de proveedores, pasos del RAG,
versión del prompt, interruptor de contenido y robustez. Sin red ni `.env`; datos ficticios.
"""

import inspect
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from structlog.testing import capture_logs

from adapters.base import Chunk, Message, TaskType
from adapters.errors import RateLimitError
from adapters.llm.fallback import INVALID_OUTPUT, FallbackLLMProvider
from adapters.llm.openai_compatible import ProviderTimeoutError, StructuredOutputError
from core import tracing
from core.rag.prompts import PROMPTS_DIR, Prompt, load_prompt
from core.tracing import (
    PAUSED,
    GraphStepHandler,
    LLMTraceObserver,
    NullTracer,
    TracingVectorStore,
    current_operation,
    note_prompt,
    operation,
    operation_name,
    operation_tags,
    secret_mask,
    with_trace_callbacks,
)
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.tracer import FakeSpan, FakeTracer, TracerDown
from tests.fakes.vector_store import FakeVectorStore

MESSAGES = [
    Message(role="system", content="Sistema ficticio."),
    Message(role="user", content="Petición ficticia sobre préstamos de la biblioteca."),
]
FICTITIOUS_KEY = "valorficticio-groq-7f3a9c2e"  # no coincide con ningún patrón de token


class Answer(BaseModel):
    text: str


def _llm(**kwargs: Any) -> FakeLLMProvider:
    """FakeLLMProvider que también sabe responder al esquema `Answer` de estas pruebas."""
    llm = FakeLLMProvider(**kwargs)
    llm.builders[Answer] = lambda _messages: Answer(text="Respuesta ficticia.")
    return llm


@pytest.fixture(autouse=True)
def fresh_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_safe` avisa una vez por tipo en todo el proceso: cada prueba empieza de cero."""
    monkeypatch.setattr(tracing, "_WARNED", set())


def _fallback(*providers: FakeLLMProvider, observer: Any = None) -> FallbackLLMProvider:
    return FallbackLLMProvider(
        lambda _task: list(providers),
        observer=LLMTraceObserver() if observer is None else observer,
    )


def _rate_limit() -> RateLimitError:
    return RateLimitError("Límite ficticio del proveedor.", "llm", 3)


def _store() -> tuple[FakeVectorStore, FakeEmbeddingProvider]:
    embeddings = FakeEmbeddingProvider()
    store = FakeVectorStore()
    for n, text in enumerate(["Renovar préstamos ficticios.", "Avisos de vencimiento ficticios."]):
        (vector,) = embeddings.embed([text])
        store.upsert(
            [
                Chunk(
                    id=f"DOC-{n}-0",
                    document_id=f"DOC-{n}",
                    ordinal=0,
                    section="Sección ficticia",
                    content=text,
                    embedding=vector,
                    metadata={"category": "negocio"},
                )
            ]
        )
    return store, embeddings


# --- Criterio 1: desactivado no hace nada ------------------------------------------------------


def test_operation_yields_none_and_creates_nothing_when_tracer_disabled() -> None:
    """Criterio 1 (RNF-24): con el trazador desactivado no se crea traza ni se hace flush."""
    tracer = FakeTracer(enabled=False)
    with operation(tracer, "crear", session_id="conv-ficticia", user_id="af-demo") as op:
        assert op is None
        assert current_operation() is None
    assert tracer.traces == [] and tracer.flushes == 0


def test_operation_with_null_tracer_never_calls_start_trace() -> None:
    """Criterio 1: `NullTracer` no crea trazas (si se le llamara, lanzaría)."""
    with capture_logs() as logs, operation(NullTracer(), "crear") as op:
        assert op is None
    assert logs == []  # ni siquiera el aviso de `_safe`: no se intentó nada


def test_null_tracer_flush_and_shutdown_do_nothing() -> None:
    """Criterio 1: `NullTracer` no llama a la red ni falla al cerrar."""
    tracer = NullTracer()
    assert tracer.enabled is False and tracer.capture_content is False
    assert tracer.flush() is None and tracer.shutdown() is None


def test_observers_do_nothing_without_operation() -> None:
    """Criterio 1: sin operación en curso, el observador del LLM y el vector store no crean nada."""
    assert LLMTraceObserver().attempt(TaskType.GENERATE_STORY, "ollama", "m", MESSAGES) is None
    store, embeddings = _store()
    (vector,) = embeddings.embed(["renovar"])
    assert TracingVectorStore(store).search(vector, "renovar", 2) == store.search(
        vector, "renovar", 2
    )


# --- Operación: traza, etiquetas, errores ------------------------------------------------------


def test_operation_creates_trace_with_session_user_and_tags() -> None:
    """Criterio 2: la traza lleva sesión, persona y etiquetas modo/flujo/proyecto."""
    tracer = FakeTracer()
    with operation(
        tracer,
        "crear",
        session_id="conv-ficticia-1",
        user_id="af-demo",
        mode="functional",
        flow="need",
        project="DEMO",
    ) as op:
        assert op is not None and current_operation() is op
    assert current_operation() is None
    (root,) = tracer.traces
    assert root.name == "crear"
    assert root.trace == {
        "session_id": "conv-ficticia-1",
        "user_id": "af-demo",
        "tags": ["modo:functional", "flujo:need", "proyecto:DEMO"],
    }
    assert root.metadata["operacion"] == "crear"
    assert root.ended and root.level is None and root.status is None
    assert tracer.flushes == 1


def test_operation_tags_skip_unknown_values() -> None:
    """Criterio 2 (límite): solo las etiquetas conocidas."""
    assert operation_tags() == []
    assert operation_tags(flow="review") == ["flujo:review"]


@pytest.mark.parametrize(
    ("operation_id", "expected"),
    [
        ("start", "crear"),
        ("iterate", "iterar"),
        ("approve", "aprobar"),
        ("retry", "reintentar"),
        ("edit", "editar"),
        ("discard", "descartar"),
        ("otra", "otra"),
        (None, "operacion"),
        ("", "operacion"),
    ],
)
def test_operation_name_maps_api_operations(operation_id: str | None, expected: str) -> None:
    """Criterio 2: nombre de la traza de cada operación de la API y de la UI."""
    assert operation_name(operation_id) == expected


def test_operation_error_propagates_unchanged_and_trace_keeps_only_type() -> None:
    """Criterio 7: el error llega igual a quien llama; en la traza solo queda su tipo."""
    tracer = FakeTracer()
    detail = "detalle-interno-ficticio-0000"
    error = ValueError(detail)
    with pytest.raises(ValueError) as raised, operation(tracer, "crear"):
        raise error
    assert raised.value is error
    (root,) = tracer.traces
    assert root.level == "ERROR" and root.status == "ValueError"
    assert detail not in repr([vars(s) for s in tracer.spans()])
    assert current_operation() is None
    assert tracer.flushes == 1


def test_operation_abandoned_generator_ends_with_warning() -> None:
    """Criterio 2: la UI abandona el progreso (`GeneratorExit`) → nivel WARNING, no ERROR."""
    tracer = FakeTracer()

    def progress() -> Iterator[str]:
        with operation(tracer, "crear"):
            yield "load_origin"
            yield "retrieve_context"

    steps = progress()
    assert next(steps) == "load_origin"
    steps.close()
    (root,) = tracer.traces
    assert root.level == "WARNING" and root.status == "GeneratorExit"


def test_nested_operations_restore_previous_operation() -> None:
    """La `ContextVar` vuelve a la operación anterior al salir."""
    tracer = FakeTracer()
    with operation(tracer, "externa") as outer:
        with operation(tracer, "interna") as inner:
            assert current_operation() is inner
        assert current_operation() is outer


# --- Criterio 7: el trazador caído o lento no rompe --------------------------------------------


def test_operation_runs_when_tracer_is_down() -> None:
    """Criterio 7: con Langfuse caído la operación termina igual y entrega `None`."""
    tracer = FakeTracer(fail=True)
    with capture_logs() as logs, operation(tracer, "crear") as op:
        assert op is None
        result = "hecho"
    assert result == "hecho"
    assert [entry["event"] for entry in logs] == ["traza no registrada"]
    assert logs[0]["error"] == "TracerDown"
    assert "Langfuse ficticio" not in repr(logs)


def test_safe_warns_once_per_error_type() -> None:
    """Criterio 7: el fallo del trazador se registra una sola vez por tipo."""
    with capture_logs() as logs:
        for _ in range(3):
            with operation(FakeTracer(fail=True), "crear"):
                pass
    assert len(logs) == 1


def test_safe_returns_value_or_none() -> None:
    """Criterio 7: `_safe` devuelve el valor o `None`, nunca propaga."""
    assert tracing._safe("prueba", lambda: 7) == 7

    def broken() -> int:
        raise TracerDown("caído ficticio")

    assert tracing._safe("prueba", broken) is None


class SpansDownTracer(FakeTracer):
    """La traza se crea, pero todo lo demás (pasos, generations, cierre, flush) falla."""

    def start_trace(self, name: str, **kwargs: Any) -> FakeSpan:
        self.fail = False
        try:
            return super().start_trace(name, **kwargs)
        finally:
            self.fail = True


def test_llm_and_retrieval_work_when_spans_fail() -> None:
    """Criterio 7: si fallan los pasos tras crear la traza, el LLM y el RAG responden igual."""
    tracer = SpansDownTracer()
    store, embeddings = _store()
    (vector,) = embeddings.embed(["renovar"])
    llm = _fallback(_llm(provider="ollama", model="modelo-ficticio-a"))
    expected_llm = FakeLLMProvider().generate(MESSAGES, TaskType.GENERATE_STORY).content
    with operation(tracer, "crear") as op:
        assert op is not None
        result = llm.generate(MESSAGES, TaskType.GENERATE_STORY)
        found = TracingVectorStore(store).search(vector, "renovar", 2)
    assert result.content == expected_llm
    assert found == store.search(vector, "renovar", 2)
    assert tracer.traces[0].children == []


# --- Criterio 3: intentos de la cadena ---------------------------------------------------------


def test_failed_attempt_is_error_generation_sibling_of_successful_one() -> None:
    """Criterio 3: 429 en el primero → dos generations hermanas; la 1.ª ERROR con «limite», la
    2.ª correcta con tokens, latencia y coste 0."""
    tracer = FakeTracer()
    first = _llm(provider="ollama", model="modelo-ficticio-a", error=_rate_limit())
    second = _llm(provider="ollama", model="modelo-ficticio-b")
    llm = _fallback(first, second)
    with operation(tracer, "crear"):
        result = llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
    assert result.model == "modelo-ficticio-b"
    (root,) = tracer.traces
    failed, ok = root.children
    assert failed.kind == ok.kind == "generation"
    assert failed.name == ok.name == "llm · generate_story"
    assert failed.model == "modelo-ficticio-a" and ok.model == "modelo-ficticio-b"
    assert failed.level == "ERROR"
    assert failed.metadata["motivo"] == "limite"
    assert failed.metadata["error"] == "RateLimitError"
    assert failed.metadata["estado"] == "fallido"
    assert failed.status == "limite: RateLimitError"
    assert failed.metadata["proveedor"] == "ollama" and failed.metadata["tarea"] == "generate_story"
    assert ok.level is None and ok.metadata["estado"] == "ok"
    assert ok.usage == {"input": result.input_tokens, "output": result.output_tokens}
    assert ok.usage["input"] > 0 and ok.usage["output"] > 0
    assert ok.cost == {"total": 0.0} and failed.cost == {"total": 0.0}
    assert ok.metadata["latencia_ms"] == result.latency_ms
    assert all(s.ended for s in root.children)


def test_structured_output_error_is_invalid_output_reason() -> None:
    """Criterio 3: `StructuredOutputError` → motivo `salida_no_valida`; se propaga igual."""
    tracer = FakeTracer()
    error = StructuredOutputError("Salida ficticia no válida.", "llm")
    llm = _fallback(_llm(error=error), FakeLLMProvider())
    with pytest.raises(StructuredOutputError) as raised, operation(tracer, "crear"):
        llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
    assert raised.value is error
    (gen,) = tracer.spans("generation")
    assert gen.level == "ERROR"
    assert gen.metadata["motivo"] == INVALID_OUTPUT == "salida_no_valida"
    assert gen.metadata["error"] == "StructuredOutputError"


def test_timeout_attempt_reason_is_tiempo_espera() -> None:
    """Criterio 3: un proveedor que no responde a tiempo queda con motivo `tiempo_espera`."""
    tracer = FakeTracer()
    slow = _llm(error=ProviderTimeoutError("Sin respuesta ficticia.", "llm"))
    llm = _fallback(slow, FakeLLMProvider())
    with operation(tracer, "crear"):
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)
    failed, ok = tracer.spans("generation")
    assert failed.metadata["motivo"] == "tiempo_espera" and ok.metadata["estado"] == "ok"


def test_unexpected_error_attempt_is_recorded_and_propagated() -> None:
    """Criterio 3: un error no previsto queda con motivo «error» y se propaga sin cambios."""
    tracer = FakeTracer()
    error = KeyError("ficticio")
    llm = _fallback(_llm(error=error), FakeLLMProvider())
    with pytest.raises(KeyError) as raised, operation(tracer, "crear"):
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)
    assert raised.value is error
    (gen,) = tracer.spans("generation")
    assert gen.metadata["motivo"] == "error" and gen.level == "ERROR"


def test_generation_is_child_of_current_graph_step() -> None:
    """Criterio 2: la generation cuelga del paso del nodo en curso, no de la raíz."""
    tracer = FakeTracer()
    llm = _fallback(FakeLLMProvider())
    with operation(tracer, "crear") as op:
        assert op is not None
        handler = GraphStepHandler(op)
        run_id = uuid4()
        handler.on_chain_start(
            {}, {}, run_id=run_id, metadata={"langgraph_node": "generate"}, name="generate"
        )
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)
        handler.on_chain_end({}, run_id=run_id)
    (root,) = tracer.traces
    (step,) = root.children
    assert step.name == "generate"
    assert [c.kind for c in step.children] == ["generation"]


class ExplodingObserver:
    def attempt(self, *_args: Any) -> Any:
        raise TracerDown("observador ficticio roto")


class ExplodingRecord:
    def succeeded(self, _result: Any) -> None:
        raise TracerDown("registro ficticio roto")

    def failed(self, *_args: Any) -> None:
        raise TracerDown("registro ficticio roto")


class RecordBreakingObserver:
    def attempt(self, *_args: Any) -> ExplodingRecord:
        return ExplodingRecord()


@pytest.mark.parametrize(
    "observer", [ExplodingObserver(), RecordBreakingObserver()], ids=["attempt", "registro"]
)
def test_failing_observer_does_not_change_llm_result(observer: Any) -> None:
    """Criterio 7: un observador que lanza no cambia el resultado ni el cambio de proveedor."""
    first = _llm(provider="ollama", model="modelo-ficticio-a", error=_rate_limit())
    second = _llm(provider="ollama", model="modelo-ficticio-b")
    plain = FallbackLLMProvider(lambda _t: [first, second])
    observed = FallbackLLMProvider(lambda _t: [first, second], observer=observer)

    expected = plain.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
    got = observed.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert got.content == expected.content
    assert (got.provider, got.model) == (expected.provider, expected.model)
    assert (got.input_tokens, got.output_tokens) == (expected.input_tokens, expected.output_tokens)


def test_failing_observer_keeps_chain_error() -> None:
    """Criterio 7: con toda la cadena caída el error final es el mismo con o sin observador."""
    failing = _llm(error=_rate_limit())
    with pytest.raises(RateLimitError):
        FallbackLLMProvider(lambda _t: [failing], observer=ExplodingObserver()).generate(
            MESSAGES, TaskType.GENERATE_STORY
        )


# --- Criterio 4: versión del prompt ------------------------------------------------------------


def _header_version(name: str) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8-sig")
    line = next(li for li in text.splitlines() if li.startswith("version:"))
    return line.split(":", 1)[1].strip().strip("\"'")


def test_load_prompt_notes_name_and_version_in_next_generation() -> None:
    """Criterio 4: `load_prompt` anota nombre y versión y la siguiente generation los lleva."""
    tracer = FakeTracer()
    llm = _fallback(FakeLLMProvider())
    with operation(tracer, "crear") as op:
        assert op is not None
        prompt = load_prompt("generate_story")
        assert op.prompt == ("generate_story", prompt.version)
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)
    (gen,) = tracer.spans("generation")
    assert gen.metadata["prompt"] == "generate_story"
    assert gen.metadata["prompt_version"] == prompt.version == _header_version("generate_story")


def test_generation_without_loaded_prompt_has_no_prompt_metadata() -> None:
    """Criterio 4 (negativo): sin prompt cargado, la generation no inventa versión."""
    tracer = FakeTracer()
    with operation(tracer, "crear"):
        _fallback(FakeLLMProvider()).generate(MESSAGES, TaskType.GENERATE_STORY)
    (gen,) = tracer.spans("generation")
    assert "prompt" not in gen.metadata and "prompt_version" not in gen.metadata


def test_graph_step_start_clears_previous_prompt() -> None:
    """Criterio 4: el prompt de un nodo no se arrastra a las generations del siguiente."""
    tracer = FakeTracer()
    with operation(tracer, "crear") as op:
        assert op is not None
        note_prompt("generate_story", "9")
        handler = GraphStepHandler(op)
        handler.on_chain_start(
            {}, {}, run_id=uuid4(), metadata={"langgraph_node": "generate"}, name="generate"
        )
        assert op.prompt is None


def test_note_prompt_without_operation_does_nothing() -> None:
    """Criterio 4: sin operación en curso, `note_prompt` no hace nada ni falla."""
    note_prompt("generate_story", "1")
    assert current_operation() is None


def test_load_prompt_returns_same_prompt_with_or_without_tracing(tmp_path: Path) -> None:
    """Criterio 4: con operación, sin ella o con NullTracer, `load_prompt` devuelve lo mismo."""
    plain = load_prompt("generate_story")
    with operation(NullTracer(), "crear"):
        with_null = load_prompt("generate_story")
    with operation(FakeTracer(), "crear"):
        traced = load_prompt("generate_story")
    assert isinstance(plain, Prompt)
    assert plain == with_null == traced
    (tmp_path / "ficticio.md").write_text("---\nversion: 3\n---\nTexto ficticio.\n", "utf-8")
    assert load_prompt("ficticio", tmp_path) == Prompt("ficticio", "3", "Texto ficticio.")


def test_load_prompt_signature_is_unchanged() -> None:
    """Criterio 4: la firma pública de `load_prompt` no cambia."""
    signature = inspect.signature(load_prompt)
    assert list(signature.parameters) == ["name", "prompts_dir"]
    assert signature.parameters["prompts_dir"].default == PROMPTS_DIR
    assert signature.return_annotation in (Prompt, "Prompt")


# --- Criterio 2 y 8: pasos del grafo -----------------------------------------------------------


class _State(TypedDict, total=False):
    value: int


def _toy_graph(fail: bool = False) -> Any:
    def first(state: _State) -> _State:
        return {"value": 1}

    def second(state: _State) -> _State:
        if fail:
            raise ValueError("detalle-interno-ficticio")
        return {"value": state.get("value", 0) + 1}

    graph = StateGraph(_State)
    graph.add_node("first", first)
    graph.add_node("second", second)
    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)
    return graph.compile()


def test_graph_step_handler_one_step_per_real_node() -> None:
    """Criterio 8: un paso por nodo real; nada de `__start__`, ChannelWrite ni similares."""
    tracer = FakeTracer()
    with operation(tracer, "crear") as op:
        result = _toy_graph().invoke({}, with_trace_callbacks({}, op))
    assert result == {"value": 2}
    (root,) = tracer.traces
    assert [s.name for s in root.children] == ["first", "second"]
    assert all(s.metadata["estado"] == "ok" and s.ended for s in root.children)
    assert root.children[0].metadata["campos"] == ["value"]
    assert all(not s.name.startswith("__") for s in tracer.spans())


def test_graph_step_handler_marks_failed_node_as_error_with_type_only() -> None:
    """Criterio 2: el nodo que falla queda en ERROR con el tipo, sin el mensaje."""
    tracer = FakeTracer()
    with pytest.raises(ValueError), operation(tracer, "crear") as op:
        _toy_graph(fail=True).invoke({}, with_trace_callbacks({}, op))
    (root,) = tracer.traces
    first, second = root.children
    assert first.metadata["estado"] == "ok"
    assert second.level == "ERROR" and second.status == "ValueError"
    assert second.metadata["estado"] == "error" and second.metadata["error"] == "ValueError"
    assert "detalle-interno-ficticio" not in repr([vars(s) for s in tracer.spans()])


def test_graph_step_handler_interrupt_is_paused_not_error() -> None:
    """Criterio 2: la interrupción de `human_review` queda como «pausado», no como error."""
    tracer = FakeTracer()
    with operation(tracer, "crear") as op:
        assert op is not None
        handler = GraphStepHandler(op)
        run_id = uuid4()
        handler.on_chain_start(
            {}, {}, run_id=run_id, metadata={"langgraph_node": "human_review"}, name="human_review"
        )
        handler.on_chain_error(GraphInterrupt(), run_id=run_id)
    (step,) = tracer.traces[0].children
    assert step.metadata["estado"] == "pausado" and step.status == PAUSED
    assert step.level is None
    assert op.step is None


@pytest.mark.parametrize(
    ("node", "name"),
    [
        ("__start__", "__start__"),
        ("__end__", "__end__"),
        ("generate", "ChannelWrite<generate>"),
        ("generate", "RunnableSequence"),
        (None, "generate"),
        (7, "generate"),
    ],
)
def test_graph_step_handler_ignores_internal_runs(node: Any, name: str) -> None:
    """Criterio 8: los internos de LangGraph (y los que no son de un nodo) no crean paso."""
    tracer = FakeTracer()
    with operation(tracer, "crear") as op:
        assert op is not None
        handler = GraphStepHandler(op)
        run_id = uuid4()
        handler.on_chain_start({}, {}, run_id=run_id, metadata={"langgraph_node": node}, name=name)
        handler.on_chain_end({}, run_id=run_id)
        handler.on_chain_error(ValueError("x"), run_id=uuid4())  # desconocido: no hace nada
    assert tracer.traces[0].children == []


def test_node_metadata_carries_only_references() -> None:
    """Criterio 5: el cierre de un nodo lleva campos y versiones, nunca contenido."""

    class FakeArtifact:
        version = 2
        prompt_version = "3"
        status = None

    found = tracing._node_metadata({"artifact": FakeArtifact(), "texto": "contenido-ficticio"})
    assert found == {
        "campos": ["artifact", "texto"],
        "artefacto_version": "2",
        "artefacto_prompt_version": "3",
    }
    assert tracing._node_metadata("no es un mapa") == {}


def test_with_trace_callbacks_keeps_config_and_existing_callbacks() -> None:
    """Criterio 2: sin operación devuelve el mismo config; con ella añade el manejador."""
    config: dict[str, Any] = {"configurable": {"thread_id": "t-ficticio"}, "callbacks": ["otro"]}
    assert with_trace_callbacks(config, None) is config
    with operation(FakeTracer(), "crear") as op:
        traced = with_trace_callbacks(config, op)
    assert traced["configurable"] == config["configurable"]
    assert traced["callbacks"][0] == "otro"
    assert isinstance(traced["callbacks"][1], GraphStepHandler)
    assert config["callbacks"] == ["otro"]  # no muta el original
    with operation(FakeTracer(), "crear") as op:
        assert len(with_trace_callbacks(None, op)["callbacks"]) == 1


# --- RAG: TracingVectorStore -------------------------------------------------------------------


def test_tracing_vector_store_records_retriever_step_with_ids_and_scores() -> None:
    """Criterio 2: paso retriever con k, filtros, ids y puntuaciones; sin texto por defecto."""
    store, embeddings = _store()
    (vector,) = embeddings.embed(["renovar préstamos"])
    tracer = FakeTracer()
    with operation(tracer, "crear"):
        found = TracingVectorStore(store).search(
            vector, "renovar préstamos", 2, {"category": "negocio"}, 1.5
        )
    (span,) = tracer.spans("retriever")
    assert span.name == "rag · buscar"
    assert span.metadata["k"] == 2
    assert span.metadata["filtros"] == {"category": "negocio"}
    assert span.metadata["memory_boost"] == 1.5
    assert span.metadata["devueltos"] == len(found) == 2
    assert span.metadata["fragmentos"] == [
        {"id": r.chunk.id, "documento": r.chunk.document_id, "puntuacion": round(r.score, 4)}
        for r in found
    ]
    assert span.input is None and span.output is None


def test_tracing_vector_store_returns_exactly_inner_result() -> None:
    """Criterio 7: devuelve exactamente lo mismo que el inner (el mismo objeto)."""

    class Recording(FakeVectorStore):
        last: Any = None

        def search(self, *args: Any, **kwargs: Any) -> Any:
            self.last = super().search(*args, **kwargs)
            return self.last

    inner = Recording()
    store, embeddings = _store()
    inner.chunks = store.chunks
    (vector,) = embeddings.embed(["avisos"])
    with operation(FakeTracer(), "crear"):
        got = TracingVectorStore(inner).search(vector, "avisos", 1)
    assert got is inner.last


def test_tracing_vector_store_propagates_inner_errors() -> None:
    """Criterio 7: el error del inner se propaga igual y el paso queda en ERROR (solo el tipo)."""

    class Broken(FakeVectorStore):
        def search(self, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("detalle-ficticio-de-conexion")

    tracer = FakeTracer()
    with pytest.raises(ConnectionError), operation(tracer, "crear"):
        TracingVectorStore(Broken()).search([0.1], "x", 1)
    (span,) = tracer.spans("retriever")
    assert span.level == "ERROR" and span.status == "ConnectionError"
    with pytest.raises(ConnectionError):
        TracingVectorStore(Broken()).search([0.1], "x", 1)  # sin operación, igual


def test_tracing_vector_store_delegates_writes() -> None:
    """Criterio 7: escritura y consultas de documento pasan al inner tal cual."""
    store, _ = _store()
    traced = TracingVectorStore(store)
    assert traced.has_document("DOC-0") is True
    chunk = store.chunks["DOC-0-0"].model_copy(update={"id": "DOC-9-0", "document_id": "DOC-9"})
    traced.upsert([chunk])
    assert store.has_document("DOC-9")
    traced.replace_document("DOC-9", [chunk.model_copy(update={"content": "Otro ficticio."})])
    assert store.chunks["DOC-9-0"].content == "Otro ficticio."
    traced.delete_by_document("DOC-9")
    assert not traced.has_document("DOC-9")


# --- Criterio 5: interruptor de contenido ------------------------------------------------------


def _traced_llm_and_rag(tracer: FakeTracer) -> None:
    store, embeddings = _store()
    (vector,) = embeddings.embed(["renovar"])
    llm = _fallback(
        _llm(provider="ollama", model="modelo-ficticio-a", error=_rate_limit()),
        _llm(provider="ollama", model="modelo-ficticio-b"),
    )
    with operation(tracer, "crear") as op:
        handler = GraphStepHandler(op)  # type: ignore[arg-type]
        run_id = uuid4()
        handler.on_chain_start(
            {}, {}, run_id=run_id, metadata={"langgraph_node": "generate"}, name="generate"
        )
        TracingVectorStore(store).search(vector, "renovar préstamos ficticios", 2)
        llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
        handler.on_chain_end({"artifact": None}, run_id=run_id)


def test_capture_off_sends_no_input_or_output_anywhere() -> None:
    """Criterio 5: sin el interruptor ningún span lleva `input` ni `output`, ni texto en
    metadatos."""
    tracer = FakeTracer(capture_content=False)
    _traced_llm_and_rag(tracer)
    spans = tracer.spans()
    assert {s.kind for s in spans} == {"span", "generation", "retriever"}
    assert all(s.input is None and s.output is None for s in spans)
    dumped = repr([s.metadata for s in spans])
    for text in ("Petición ficticia", "renovar préstamos ficticios", "Renovar préstamos"):
        assert text not in dumped


def test_capture_on_sends_messages_query_and_outputs() -> None:
    """Criterio 5: con el interruptor viajan los mensajes, la consulta, los fragmentos y la
    respuesta."""
    tracer = FakeTracer(capture_content=True)
    _traced_llm_and_rag(tracer)
    failed, ok = tracer.spans("generation")
    assert ok.input == [{"role": m.role, "content": m.content} for m in MESSAGES]
    assert failed.input == ok.input and failed.output is None
    assert isinstance(ok.output, dict) and "text" in ok.output
    (retriever,) = tracer.spans("retriever")
    assert retriever.input == {"consulta": "renovar préstamos ficticios"}
    assert [o["id"] for o in retriever.output] == [
        f["id"] for f in retriever.metadata["fragmentos"]
    ]
    assert all(o["texto"] for o in retriever.output)


def test_capture_on_plain_text_generation_output_is_the_text() -> None:
    """Criterio 5: en `generate` (texto libre) la salida es el propio texto."""
    tracer = FakeTracer(capture_content=True)
    with operation(tracer, "crear"):
        result = _fallback(FakeLLMProvider()).generate(MESSAGES, TaskType.GENERATE_STORY)
    (gen,) = tracer.spans("generation")
    assert gen.output == result.content


def test_secret_mask_hides_configured_values_token_patterns_and_sensitive_keys() -> None:
    """Criterio 5: el enmascarado de las trazas es el de los logs."""
    mask = secret_mask([FICTITIOUS_KEY])
    data = {
        "texto": f"clave {FICTITIOUS_KEY} y Bearer abcdefghijklmnop123",
        "lista": [FICTITIOUS_KEY],
        "api_key": "cualquier-cosa-ficticia",
        "numero": 3,
    }
    masked = mask(data)
    assert masked == {
        "texto": "clave *** y ***",
        "lista": ["***"],
        "api_key": "***",
        "numero": 3,
    }
    assert mask(f"solo {FICTITIOUS_KEY}") == "solo ***"
    assert mask(None) is None


# --- Criterio 7: lentitud del fake --------------------------------------------------------------


@dataclass
class SlowFlushTracer(FakeTracer):
    """Solo `flush` es lento (el núcleo lo llama al cerrar cada operación)."""

    flush_delay_s: float = 0.0

    def flush(self) -> None:
        self.flushes += 1
        time.sleep(self.flush_delay_s)


def test_operation_body_is_not_delayed_by_tracer_steps() -> None:
    """Criterio 7 (núcleo): el trabajo de la operación no espera a la red; solo el `flush`
    del final depende del trazador (el adaptador real lo lanza en segundo plano)."""
    tracer = SlowFlushTracer(flush_delay_s=0.3)
    begin = time.monotonic()
    with operation(tracer, "crear"):
        inside = time.monotonic() - begin
    assert inside < 0.1
    assert tracer.flushes == 1
