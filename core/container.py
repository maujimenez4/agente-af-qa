"""Raíz de composición: decide qué implementación de cada protocolo usa la aplicación.

El núcleo solo recibe un `Container` con protocolos de `adapters/base.py`. Los adaptadores
reales (Jira, LLM, pgvector…) se conectan aquí a partir del día 2; hasta entonces las
dependencias se inyectan explícitamente (en las pruebas, con los fakes de `tests/fakes/`).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from adapters.base import (
    AuthProvider,
    EmbeddingProvider,
    IssueTracker,
    LLMProvider,
    MemoryGenerator,
    TestManagement,
    VectorStore,
)
from core.approvals import ApprovalLedger
from core.artifact_state import ArtifactStateStore, InMemoryArtifactStateStore
from core.audit import AuditTrail, InMemoryAuditTrail
from core.config import ROOT_DIR, AppConfig, ConfigError
from core.conversations import ConversationStore, InMemoryConversationStore
from core.logging import configure_logging
from core.projects import InMemoryLastProjectStore, LastProjectStore, ProjectService
from schemas.artifact import Artifact

DEFAULT_MEMORY_DIR = ROOT_DIR / "data" / "memory"
DEFAULT_TOP_K = 6
PublishMode = Literal["simulation", "live"]


class VersionSink(Protocol):
    """Guarda cada versión de un artefacto (`core/impact/versions.StoryVersionStore`, T-19)."""

    def save(self, artifact: Artifact) -> None: ...
    def update_status(
        self, artifact_id: UUID, status: str, jira_key: str | None = None
    ) -> None: ...


@dataclass(frozen=True)
class Container:
    issue_tracker: IssueTracker
    test_management: TestManagement
    llm: LLMProvider
    embeddings: EmbeddingProvider
    vector_store: VectorStore
    memory_generator: MemoryGenerator
    auth: AuthProvider
    config: AppConfig | None = None
    memory_dir: Path = DEFAULT_MEMORY_DIR
    approvals: ApprovalLedger = field(default_factory=ApprovalLedger)
    # T-25: auditoría, versiones y estado persistente; en memoria si no se inyectan.
    audit: AuditTrail = field(default_factory=InMemoryAuditTrail)
    versions: VersionSink | None = None
    state_store: ArtifactStateStore = field(default_factory=InMemoryArtifactStateStore)
    publish_mode: PublishMode = "simulation"
    # T-50: último proyecto de Jira usado por cada persona.
    last_projects: LastProjectStore = field(default_factory=InMemoryLastProjectStore)
    # T-52: lista de conversaciones por usuario (el estado vive en el checkpointer).
    conversations: ConversationStore = field(default_factory=InMemoryConversationStore)
    # T-52: en la app, toda invocación del grafo lleva `configurable.user` (si falta, falla).
    require_actor: bool = False

    def __post_init__(self) -> None:
        # El registro de aprobaciones persiste en el mismo almacén de estado del contenedor.
        if self.approvals.store is None:
            self.approvals.store = self.state_store

    @property
    def projects(self) -> ProjectService:
        """Proyectos visibles, preselección (último usado o `JIRA_PROJECT_KEY`) y elección."""
        default = self.config.settings.jira_project_key if self.config else None
        return ProjectService(self.issue_tracker, self.last_projects, default)

    @property
    def top_k(self) -> int:
        return self.config.models.rag.top_k if self.config else DEFAULT_TOP_K

    @property
    def memory_boost(self) -> float:
        return self.config.models.rag.memory_boost if self.config else 1.0


def bootstrap_logging(config: AppConfig) -> None:
    """Logging JSON con los secretos de la configuración enmascarados (RNF-02)."""
    configure_logging(config.settings.log_level, secrets=config.settings.secret_values())
    # Las bibliotecas HTTP registran URLs completas (con query string): solo avisos.
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


def build_container(
    config: AppConfig | None = None,
    *,
    issue_tracker: IssueTracker | None = None,
    test_management: TestManagement | None = None,
    llm: LLMProvider | None = None,
    embeddings: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    memory_generator: MemoryGenerator | None = None,
    auth: AuthProvider | None = None,
    memory_dir: Path | None = None,
    audit: AuditTrail | None = None,
    versions: VersionSink | None = None,
    state_store: ArtifactStateStore | None = None,
    publish_mode: PublishMode | None = None,
    last_projects: LastProjectStore | None = None,
    conversations: ConversationStore | None = None,
    require_actor: bool = False,
) -> Container:
    """Compone el contenedor. Sin adaptadores reales todavía, cada dependencia es obligatoria."""
    if config is not None:
        bootstrap_logging(config)
    dependencies = {
        "issue_tracker": issue_tracker,
        "test_management": test_management,
        "llm": llm,
        "embeddings": embeddings,
        "vector_store": vector_store,
        "memory_generator": memory_generator,
        "auth": auth,
    }
    missing = [name for name, value in dependencies.items() if value is None]
    if missing:
        raise ConfigError(
            "Adaptadores no disponibles todavía (se implementan a partir del día 2): "
            + ", ".join(missing)
        )
    store = state_store or InMemoryArtifactStateStore()
    # Por defecto, simulación: nada se escribe en Jira salvo que se pida `live` (T-25).
    mode = publish_mode or (config.settings.jira_publish_mode if config else "simulation")
    return Container(
        **dependencies,  # type: ignore[arg-type]
        config=config,
        memory_dir=memory_dir or DEFAULT_MEMORY_DIR,
        approvals=ApprovalLedger(store=store),
        audit=audit or InMemoryAuditTrail(),
        versions=versions,
        state_store=store,
        publish_mode=mode,
        last_projects=last_projects or InMemoryLastProjectStore(),
        conversations=conversations or InMemoryConversationStore(),
        require_actor=require_actor,
    )
