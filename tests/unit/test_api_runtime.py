"""Composición por sesión, registro de operaciones y arranque de la API (T-55, parte 2).

- `core.factories.build_session_container`: un LLM propio por sesión (RF-42) sobre los
  adaptadores compartidos del proceso.
- `RunRegistry` (H1): nunca dos `Run` por conversación; una operación a la vez.
- `api.__main__`: un solo proceso y sin access log de uvicorn.

Solo fakes y datos ficticios; sin red ni `.env`.
"""

import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from adapters.base import Message, TaskType
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.router import ModelChoice, ModelRouter
from api import __main__ as api_main
from api import service
from api.errors import ApiError
from api.models import ConversationCreateIn
from api.runtime import Run, RunRegistry, Runtime
from core.config import AppConfig, Settings, load_models_config
from core.factories import build_session_container
from core.memory.generator import LLMMemoryGenerator
from tests.fakes import dataset
from tests.fakes.api import FAKE_CHAINS, fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement

TEST_MODELS = Path(__file__).resolve().parents[1] / "fixtures" / "models.yaml"
MESSAGES = [Message(role="user", content="Texto ficticio para clasificar.")]
EVOLVE = {"flow": "evolve", "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}}
SHARED = (
    "issue_tracker",
    "test_management",
    "embeddings",
    "vector_store",
    "auth",
    "approvals",
    "audit",
    "state_store",
    "last_projects",
    "conversations",
    "publish_mode",
    "require_actor",
    "memory_dir",
)


def _router() -> ModelRouter:
    def factory(choice: ModelChoice) -> FakeLLMProvider:
        return FakeLLMProvider(provider=choice.provider, model=choice.model)

    return ModelRouter(FAKE_CHAINS, factory, providers={"ollama": True})


@pytest.fixture
def config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    return AppConfig(Settings(_env_file=None), load_models_config(TEST_MODELS))


# --- build_session_container ----------------------------------------------------------------


def test_session_container_has_own_llm_and_memory_generator(
    tmp_path: Path, config: AppConfig
) -> None:
    """RF-42 / T-55: el contenedor de la sesión tiene su LLM y su generador de memoria."""
    base = fake_container(tmp_path)
    session = build_session_container(config, base, _router())
    assert session is not base
    assert isinstance(session.llm, FallbackLLMProvider) and session.llm is not base.llm
    assert isinstance(session.memory_generator, LLMMemoryGenerator)
    assert session.memory_generator is not base.memory_generator
    assert session.memory_generator._llm is session.llm


def test_session_container_shares_process_adapters(tmp_path: Path, config: AppConfig) -> None:
    """T-55: Jira, aprobaciones, estado y conversaciones se comparten con el contenedor base."""
    base = fake_container(tmp_path)
    session = build_session_container(config, base, _router())
    for name in SHARED:
        assert getattr(session, name) is getattr(base, name), name
    assert session.approvals.store is base.state_store


def test_session_override_only_affects_its_own_container(tmp_path: Path, config: AppConfig) -> None:
    """RF-42: el selector de modelo de una sesión no cambia el modelo de otra."""
    base = fake_container(tmp_path)
    router_a, router_b = _router(), _router()
    first = build_session_container(config, base, router_a)
    second = build_session_container(config, base, router_b)
    router_a.set_override(TaskType.CLASSIFY_SOURCE, ModelChoice("ollama", "modelo-ficticio-b"))
    assert first.llm.generate(MESSAGES, TaskType.CLASSIFY_SOURCE).model == "modelo-ficticio-b"
    assert second.llm.generate(MESSAGES, TaskType.CLASSIFY_SOURCE).model == "modelo-ficticio-a"
    base_llm = base.llm
    assert isinstance(base_llm, FakeLLMProvider) and base_llm.calls == []


# --- RunRegistry (H1) -----------------------------------------------------------------------


def _run(thread_id: str = "hilo-ficticio-1", owner: str = "af-demo") -> Run:
    return Run(
        thread_id=thread_id,
        owner=owner,
        flow="evolve",
        mode="functional",
        project="DEMO",
        title="Conversación ficticia",
    )


def test_run_registry_add_is_get_or_create() -> None:
    """H1: `add` dos veces con el mismo `thread_id` devuelve el primer `Run`."""
    registry = RunRegistry()
    first, second = _run(), _run()
    assert registry.add(first) is first
    assert registry.add(second) is first
    assert registry.get("hilo-ficticio-1") is first
    assert registry.add(_run("hilo-ficticio-2")) is not first


def test_run_registry_begin_allows_one_operation_at_a_time() -> None:
    """H1: `begin` falla mientras haya otra operación; `finish` la libera."""
    registry = RunRegistry()
    run = registry.add(_run())
    seq = run.seq
    assert registry.begin(run, "approve")
    assert not registry.begin(run, "iterate")
    assert run.operation == "approve" and run.running
    registry.finish(run)
    assert not run.running and run.seq > seq
    assert registry.begin(run, "iterate")


def test_run_registry_add_is_atomic_across_threads() -> None:
    """H1: con muchos hilos a la vez, todos reciben el mismo `Run`."""
    registry = RunRegistry()
    barrier = threading.Barrier(8)
    results: list[Run] = []

    def worker() -> None:
        barrier.wait()
        results.append(registry.add(_run()))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(results) == 8 and all(r is results[0] for r in results)


class HeldExecutor:
    """Ejecutor que guarda las tareas sin ejecutarlas: la operación sigue «en curso»."""

    def __init__(self) -> None:
        self.tasks: list[Callable[[], None]] = []

    def submit(self, fn: Callable[[], None]) -> None:
        self.tasks.append(fn)

    def shutdown(self, **_kw: Any) -> None:
        self.tasks.clear()


def _conversation_not_in_registry(tmp_path: Path) -> tuple[Runtime, Any, str, str]:
    """Conversación en revisión que este proceso no conoce (como tras reiniciar la API)."""
    rt = fake_runtime(tmp_path)
    session = rt.sessions.create(dataset.DEMO_USERS["af-demo"][1], rt.workspace_factory())
    ws, user = session.workspace, session.user
    run = service.create_conversation(rt, ws, user, ConversationCreateIn.model_validate(EVOLVE))
    out = service.conversation_out(rt, ws, user, run.thread_id)
    assert out.state == "in_review" and out.review is not None
    del rt.runs._runs[run.thread_id]
    rt.run_inline = False
    rt.executor = HeldExecutor()  # type: ignore[assignment]
    return rt, session, run.thread_id, out.review.fingerprint


def test_concurrent_approve_after_restart_only_one_begins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H1: dos `approve` simultáneos sobre una conversación sin `Run`: solo uno empieza."""
    rt, session, cid, fingerprint = _conversation_not_in_registry(tmp_path)
    barrier = threading.Barrier(2, timeout=5)
    real_pending = service._pending

    def synchronized_pending(*args: Any) -> Any:
        result = real_pending(*args)
        barrier.wait()  # los dos hilos pasan `_ensure_run` antes de que ninguno haga `begin`
        return result

    monkeypatch.setattr(service, "_pending", synchronized_pending)
    outcomes: list[Run | ApiError] = []
    answer = {"decision": "approve", "fingerprint": fingerprint}

    def approve() -> None:
        try:
            outcomes.append(
                service.resume(rt, session.workspace, session.user, cid, "approve", answer)
            )
        except ApiError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    runs = [o for o in outcomes if isinstance(o, Run)]
    errors = [o for o in outcomes if isinstance(o, ApiError)]
    assert len(runs) == 1 and len(errors) == 1, outcomes
    assert (errors[0].status, errors[0].code) == (409, "not_in_review")
    assert rt.runs.get(cid) is runs[0]
    assert len(rt.executor.tasks) == 1  # type: ignore[union-attr]
    tracker = session.workspace.container.issue_tracker
    testmgmt = session.workspace.container.test_management
    assert isinstance(tracker, FakeIssueTracker) and tracker.writes == []
    assert isinstance(testmgmt, FakeTestManagement) and testmgmt.publish_calls == 0


def test_resume_reuses_existing_run_when_registry_already_has_it(tmp_path: Path) -> None:
    """H1: `_ensure_run` devuelve el `Run` ya registrado (no crea otro)."""
    rt, session, cid, _fp = _conversation_not_in_registry(tmp_path)
    service.resume(rt, session.workspace, session.user, cid, "iterate", service.iterate_answer("x"))
    first = rt.runs.get(cid)
    assert first is not None and first.running
    with pytest.raises(ApiError) as info:
        service.resume(
            rt, session.workspace, session.user, cid, "iterate", service.iterate_answer("y")
        )
    assert info.value.code == "not_in_review"
    assert rt.runs.get(cid) is first


# --- api/__main__ ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "host", "port"),
    [([], "127.0.0.1", 8000), (["--host", "0.0.0.0", "--port", "9001"], "0.0.0.0", 9001)],  # noqa: S104
    ids=["por-defecto", "con-argumentos"],
)
def test_main_runs_single_worker_without_access_log(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], host: str, port: int
) -> None:
    """Req. 13 y 14: `python -m api` arranca uvicorn con un proceso y sin access log."""
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(sys, "argv", ["api", *argv])
    api_main.main()
    assert calls == [
        (("api.app:app",), {"host": host, "port": port, "workers": 1, "access_log": False})
    ]


def test_main_rejects_non_numeric_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Req. 14 (error): un puerto no numérico no arranca el servidor."""
    calls: list[Any] = []
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(sys, "argv", ["api", "--port", "ochenta"])
    with pytest.raises(SystemExit):
        api_main.main()
    assert calls == []
