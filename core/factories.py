"""Construcción de los adaptadores reales del área A a partir de la configuración.

Traduce `AppConfig`/`Settings` a los valores simples que reciben los adaptadores, que nunca
importan `core/` (SPEC-00 §2). `core/container.py` usará estas funciones cuando los adaptadores
reales sustituyan a los fakes (sincronización del día 3).

Para el selector de modelo de la UI (RF-42), la composición crea el router con `model_router`,
lo conserva y lo pasa a `build_llm_provider(router=...)`: `set_override` afecta entonces a las
llamadas del proveedor compuesto.
"""

import atexit
import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import SecretStr

from adapters.auth.local import LocalAuthProvider
from adapters.base import IssueSummary, IssueTracker, LLMProvider, PublishResult, TaskType
from adapters.embeddings.ollama import OllamaEmbeddings
from adapters.errors import AuthenticationError, ExternalServiceError, PublishError
from adapters.jira.tracker import JiraCloudTracker
from adapters.llm.catalog import HttpModelCatalog
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.openai_compatible import OpenAICompatibleProvider, StructuredPrompts
from adapters.llm.router import ModelChoice, ModelRouter
from adapters.llm.usage import SqlUsageRecorder, UsageRecorder
from adapters.testmgmt.jira_native import JiraNativeTests
from adapters.vectorstore.pgvector import PgVectorStore
from core.artifact_state import SqlArtifactStateStore
from core.audit import SqlAuditTrail
from core.config import AppConfig, ConfigError, Settings
from core.container import Container, build_container
from core.conversations import SqlConversationStore
from core.functional.determinism import current_call_options
from core.graph.builder import postgres_checkpointer
from core.handoff import SqlHandoffStore
from core.health import ConnectionTester, database_check
from core.impact.versions import StoryVersionStore
from core.logging import get_logger
from core.memory.generator import LLMMemoryGenerator
from core.projects import SqlLastProjectStore
from core.rag.prompts import load_prompt
from core.tracing import (
    LLMTraceObserver,
    NullTracer,
    Tracer,
    TracingVectorStore,
    secret_mask,
)
from schemas.artifact import Artifact
from schemas.memory import Memory
from schemas.test_case import ExecutionStatus, TestSuite

log = get_logger(__name__)

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
        observer=LLMTraceObserver(),  # T-40: sin operación trazada en curso no hace nada
        call_options=current_call_options,  # PA-432: temperatura 0 al estructurar una HU
    )


_TRACER_LOGGED = False
_TRACERS: dict[tuple[str, str, str, bool], Tracer] = {}
_TRACERS_LOCK = threading.Lock()


def build_tracer(settings: Settings) -> Tracer:
    """Trazas en Langfuse Cloud (T-40) si están las dos claves; si no, `NullTracer`: no hace
    nada, no llama a la red y lo dice una sola vez en el log. Si el SDK no arranca, tampoco.

    Uno por proceso y configuración (Streamlit compone un contenedor por sesión); al cerrar el
    proceso se envía lo pendiente con tope de tiempo (`atexit`).
    """
    global _TRACER_LOGGED
    public, private = settings.langfuse_public_key, settings.langfuse_secret_key
    if not (public and private and public.get_secret_value() and private.get_secret_value()):
        if not _TRACER_LOGGED:
            _TRACER_LOGGED = True
            log.info("trazas de Langfuse desactivadas: faltan las claves", action="tracing")
        return NullTracer()
    if not _secure_host(settings.langfuse_host):
        log.warning("trazas de Langfuse desactivadas: LANGFUSE_HOST sin https", action="tracing")
        return NullTracer()
    key = (  # también la secreta: rotarla crea otro trazador
        public.get_secret_value(),
        private.get_secret_value(),
        settings.langfuse_host,
        settings.langfuse_capture_content,
    )
    with _TRACERS_LOCK:
        if key not in _TRACERS:
            _TRACERS[key] = _langfuse_tracer(settings, public, private)
        return _TRACERS[key]


def _secure_host(host: str) -> bool:
    """Las claves viajan en cada envío: solo `https`, salvo un Langfuse local."""
    parsed = urlparse(host.strip())
    local = parsed.hostname in {"localhost", "127.0.0.1"}
    return parsed.scheme == "https" or (parsed.scheme == "http" and local)


def _langfuse_tracer(settings: Settings, public: SecretStr, private: SecretStr) -> Tracer:
    # Sus avisos de depuración podrían incluir el contenido de los spans sin enmascarar.
    logging.getLogger("langfuse").setLevel(logging.WARNING)
    try:
        from adapters.observability.langfuse import LangfuseTracer

        tracer = LangfuseTracer(
            public_key=public,
            secret_key=private,
            host=settings.langfuse_host,
            capture_content=settings.langfuse_capture_content,
            mask=secret_mask(settings.secret_values()),
        )
    except Exception as exc:  # las trazas nunca impiden arrancar
        log.warning("trazas de Langfuse no disponibles", action="tracing", error=type(exc).__name__)
        return NullTracer()
    atexit.register(tracer.shutdown)
    return tracer


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
    options = _model_options(config)

    def create(choice: ModelChoice) -> LLMProvider:
        limits = config.models.limits_for(choice.provider)  # PA-443: los de su proveedor
        return OpenAICompatibleProvider.create(
            choice.provider,
            choice.model,
            config.base_url_for(choice.provider),
            config.api_key_for(choice.provider),
            prompts=prompts,
            max_retries_on_429=limits.max_retries_on_429,
            max_wait_s=limits.max_wait_s,
            timeout_s=limits.request_timeout_s,
            max_output_tokens=limits.max_output_tokens,
            extra_body=options.get((choice.provider, choice.model)),
            context_window=limits.context_window,  # PA-457: guarda del reintento por formato
        )

    return create


def _model_options(config: AppConfig) -> dict[tuple[str, str], dict[str, Any]]:
    """`options` de cada modelo de las cadenas (T-58); las mismas en todas las tareas."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for chain in config.models.tasks.values():
        for ref in chain:
            body = ref.options.request_body() if ref.options else {}
            if found.setdefault((ref.provider, ref.model), body) != body:
                raise ConfigError(
                    f"El modelo «{ref.model}» de «{ref.provider}» tiene 'options' distintas en "
                    "varias tareas de config/models.yaml; deben coincidir."
                )
    return {key: body for key, body in found.items() if body}


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


def build_handoffs(config: AppConfig) -> SqlHandoffStore:
    """Entregas de HU a QA en `qa_handoffs` (T-54, migración `0005`); va a `build_graph`."""
    return SqlHandoffStore.from_url(config.settings.sqlalchemy_url())


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
        vector_store=TracingVectorStore(build_vector_store(config)),  # T-40: pasos del RAG
        memory_generator=LLMMemoryGenerator(llm),  # T-33
        auth=build_auth(config),
        audit=build_audit(config),
        versions=build_versions(config),
        state_store=build_state_store(config),
        last_projects=build_last_projects(config),
        conversations=build_conversations(config),
        require_actor=True,  # T-52: sin persona autenticada en la config no se actúa
        tracer=build_tracer(config.settings),  # T-40
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


def build_connection_tester(
    config: AppConfig, issue_tracker: IssueTracker | None
) -> tuple[ConnectionTester, HttpModelCatalog]:
    """Prueba de conexiones de la Administración (T-29): el catálogo de modelos de cada proveedor
    de las cadenas y de embeddings, y `SELECT 1` en PostgreSQL. Quien llama cierra el catálogo."""
    names = {ref.provider for chain in config.models.tasks.values() for ref in chain}
    names.add(config.models.embeddings.provider)
    providers = names & set(config.models.providers)
    catalog = HttpModelCatalog(
        base_urls={p: config.base_url_for(p) for p in providers},
        api_keys={p: config.api_key_for(p) for p in providers},
    )
    tester = ConnectionTester(
        config,
        catalog,
        issue_tracker=issue_tracker,
        database_check=database_check(config.settings.sqlalchemy_url()),
    )
    return tester, catalog
