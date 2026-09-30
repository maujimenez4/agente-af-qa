"""Servicio de contexto contra Jira, PostgreSQL + pgvector y Ollama reales (T-18: RF-11, RF-14).

SOLO LECTURA: no se llama a ningún método de escritura de Jira ni del almacén vectorial. Se
salta si faltan las variables de Jira o JIRA_PROJECT_KEY, si PostgreSQL u Ollama no responden
o si el corpus no está indexado (`uv run python -m core.rag.indexing`). Nunca se imprimen
valores del `.env`.
"""

from typing import Any

import pytest

from adapters.base import EmbeddingProvider, IssueTracker, RetrievedChunk, VectorStore
from core.config import AppConfig, build_config
from core.context.budget import estimate_tokens, issue_tokens
from core.context.service import ContextService, GatheredContext
from core.factories import build_embeddings, build_issue_tracker, build_vector_store

pytestmark = pytest.mark.integration

BUDGET = 6000
PROBE_QUERY = "reglamento de reservas"


@pytest.fixture(scope="module")
def live_config() -> AppConfig:
    return build_config()


@pytest.fixture(scope="module")
def project_key(live_config: AppConfig) -> str:
    settings = live_config.settings
    missing = [
        name
        for name, value in (
            ("JIRA_BASE_URL", settings.jira_base_url),
            ("JIRA_EMAIL", settings.jira_email),
            ("JIRA_API_TOKEN", settings.jira_api_token),
            ("JIRA_PROJECT_KEY", settings.jira_project_key),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"Faltan variables de Jira: {', '.join(missing)}")
    assert settings.jira_project_key is not None
    return settings.jira_project_key


@pytest.fixture(scope="module")
def tracker(live_config: AppConfig, project_key: str) -> IssueTracker:
    tracker = build_issue_tracker(live_config.settings)
    try:
        tracker.test_connection()
    except Exception as exc:
        pytest.skip(f"Jira no responde ({type(exc).__name__}).")
    return tracker


@pytest.fixture(scope="module")
def rag(live_config: AppConfig) -> tuple[EmbeddingProvider, VectorStore]:
    try:
        embeddings = build_embeddings(live_config)
        store = build_vector_store(live_config)
        (vector,) = embeddings.embed([PROBE_QUERY])
        probe = store.search(vector, PROBE_QUERY, k=1)
    except Exception as exc:
        pytest.skip(f"PostgreSQL u Ollama no disponibles ({type(exc).__name__}).")
    if not probe:
        pytest.skip("El corpus no está indexado: uv run python -m core.rag.indexing")
    return embeddings, store


@pytest.fixture(scope="module")
def service(
    live_config: AppConfig,
    project_key: str,
    tracker: IssueTracker,
    rag: tuple[EmbeddingProvider, VectorStore],
) -> ContextService:
    embeddings, store = rag
    return ContextService(
        tracker,
        embeddings,
        store,
        top_k=live_config.models.rag.top_k,
        memory_boost=live_config.models.rag.memory_boost,
        token_budget=BUDGET,
        project_key=project_key,
    )


def _doc_ids(chunks: list[RetrievedChunk]) -> set[str]:
    return {c.chunk.metadata.get("doc_id") or c.chunk.document_id for c in chunks}


def _used(context: GatheredContext) -> int:
    return sum(issue_tokens(i) for i in context.jira) + sum(
        estimate_tokens(c.chunk.content) for c in context.rag
    )


def test_need_about_reservation_hours_brings_norm_and_minutes(service: ContextService) -> None:
    """RF-11: la necesidad sobre las horas de bloqueo trae la norma (DOC-02) y su acta (DOC-19)."""
    origin: dict[str, Any] = {
        "kind": "need",
        "text": "¿Cuántas horas queda bloqueado un ejemplar reservado y qué acuerdo cambió "
        "ese plazo?",
    }
    context = service.gather(origin, None)

    assert {"DOC-02", "DOC-19"} <= _doc_ids(context.rag)
    assert context.budget.used <= BUDGET


def test_need_about_mobile_renewal_ranks_renewal_story_first(service: ContextService) -> None:
    """RF-14: «renovar un préstamo desde la aplicación móvil» → la primera HU es [HU-02]."""
    context = service.gather(
        {"kind": "need", "text": "renovar un préstamo desde la aplicación móvil"}, None
    )

    assert context.jira, "La búsqueda por palabras clave no devolvió ninguna HU."
    assert context.jira[0].summary.startswith("[HU-02]")


def test_story_origin_hu01_includes_its_epic_within_budget(
    service: ContextService, tracker: IssueTracker, project_key: str
) -> None:
    """RF-14, PA-07: origen HU-01 del seed → incluye su épica y respeta el presupuesto de 6000."""
    hu01 = next(
        (
            story
            for epic in tracker.list_epics(project_key)
            for story in tracker.list_children(epic.key)
            if story.summary.startswith("[HU-01]")
        ),
        None,
    )
    if hu01 is None:
        pytest.skip("El seed de Jira no está importado (no se encuentra [HU-01]).")
    origin_issue = tracker.get_issue(hu01.key)
    assert origin_issue.parent_key is not None

    context = service.gather({"kind": "story", "key": hu01.key}, origin_issue)

    keys = [i.key for i in context.jira]
    assert keys[0] == hu01.key
    assert origin_issue.parent_key in keys
    assert context.budget.used <= BUDGET
    assert _used(context) == context.budget.used
