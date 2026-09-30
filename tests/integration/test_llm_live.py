"""Llamada real a un proveedor LLM (T-10: RF-40, RF-43, RF-44).

Se salta si ningún proveedor de la cadena de `classify_source` está disponible en la
configuración (`.env` + `config/models.yaml`). Solo hace una llamada `generate` mínima.
"""

import httpx
import pytest

from adapters.base import Message, TaskType
from adapters.llm.usage import InMemoryUsageRecorder
from core.config import AppConfig, build_config
from core.factories import build_llm_provider

pytestmark = pytest.mark.integration

TASK = TaskType.CLASSIFY_SOURCE


def _local_reachable(config: AppConfig, provider: str) -> bool:
    try:
        httpx.get(f"{config.base_url_for(provider)}/models", timeout=2.0)
    except httpx.HTTPError:
        return False
    return True


@pytest.fixture
def live_config() -> AppConfig:
    config = build_config()
    # Modelos sin fijar (T-08) y proveedores sin clave cuyo servidor local no responde.
    usable = [
        ref
        for ref in config.task_chain(TASK)
        if "POR_DEFINIR" not in ref.model
        and (
            config.models.providers[ref.provider].api_key_env is not None
            or _local_reachable(config, ref.provider)
        )
    ]
    if not usable:
        pytest.skip(f"No hay ningún proveedor LLM utilizable para '{TASK.value}'.")
    return config


def test_generate_returns_content_and_records_usage_when_live(live_config: AppConfig) -> None:
    """RF-40 · RF-43: una llamada real devuelve contenido y deja un registro de uso."""
    recorder = InMemoryUsageRecorder()
    provider = build_llm_provider(live_config, recorder)

    result = provider.generate(
        [Message(role="user", content="Responde solo con la palabra: listo")], TASK
    )

    assert result.content.strip()
    assert len(recorder.records) == 1
    usage = recorder.records[0]
    assert usage.task == TASK
    assert usage.provider == result.provider
    assert usage.total_tokens > 0
