"""Pruebas de core/config.py (T-03 · RNF-01)."""

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr

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

# Valores claramente ficticios; no son credenciales reales.
FAKE_GROQ_KEY = "fake-groq-key-0000000000"
FAKE_JIRA_TOKEN = "fake-jira-token-0000000000"


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def models_data() -> dict:
    return yaml.safe_load(DEFAULT_MODELS_PATH.read_text(encoding="utf-8"))


# --- models.yaml -------------------------------------------------------------------------


def test_current_models_yaml_is_valid() -> None:
    models = load_models_config()
    assert set(models.tasks) == set(TaskType)
    assert models.embeddings.dimensions == 1024
    assert all(models.tasks.values())


def test_task_chain_keeps_yaml_order() -> None:
    models = load_models_config()
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
    config = AppConfig(settings, load_models_config())
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
    config = AppConfig(no_keys_settings, load_models_config())
    status = config.providers_status()
    assert status["local"].available
    assert not status["groq"].available
    assert "GROQ_API_KEY" in (status["groq"].reason or "")
    assert not status["openrouter"].available


def test_without_keys_chains_keep_only_local(no_keys_settings: Settings) -> None:
    config = AppConfig(no_keys_settings, load_models_config())
    assert config.task_chain(TaskType.GENERATE_STORY) == []
    assert [r.provider for r in config.task_chain(TaskType.CLASSIFY_SOURCE)] == ["local"]
    assert len(config.task_chain(TaskType.GENERATE_STORY, only_available=False)) == 2


def test_key_makes_provider_available(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GROQ_API_KEY", FAKE_GROQ_KEY)
    config = AppConfig(Settings(_env_file=None), load_models_config())
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
    config = AppConfig(Settings(_env_file=None), load_models_config())
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
