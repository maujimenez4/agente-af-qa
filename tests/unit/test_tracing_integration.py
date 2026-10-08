"""Trazas de punta a punta (T-40 · RNF-24 · DT-09): composición, API, UI de Streamlit y MCP.

`fake_runtime` con un `FakeTracer` en el contenedor, el LLM de la app (`FallbackLLMProvider`
con `LLMTraceObserver`) y el vector store envuelto en `TracingVectorStore`, como en
`core/factories.build_app_container`. Sin red, sin `.env` y con datos 100 % ficticios.
"""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from adapters.base import IssueSummary, TaskType
from adapters.errors import RateLimitError
from adapters.llm.fallback import FallbackLLMProvider
from api.runtime import Runtime
from app.conversation import Conversation, Workspace, resume, run_start, start
from app.origin import fix_origin
from app.review import approve_answer, iterate_answer
from core import factories, tracing
from core.config import ROOT_DIR, AppConfig, Settings, load_models_config
from core.container import Container
from core.graph import build_graph, memory_checkpointer
from core.tracing import PAUSED, LLMTraceObserver, NullTracer, TracingVectorStore
from mcp_server.server import review_quality
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.tracer import FakeSpan, FakeTracer
from tests.fixtures import MODELS_FIXTURE
from tests.unit.test_api_app import AF, EVOLVE, NEED, QA, TESTS, Api

PUBLIC = "pk-lf-ficticia-composicion"
PRIVATE = "sk-lf-ficticia-composicion"
AF_USER = dataset.DEMO_USERS["af-demo"][1]
CASES = [
    IssueSummary(key="DEMO-501", summary="[CP-01] Caso ficticio", issue_type="Subtarea", status="")
]
CONVERSATION_NODES = ["load_origin", "retrieve_context", "generate", "human_review"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin variables `LANGFUSE_*` del entorno y con el estado de proceso de las trazas limpio."""
    for name in list(os.environ):
        if name.upper().startswith("LANGFUSE_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(tracing, "_WARNED", set())
    monkeypatch.setattr(factories, "_TRACER_LOGGED", False)
    monkeypatch.setattr(factories, "_TRACERS", {})


def _app_llm(inner: FakeLLMProvider | None = None) -> FallbackLLMProvider:
    """El LLM de la app: cadena de respaldo con el observador de trazas."""
    provider = inner or FakeLLMProvider(provider="ollama", model="modelo-ficticio-a")
    return FallbackLLMProvider(lambda _task: [provider], observer=LLMTraceObserver())


def _traced_container(tmp_path: Path, tracer: Any, **overrides: Any) -> Container:
    overrides.setdefault("llm", _app_llm())
    base = fake_container(
        tmp_path, require_actor=True, publish_mode="simulation", tracer=tracer, **overrides
    )
    return replace(base, vector_store=TracingVectorStore(base.vector_store))


def _runtime(tmp_path: Path, tracer: Any, **overrides: Any) -> Runtime:
    rt = fake_runtime(tmp_path, container=_traced_container(tmp_path, tracer, **overrides))
    tm = rt.workspace_factory().container.test_management
    assert isinstance(tm, FakeTestManagement)
    tm.cases["DEMO-3"] = list(CASES)
    return rt


def _login(rt: Runtime, who: tuple[str, str] = AF) -> Api:
    api = Api(rt)
    assert api.login(who).status_code == 200
    return api


def _steps(trace: FakeSpan) -> list[str]:
    return [s.name for s in trace.children if s.kind == "span"]


def _child(trace: FakeSpan, name: str) -> FakeSpan:
    return next(s for s in trace.children if s.name == name)


# --- Criterio 1: composición sin claves --------------------------------------------------------


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class LangfuseNotAllowed:
    """Si alguien construye el cliente de Langfuse, la prueba falla."""

    calls = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).calls += 1
        raise AssertionError("No debe construirse el cliente de Langfuse")


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"langfuse_public_key": "", "langfuse_secret_key": ""},
        {"langfuse_public_key": PUBLIC},
        {"langfuse_secret_key": PRIVATE},
        {"langfuse_public_key": PUBLIC, "langfuse_secret_key": ""},
        {"langfuse_public_key": "", "langfuse_secret_key": PRIVATE},
    ],
    ids=["sin_claves", "vacias", "solo_publica", "solo_privada", "privada_vacia", "publica_vacia"],
)
def test_build_tracer_without_both_keys_is_null_tracer(
    values: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterio 1: sin las dos claves (o vacías) → `NullTracer`, sin construir el cliente."""
    import adapters.observability.langfuse as adapter

    LangfuseNotAllowed.calls = 0
    monkeypatch.setattr(adapter, "Langfuse", LangfuseNotAllowed)
    tracer = factories.build_tracer(_settings(**values))
    assert isinstance(tracer, NullTracer) and tracer.enabled is False
    assert LangfuseNotAllowed.calls == 0
    assert factories._TRACERS == {}


@pytest.mark.parametrize(
    "host",
    ["http://langfuse.ejemplo.invalid", "ftp://cloud.langfuse.com", "cloud.langfuse.com"],
)
def test_build_tracer_rejects_host_without_https(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """security-reviewer: las claves viajan en cada envío; sin `https` (salvo local), nada."""
    import adapters.observability.langfuse as adapter

    LangfuseNotAllowed.calls = 0
    monkeypatch.setattr(adapter, "Langfuse", LangfuseNotAllowed)
    values = {"langfuse_public_key": PUBLIC, "langfuse_secret_key": PRIVATE, "langfuse_host": host}
    with capture_logs() as logs:
        tracer = factories.build_tracer(_settings(**values))
    assert isinstance(tracer, NullTracer) and LangfuseNotAllowed.calls == 0
    assert any("https" in e["event"] for e in logs)


@pytest.mark.parametrize("host", ["https://cloud.langfuse.com", "http://localhost:3000"])
def test_build_tracer_accepts_https_or_local_host(host: str) -> None:
    assert factories._secure_host(host)


def test_build_tracer_logs_disabled_only_once() -> None:
    """Criterio 1: el aviso «desactivadas» sale una sola vez por proceso."""
    with capture_logs() as logs:
        for _ in range(3):
            factories.build_tracer(_settings())
    disabled = [e for e in logs if "desactivadas" in e["event"]]
    assert len(disabled) == 1
    assert disabled[0]["action"] == "tracing" and disabled[0]["log_level"] == "info"


def test_build_tracer_without_keys_does_not_import_langfuse(tmp_path: Path) -> None:
    """Criterio 1: sin claves ni siquiera se importa el SDK (ni se llama a la red)."""
    code = (
        "import sys\n"
        "from core.config import Settings\n"
        "from core.factories import build_tracer\n"
        "tracer = build_tracer(Settings(_env_file=None))\n"
        "assert type(tracer).__name__ == 'NullTracer'\n"
        "assert 'langfuse' not in sys.modules, 'langfuse importado'\n"
        "assert 'adapters.observability.langfuse' not in sys.modules\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("LANGFUSE_")}
    env["PYTHONPATH"] = str(ROOT_DIR)
    done = subprocess.run(  # noqa: S603 - intérprete y código fijos de la prueba
        [sys.executable, "-c", code],
        cwd=tmp_path,  # sin `.env` en el directorio de trabajo
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]


def test_container_defaults_to_null_tracer(tmp_path: Path) -> None:
    """Criterio 1: el contenedor sin trazador explícito usa `NullTracer`."""
    assert isinstance(fake_container(tmp_path).tracer, NullTracer)
    tracer = FakeTracer()
    assert fake_container(tmp_path, tracer=tracer).tracer is tracer


def test_api_without_tracer_works_and_creates_nothing(tmp_path: Path) -> None:
    """Criterio 1: la API sin trazas (NullTracer) funciona igual."""
    rt = fake_runtime(tmp_path)
    api = _login(rt)
    assert api.post("/conversations", NEED).json()["state"] == "in_review"


# --- Composición con claves --------------------------------------------------------------------


class RecordingLangfuseTracer:
    """Sustituye al adaptador real en las pruebas de composición (sin SDK ni red)."""

    built: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        type(self).built.append(kwargs)
        self.kwargs = kwargs
        self.enabled = True
        self.capture_content = kwargs["capture_content"]

    def shutdown(self) -> None:
        return None


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    import adapters.observability.langfuse as adapter

    RecordingLangfuseTracer.built = []
    monkeypatch.setattr(adapter, "LangfuseTracer", RecordingLangfuseTracer)
    registered: list[Any] = []
    monkeypatch.setattr(factories.atexit, "register", registered.append)
    return registered


def _keyed(**values: Any) -> Settings:
    base: dict[str, Any] = {
        "langfuse_public_key": PUBLIC,
        "langfuse_secret_key": PRIVATE,
        "groq_api_key": "valorficticio-groq-3c9d1f0b",
    }
    return _settings(**(base | values))


def test_build_tracer_with_keys_builds_one_langfuse_tracer_per_configuration(
    recording: list[Any],
) -> None:
    """Criterio 1 (positivo): con las dos claves, un `LangfuseTracer` por proceso y config."""
    first = factories.build_tracer(_keyed())
    again = factories.build_tracer(_keyed())
    other = factories.build_tracer(_keyed(langfuse_capture_content=True))
    assert isinstance(first, RecordingLangfuseTracer)
    assert again is first and other is not first
    assert len(RecordingLangfuseTracer.built) == 2
    kwargs = RecordingLangfuseTracer.built[0]
    assert kwargs["public_key"].get_secret_value() == PUBLIC
    assert kwargs["secret_key"].get_secret_value() == PRIVATE
    assert kwargs["host"] == "https://cloud.langfuse.com"
    assert kwargs["capture_content"] is False
    assert kwargs["mask"]("x valorficticio-groq-3c9d1f0b") == "x ***"
    assert recording == [first.shutdown, other.shutdown]  # envío pendiente al salir


def test_build_tracer_uses_configured_host(recording: list[Any]) -> None:
    """Configuración: `LANGFUSE_HOST` llega al adaptador."""
    factories.build_tracer(_keyed(langfuse_host="http://127.0.0.1:9"))
    assert RecordingLangfuseTracer.built[0]["host"] == "http://127.0.0.1:9"


def test_settings_langfuse_defaults() -> None:
    """Configuración: host de la UE y contenido desactivado por defecto; claves secretas."""
    settings = _keyed()
    assert _settings().langfuse_host == "https://cloud.langfuse.com"
    assert _settings().langfuse_capture_content is False
    assert isinstance(settings.langfuse_public_key, SecretStr)
    assert PUBLIC in settings.secret_values() and PRIVATE in settings.secret_values()
    assert PRIVATE not in repr(settings)


def test_build_tracer_falls_back_to_null_when_sdk_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterio 7: si el SDK no arranca, `NullTracer` y un aviso con el tipo (nunca la clave)."""
    import adapters.observability.langfuse as adapter

    def broken(**_kwargs: Any) -> Any:
        raise RuntimeError(f"fallo ficticio {PRIVATE}")

    monkeypatch.setattr(adapter, "LangfuseTracer", broken)
    with capture_logs() as logs:
        tracer = factories.build_tracer(_keyed())
    assert isinstance(tracer, NullTracer)
    assert logs[0]["error"] == "RuntimeError"
    assert PRIVATE not in repr(logs)


def test_build_llm_provider_attaches_trace_observer() -> None:
    """Criterio 3: el LLM de la app lleva el observador de trazas."""
    config = AppConfig(_settings(), load_models_config(MODELS_FIXTURE))
    provider = factories.build_llm_provider(
        config, provider_factory=lambda _choice: FakeLLMProvider()
    )
    assert isinstance(provider._observer, LLMTraceObserver)


def test_build_app_container_wraps_vector_store_and_sets_tracer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterio 2: el contenedor de la app envuelve el vector store y lleva `build_tracer`."""
    for name in (
        "build_issue_tracker",
        "build_llm_provider",
        "build_embeddings",
        "build_auth",
        "build_audit",
        "build_versions",
        "build_state_store",
        "build_last_projects",
        "build_conversations",
        "build_test_management",
    ):
        monkeypatch.setattr(factories, name, lambda *a, **k: object())
    inner = object()
    monkeypatch.setattr(factories, "build_vector_store", lambda *_a, **_k: inner)
    sentinel = FakeTracer()
    monkeypatch.setattr(factories, "build_tracer", lambda _settings: sentinel)
    monkeypatch.setattr("core.container.bootstrap_logging", lambda _config: None)
    config = AppConfig(_settings(), load_models_config(MODELS_FIXTURE))

    container = factories.build_app_container(config)

    assert isinstance(container.vector_store, TracingVectorStore)
    assert container.vector_store._inner is inner
    assert container.tracer is sentinel


# --- Criterio 2: de punta a punta por la API ---------------------------------------------------


def test_create_story_leaves_one_trace_with_steps_generations_and_retrieval(
    tmp_path: Path,
) -> None:
    """Criterio 2: crear una HU → traza con sesión = conversación, persona, etiquetas, un paso
    por nodo real (human_review pausado), generation con tokens bajo `generate` y retriever."""
    tracer = FakeTracer()
    rt = _runtime(tmp_path, tracer)
    conv = _login(rt).post("/conversations", NEED).json()
    assert conv["state"] == "in_review", conv

    (trace,) = tracer.traces
    assert trace.name == "crear"
    assert trace.trace == {
        "session_id": conv["id"],
        "user_id": "af-demo",
        "tags": ["modo:functional", "flujo:need", "proyecto:DEMO"],
    }
    assert _steps(trace) == CONVERSATION_NODES
    review = _child(trace, "human_review")
    assert review.status == PAUSED and review.metadata["estado"] == "pausado"
    assert review.level is None
    assert all(s.ended for s in tracer.spans())
    assert trace.level is None and trace.status is None

    (retriever,) = _child(trace, "retrieve_context").children
    assert retriever.kind == "retriever" and retriever.metadata["devueltos"] > 0

    generations = _child(trace, "generate").children
    assert [g.kind for g in generations] == ["generation"]
    (gen,) = generations
    assert gen.metadata["tarea"] == TaskType.GENERATE_STORY.value
    assert gen.metadata["proveedor"] == "ollama" and gen.model == "modelo-ficticio-a"
    assert gen.metadata["prompt"] == "generate_story" and gen.metadata["prompt_version"]
    assert gen.usage is not None and gen.usage["input"] > 0 and gen.usage["output"] > 0
    assert gen.cost == {"total": 0.0}
    assert tracer.flushes >= 1


def test_evolve_trace_has_evolve_flow_tag(tmp_path: Path) -> None:
    """Criterio 2: la etiqueta de flujo sigue a la petición."""
    tracer = FakeTracer()
    _login(_runtime(tmp_path, tracer)).post("/conversations", EVOLVE)
    assert "flujo:evolve" in tracer.traces[0].trace["tags"]


def test_iterate_and_approve_leave_their_own_traces(tmp_path: Path) -> None:
    """Criterio 2: iterar y aprobar (simulación) dejan su traza en la misma sesión."""
    tracer = FakeTracer()
    rt = _runtime(tmp_path, tracer)
    api = _login(rt)
    conv = api.post("/conversations", NEED).json()
    cid = conv["id"]
    iterated = api.post(f"/conversations/{cid}/iterate", {"feedback": "Cambio ficticio."}).json()
    assert iterated["state"] == "in_review"
    approved = api.post(
        f"/conversations/{cid}/approve", {"fingerprint": iterated["review"]["fingerprint"]}
    ).json()
    assert approved["state"] == "simulated", approved

    names = [t.name for t in tracer.traces]
    assert names == ["crear", "iterar", "aprobar"]
    assert {t.trace["session_id"] for t in tracer.traces} == {cid}
    iterate, approve = tracer.traces[1:]
    assert "generate" in _steps(iterate) and _steps(iterate)[-1] == "human_review"
    assert any(s.kind == "generation" for s in iterate.walk())
    assert "publish" in _steps(approve)
    assert all(t.level is None for t in tracer.traces)


def test_retry_leaves_reintentar_trace_and_failed_create_is_error(tmp_path: Path) -> None:
    """Criterio 2 y 3: la creación que falla (429) deja su generation en ERROR; reintentar deja
    su traza «reintentar» con la generation correcta."""
    tracer = FakeTracer()
    inner = FakeLLMProvider(
        provider="ollama",
        model="modelo-ficticio-a",
        error=RateLimitError("Límite ficticio.", "llm", 1),
    )
    rt = _runtime(tmp_path, tracer, llm=_app_llm(inner))
    api = _login(rt)
    conv = api.post("/conversations", NEED).json()
    assert conv["state"] == "error", conv
    inner.error = None
    retried = api.post(f"/conversations/{conv['id']}/retry").json()
    assert retried["state"] == "in_review", retried

    create, retry = tracer.traces
    assert (create.name, retry.name) == ("crear", "reintentar")
    failed = next(s for s in create.walk() if s.kind == "generation")
    assert failed.level == "ERROR" and failed.metadata["motivo"] == "limite"
    assert _child(create, "generate").level == "ERROR"
    ok = next(s for s in retry.walk() if s.kind == "generation")
    assert ok.level is None and ok.usage and ok.usage["output"] > 0
    assert "load_origin" not in _steps(retry)


def test_quality_review_leaves_revisar_calidad_trace(tmp_path: Path) -> None:
    """Criterio 2: la revisión de calidad deja su traza con su sesión y una generation."""
    tracer = FakeTracer()
    rt = _runtime(tmp_path, tracer)
    created = _login(rt).post("/quality-reviews", {"issue_key": "DEMO-3"}).json()

    (trace,) = tracer.traces
    assert trace.name == "revisar_calidad"
    assert trace.trace == {
        "session_id": created["id"],
        "user_id": "af-demo",
        "tags": ["modo:functional", "flujo:review", "proyecto:DEMO"],
    }
    gens = [s for s in trace.walk() if s.kind == "generation"]
    review = next(g for g in gens if g.metadata["tarea"] == TaskType.REVIEW_STORY.value)
    assert review.metadata["prompt"] == "review_quality" and review.usage


def test_execution_record_leaves_traces_for_create_save_and_approve(tmp_path: Path) -> None:
    """Criterio 2: el registro de la ejecución deja una traza por operación."""
    tracer = FakeTracer()
    rt = _runtime(tmp_path, tracer)
    qa = _login(rt, QA)
    created = qa.post("/executions", {"story_key": "DEMO-3"}).json()
    eid = created["id"]
    saved = qa.put(
        f"/executions/{eid}/results",
        {"results": [{"case_key": "DEMO-501", "status": "paso", "evidence_md": ""}]},
    ).json()
    qa.post(f"/executions/{eid}/approve", {"fingerprint": saved["fingerprint"]})

    names = [t.name for t in tracer.traces]
    assert names == ["ejecucion · crear", "ejecucion · guardar", "ejecucion · aprobar"]
    first = tracer.traces[0]
    assert first.trace == {
        "session_id": eid,
        "user_id": "qa-demo",
        "tags": ["modo:qa", "flujo:execution", "proyecto:DEMO"],
    }
    assert _steps(first) == ["load_cases", "review"]
    assert _child(first, "review").status == PAUSED
    assert {t.trace["session_id"] for t in tracer.traces} == {eid}
    assert "publish" in _steps(tracer.traces[2])


# --- Criterio 5: interruptor en la API ---------------------------------------------------------


def test_api_capture_off_sends_no_text_in_any_span(tmp_path: Path) -> None:
    """Criterio 5: sin interruptor, ni `input` ni `output` en ningún paso de la API."""
    tracer = FakeTracer(capture_content=False)
    rt = _runtime(tmp_path, tracer)
    api = _login(rt)
    conv = api.post("/conversations", NEED).json()
    api.post(f"/conversations/{conv['id']}/iterate", {"feedback": "Cambio ficticio."})
    spans = tracer.spans()
    assert {s.kind for s in spans} == {"span", "generation", "retriever"}
    assert all(s.input is None and s.output is None for s in spans)
    dumped = repr([s.metadata for s in spans])
    assert "Avisar del vencimiento" not in dumped and "Cambio ficticio" not in dumped


def test_api_capture_on_sends_prompts_context_and_answers(tmp_path: Path) -> None:
    """Criterio 5: con interruptor viajan los mensajes, la consulta y la respuesta."""
    tracer = FakeTracer(capture_content=True)
    rt = _runtime(tmp_path, tracer)
    _login(rt).post("/conversations", NEED)
    (gen,) = tracer.spans("generation")
    assert gen.input and any("Avisar del vencimiento" in m["content"] for m in gen.input)
    assert gen.output
    (retriever,) = tracer.spans("retriever")
    assert retriever.input and retriever.output


# --- Criterio 7: el trazador caído no cambia nada ----------------------------------------------


class SpansDownTracer(FakeTracer):
    """La traza se crea pero luego todo falla (pasos, generations, cierre y flush)."""

    def start_trace(self, name: str, **kwargs: Any) -> FakeSpan:
        self.fail = False
        try:
            return super().start_trace(name, **kwargs)
        finally:
            self.fail = True


def _final_state(tmp_path: Path, tracer: Any) -> tuple[dict[str, Any], str]:
    rt = _runtime(tmp_path, tracer)
    api = _login(rt)
    conv = api.post("/conversations", NEED).json()
    iterated = api.post(f"/conversations/{conv['id']}/iterate", {"feedback": "Cambio ficticio."})
    body = iterated.json()
    return {
        "state": body["state"],
        "version": body["review"]["version"],
        "error": body["error"],
        "title": body["review"]["artifact"]["content"]["title"],
    }, iterated.text


@pytest.mark.parametrize(
    "broken", [FakeTracer(fail=True), SpansDownTracer()], ids=["caido", "pasos_caidos"]
)
def test_api_operation_is_identical_when_tracer_is_down(tmp_path: Path, broken: Any) -> None:
    """Criterio 7: con Langfuse caído la API termina igual y el error no llega al usuario."""
    expected, _ = _final_state(tmp_path / "sano", NullTracer())
    with capture_logs() as logs:
        got, text = _final_state(tmp_path / "caido", broken)
    assert got == expected
    assert "TracerDown" not in text and "Langfuse" not in text
    warnings = [e for e in logs if e["event"] == "traza no registrada"]
    assert warnings and all(e["error"] == "TracerDown" for e in warnings)
    assert len({e["action"] for e in warnings}) == len(warnings)  # una vez por tipo


def test_quality_review_is_identical_when_tracer_is_down(tmp_path: Path) -> None:
    """Criterio 7: la revisión de calidad termina en `done` con Langfuse caído."""
    rt = _runtime(tmp_path, FakeTracer(fail=True))
    api = _login(rt)
    created = api.post("/quality-reviews", {"issue_key": "DEMO-3"}).json()
    detail = api.get(f"/quality-reviews/{created['id']}").json()
    assert detail["state"] == "done" and detail["error"] is None


# --- Criterio 8: cierre ------------------------------------------------------------------------


def test_runtime_shutdown_calls_tracer_shutdown(tmp_path: Path) -> None:
    """Criterio 8: `Runtime.shutdown()` envía lo pendiente del trazador."""
    rt = fake_runtime(tmp_path)
    assert isinstance(rt.tracer, NullTracer)
    tracer = FakeTracer()
    rt.tracer = tracer
    rt.shutdown()
    assert tracer.shutdowns == 1


def test_runtime_shutdown_with_default_null_tracer_does_not_fail(tmp_path: Path) -> None:
    """Criterio 8 (límite): sin trazas configuradas, cerrar no falla."""
    fake_runtime(tmp_path).shutdown()


# --- UI de Streamlit (app/conversation) --------------------------------------------------------


def _ws(tmp_path: Path, tracer: FakeTracer) -> Workspace:
    container = fake_container(tmp_path, tracer=tracer, llm=_app_llm())
    return Workspace(container=container, graph=build_graph(container, memory_checkpointer()))


def test_streamlit_start_iterate_approve_leave_traces(tmp_path: Path) -> None:
    """Criterio 2: la UI de Streamlit deja crear, iterar y aprobar con sesión = hilo."""
    tracer = FakeTracer()
    ws = _ws(tmp_path, tracer)
    request = fix_origin("need", "DEMO", text="Avisar del vencimiento (ficticio).")
    conv = Conversation(request=request, user=AF_USER.username)
    run_start(ws, conv)
    assert conv.error is None and conv.view is not None
    resume(ws, conv, iterate_answer("Cambio ficticio."))
    assert conv.view is not None
    resume(ws, conv, approve_answer(conv.view), actor=AF_USER)
    assert conv.error is None, conv.error

    assert [t.name for t in tracer.traces] == ["crear", "iterar", "aprobar"]
    first = tracer.traces[0]
    assert first.trace["session_id"] == conv.thread_id
    assert first.trace["user_id"] == AF_USER.username
    assert first.trace["tags"] == ["modo:functional", "flujo:need", "proyecto:DEMO"]
    assert _steps(first) == CONVERSATION_NODES


def test_streamlit_abandoned_progress_ends_trace_with_warning(tmp_path: Path) -> None:
    """Criterio 2: si la UI abandona el progreso, la traza termina en WARNING, no en ERROR."""
    tracer = FakeTracer()
    ws = _ws(tmp_path, tracer)
    conv = Conversation(
        request=fix_origin("need", "DEMO", text="Texto ficticio."), user=AF_USER.username
    )
    progress = start(ws, conv)
    assert next(progress) == "load_origin"
    progress.close()
    (trace,) = tracer.traces
    assert trace.level == "WARNING" and trace.status == "GeneratorExit"


# --- MCP ----------------------------------------------------------------------------------------


def test_mcp_review_quality_leaves_trace(tmp_path: Path) -> None:
    """Criterio 2: la herramienta MCP de calidad deja su traza (modo mcp, flujo review)."""
    tracer = FakeTracer()
    container = fake_container(tmp_path, publish_mode="simulation", tracer=tracer, llm=_app_llm())
    review_quality(container, AF_USER, "DEMO-3")
    (trace,) = tracer.traces
    assert trace.name == "revisar_calidad"
    assert trace.trace == {
        "session_id": None,
        "user_id": AF_USER.username,
        "tags": ["modo:mcp", "flujo:review", "proyecto:DEMO"],
    }
    assert any(s.kind == "generation" for s in trace.walk())


def test_qa_tests_flow_trace_has_qa_tags_and_generate_tests_generation(tmp_path: Path) -> None:
    """Criterio 2: la operación de QA (flujo `tests`) deja su traza con modo qa."""
    tracer = FakeTracer()
    conv = _login(_runtime(tmp_path, tracer), QA).post("/conversations", TESTS).json()
    assert conv["state"] == "in_review", conv
    (trace,) = tracer.traces
    assert trace.name == "crear" and trace.trace["session_id"] == conv["id"]
    assert trace.trace["tags"] == ["modo:qa", "flujo:tests", "proyecto:DEMO"]
    tasks = {s.metadata["tarea"] for s in trace.walk() if s.kind == "generation"}
    assert TaskType.GENERATE_TESTS.value in tasks


# --- Etiqueta de proyecto (defectos corregidos tras test-writer) -------------------------------


def test_execution_resume_traces_keep_project_tag(tmp_path: Path) -> None:
    """Criterio 2: toda operación lleva las etiquetas modo, flujo y proyecto (también las que
    reanudan el registro de la ejecución)."""
    tracer = FakeTracer()
    qa = _login(_runtime(tmp_path, tracer), QA)
    eid = qa.post("/executions", {"story_key": "DEMO-3"}).json()["id"]
    qa.put(
        f"/executions/{eid}/results",
        {"results": [{"case_key": "DEMO-501", "status": "paso", "evidence_md": ""}]},
    )
    qa.post(f"/executions/{eid}/discard")
    assert [t.name for t in tracer.traces][1:] == ["ejecucion · guardar", "ejecucion · descartar"]
    for trace in tracer.traces:
        assert "proyecto:DEMO" in trace.trace["tags"], (trace.name, trace.trace["tags"])


def test_mcp_review_quality_trace_has_project_tag(tmp_path: Path) -> None:
    """Criterio 2: la traza de la herramienta MCP también lleva la etiqueta de proyecto."""
    tracer = FakeTracer()
    container = fake_container(tmp_path, publish_mode="simulation", tracer=tracer, llm=_app_llm())
    review_quality(container, AF_USER, "DEMO-3")
    assert "proyecto:DEMO" in tracer.traces[0].trace["tags"]
