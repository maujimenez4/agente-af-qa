"""Pruebas de core/config.py (T-03 · RNF-01)."""

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from adapters.base import TaskType
from core.config import (
    DEFAULT_MODELS_PATH,
    ROOT_DIR,
    AppConfig,
    ConfigError,
    Settings,
    is_placeholder,
    load_models_config,
)

TEST_MODELS = (
    Path(__file__).resolve().parents[1] / "fixtures" / "models.yaml"
)  # modelos fijos de prueba

# Valores claramente ficticios; no son credenciales reales.
FAKE_GROQ_KEY = "fake-groq-key-0000000000"
FAKE_JIRA_TOKEN = "fake-jira-token-0000000000"


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


# Variante con proveedores en la nube: la lógica de claves se prueba sobre ella (desde el
# 2026-10-01 el models.yaml por defecto es solo local).
GROQ_MODELS = DEFAULT_MODELS_PATH.parent / "models.groq.yaml"


@pytest.fixture
def models_data() -> dict:
    return yaml.safe_load(GROQ_MODELS.read_text(encoding="utf-8"))


# --- models.yaml -------------------------------------------------------------------------


def test_current_models_yaml_is_valid() -> None:
    models = load_models_config()
    assert set(models.tasks) == set(TaskType)
    assert models.embeddings.dimensions == 1024
    assert all(models.tasks.values())


def test_task_chain_keeps_yaml_order() -> None:
    models = load_models_config(TEST_MODELS)
    chain = models.tasks[TaskType.GENERATE_STORY]
    assert [ref.provider for ref in chain] == ["groq", "openrouter"]


def _set_first_model(data: dict, **fields: str) -> None:
    data["tasks"]["generate_story"][0].update(fields)


INVALID_CASES: list[tuple[Callable[[dict], object], str]] = [
    (lambda d: d["tasks"].update(generate_story=[]), "vacía"),
    (lambda d: d["tasks"].pop("nl_to_jql"), "faltan tareas"),
    (lambda d: d["tasks"]["generate_story"].append({"provider": "otro", "model": "x"}), "otro"),
    (lambda d: d["tasks"]["generate_story"][0].pop("model"), "model"),
    (lambda d: _set_first_model(d, extra="x"), "extra"),
    (lambda d: d["tasks"].update(tarea_inventada=[{"provider": "groq", "model": "x"}]), "tasks"),
    (lambda d: d["embeddings"].update(dimensions=0), "dimensions"),
    (lambda d: d["rag"].update(overlap_tokens=10_000), "overlap_tokens"),
    (lambda d: d.pop("limits"), "limits"),
]


@pytest.mark.parametrize(("mutate", "message"), INVALID_CASES)
def test_invalid_structure_raises_config_error(
    tmp_path: Path, models_data: dict, mutate: Callable[[dict], object], message: str
) -> None:
    mutate(models_data)
    with pytest.raises(ConfigError, match=message):
        load_models_config(_write_yaml(tmp_path, models_data))


def test_unreadable_yaml_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No se pudo leer"):
        load_models_config(tmp_path / "no-existe.yaml")


# --- Settings y secretos -----------------------------------------------------------------


def test_settings_load_without_env_file(no_keys_settings: Settings) -> None:
    assert no_keys_settings.groq_api_key is None
    assert no_keys_settings.jira_api_token is None
    assert no_keys_settings.secret_values() == []


def test_placeholders_are_treated_as_missing(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GROQ_API_KEY", "TU_API_KEY_GROQ")
    clean_env.setenv("JIRA_API_TOKEN", "TU_TOKEN_JIRA")
    clean_env.setenv("JIRA_BASE_URL", "https://TU_SITIO.atlassian.net")
    settings = Settings(_env_file=None)
    assert settings.groq_api_key is None
    assert settings.jira_api_token is None
    assert settings.jira_base_url is None


def test_env_example_behaves_as_no_keys(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=ROOT_DIR / ".env.example")
    config = AppConfig(settings, load_models_config(GROQ_MODELS))
    assert not config.provider_status("groq").available
    assert not config.provider_status("openrouter").available


@pytest.mark.parametrize("value", ["", "   ", "TU_API_KEY", "TU_CONTRASEÑA_LOCAL", None])
def test_is_placeholder_true(value: str | None) -> None:
    assert is_placeholder(value)


@pytest.mark.parametrize("value", ["fake-key-123", "tu_minusculas", "XTU_ALGO"])
def test_is_placeholder_false(value: str) -> None:
    assert not is_placeholder(value)


def test_secrets_are_secretstr_and_hidden_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GROQ_API_KEY", FAKE_GROQ_KEY)
    clean_env.setenv("JIRA_API_TOKEN", FAKE_JIRA_TOKEN)
    settings = Settings(_env_file=None)
    assert isinstance(settings.groq_api_key, SecretStr)
    assert settings.groq_api_key.get_secret_value() == FAKE_GROQ_KEY
    for text in (repr(settings), str(settings), settings.model_dump_json()):
        assert FAKE_GROQ_KEY not in text
        assert FAKE_JIRA_TOKEN not in text
    assert set(settings.secret_values()) == {FAKE_GROQ_KEY, FAKE_JIRA_TOKEN}


# --- Disponibilidad de proveedores -------------------------------------------------------


def test_without_keys_only_local_provider_is_available(no_keys_settings: Settings) -> None:
    config = AppConfig(no_keys_settings, load_models_config(GROQ_MODELS))
    status = config.providers_status()
    assert status["local"].available
    assert not status["groq"].available
    assert "GROQ_API_KEY" in (status["groq"].reason or "")
    assert not status["openrouter"].available


def test_without_keys_chains_keep_only_local(no_keys_settings: Settings) -> None:
    config = AppConfig(no_keys_settings, load_models_config(TEST_MODELS))
    assert config.task_chain(TaskType.GENERATE_STORY) == []
    assert [r.provider for r in config.task_chain(TaskType.CLASSIFY_SOURCE)] == ["local"]
    assert len(config.task_chain(TaskType.GENERATE_STORY, only_available=False)) == 2


def test_key_makes_provider_available(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GROQ_API_KEY", FAKE_GROQ_KEY)
    config = AppConfig(Settings(_env_file=None), load_models_config(TEST_MODELS))
    assert config.provider_status("groq").available
    assert [r.provider for r in config.task_chain(TaskType.GENERATE_STORY)] == ["groq"]
    key = config.api_key_for("groq")
    assert key is not None
    assert key.get_secret_value() == FAKE_GROQ_KEY
    assert config.api_key_for("local") is None


def test_unknown_key_env_is_read_from_environment(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict
) -> None:
    models_data["providers"]["otro"] = {
        "type": "openai_compatible",
        "base_url": "https://proveedor.example.invalid/v1",
        "api_key_env": "OTRO_API_KEY",
    }
    config = AppConfig(
        Settings(_env_file=None), load_models_config(_write_yaml(tmp_path, models_data))
    )
    clean_env.delenv("OTRO_API_KEY", raising=False)
    assert not config.provider_status("otro").available
    clean_env.setenv("OTRO_API_KEY", "TU_API_KEY_OTRO")
    assert not config.provider_status("otro").available
    clean_env.setenv("OTRO_API_KEY", "fake-otro-key-000000")
    assert config.provider_status("otro").available


def test_ollama_base_url_overrides_local_provider(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OLLAMA_BASE_URL", "http://ollama.local.invalid:11434/v1")
    config = AppConfig(Settings(_env_file=None), load_models_config(GROQ_MODELS))
    assert config.base_url_for("local") == "http://ollama.local.invalid:11434/v1"
    assert config.base_url_for("groq") == "https://api.groq.com/openai/v1"


def test_config_error_does_not_echo_input_values(tmp_path: Path, models_data: dict) -> None:
    leaked = "gsk_" + "9" * 40
    models_data["providers"]["groq"]["api_key"] = leaked
    with pytest.raises(ConfigError) as info:
        load_models_config(_write_yaml(tmp_path, models_data))
    assert leaked not in str(info.value)
    assert info.value.__cause__ is None
    assert "providers.groq.api_key" in str(info.value)


def test_api_key_env_must_be_a_variable_name(tmp_path: Path, models_data: dict) -> None:
    leaked = "gsk_" + "8" * 40
    models_data["providers"]["groq"]["api_key_env"] = leaked
    with pytest.raises(ConfigError, match="api_key_env") as info:
        load_models_config(_write_yaml(tmp_path, models_data))
    assert leaked not in str(info.value)


def test_yaml_syntax_error_does_not_echo_content(tmp_path: Path) -> None:
    leaked = "gsk_" + "7" * 40
    path = tmp_path / "models.yaml"
    path.write_text(f"providers: [\n  {leaked}: : :\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_models_config(path)
    assert leaked not in str(info.value)
    assert info.value.__cause__ is None


@pytest.mark.parametrize("path", [DEFAULT_MODELS_PATH, GROQ_MODELS], ids=["local", "groq"])
def test_real_models_yaml_has_no_placeholders(path: Path) -> None:
    """R-07: sin modelos por definir en ninguna de las dos variantes versionadas."""
    models = load_models_config(path)
    assert set(models.tasks) == set(TaskType)
    for task, chain in models.tasks.items():
        assert chain and all("POR_DEFINIR" not in ref.model for ref in chain), task.value


def test_default_models_yaml_is_local_only() -> None:
    """Decisión del 2026-10-01: por defecto solo modelos locales de Ollama, sin claves ni cuota."""
    models = load_models_config()
    providers = {ref.provider for chain in models.tasks.values() for ref in chain}
    assert providers == {"local"}
    assert all(models.providers[p].api_key_env is None for p in providers)
    assert models.embeddings.model == "bge-m3"  # cambiarlo invalidaría el índice del RAG


def test_groq_variant_has_a_keyed_provider_in_every_chain() -> None:
    """R-07: en la variante de Groq, cada cadena tiene al menos un proveedor con clave."""
    models = load_models_config(GROQ_MODELS)
    for task, chain in models.tasks.items():
        assert any(models.providers[ref.provider].api_key_env for ref in chain), task.value


def test_request_timeout_defaults_to_60_and_local_config_raises_it() -> None:
    """El modelo local en CPU necesita más tiempo por llamada que uno en la nube."""
    assert load_models_config(GROQ_MODELS).limits.request_timeout_s == 60.0
    assert load_models_config().limits.request_timeout_s == 600


def test_request_timeout_reaches_the_sdk_client() -> None:
    from adapters.llm.router import ModelChoice
    from core.factories import _openai_factory

    config = AppConfig(Settings(_env_file=None), load_models_config())  # type: ignore[call-arg]
    provider = _openai_factory(config)(ModelChoice("local", "qwen3:4b-instruct"))
    assert provider._client.timeout == 600


def test_max_output_tokens_per_task_reach_the_provider() -> None:
    """Tope de salida por tarea: la HU acotada deja sitio al reintento en la ventana local."""
    from adapters.base import TaskType
    from adapters.llm.router import ModelChoice
    from core.factories import _openai_factory

    models = load_models_config()
    assert models.limits.max_output_tokens[TaskType.GENERATE_STORY] == 2500
    assert load_models_config(GROQ_MODELS).limits.max_output_tokens == {}  # sin tope
    config = AppConfig(Settings(_env_file=None), models)  # type: ignore[call-arg]
    provider = _openai_factory(config)(ModelChoice("local", "qwen3:4b-instruct"))
    assert provider._max_output_tokens[TaskType.GENERATE_STORY] == 2500


def test_provider_sends_max_tokens_only_for_tasks_with_a_cap() -> None:
    from unittest.mock import MagicMock

    from adapters.base import Message, TaskType
    from adapters.llm.openai_compatible import OpenAICompatibleProvider
    from core.factories import structured_prompts

    client = MagicMock()
    client.chat.completions.create.return_value.choices = [MagicMock()]
    client.chat.completions.create.return_value.choices[0].message.content = "hola"
    client.chat.completions.create.return_value.usage.prompt_tokens = 3
    client.chat.completions.create.return_value.usage.completion_tokens = 1
    provider = OpenAICompatibleProvider(
        "local",
        "m",
        client,
        prompts=structured_prompts(),
        max_output_tokens={TaskType.CLASSIFY_SOURCE: 200},
    )
    provider.generate([Message(role="user", content="x")], TaskType.CLASSIFY_SOURCE)
    assert client.chat.completions.create.call_args.kwargs["max_tokens"] == 200
    provider.generate([Message(role="user", content="x")], TaskType.NL_TO_JQL)
    assert "max_tokens" not in client.chat.completions.create.call_args.kwargs


# --- API_ALLOWED_ORIGINS (T-55, H2) ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        "localhost:5173",
        "https://*.example",
        "http://localhost:5173, *",
        "https://app.example/ruta",
        "ftp://app.example",
        "https://app.example:8443:1",
    ],
)
def test_api_allowed_origins_rejects_wildcards_and_non_origins(
    clean_env: pytest.MonkeyPatch, raw: str
) -> None:
    """Req. 3 / H2: nunca `*`, comodines, rutas ni orígenes sin esquema http(s)."""
    clean_env.setenv("API_ALLOWED_ORIGINS", raw)
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)
    assert "API_ALLOWED_ORIGINS" in str(info.value)


def test_api_allowed_origins_accepts_explicit_list_and_normalizes(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Req. 3 / H2: lista explícita con espacios y barra final -> orígenes limpios."""
    clean_env.setenv("API_ALLOWED_ORIGINS", "http://localhost:5173, https://app.example:8443/ ,")
    settings = Settings(_env_file=None)
    assert settings.api_origins == ["http://localhost:5173", "https://app.example:8443"]


@pytest.mark.parametrize("raw", ["", " ", ","])
def test_api_allowed_origins_empty_means_same_origin_only(
    clean_env: pytest.MonkeyPatch, raw: str
) -> None:
    """Req. 3 (límite): vacío -> sin orígenes extra (solo el mismo origen, sin CORS)."""
    clean_env.setenv("API_ALLOWED_ORIGINS", raw)
    assert Settings(_env_file=None).api_origins == []
