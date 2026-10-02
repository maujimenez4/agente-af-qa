"""Construcción de los adaptadores reales del área A a partir de la configuración.

Traduce `AppConfig`/`Settings` a los valores simples que reciben los adaptadores, que nunca
importan `core/` (SPEC-00 §2). `core/container.py` usará estas funciones cuando los adaptadores
reales sustituyan a los fakes (sincronización del día 3).

Para el selector de modelo de la UI (RF-42), la composición crea el router con `model_router`,
lo conserva y lo pasa a `build_llm_provider(router=...)`: `set_override` afecta entonces a las
llamadas del proveedor compuesto.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import SecretStr

from adapters.auth.local import LocalAuthProvider
from adapters.base import IssueSummary, LLMProvider, PublishResult, TaskType
from adapters.embeddings.ollama import OllamaEmbeddings
from adapters.errors import AuthenticationError, ExternalServiceError, PublishError
from adapters.jira.tracker import JiraCloudTracker
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.openai_compatible import OpenAICompatibleProvider, StructuredPrompts
from adapters.llm.router import ModelChoice, ModelRouter
from adapters.llm.usage import SqlUsageRecorder, UsageRecorder
from adapters.testmgmt.jira_native import JiraNativeTests
from adapters.vectorstore.pgvector import PgVectorStore
from core.artifact_state import SqlArtifactStateStore
from core.audit import SqlAuditTrail
from core.config import AppConfig, Settings
from core.container import Container, build_container
from core.conversations import SqlConversationStore
from core.graph.builder import postgres_checkpointer
from core.impact.versions import StoryVersionStore
from core.memory.generator import LLMMemoryGenerator
from core.projects import SqlLastProjectStore
from core.rag.prompts import load_prompt
from schemas.artifact import Artifact
from schemas.memory import Memory
from schemas.test_case import ExecutionStatus, TestSuite

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


def build_usage_recorder(config: AppConfig) -> SqlUsageRecorder:
    """Consumo de cada llamada al LLM en `llm_usage`, sobre la base de datos de `.env` (RF-43)."""
    return SqlUsageRecorder.from_url(config.settings.sqlalchemy_url())


def _jira_credentials(settings: Settings) -> tuple[str, SecretStr, SecretStr]:
    """URL, email y token de Jira desde `.env`; `AuthenticationError` si falta alguno."""
    base_url, email, token = settings.jira_base_url, settings.jira_email, settings.jira_api_token
    if not (base_url and email and token):
        required = {"JIRA_BASE_URL": base_url, "JIRA_EMAIL": email, "JIRA_API_TOKEN": token}
        missing = [name for name, value in required.items() if not value]
        raise AuthenticationError(
            f"Falta configurar Jira: {', '.join(missing)}. Revisa el archivo .env.",
            service="jira",
        )
    return base_url, email, token


def build_issue_tracker(settings: Settings, **kwargs: Any) -> JiraCloudTracker:
    """`JiraCloudTracker` desde `.env`; `AuthenticationError` si falta alguna variable."""
    base_url, email, token = _jira_credentials(settings)
    return JiraCloudTracker(base_url, email, token, cloud_id=settings.jira_cloud_id, **kwargs)


def build_test_management(settings: Settings, **kwargs: Any) -> JiraNativeTests:
    """Casos de prueba como subtareas, etiquetas y adjuntos de Jira (T-30, D-09)."""
    base_url, email, token = _jira_credentials(settings)
    return JiraNativeTests(
        base_url,
        email,
        token,
        cloud_id=settings.jira_cloud_id,
        subtask_type=settings.jira_test_subtask_type,
        **kwargs,
    )


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


def build_last_projects(config: AppConfig) -> SqlLastProjectStore:
    """Último proyecto de Jira usado por cada persona en `user_last_project` (T-50)."""
    return SqlLastProjectStore.from_url(config.settings.sqlalchemy_url())


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
            timeout_s=config.models.limits.request_timeout_s,
            max_output_tokens=config.models.limits.max_output_tokens,
        )

    return create


# --- Contenedor de la aplicación (T-24) ---------------------------------------------------------


class PendingTestManagement:
    """Hasta T-30 no hay publicación de casos en Jira; en simulación nunca se llama."""

    def publish_suite(self, suite: TestSuite) -> PublishResult:
        raise PublishError("La publicación de casos de prueba en Jira llega con T-30.")

    def list_cases(self, story_key: str) -> list[IssueSummary]:
        raise ExternalServiceError(
            "La consulta de casos de prueba en Jira llega con T-30.", service="jira"
        )

    def record_execution(self, case_key: str, status: ExecutionStatus, evidence_md: str) -> None:
        raise PublishError("El registro de la ejecución en Jira llega con T-47.")


class PendingMemoryGenerator:
    """Hasta T-33 no hay memoria real; solo se llamaría tras publicar en `live`."""

    def generate(self, artifact: Artifact) -> Memory:
        raise ExternalServiceError(
            "La memoria de la HU publicada llega con T-33.", service="memoria"
        )


def build_conversations(config: AppConfig) -> SqlConversationStore:
    """Lista de conversaciones por usuario en `conversations` (T-52, migración `0004`)."""
    return SqlConversationStore.from_url(config.settings.sqlalchemy_url())


def build_checkpointer(config: AppConfig) -> PostgresSaver:
    """Checkpointer de la aplicación sobre la base de datos de `.env` (T-52)."""
    url = config.settings.sqlalchemy_url().set(drivername="postgresql")
    return postgres_checkpointer(url.render_as_string(hide_password=False))


def build_app_container(config: AppConfig, *, router: ModelRouter | None = None) -> Container:
    """Contenedor real de la UI: Jira, LLM, embeddings, pgvector, usuarios y persistencia.

    Auditoría, versiones y estado de los artefactos van siempre juntos (`audit_log` tiene FK a
    `artifacts`). Para el selector de modelo (RF-42), crea el router con `model_router(config)`,
    consérvalo y pásalo aquí. Escritura en Jira (T-27), casos de prueba (T-30) y memoria (T-33)
    son los reales. `JIRA_PUBLISH_MODE=simulation` por defecto; `live` se activa en el `.env`
    (escritura validada en el sandbox el 2026-10-02).
    """
    llm = build_llm_provider(config, build_usage_recorder(config), router=router)
    return build_container(
        config,
        issue_tracker=build_issue_tracker(config.settings),
        test_management=build_test_management(config.settings),  # T-30
        llm=llm,
        embeddings=build_embeddings(config),
        vector_store=build_vector_store(config),
        memory_generator=LLMMemoryGenerator(llm),  # T-33
        auth=build_auth(config),
        audit=build_audit(config),
        versions=build_versions(config),
        state_store=build_state_store(config),
        last_projects=build_last_projects(config),
        conversations=build_conversations(config),
        require_actor=True,  # T-52: sin persona autenticada en la config no se actúa
    )


def build_session_container(
    config: AppConfig,
    base: Container,
    router: ModelRouter,
    recorder: UsageRecorder | None = None,
) -> Container:
    """Contenedor de una sesión de la API (T-55): los adaptadores de `base` y un LLM propio.

    Cada sesión tiene su router para que el selector de modelo (RF-42) no afecte a las demás;
    Jira, la base de datos, el registro de aprobaciones y el resto se comparten en el proceso.
    `recorder`: el registro de consumo del proceso (T-32, `build_usage_recorder`).
    """
    llm = build_llm_provider(config, recorder, router=router)
    return replace(base, llm=llm, memory_generator=LLMMemoryGenerator(llm))
