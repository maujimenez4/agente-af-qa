"""Estado del proceso de la API (T-55): sesiones, espacios de trabajo y operaciones en curso.

- `Workspace`: contenedor, grafo y router de modelos de una sesión (RF-42). Los adaptadores y el
  checkpointer se comparten en el proceso (`build_session_container`).
- `Run`: lo que el proceso sabe de una conversación mientras trabaja (pasos terminados, error de
  la última operación). El estado de verdad está en el checkpointer y en `conversations`.
- `Runtime`: todo lo anterior más el ejecutor de las operaciones largas (respuestas 202).
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from adapters.base import AuthProvider, TaskType
from adapters.llm.router import ModelChoice, ModelRouter
from api.models import ErrorBody, Flow, Mode
from api.sessions import LoginLimiter, SessionStore
from core.config import Settings
from core.container import Container
from core.logging import get_logger
from core.usage import UsageQueries

log = get_logger("api.runtime")

Chains = dict[TaskType, list[ModelChoice]]


@dataclass
class Workspace:
    container: Container
    graph: CompiledStateGraph
    router: ModelRouter | None = None
    chains: Chains = field(default_factory=dict)  # cadenas configuradas (D-14)
    overrides: dict[TaskType, ModelChoice] = field(default_factory=dict)
    # T-47: registro de la ejecución (grafo propio, mismo checkpointer).
    execution_graph: CompiledStateGraph | None = None


WorkspaceFactory = Callable[[], Workspace]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Run:
    """Una conversación vista por este proceso (operación en curso y su resultado)."""

    thread_id: str
    owner: str
    flow: Flow
    mode: Mode
    project: str
    title: str
    operation: str | None = None  # start | iterate | approve | edit | discard
    running: bool = False
    nodes: list[str] = field(default_factory=list)  # nodos terminados en la operación
    error: ErrorBody | None = None
    seq: int = 0  # cambia con cada evento (SSE)
    updated_at: datetime = field(default_factory=_now)


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self.changed = threading.Condition(self._lock)

    def add(self, run: Run) -> Run:
        """Registra `run` o devuelve el que ya había: nunca hay dos por conversación (una
        operación a la vez, también con dos peticiones simultáneas tras reiniciar la API)."""
        with self._lock:
            return self._runs.setdefault(run.thread_id, run)

    def get(self, thread_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(thread_id)

    def begin(self, run: Run, operation: str) -> bool:
        """Marca la operación en curso; False si ya hay otra (una a la vez por conversación)."""
        with self._lock:
            if run.running:
                return False
            run.operation, run.running, run.nodes, run.error = operation, True, [], None
            self._bump(run)
            return True

    def node_done(self, run: Run, node: str) -> None:
        with self._lock:
            run.nodes.append(node)
            self._bump(run)

    def finish(self, run: Run, error: ErrorBody | None = None) -> None:
        with self._lock:
            run.running, run.error = False, error
            self._bump(run)

    def _bump(self, run: Run) -> None:
        run.seq += 1
        run.updated_at = _now()
        self.changed.notify_all()


@dataclass
class QualityJob:
    """Revisión de calidad (T-48) lanzada desde la API; solo lectura, en memoria (PA-103)."""

    id: str
    owner: str
    issue_key: str
    state: str = "running"  # running | done | error
    result: Any = None  # core.quality.QualityReview
    error: ErrorBody | None = None


@dataclass
class Runtime:
    settings: Settings
    auth: AuthProvider
    workspace_factory: WorkspaceFactory
    sessions: SessionStore[Workspace]
    limiter: LoginLimiter
    runs: RunRegistry = field(default_factory=RunRegistry)
    execution_runs: RunRegistry = field(default_factory=RunRegistry)  # T-47
    quality: dict[str, QualityJob] = field(default_factory=dict)
    quality_lock: threading.Lock = field(default_factory=threading.Lock)
    executor: ThreadPoolExecutor | None = None
    run_inline: bool = False  # pruebas: la operación termina antes de responder
    # PA-305: lectura de `llm_usage` (T-32) y umbral de aviso diario.
    usage: UsageQueries | None = None
    token_warning: int = 180_000

    def submit(self, fn: Callable[[], None]) -> None:
        if self.run_inline:
            fn()
            return
        if self.executor is None:
            self.executor = ThreadPoolExecutor(
                max_workers=self.settings.api_workers, thread_name_prefix="api-job"
            )
        self.executor.submit(fn)

    def shutdown(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)


def new_runtime(
    settings: Settings,
    auth: AuthProvider,
    workspace_factory: WorkspaceFactory,
    *,
    clock: Callable[[], float] | None = None,
) -> Runtime:
    clock_kwargs: dict[str, Any] = {"clock": clock} if clock else {}
    return Runtime(
        settings=settings,
        auth=auth,
        workspace_factory=workspace_factory,
        sessions=SessionStore(
            idle_s=settings.api_session_idle_minutes * 60,
            absolute_s=settings.api_session_max_hours * 3600,
            **clock_kwargs,
        ),
        limiter=LoginLimiter(
            max_attempts=settings.api_login_max_attempts,
            lock_s=settings.api_login_lock_seconds,
            **clock_kwargs,
        ),
    )


def build_runtime() -> Runtime:
    """Composición real: `.env`, `config/models.yaml`, PostgreSQL, Jira y Ollama.

    Un contenedor base y un checkpointer por proceso; un router y un grafo por sesión.
    """
    from core.config import build_config
    from core.container import bootstrap_logging
    from core.factories import (
        build_app_container,
        build_checkpointer,
        build_session_container,
        build_usage_recorder,
        model_router,
    )
    from core.graph import build_graph
    from core.graph.execution import build_execution_graph
    from core.usage import SqlUsageQueries

    config = build_config()
    bootstrap_logging(config)
    base = build_app_container(config)
    recorder = build_usage_recorder(config)  # consumo del LLM de todas las sesiones (T-32)
    checkpointer = build_checkpointer(config)
    chains: Chains = {
        task: [ModelChoice(r.provider, r.model) for r in config.task_chain(task)]
        for task in TaskType
    }

    def workspace() -> Workspace:
        router = model_router(config)
        container = build_session_container(config, base, router, recorder)
        graph = build_graph(container, checkpointer=checkpointer)
        return Workspace(
            container=container,
            graph=graph,
            router=router,
            chains=chains,
            execution_graph=build_execution_graph(container, checkpointer=checkpointer),
        )

    rt = new_runtime(config.settings, base.auth, workspace)
    rt.usage = SqlUsageQueries.from_url(config.settings.sqlalchemy_url())
    rt.token_warning = config.models.limits.daily_token_warning
    return rt
