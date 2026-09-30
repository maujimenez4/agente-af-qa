"""Generación real de la suite de QA con un LLM real (T-26: RF-22, RF-23, RF-24, RF-25).

Se salta si no hay proveedor LLM utilizable para `generate_tests` (modelo fijado —sin
POR_DEFINIR— y con clave, o local accesible). Usa la HU sintética de renovación de
Villaficticia y no escribe en Jira.
"""

import httpx
import pytest

from adapters.base import TaskType
from core.config import AppConfig, build_config
from core.factories import build_llm_provider
from core.qa.validation import suite_errors
from core.qa.writer import TestWriter
from tests.fakes import dataset

pytestmark = pytest.mark.integration

TASK = TaskType.GENERATE_TESTS


def _local_reachable(config: AppConfig, provider: str) -> bool:
    try:
        httpx.get(f"{config.base_url_for(provider)}/models", timeout=2.0)
    except httpx.HTTPError:
        return False
    return True


@pytest.fixture
def live_config() -> AppConfig:
    config = build_config()
    usable = [
        ref
        for ref in config.task_chain(TASK)  # solo proveedores con clave o locales
        if "POR_DEFINIR" not in ref.model
        and (
            config.api_key_for(ref.provider) is not None
            or (
                config.models.providers[ref.provider].api_key_env is None
                and _local_reachable(config, ref.provider)
            )
        )
    ]
    if not usable:
        pytest.skip(f"No hay ningún proveedor LLM utilizable para '{TASK.value}'.")
    return config


def test_generate_covers_renewal_story_when_live(live_config: AppConfig) -> None:
    """RF-22 · RF-23 · RF-24 · RF-25: suite real que cubre la HU sin errores de validación."""
    story = dataset.renewal_story()

    draft = TestWriter(build_llm_provider(live_config)).generate(story)

    assert suite_errors(draft.suite, story, []) == []
    assert draft.suite.story_jira_key == "DEMO-3"
    assert draft.coverage_md == draft.suite.coverage_md()
    assert draft.provider and draft.model
    assert draft.prompt_version
