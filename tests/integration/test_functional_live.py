"""Generación real de una HU con el RAG indexado y un LLM real (T-20: RF-15, RF-16, RF-21, RNF-14).

Se salta si no hay proveedor LLM utilizable para `generate_story` (modelo fijado y con clave,
o local accesible), si PostgreSQL/Ollama no responden o si el corpus no está indexado
(`uv run python -m core.rag.indexing`). No escribe en Jira.
"""

import httpx
import pytest

from adapters.base import RetrievedChunk, TaskType
from adapters.errors import AgentError
from core.config import AppConfig, build_config
from core.factories import build_embeddings, build_llm_provider, build_vector_store
from core.functional.context import StoryContext
from core.functional.writer import StoryWriter

pytestmark = pytest.mark.integration

TASK = TaskType.GENERATE_STORY
QUERY = "Reglas de reservas de ejemplares: máximo de reservas activas y plazo de recogida"
NEED = (
    "Como persona socia de la Biblioteca Municipal de Villaficticia quiero reservar un "
    "ejemplar desde la web para recogerlo en el mostrador (necesidad ficticia)."
)


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


@pytest.fixture
def retrieved(live_config: AppConfig) -> list[RetrievedChunk]:
    try:
        vector = build_embeddings(live_config).embed([QUERY])[0]
    except (AgentError, httpx.HTTPError, OSError) as exc:
        pytest.skip(f"Ollama no responde para los embeddings: {type(exc).__name__}.")
    try:
        hits = build_vector_store(live_config).search(vector, QUERY, live_config.models.rag.top_k)
    except (AgentError, OSError) as exc:
        pytest.skip(f"La base de datos vectorial no responde: {type(exc).__name__}.")
    if not hits:
        pytest.skip("El corpus no está indexado (uv run python -m core.rag.indexing).")
    return hits


def test_generate_cites_only_context_sources_when_live(
    live_config: AppConfig, retrieved: list[RetrievedChunk]
) -> None:
    """RF-15 · RF-16 · RF-21 · RNF-14: HU real con al menos un CA y citas solo del contexto."""
    ctx = StoryContext(origin_kind="need", need=NEED, rag=retrieved)
    allowed = {(s.kind, s.ref) for s in ctx.sources()}

    draft = StoryWriter(build_llm_provider(live_config)).generate(ctx)

    assert draft.story.acceptance_criteria
    assert draft.story.sources
    assert {(s.kind, s.ref) for s in draft.story.sources} <= allowed
    assert all(s.excerpt for s in draft.story.sources)
    assert draft.provider and draft.model
    assert draft.prompt_version
