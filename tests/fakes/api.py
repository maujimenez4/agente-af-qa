"""Runtime de la API (T-55) con los fakes: sin `.env`, sin PostgreSQL, sin Jira ni LLM reales.

Un contenedor y un checkpointer en memoria compartidos por todas las sesiones (como en la API
real); cada sesión tiene su grafo y su router. `run_inline=True` hace que las operaciones
largas terminen antes de responder, para que las pruebas sean deterministas.
"""

from pathlib import Path
from typing import Any

from adapters.base import TaskType
from adapters.llm.router import ModelChoice, ModelRouter
from api.runtime import Runtime, Workspace, new_runtime
from core.config import Settings
from core.container import Container
from core.graph import build_graph, memory_checkpointer
from core.graph.execution import build_execution_graph
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider

FAKE_CHAINS: dict[TaskType, list[ModelChoice]] = {
    task: [ModelChoice("ollama", "modelo-ficticio-a"), ModelChoice("ollama", "modelo-ficticio-b")]
    for task in TaskType
}


def api_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"app_env": "development", "jira_publish_mode": "simulation"}
    return Settings(_env_file=None, **(values | overrides))  # type: ignore[call-arg]


def fake_runtime(
    tmp_path: Path,
    *,
    container: Container | None = None,
    settings: Settings | None = None,
    run_inline: bool = True,
    **container_overrides: object,
) -> Runtime:
    # Como la app: simulación por defecto; las pruebas de publicación real pasan `publish_mode`.
    container_overrides.setdefault("publish_mode", "simulation")
    base = container or fake_container(tmp_path, require_actor=True, **container_overrides)
    checkpointer = memory_checkpointer()

    def workspace() -> Workspace:
        router = ModelRouter(FAKE_CHAINS, lambda _c: FakeLLMProvider(), providers={"ollama": True})
        graph = build_graph(base, checkpointer=checkpointer)
        chains = {task: list(chain) for task, chain in FAKE_CHAINS.items()}
        return Workspace(
            container=base,
            graph=graph,
            router=router,
            chains=chains,
            execution_graph=build_execution_graph(base, checkpointer=checkpointer),
        )

    rt = new_runtime(settings or api_settings(), base.auth, workspace)
    rt.run_inline = run_inline
    return rt
