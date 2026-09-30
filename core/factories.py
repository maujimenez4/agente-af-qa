"""Construcción de los adaptadores reales del área A a partir de la configuración.

Traduce `AppConfig`/`Settings` a los valores simples que reciben los adaptadores, que nunca
importan `core/` (SPEC-00 §2). `core/container.py` usará estas funciones cuando los adaptadores
reales sustituyan a los fakes (sincronización del día 3).

Para el selector de modelo de la UI (RF-42), la composición crea el router con `model_router`,
lo conserva y lo pasa a `build_llm_provider(router=...)`: `set_override` afecta entonces a las
llamadas del proveedor compuesto.
"""

from collections.abc import Callable
from typing import Any

from adapters.auth.local import LocalAuthProvider
from adapters.base import LLMProvider, TaskType
from adapters.embeddings.ollama import OllamaEmbeddings
from adapters.errors import AuthenticationError
from adapters.jira.tracker import JiraCloudTracker
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.openai_compatible import OpenAICompatibleProvider, StructuredPrompts
from adapters.llm.router import ModelChoice, ModelRouter
from adapters.llm.usage import UsageRecorder
from adapters.vectorstore.pgvector import PgVectorStore
from core.artifact_state import SqlArtifactStateStore
from core.audit import SqlAuditTrail
from core.config import AppConfig, Settings
from core.impact.versions import StoryVersionStore
from core.rag.prompts import load_prompt

ProviderFactory = Callable[[ModelChoice], LLMProvider]


def model_router(
    config: AppConfig, *, provider_factory: ProviderFactory | None = None
) -> ModelRouter:
    """Router con las cadenas de `config/models.yaml` y la disponibilidad de cada proveedor."""
    chains = {
        task: [
            ModelChoice(ref.provider, ref.model)
            for ref in config.task_chain(task, only_available=False)
        ]
        for task in TaskType
    }
    providers = {name: status.available for name, status in config.providers_status().items()}
    return ModelRouter(chains, provider_factory or _openai_factory(config), providers=providers)


def build_llm_provider(
    config: AppConfig,
    recorder: UsageRecorder | None = None,
    *,
    provider_factory: ProviderFactory | None = None,
    router: ModelRouter | None = None,
) -> FallbackLLMProvider:
    """`LLMProvider` de la aplicación: router por tarea + cadena de respaldo + registro de uso.

    Si se pasa `router`, se usa ese (y sus overrides de sesión, RF-42) en lugar de crear uno.
    """
    router = router or model_router(config, provider_factory=provider_factory)
    return FallbackLLMProvider(
        router.chain,
        recorder,
        daily_token_warning=config.models.limits.daily_token_warning,
    )


def build_issue_tracker(settings: Settings, **kwargs: Any) -> JiraCloudTracker:
    """`JiraCloudTracker` desde `.env`; `AuthenticationError` si falta alguna variable."""
    base_url, email, token = settings.jira_base_url, settings.jira_email, settings.jira_api_token
    if not (base_url and email and token):
        required = {"JIRA_BASE_URL": base_url, "JIRA_EMAIL": email, "JIRA_API_TOKEN": token}
        missing = [name for name, value in required.items() if not value]
        raise AuthenticationError(
            f"Falta configurar Jira: {', '.join(missing)}. Revisa el archivo .env.",
            service="jira",
        )
    return JiraCloudTracker(base_url, email, token, cloud_id=settings.jira_cloud_id, **kwargs)


def build_auth(config: AppConfig) -> LocalAuthProvider:
    """Usuarios locales (argon2) sobre la base de datos de `.env` (RF-45)."""
    return LocalAuthProvider.from_url(config.settings.sqlalchemy_url())


def build_audit(config: AppConfig) -> SqlAuditTrail:
    """Auditoría en `audit_log` (RF-35, T-25)."""
    return SqlAuditTrail.from_url(config.settings.sqlalchemy_url())


def build_versions(config: AppConfig) -> StoryVersionStore:
    """Versiones de cada artefacto en `artifact_versions` (T-19)."""
    return StoryVersionStore.from_url(config.settings.sqlalchemy_url())


def build_state_store(config: AppConfig) -> SqlArtifactStateStore:
    """Aprobaciones y versión de partida por artefacto en `artifact_state` (T-25)."""
    return SqlArtifactStateStore.from_url(config.settings.sqlalchemy_url())


def build_embeddings(config: AppConfig) -> OllamaEmbeddings:
    """Embeddings de `config/models.yaml` (bge-m3 en Ollama, D-14)."""
    embeddings = config.models.embeddings
    return OllamaEmbeddings(
        embeddings.model, embeddings.dimensions, config.base_url_for(embeddings.provider)
    )


def build_vector_store(config: AppConfig) -> PgVectorStore:
    """`PgVectorStore` sobre la base de datos de `.env`, ligado al modelo de embeddings."""
    embeddings = config.models.embeddings
    return PgVectorStore.from_url(
        config.settings.sqlalchemy_url(), embeddings.model, embeddings.dimensions
    )


def structured_prompts() -> StructuredPrompts:
    """Textos de apoyo a la salida estructurada, desde `prompts/` (CLAUDE.md)."""
    return StructuredPrompts(
        json_mode=load_prompt("structured_json_mode").text,
        retry=load_prompt("structured_retry").text,
    )


def _openai_factory(config: AppConfig) -> ProviderFactory:
    prompts = structured_prompts()

    def create(choice: ModelChoice) -> LLMProvider:
        return OpenAICompatibleProvider.create(
            choice.provider,
            choice.model,
            config.base_url_for(choice.provider),
            config.api_key_for(choice.provider),
            prompts=prompts,
            max_retries_on_429=config.models.limits.max_retries_on_429,
        )

    return create
