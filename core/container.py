"""Raíz de composición: decide qué implementación de cada protocolo usa la aplicación.

El núcleo solo recibe un `Container` con protocolos de `adapters/base.py`. Los adaptadores
reales (Jira, LLM, pgvector…) se conectan aquí a partir del día 2; hasta entonces las
dependencias se inyectan explícitamente (en las pruebas, con los fakes de `tests/fakes/`).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

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
from core.config import ROOT_DIR, AppConfig, ConfigError
from core.logging import configure_logging

DEFAULT_MEMORY_DIR = ROOT_DIR / "data" / "memory"
DEFAULT_TOP_K = 6


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
    return Container(
        **dependencies,  # type: ignore[arg-type]
        config=config,
        memory_dir=memory_dir or DEFAULT_MEMORY_DIR,
    )
