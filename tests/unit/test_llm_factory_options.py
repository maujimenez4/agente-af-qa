"""Opciones por modelo de `config/models.yaml` en la factoría de proveedores (T-58 · RNF-09).

`core/factories._model_options` recoge las `options` por (proveedor, modelo) y
`_openai_factory` las pasa como `extra_body`. Sin red: el HTTP va por `httpx.MockTransport` y
la configuración se escribe en `tmp_path` a partir de la copia fija de pruebas.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from pydantic import SecretStr

from adapters.base import Message, TaskType
from adapters.llm.openai_compatible import OpenAICompatibleProvider
from adapters.llm.router import ModelChoice
from core.config import ROOT_DIR, AppConfig, ConfigError, Settings, load_models_config
from core.factories import _model_options, _openai_factory, model_router

TEST_MODELS = ROOT_DIR / "tests" / "fixtures" / "models.yaml"
LOCAL = ("local", "POR_DEFINIR")  # aparece en synthesize_memory, classify_source y nl_to_jql
GROQ = ("groq", "openai/gpt-oss-120b")
LOCAL_TASKS = ("synthesize_memory", "classify_source", "nl_to_jql")
MESSAGES = [Message(role="user", content="Clasifica un documento ficticio de Villaficticia.")]


@pytest.fixture
def models_data() -> dict[str, Any]:
    return yaml.safe_load(TEST_MODELS.read_text(encoding="utf-8"))


def set_options(data: dict[str, Any], key: tuple[str, str], options: Any, *tasks: str) -> None:
    """Pone `options` al modelo `key` en las tareas indicadas (todas si no se indica ninguna)."""
    for task, chain in data["tasks"].items():
        if tasks and task not in tasks:
            continue
        for ref in chain:
            if (ref["provider"], ref["model"]) == key:
                ref["options"] = options


def make_config(tmp_path: Path, data: dict[str, Any]) -> AppConfig:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return AppConfig(Settings(_env_file=None), load_models_config(path))  # type: ignore[call-arg]


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
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        },
    )


# --- _model_options -----------------------------------------------------------------------------


def test_model_options_returns_body_per_provider_and_model(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58: devuelve {(prov, model): {"think": False}} solo para los modelos con options."""
    set_options(models_data, LOCAL, {"think": False})

    assert _model_options(make_config(tmp_path, models_data)) == {LOCAL: {"think": False}}


def test_model_options_is_empty_when_no_model_has_options(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58 (límite): sin `options` en ningún modelo, el resultado es vacío."""
    assert _model_options(make_config(tmp_path, models_data)) == {}


def test_model_options_accepts_same_options_repeated_in_several_tasks(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58: el mismo modelo con las mismas options en varias tareas es correcto."""
    set_options(models_data, GROQ, {"reasoning_effort": "none"})
    set_options(models_data, LOCAL, {"think": False})

    options = _model_options(make_config(tmp_path, models_data))

    assert options == {GROQ: {"reasoning_effort": "none"}, LOCAL: {"think": False}}


def test_model_options_raises_config_error_when_same_model_has_different_options(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58 (error): options distintas para el mismo modelo en dos tareas → ConfigError."""
    set_options(models_data, LOCAL, {"think": False}, "classify_source")
    set_options(models_data, LOCAL, {"think": True}, "nl_to_jql", "synthesize_memory")
    config = make_config(tmp_path, models_data)

    with pytest.raises(ConfigError) as info:
        _model_options(config)

    message = str(info.value)
    assert "POR_DEFINIR" in message and "local" in message
    assert "options" in message and "distintas" in message


def test_model_options_raises_when_options_only_in_some_tasks(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58 (error): options en una tarea y ausentes en otra también se consideran distintas."""
    set_options(models_data, LOCAL, {"think": False}, "classify_source")

    with pytest.raises(ConfigError, match="distintas"):
        _model_options(make_config(tmp_path, models_data))


def test_openai_factory_raises_config_error_when_options_conflict(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58 (error): el conflicto se detecta al construir la factoría (y el router)."""
    set_options(models_data, LOCAL, {"think": False}, "classify_source")
    set_options(models_data, LOCAL, {"reasoning_effort": "low"}, "nl_to_jql", "synthesize_memory")
    config = make_config(tmp_path, models_data)

    with pytest.raises(ConfigError):
        _openai_factory(config)
    with pytest.raises(ConfigError):
        model_router(config)


# --- _openai_factory --------------------------------------------------------------------------


def test_openai_factory_creates_provider_with_model_extra_body(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58: el proveedor del modelo con options recibe ese extra_body; el resto, ninguno."""
    set_options(models_data, LOCAL, {"think": False})
    factory = _openai_factory(make_config(tmp_path, models_data))

    local = factory(ModelChoice(*LOCAL))
    other = factory(ModelChoice(*GROQ))

    assert isinstance(local, OpenAICompatibleProvider)
    assert local._extra_body == {"think": False}
    assert isinstance(other, OpenAICompatibleProvider)
    assert other._extra_body == {}


def test_openai_factory_passes_extra_body_to_create_and_request(
    clean_env: pytest.MonkeyPatch,
    tmp_path: Path,
    models_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E · T-58: `create` recibe extra_body y la petición HTTP lleva "think": false."""
    set_options(models_data, LOCAL, {"think": False})
    calls: list[dict[str, Any]] = []
    requests: list[httpx.Request] = []
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
        calls.append({"provider": provider, "model": model, **kwargs})
        kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(handler))
        return original(cls, provider, model, base_url, api_key, **kwargs)

    monkeypatch.setattr(OpenAICompatibleProvider, "create", classmethod(spy_create))
    factory = _openai_factory(make_config(tmp_path, models_data))

    factory(ModelChoice(*LOCAL)).generate(MESSAGES, TaskType.CLASSIFY_SOURCE)
    factory(ModelChoice(*GROQ)).generate(MESSAGES, TaskType.GENERATE_STORY)

    assert calls[0]["extra_body"] == {"think": False}
    assert calls[1]["extra_body"] is None
    first, second = (json.loads(request.content) for request in requests)
    assert first["think"] is False
    assert "think" not in second


def test_openai_factory_sends_no_extra_body_for_model_outside_chains(
    clean_env: pytest.MonkeyPatch, tmp_path: Path, models_data: dict[str, Any]
) -> None:
    """E · T-58 (límite): un modelo elegido fuera de las cadenas no recibe options."""
    set_options(models_data, LOCAL, {"think": False})
    factory = _openai_factory(make_config(tmp_path, models_data))

    provider = factory(ModelChoice("local", "otro-modelo-ficticio"))

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._extra_body == {}
