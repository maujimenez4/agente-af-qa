"""Construcción de adaptadores desde la configuración (`core/factories.py`).

Datos 100 % sintéticos; sin red (HTTP con `httpx.MockTransport`).
"""

import base64
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from adapters.base import LLMProvider, Message, TaskType
from adapters.embeddings.ollama import OllamaEmbeddings
from adapters.errors import AuthenticationError, ExternalServiceError
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.openai_compatible import OpenAICompatibleProvider
from adapters.llm.router import ModelChoice, ModelRouter
from adapters.llm.usage import InMemoryUsageRecorder
from adapters.vectorstore.pgvector import PgVectorStore
from core.config import AppConfig, Settings, load_models_config
from core.factories import (
    build_embeddings,
    build_issue_tracker,
    build_llm_provider,
    build_vector_store,
    model_router,
    structured_prompts,
)
from tests.fakes.llm import FakeLLMProvider

# --- Jira (T-11) -----------------------------------------------------------------------------

JIRA_BASE_URL = "https://villaficticia.example"
JIRA_EMAIL = "persona@example.com"
JIRA_TOKEN = "test-token"
JIRA_CLOUD_ID = "test-cloud-id"


def jira_settings(**overrides: str) -> Settings:
    """Settings sin `.env` con la configuración mínima de Jira; "" elimina una variable."""
    values: dict[str, str] = {
        "jira_base_url": JIRA_BASE_URL,
        "jira_email": JIRA_EMAIL,
        "jira_api_token": JIRA_TOKEN,
    }
    values.update(overrides)
    return Settings(_env_file=None, **{k: v for k, v in values.items() if v})


def test_build_issue_tracker_builds_working_tracker_when_all_values_present(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """RF-01: con URL, email y token construye el tracker; los kwargs llegan al constructor."""
    requests: list[httpx.Request] = []
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"accountId": "id-ficticio"})

    tracker = build_issue_tracker(
        jira_settings(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append,
    )
    assert tracker.api_root == JIRA_BASE_URL
    tracker.test_connection()

    credentials = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
    assert len(requests) == 1
    assert str(requests[0].url) == f"{JIRA_BASE_URL}/rest/api/3/project/search"
    assert requests[0].headers["Authorization"] == f"Basic {credentials}"
    assert waits == []


def test_build_issue_tracker_uses_atlassian_gateway_when_cloud_id(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """RNF-04: con JIRA_CLOUD_ID (token con scopes) el api_root apunta a api.atlassian.com."""
    tracker = build_issue_tracker(jira_settings(jira_cloud_id=JIRA_CLOUD_ID))
    assert tracker.api_root == f"https://api.atlassian.com/ex/jira/{JIRA_CLOUD_ID}"


@pytest.mark.parametrize(
    ("field", "env_name"),
    [
        ("jira_base_url", "JIRA_BASE_URL"),
        ("jira_email", "JIRA_EMAIL"),
        ("jira_api_token", "JIRA_API_TOKEN"),
    ],
)
def test_build_issue_tracker_raises_authentication_error_when_value_missing(
    clean_env: pytest.MonkeyPatch, field: str, env_name: str
) -> None:
    """RF-01: falta una variable → AuthenticationError que la nombra sin mostrar valores."""
    with pytest.raises(AuthenticationError) as info:
        build_issue_tracker(jira_settings(**{field: ""}))
    message = str(info.value)
    assert env_name in message
    assert info.value.service == "jira"
    for value in (JIRA_BASE_URL, JIRA_EMAIL, JIRA_TOKEN):
        assert value not in message


def test_build_issue_tracker_raises_authentication_error_when_value_is_placeholder(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """RF-01: un placeholder `TU_*` de `.env.example` cuenta como ausente."""
    with pytest.raises(AuthenticationError) as info:
        build_issue_tracker(jira_settings(jira_api_token="TU_API_TOKEN"))
    assert "JIRA_API_TOKEN" in str(info.value)


def test_build_issue_tracker_raises_authentication_error_when_no_jira_config(
    no_keys_settings: Settings,
) -> None:
    """RF-01: sin ninguna variable de Jira → AuthenticationError que nombra las que faltan."""
    with pytest.raises(AuthenticationError) as info:
        build_issue_tracker(no_keys_settings)
    message = str(info.value)
    assert any(name in message for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))


# --- LLM (T-10) ------------------------------------------------------------------------------

LLM_FAKE_KEY = "test-key"
LLM_MESSAGES = [Message(role="user", content="Clasifica este documento ficticio.")]


@pytest.fixture
def no_keys_config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    """AppConfig real (models.yaml) sin ninguna clave de proveedor."""
    return AppConfig(Settings(_env_file=None), load_models_config())


@pytest.fixture
def groq_config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    """AppConfig real con una clave de groq ficticia."""
    return AppConfig(Settings(_env_file=None, groq_api_key=LLM_FAKE_KEY), load_models_config())


def fake_llm_factory(choice: ModelChoice) -> LLMProvider:
    return FakeLLMProvider(provider=choice.provider, model=choice.model)


def as_choices(config: AppConfig, task: TaskType) -> list[ModelChoice]:
    return [ModelChoice(provider=r.provider, model=r.model) for r in config.task_chain(task)]


def chat_completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def test_model_router_returns_router(no_keys_config: AppConfig) -> None:
    """RF-41: `model_router` compone un ModelRouter desde la configuración."""
    assert isinstance(model_router(no_keys_config, provider_factory=fake_llm_factory), ModelRouter)


def test_model_router_has_no_models_for_story_when_no_keys(no_keys_config: AppConfig) -> None:
    """RF-40 · RF-41: sin claves, groq y openrouter no están disponibles → generate_story vacía."""
    router = model_router(no_keys_config, provider_factory=fake_llm_factory)

    assert router.models_for(TaskType.GENERATE_STORY) == []


def test_model_router_keeps_only_local_when_no_keys(no_keys_config: AppConfig) -> None:
    """RF-40 · RF-41: sin claves, classify_source queda solo con el proveedor local."""
    router = model_router(no_keys_config, provider_factory=fake_llm_factory)

    chain = router.models_for(TaskType.CLASSIFY_SOURCE)

    assert [choice.provider for choice in chain] == ["local"]
    assert chain == as_choices(no_keys_config, TaskType.CLASSIFY_SOURCE)


def test_model_router_puts_groq_first_when_key_present(groq_config: AppConfig) -> None:
    """RF-41 · RF-44: con clave de groq, groq es el principal de generate_story."""
    router = model_router(groq_config, provider_factory=fake_llm_factory)

    chain = router.models_for(TaskType.GENERATE_STORY)

    assert chain[0].provider == "groq"
    assert all(choice.provider != "openrouter" for choice in chain)


@pytest.mark.parametrize("task", list(TaskType))
def test_model_router_matches_config_chain_for_every_task(
    groq_config: AppConfig, task: TaskType
) -> None:
    """RF-41: la cadena de cada tarea es la de models.yaml filtrada por disponibilidad."""
    router = model_router(groq_config, provider_factory=fake_llm_factory)

    assert router.models_for(task) == as_choices(groq_config, task)


def test_model_router_rejects_override_when_provider_has_no_key(groq_config: AppConfig) -> None:
    """RF-42 (error): elegir un proveedor declarado pero sin clave (openrouter) → ValueError."""
    router = model_router(groq_config, provider_factory=fake_llm_factory)

    with pytest.raises(ValueError, match="openrouter"):
        router.set_override(
            TaskType.GENERATE_STORY, ModelChoice(provider="openrouter", model="modelo:free")
        )


def test_model_router_rejects_override_when_provider_undeclared(groq_config: AppConfig) -> None:
    """RF-42 (error): elegir un proveedor no declarado en models.yaml → ValueError."""
    router = model_router(groq_config, provider_factory=fake_llm_factory)

    with pytest.raises(ValueError):
        router.set_override(TaskType.GENERATE_STORY, ModelChoice(provider="inexistente", model="x"))


def test_model_router_accepts_local_override_when_no_keys(no_keys_config: AppConfig) -> None:
    """RF-42: sin claves se puede elegir el modelo local para cualquier tarea."""
    router = model_router(no_keys_config, provider_factory=fake_llm_factory)
    chosen = ModelChoice(provider="local", model="modelo-local-ficticio")

    router.set_override(TaskType.GENERATE_STORY, chosen)

    assert router.models_for(TaskType.GENERATE_STORY) == [chosen]


def test_model_router_default_factory_creates_openai_compatible(groq_config: AppConfig) -> None:
    """RF-40: sin provider_factory se crean OpenAICompatibleProvider (sin llamadas de red)."""
    chain = model_router(groq_config).chain(TaskType.GENERATE_STORY)

    expected = as_choices(groq_config, TaskType.GENERATE_STORY)[0]
    assert isinstance(chain[0], OpenAICompatibleProvider)
    assert (chain[0].provider, chain[0].model) == (expected.provider, expected.model)


def test_model_router_default_factory_uses_config_url_key_and_limits(
    groq_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RF-40 · RNF-27: la fábrica por defecto usa el base_url, la clave y el límite de 429."""
    requests: list[httpx.Request] = []
    calls: list[dict[str, Any]] = []
    original = OpenAICompatibleProvider.create.__func__  # type: ignore[attr-defined]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return chat_completion("ok")

    def spy_create(
        cls: type[OpenAICompatibleProvider],
        provider: str,
        model: str,
        base_url: str,
        api_key: SecretStr | None,
        **kwargs: Any,
    ) -> OpenAICompatibleProvider:
        calls.append({"provider": provider, "base_url": base_url, **kwargs})
        kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(handler))
        return original(cls, provider, model, base_url, api_key, **kwargs)

    monkeypatch.setattr(OpenAICompatibleProvider, "create", classmethod(spy_create))

    provider = model_router(groq_config).chain(TaskType.GENERATE_STORY)[0]
    provider.generate(LLM_MESSAGES, TaskType.GENERATE_STORY)

    groq_url = groq_config.models.providers["groq"].base_url.rstrip("/")
    assert calls[0]["provider"] == "groq"
    assert calls[0]["base_url"].rstrip("/") == groq_url
    assert calls[0]["max_retries_on_429"] == groq_config.models.limits.max_retries_on_429
    assert str(requests[0].url) == f"{groq_url}/chat/completions"
    assert requests[0].headers["authorization"] == f"Bearer {LLM_FAKE_KEY}"
    assert json.loads(requests[0].content)["model"] == provider.model  # type: ignore[attr-defined]


@pytest.mark.parametrize("with_recorder", [False, True], ids=["sin_recorder", "con_recorder"])
def test_build_llm_provider_returns_fallback(
    no_keys_config: AppConfig, with_recorder: bool
) -> None:
    """RF-40 · RF-44: `build_llm_provider` compone un FallbackLLMProvider sobre el router."""
    recorder = InMemoryUsageRecorder() if with_recorder else None

    provider = build_llm_provider(no_keys_config, recorder)

    assert isinstance(provider, FallbackLLMProvider)
    assert isinstance(provider, LLMProvider)


def test_build_llm_provider_records_usage_with_injected_factory(
    no_keys_config: AppConfig,
) -> None:
    """RF-43 · RF-44: con una fábrica inyectada responde el local y se registra el uso."""
    recorder = InMemoryUsageRecorder()
    provider = build_llm_provider(no_keys_config, recorder, provider_factory=fake_llm_factory)

    result = provider.generate(LLM_MESSAGES, TaskType.CLASSIFY_SOURCE)

    assert result.provider == "local"
    assert len(recorder.records) == 1
    assert recorder.records[0].task == TaskType.CLASSIFY_SOURCE


def test_build_llm_provider_raises_when_task_has_no_models(no_keys_config: AppConfig) -> None:
    """RF-44 (error): sin modelos disponibles para la tarea se informa sin llamar a la red."""
    provider = build_llm_provider(no_keys_config, provider_factory=fake_llm_factory)

    with pytest.raises(ExternalServiceError) as info:
        provider.generate(LLM_MESSAGES, TaskType.GENERATE_STORY)

    assert "generate_story" in str(info.value)


# --- Cierre de spec-checker (T-10) ---


def test_structured_prompts_are_loaded_from_prompts_dir() -> None:
    """Los textos de apoyo a la salida estructurada salen de prompts/ con sus marcadores."""
    prompts = structured_prompts()

    assert "{schema}" in prompts.json_mode
    assert "JSON" in prompts.json_mode
    assert "{errors}" in prompts.retry


def test_build_llm_provider_honours_router_override(groq_config: AppConfig) -> None:
    """RF-42: el override del router compartido cambia el modelo del proveedor compuesto."""
    router = model_router(groq_config, provider_factory=fake_llm_factory)
    provider = build_llm_provider(groq_config, router=router)
    task = TaskType.CLASSIFY_SOURCE

    default = provider.generate(LLM_MESSAGES, task)
    router.set_override(task, ModelChoice(provider="groq", model="modelo-elegido-ficticio"))
    chosen = provider.generate(LLM_MESSAGES, task)
    router.clear_override(task)
    restored = provider.generate(LLM_MESSAGES, task)

    assert (chosen.provider, chosen.model) == ("groq", "modelo-elegido-ficticio")
    assert (restored.provider, restored.model) == (default.provider, default.model)


# --- Embeddings y VectorStore (T-16) ---------------------------------------------------------

OLLAMA_FAKE_URL = "http://ollama.villaficticia.example:11434/v1"


def test_build_embeddings_uses_models_yaml_when_no_env(no_keys_config: AppConfig) -> None:
    """T-16 / D-14: OllamaEmbeddings con modelo, dimensiones y base_url de models.yaml."""
    expected = no_keys_config.models.embeddings
    embeddings = build_embeddings(no_keys_config)

    assert isinstance(embeddings, OllamaEmbeddings)
    assert embeddings.model_name == expected.model == "bge-m3"
    assert embeddings.dimensions == expected.dimensions == 1024
    base_url = no_keys_config.models.providers[expected.provider].base_url
    assert str(embeddings._client.base_url).rstrip("/") == base_url.rstrip("/")


def test_build_embeddings_uses_ollama_base_url_when_env_set(clean_env: pytest.MonkeyPatch) -> None:
    """T-16: OLLAMA_BASE_URL tiene prioridad sobre la base_url de models.yaml."""
    config = AppConfig(
        Settings(_env_file=None, ollama_base_url=OLLAMA_FAKE_URL), load_models_config()
    )
    embeddings = build_embeddings(config)
    assert str(embeddings._client.base_url).rstrip("/") == OLLAMA_FAKE_URL


def test_build_vector_store_binds_embedding_model_when_built(no_keys_config: AppConfig) -> None:
    """T-16 / DT-03: PgVectorStore ligado al modelo y dimensiones de embeddings, sin conectar."""
    expected = no_keys_config.models.embeddings
    store = build_vector_store(no_keys_config)

    assert isinstance(store, PgVectorStore)
    assert store.embedding_model == expected.model
    assert store.dimensions == expected.dimensions
    url = store._engine.url
    assert url.drivername == no_keys_config.settings.sqlalchemy_url().drivername
    assert url.database == no_keys_config.settings.sqlalchemy_url().database
