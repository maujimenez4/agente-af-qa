"""Servicio de contexto del nodo `retrieve_context` (T-18: RF-11, RF-14, RF-51).

Cubre `core/context/service.py` (prioridad de Jira, necesidad nueva, RAG con memorias y pares
norma↔acta, presupuesto) y la delegación desde `core/graph/nodes.py`. Solo fakes de
`tests/fakes/` (con espías finos definidos aquí); datos 100 % ficticios.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import structlog

from adapters.base import Chunk, IssueDetail, IssueLink, IssueSummary, RetrievedChunk
from core.config import AppConfig, Settings, load_models_config
from core.context.budget import issue_tokens
from core.context.service import (
    MAX_LINKED,
    MAX_NEED_MATCHES,
    MAX_RELATED_DOCS,
    ContextService,
)
from core.graph import initial_state
from core.graph.nodes import GraphNodes
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.vector_store import FakeVectorStore

STORY_ORIGIN = {"kind": "story", "key": "DEMO-3"}
EPIC_ORIGIN = {"kind": "epic", "key": "DEMO-1"}


# --- espías sobre los fakes ------------------------------------------------------------------


@dataclass
class SpyIssueTracker(FakeIssueTracker):
    """FakeIssueTracker que cuenta `get_issue` y registra (o sustituye) `search`."""

    get_calls: list[str] = field(default_factory=list)
    searches: list[tuple[str, int]] = field(default_factory=list)
    search_results: list[IssueSummary] | None = None

    def get_issue(self, key: str) -> IssueDetail:
        self.get_calls.append(key)
        return super().get_issue(key)

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        self.searches.append((jql, limit))
        if self.search_results is not None:
            return list(self.search_results)
        return super().search(jql, limit)


@dataclass
class SpyEmbeddings(FakeEmbeddingProvider):
    calls: list[list[str]] = field(default_factory=list)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return super().embed(texts)


@dataclass
class SpyVectorStore(FakeVectorStore):
    calls: list[dict[str, Any]] = field(default_factory=list)

    def search(
        self,
        query_vector: list[float],
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
        memory_boost: float = 1.0,
    ) -> list[RetrievedChunk]:
        self.calls.append({"k": k, "filters": filters, "memory_boost": memory_boost})
        return super().search(query_vector, query_text, k, filters, memory_boost)


# --- utilidades --------------------------------------------------------------------------------


def add_doc(
    store: FakeVectorStore,
    embeddings: FakeEmbeddingProvider,
    doc_id: str,
    category: str,
    content: str,
    related: str = "",
) -> None:
    metadata = {"category": category, "doc_id": doc_id}
    if related:
        metadata["related"] = related
    (vector,) = embeddings.embed([content])
    store.upsert(
        [
            Chunk(
                id=f"{doc_id}#0",
                document_id=doc_id,
                ordinal=0,
                content=content,
                embedding=vector,
                metadata=metadata,
            )
        ]
    )


def make_service(
    tracker: FakeIssueTracker | None = None,
    embeddings: FakeEmbeddingProvider | None = None,
    store: FakeVectorStore | None = None,
    *,
    top_k: int = 6,
    memory_boost: float = 1.0,
    token_budget: int = 6000,
    project_key: str | None = None,
) -> ContextService:
    return ContextService(
        tracker or SpyIssueTracker(),
        embeddings or SpyEmbeddings(),
        store if store is not None else SpyVectorStore(),
        top_k=top_k,
        memory_boost=memory_boost,
        token_budget=token_budget,
        project_key=project_key,
    )


def summary(key: str, title: str) -> IssueSummary:
    return IssueSummary(key=key, summary=title, issue_type="Story", status="Por hacer")


def doc_ids(chunks: list[RetrievedChunk]) -> list[str]:
    return [c.chunk.metadata.get("doc_id") or c.chunk.document_id for c in chunks]


def rag_fixture() -> tuple[SpyEmbeddings, SpyVectorStore]:
    """Corpus ficticio: norma ↔ acta relacionadas, un glosario y una memoria."""
    embeddings = SpyEmbeddings()
    store = SpyVectorStore()
    add_doc(
        store,
        embeddings,
        "DOC-A",
        "politicas",
        "Norma ficticia: las reservas quedan bloqueadas cuarenta y ocho horas en mostrador.",
        related="DOC-B, DOC-G",
    )
    add_doc(
        store,
        embeddings,
        "DOC-B",
        "documentacion",
        "Acta ficticia de la comisión: acuerdo sobre plazos y calendario anual.",
        related="DOC-A",
    )
    add_doc(
        store,
        embeddings,
        "DOC-G",
        "glosarios",
        "Glosario ficticio: término, definición y sinónimo.",
    )
    add_doc(
        store,
        embeddings,
        "memoria-DEMO-9",
        "memoria",
        "Memoria ficticia de una historia publicada sobre el catálogo en línea.",
    )
    return embeddings, store


# --- Jira: origen HU ----------------------------------------------------------------------------


def test_gather_story_origin_puts_origin_first_then_epic_links_and_siblings() -> None:
    """RF-14: origen HU → origen, épica padre, vínculos y hermanas, en ese orden y sin duplicar."""
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)
    context = make_service(tracker).gather(STORY_ORIGIN, origin)

    keys = [i.key for i in context.jira]
    assert keys == ["DEMO-3", "DEMO-1", "DEMO-2", "DEMO-4"]
    assert len(keys) == len(set(keys))


def test_gather_story_origin_siblings_do_not_trigger_extra_get_issue() -> None:
    """RF-14 (eficiencia): las hermanas se añaden como resumen, sin pedir su detalle."""
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)
    context = make_service(tracker).gather(STORY_ORIGIN, origin)

    assert sorted(tracker.get_calls) == ["DEMO-1", "DEMO-2"]
    sibling = next(i for i in context.jira if i.key == "DEMO-4")
    assert sibling.description_text == ""
    assert sibling.parent_key == dataset.EPIC_KEY
    assert sibling.summary == dataset.STORIES["DEMO-4"].summary


def test_gather_story_origin_linked_issue_keeps_full_detail() -> None:
    """RF-14: la incidencia vinculada llega con su descripción (se pidió con get_issue)."""
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)
    context = make_service(tracker).gather(STORY_ORIGIN, origin)

    linked = next(i for i in context.jira if i.key == "DEMO-2")
    assert linked.description_text == dataset.STORIES["DEMO-2"].description_text


def test_gather_story_origin_limits_links_to_max_linked() -> None:
    """RF-14 (límite): como mucho MAX_LINKED (5) vínculos se consultan."""
    tracker = SpyIssueTracker()
    for n in range(10, 17):
        tracker.issues[f"DEMO-{n}"] = IssueDetail(
            key=f"DEMO-{n}", summary=f"HU ficticia {n}", issue_type="Story", status="Por hacer"
        )
    origin = IssueDetail(
        key="DEMO-50",
        summary="HU ficticia con muchos vínculos",
        issue_type="Story",
        status="Por hacer",
        links=[IssueLink(link_type="relates to", key=f"DEMO-{n}") for n in range(10, 17)],
    )
    context = make_service(tracker).gather(STORY_ORIGIN, origin)

    assert MAX_LINKED == 5
    assert tracker.get_calls == [f"DEMO-{n}" for n in range(10, 15)]
    assert [i.key for i in context.jira] == ["DEMO-50", *[f"DEMO-{n}" for n in range(10, 15)]]


def test_gather_missing_parent_epic_is_skipped_without_failing() -> None:
    """RF-14 (error): épica padre inexistente (NotFoundError) se omite y el resto continúa."""
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-3"].model_copy(update={"parent_key": "DEMO-99"}, deep=True)
    context = make_service(tracker).gather(STORY_ORIGIN, origin)

    keys = [i.key for i in context.jira]
    assert keys == ["DEMO-3", "DEMO-2"]
    assert "DEMO-99" in tracker.get_calls


def test_gather_missing_linked_issue_is_skipped_without_failing() -> None:
    """RF-14 (error): un vínculo a una incidencia inexistente se omite."""
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-3"].model_copy(
        update={"links": [IssueLink(link_type="relates to", key="DEMO-98")]}, deep=True
    )
    keys = [i.key for i in make_service(tracker).gather(STORY_ORIGIN, origin).jira]
    assert "DEMO-98" not in keys
    assert keys[0] == "DEMO-3"


def test_gather_story_without_parent_or_links_returns_only_origin() -> None:
    """RF-14 (límite): HU suelta → solo el origen, sin llamadas extra a Jira."""
    tracker = SpyIssueTracker()
    origin = IssueDetail(
        key="DEMO-60", summary="HU ficticia suelta", issue_type="Story", status="Por hacer"
    )
    context = make_service(tracker).gather(STORY_ORIGIN, origin)
    assert [i.key for i in context.jira] == ["DEMO-60"]
    assert tracker.get_calls == []


# --- Jira: origen épica ------------------------------------------------------------------------


def test_gather_epic_origin_includes_epic_and_its_children() -> None:
    """RF-14: origen épica → la épica primero y después sus HU hijas (como resumen)."""
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-1"].model_copy(deep=True)
    context = make_service(tracker).gather(EPIC_ORIGIN, origin)

    assert [i.key for i in context.jira] == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]
    assert all(i.parent_key == "DEMO-1" for i in context.jira[1:])
    assert tracker.get_calls == []


# --- Jira: necesidad nueva ------------------------------------------------------------------------


def test_gather_need_searches_with_keywords_jql() -> None:
    """RF-14, §6.1: con necesidad nueva se busca en Jira con las palabras clave (OR)."""
    tracker = SpyIssueTracker(search_results=[])
    origin = {"kind": "need", "text": "Como persona socia quiero renovar un préstamo vencido"}
    make_service(tracker, project_key="DEMO").gather(origin, None)

    assert len(tracker.searches) == 1
    jql, limit = tracker.searches[0]
    assert jql.startswith('project = "DEMO" AND text ~ ')
    assert "renovar OR préstamo OR vencido" in jql
    assert "quiero" not in jql
    assert limit >= MAX_NEED_MATCHES


def test_gather_need_reorders_by_title_matches_and_limits_to_three() -> None:
    """RF-14: candidatas reordenadas por coincidencias en el título (estable) y máximo 3."""
    tracker = SpyIssueTracker(
        search_results=[
            summary("DEMO-20", "Consultar horarios ficticios"),
            summary("DEMO-21", "Renovar préstamo digital"),
            summary("DEMO-22", "Aviso de préstamo"),
            summary("DEMO-23", "Renovar un préstamo vencido"),
            summary("DEMO-24", "Renovar el carné"),
        ]
    )
    origin = {"kind": "need", "text": "renovar préstamo vencido"}
    context = make_service(tracker, project_key="DEMO").gather(origin, None)

    assert MAX_NEED_MATCHES == 3
    assert [i.key for i in context.jira] == ["DEMO-23", "DEMO-21", "DEMO-22"]


def test_gather_need_ties_keep_jira_order() -> None:
    """RF-14 (límite): con el mismo número de coincidencias se conserva el orden de Jira."""
    tracker = SpyIssueTracker(
        search_results=[summary(f"DEMO-{n}", "Renovar préstamo") for n in range(30, 35)]
    )
    origin = {"kind": "need", "text": "renovar préstamo"}
    context = make_service(tracker, project_key="DEMO").gather(origin, None)
    assert [i.key for i in context.jira] == ["DEMO-30", "DEMO-31", "DEMO-32"]


def test_gather_need_uses_detail_when_issue_exists_and_summary_otherwise() -> None:
    """RF-14: la coincidencia se enriquece con get_issue; si no existe, queda su resumen."""
    tracker = SpyIssueTracker(
        search_results=[
            summary("DEMO-3", dataset.STORIES["DEMO-3"].summary),
            summary("DEMO-97", "Renovar un préstamo ficticio"),
        ]
    )
    origin = {"kind": "need", "text": "renovar préstamo"}
    context = make_service(tracker, project_key="DEMO").gather(origin, None)

    by_key = {i.key: i for i in context.jira}
    assert by_key["DEMO-3"].description_text == dataset.STORIES["DEMO-3"].description_text
    assert by_key["DEMO-97"].description_text == ""
    assert by_key["DEMO-97"].summary == "Renovar un préstamo ficticio"


def test_gather_need_with_default_fake_search_finds_renewal_story() -> None:
    """RF-14: contra el fake por defecto, una palabra clave localiza la HU del dataset."""
    tracker = SpyIssueTracker()
    origin = {"kind": "need", "text": "renovaciones"}
    context = make_service(tracker, project_key="DEMO").gather(origin, None)
    assert [i.key for i in context.jira] == ["DEMO-3"]


def test_gather_need_without_project_key_skips_jira() -> None:
    """RF-14: sin clave de proyecto, una necesidad nueva no consulta Jira."""
    tracker = SpyIssueTracker()
    origin = {"kind": "need", "text": "renovar préstamo vencido"}
    context = make_service(tracker, project_key=None).gather(origin, None)
    assert context.jira == []
    assert tracker.searches == []
    assert tracker.get_calls == []


@pytest.mark.parametrize(
    "text",
    ["como quiero para que", "a b c 12 345", "¿¡!?", "sistema usuario persona socia"],
)
def test_gather_need_without_meaningful_words_skips_search(text: str) -> None:
    """RF-14 (límite): sin palabras significativas no se lanza ninguna búsqueda en Jira."""
    tracker = SpyIssueTracker()
    context = make_service(tracker, project_key="DEMO").gather({"kind": "need", "text": text}, None)
    assert tracker.searches == []
    assert context.jira == []


# --- RAG ---------------------------------------------------------------------------------------


def test_gather_rag_puts_memories_first() -> None:
    """RF-51: las memorias van delante del resto aunque puntúen menos."""
    embeddings, store = rag_fixture()
    origin = {"kind": "need", "text": "reservas bloqueadas horas mostrador catálogo"}
    context = make_service(embeddings=embeddings, store=store, top_k=4).gather(origin, None)

    assert context.rag[0].chunk.metadata["category"] == "memoria"
    others = [r.score for r in context.rag[1:]]
    assert others == sorted(others, reverse=True)


def test_gather_rag_passes_top_k_and_memory_boost_to_store() -> None:
    """RF-11, RF-51: la búsqueda principal usa top_k y memory_boost del servicio."""
    embeddings, store = rag_fixture()
    make_service(embeddings=embeddings, store=store, top_k=3, memory_boost=1.5).gather(
        {"kind": "need", "text": "reservas bloqueadas"}, None
    )
    main = store.calls[0]
    assert main == {"k": 3, "filters": None, "memory_boost": 1.5}


def test_gather_rag_norm_adds_related_minutes_with_filters() -> None:
    """RF-11: una norma recuperada trae su acta relacionada (filtros doc_id + category)."""
    embeddings, store = rag_fixture()
    origin = {"kind": "need", "text": "reservas bloqueadas cuarenta ocho horas mostrador"}
    context = make_service(embeddings=embeddings, store=store, top_k=1).gather(origin, None)

    assert doc_ids(context.rag) == ["DOC-A", "DOC-B"]
    related_calls = [c for c in store.calls if c["filters"]]
    expected = {"doc_id": "DOC-B", "category": "documentacion"}
    assert {"k": 1, "filters": expected, "memory_boost": 1.0} in related_calls
    # DOC-G (glosario) figura en `related` pero no es un acta: no se añade.
    assert {"doc_id": "DOC-G", "category": "documentacion"} in [c["filters"] for c in related_calls]


def test_gather_rag_minutes_add_related_norm() -> None:
    """RF-11: un acta recuperada trae la norma que modifica (y viceversa)."""
    embeddings, store = rag_fixture()
    origin = {"kind": "need", "text": "acta comisión acuerdo plazos calendario anual"}
    context = make_service(embeddings=embeddings, store=store, top_k=1).gather(origin, None)

    assert doc_ids(context.rag) == ["DOC-B", "DOC-A"]
    assert {"doc_id": "DOC-A", "category": "politicas"} in [c["filters"] for c in store.calls]


def test_gather_rag_does_not_duplicate_already_retrieved_related_docs() -> None:
    """RF-11: si la norma y el acta ya se recuperaron, no se repiten ni se buscan otra vez."""
    embeddings, store = rag_fixture()
    origin = {"kind": "need", "text": "reservas bloqueadas acta comisión acuerdo plazos"}
    context = make_service(embeddings=embeddings, store=store, top_k=4).gather(origin, None)

    ids = doc_ids(context.rag)
    assert len(ids) == len(set(ids))
    filters = [c["filters"] for c in store.calls if c["filters"]]
    assert {"doc_id": "DOC-B", "category": "documentacion"} not in filters
    assert {"doc_id": "DOC-A", "category": "politicas"} not in filters


def test_gather_rag_related_docs_are_capped_at_four() -> None:
    """RF-11 (límite): como mucho MAX_RELATED_DOCS (4) documentos relacionados se añaden."""
    embeddings = SpyEmbeddings()
    store = SpyVectorStore()
    minutes = [f"ACT-{n}" for n in range(1, 8)]
    add_doc(
        store,
        embeddings,
        "NORM-1",
        "politicas",
        "Norma ficticia sobre sanciones por retraso en devoluciones.",
        related=", ".join(minutes),
    )
    for n, doc_id in enumerate(minutes, start=1):
        text = f"Acta ficticia número {n} de la comisión."
        add_doc(store, embeddings, doc_id, "documentacion", text)
    origin = {"kind": "need", "text": "sanciones retraso devoluciones"}
    context = make_service(embeddings=embeddings, store=store, top_k=1).gather(origin, None)

    assert MAX_RELATED_DOCS == 4
    assert doc_ids(context.rag) == ["NORM-1", *minutes[:4]]


def test_gather_rag_ignores_related_of_other_categories() -> None:
    """RF-11: solo politicas ↔ documentacion; un glosario con `related` no busca más."""
    embeddings = SpyEmbeddings()
    store = SpyVectorStore()
    add_doc(
        store,
        embeddings,
        "GLO-1",
        "glosarios",
        "Glosario ficticio de términos de préstamo.",
        related="ACT-1",
    )
    add_doc(store, embeddings, "ACT-1", "documentacion", "Acta ficticia sin relación léxica.")
    origin = {"kind": "need", "text": "glosario términos préstamo"}
    context = make_service(embeddings=embeddings, store=store, top_k=1).gather(origin, None)
    assert doc_ids(context.rag) == ["GLO-1"]
    assert len(store.calls) == 1


def test_gather_empty_query_skips_rag() -> None:
    """RF-11 (límite): sin texto de consulta no se calculan embeddings ni se busca en el RAG."""
    embeddings, store = rag_fixture()
    embeddings.calls.clear()
    for text in ("", "   "):
        context = make_service(embeddings=embeddings, store=store).gather(
            {"kind": "need", "text": text}, None
        )
        assert context.rag == []
    assert embeddings.calls == []
    assert store.calls == []


def test_gather_story_origin_uses_origin_text_as_rag_query() -> None:
    """RF-11: con origen HU, la consulta al RAG es el resumen y la descripción del origen."""
    embeddings, store = rag_fixture()
    embeddings.calls.clear()
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-3"]
    make_service(tracker, embeddings, store).gather(STORY_ORIGIN, origin)
    assert embeddings.calls == [[f"{origin.summary} {origin.description_text}"]]


# --- presupuesto ----------------------------------------------------------------------------------


def test_gather_applies_token_budget_and_reports_it() -> None:
    """PA-07, RF-11: el contexto reunido respeta el presupuesto y lo informa."""
    embeddings, store = rag_fixture()
    tracker = SpyIssueTracker()
    origin = tracker.issues["DEMO-3"]
    budget = 120
    context = make_service(tracker, embeddings, store, token_budget=budget).gather(
        STORY_ORIGIN, origin
    )
    assert context.budget.budget == budget
    assert context.budget.used <= budget
    assert context.jira[0].key == "DEMO-3"
    used = sum(issue_tokens(i) for i in context.jira) + sum(
        len(c.chunk.content) // 4 for c in context.rag
    )
    assert used <= budget


def test_gather_large_budget_keeps_everything() -> None:
    """PA-07: con presupuesto holgado no se descarta ni se recorta nada."""
    embeddings, store = rag_fixture()
    tracker = SpyIssueTracker()
    context = make_service(tracker, embeddings, store, token_budget=100_000).gather(
        STORY_ORIGIN, tracker.issues["DEMO-3"]
    )
    report = context.budget
    assert (report.dropped_issues, report.dropped_chunks, report.truncated_issues) == (0, 0, 0)
    assert len(context.jira) == 4


# --- grafo: retrieve_context delega en ContextService --------------------------------------------


@pytest.fixture
def restore_logging() -> Iterator[None]:
    levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore", "openai")}
    yield
    structlog.reset_defaults()
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


def _app_config(budget: int | None = None, groq_budget: int | None = None) -> AppConfig:
    """`config/models.yaml` con el presupuesto global (`budget`) o el del proveedor `groq`
    (`groq_budget`, PA-443: el de las tareas de HU) sustituidos."""
    models = load_models_config()
    if budget is not None:
        limits = models.limits.model_copy(update={"context_token_budget": budget})
        models = models.model_copy(update={"limits": limits})
    if groq_budget is not None:
        groq = models.providers["groq"]
        assert groq.limits is not None
        own = groq.limits.model_copy(update={"context_token_budget": groq_budget})
        providers = {**models.providers, "groq": groq.model_copy(update={"limits": own})}
        models = models.model_copy(update={"providers": providers})
    return AppConfig(Settings(_env_file=None), models)


def test_retrieve_context_node_respects_config_budget(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, restore_logging: None
) -> None:
    """PA-07 · PA-443: con AppConfig, el nodo usa el `context_token_budget` del proveedor de
    la tarea (evolucionar una HU → groq); el origen entra entero (PA-442) y, si se come el
    presupuesto, no entra ninguna fuente opcional."""
    container = fake_container(tmp_path, config=_app_config(budget=100_000, groq_budget=60))
    nodes = GraphNodes(container)
    state = initial_state("af-demo", "functional", STORY_ORIGIN)  # type: ignore[arg-type]
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]
    origin = state["jira_context"][0]
    assert issue_tokens(origin) > 60

    update = nodes.retrieve_context(state)

    assert update["jira_context"] == [origin]  # entero, sin recortar
    assert update["rag_context"] == []
    # con el presupuesto global (100 000) habrían entrado las 4 HU del fake


def test_retrieve_context_node_default_config_keeps_full_context(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, restore_logging: None
) -> None:
    """PA-07 · PA-114 · PA-443: con el presupuesto de config/models.yaml para evolucionar una HU
    (el de groq, 2000) entran las HU del fake."""
    config = _app_config()
    assert config.models.context_budget_for(["groq", "local"]) == 2000
    nodes = GraphNodes(fake_container(tmp_path, config=config))
    state = initial_state("af-demo", "functional", STORY_ORIGIN)  # type: ignore[arg-type]
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    update = nodes.retrieve_context(state)
    assert sorted(i.key for i in update["jira_context"]) == ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"]
    assert update["rag_context"]


def test_retrieve_context_node_uses_origin_project_over_config_for_need(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, restore_logging: None
) -> None:
    """RF-14 · T-50: una necesidad busca HU en el proyecto de la conversación, no en `.env`."""
    clean_env.setenv("JIRA_PROJECT_KEY", "OTRO")
    tracker = SpyIssueTracker()
    container = fake_container(tmp_path, config=_app_config(), issue_tracker=tracker)
    nodes = GraphNodes(container)
    origin = {"kind": "need", "text": "renovaciones", "project": "DEMO"}  # AND de palabras
    state = initial_state("af-demo", "functional", origin)  # type: ignore[arg-type]
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    update = nodes.retrieve_context(state)

    assert len(tracker.searches) == 1
    assert tracker.searches[0][0].startswith('project = "DEMO"')
    assert [i.key for i in update["jira_context"]] == ["DEMO-3"]


def test_retrieve_context_node_without_config_uses_origin_project_for_need(
    tmp_path: Path,
) -> None:
    """RF-14 · T-50: sin AppConfig, la necesidad sigue buscando en el proyecto del origen."""
    tracker = SpyIssueTracker()
    nodes = GraphNodes(fake_container(tmp_path, issue_tracker=tracker))
    origin = {"kind": "need", "text": "renovar un préstamo", "project": "OTRO"}
    state = initial_state("af-demo", "functional", origin)  # type: ignore[arg-type]
    state.update(nodes.load_origin(state))  # type: ignore[typeddict-item]

    nodes.retrieve_context(state)

    assert len(tracker.searches) == 1
    assert tracker.searches[0][0].startswith('project = "OTRO" AND text ~ ')
