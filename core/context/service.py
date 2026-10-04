"""Servicio de contexto del nodo `retrieve_context` (T-18, RF-11, RF-14, RF-51).

Reúne el contexto de Jira según el origen (HU, épica o necesidad nueva) y el del RAG, y lo
ajusta al presupuesto de tokens. Solo depende de protocolos de `adapters/base.py`.
"""

import unicodedata
from collections.abc import Collection, Iterable, Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel

from adapters.base import (
    EmbeddingProvider,
    IssueDetail,
    IssueSummary,
    IssueTracker,
    RetrievedChunk,
    VectorStore,
)
from adapters.errors import NotFoundError
from core.context.budget import BudgetReport, apply_budget, estimate_tokens
from core.context.jql import any_keyword_jql, keywords

if TYPE_CHECKING:
    from core.container import Container

MEMORY_CATEGORY = "memoria"
DEFAULT_TOKEN_BUDGET = 3300  # igual que `limits.context_token_budget` de models.yaml (PA-114)
# Tipos de incidencia que no son HU: no se proponen como «HU parecida» (T-53).
NOT_STORIES = frozenset({"epic", "épica", "subtarea", "sub-task", "subtask", "task", "tarea"})
EPIC_TYPES = frozenset({"epic", "épica"})
# Una norma y el acta que la cambió deben llegar juntas al LLM (hallazgo de T-17).
RELATED_PAIRS = {"politicas": "documentacion", "documentacion": "politicas"}  # T-49: normas ↔ actas
MAX_LINKED = 5
MAX_NEED_MATCHES = 3
MAX_NEED_CANDIDATES = 20
MAX_RELATED_DOCS = 4
MAX_RAG_SEARCH = 200  # tope de fragmentos pedidos al rellenar `top_k` (PA-197)


def type_key(issue_type: str) -> str:
    """Tipo de incidencia comparable (PA-223): NFC, sin espacios y en minúsculas."""
    return unicodedata.normalize("NFC", issue_type).strip().casefold()


def is_story(issue_type: str) -> bool:
    """`True` si el tipo puede ser una HU: no es épica, subtarea ni tarea (T-48, T-53)."""
    return type_key(issue_type) not in NOT_STORIES


class GatheredContext(BaseModel):
    jira: list[IssueDetail]
    rag: list[RetrievedChunk]
    budget: BudgetReport


def _detail_from_summary(summary: IssueSummary, parent_key: str | None) -> IssueDetail:
    """Hermanas sin petición extra: solo el resumen (el detalle se pide si hace falta)."""
    return IssueDetail(**summary.model_dump(), parent_key=parent_key)


def _related_ids(chunk: RetrievedChunk) -> list[str]:
    raw = chunk.chunk.metadata.get("related", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _doc_id(chunk: RetrievedChunk) -> str:
    return chunk.chunk.metadata.get("doc_id") or chunk.chunk.document_id


def _is_excluded(chunk: RetrievedChunk, excluded: Collection[str]) -> bool:
    """Fuente desmarcada por la persona, por su referencia citable o su id de documento."""
    return chunk.source.ref in excluded or _doc_id(chunk) in excluded


class ContextService:
    def __init__(
        self,
        tracker: IssueTracker,
        embeddings: EmbeddingProvider,
        store: VectorStore,
        *,
        top_k: int,
        memory_boost: float,
        token_budget: int,
        project_key: str | None = None,
    ) -> None:
        self._tracker = tracker
        self._embeddings = embeddings
        self._store = store
        self._top_k = top_k
        self._memory_boost = memory_boost
        self._token_budget = token_budget
        self._project_key = project_key

    def gather(
        self,
        origin: Mapping[str, str],
        origin_issue: IssueDetail | None,
        excluded: Collection[str] = (),
    ) -> GatheredContext:
        """`excluded`: fuentes desmarcadas por la persona (T-51); se quitan antes del presupuesto,
        así su espacio lo aprovechan las demás. La incidencia de origen nunca se excluye."""
        issues = self._jira_context(origin, origin_issue)
        query = origin.get("text") or " ".join(
            f"{i.summary} {i.description_text}" for i in issues[:1]
        )
        chunks = self._rag_context(query, set(excluded)) if query.strip() else []
        if excluded:
            origin_key = origin_issue.key if origin_issue else None
            issues = [i for i in issues if i.key == origin_key or i.key not in excluded]
        # El texto de la necesidad también viaja al LLM: se reserva su espacio.
        reserved = estimate_tokens(origin.get("text") or "")
        budget = max(self._token_budget - reserved, 0)
        jira, rag, report = apply_budget(
            issues, chunks, budget, has_origin=origin_issue is not None
        )
        return GatheredContext(jira=jira, rag=rag, budget=report)

    # --- Jira -------------------------------------------------------------------------------

    def _jira_context(
        self, origin: Mapping[str, str], origin_issue: IssueDetail | None
    ) -> list[IssueDetail]:
        """Incidencias por prioridad: origen, épica, vínculos, hermanas o hijas, relacionadas."""
        found: dict[str, IssueDetail] = {}

        def add(issue: IssueDetail) -> None:
            found.setdefault(issue.key, issue)

        if origin_issue is not None:
            add(origin_issue)
            if origin_issue.parent_key and (parent := self._safe_get(origin_issue.parent_key)):
                add(parent)
            for link in origin_issue.links[:MAX_LINKED]:
                if linked := self._safe_get(link.key):
                    add(linked)
            if origin["kind"] == "epic":
                children = self._tracker.list_children(origin_issue.key)
                for child in children:
                    add(_detail_from_summary(child, origin_issue.key))
            elif origin_issue.parent_key:
                for sibling in self._tracker.list_children(origin_issue.parent_key):
                    add(_detail_from_summary(sibling, origin_issue.parent_key))
        elif origin["kind"] == "need" and self._project_key:
            # §6.1: con una necesidad nueva se buscan HU que podría modificar.
            for match in self._related_to_need(origin.get("text", "")):
                add(self._safe_get(match.key) or _detail_from_summary(match, None))
        return list(found.values())

    def similar_stories(self, text: str, project: str) -> list[IssueSummary]:
        """HU del proyecto parecidas al texto, por búsqueda de texto en Jira y sin IA (T-53)."""
        stories = [
            issue for issue in self._ranked_candidates(text, project) if is_story(issue.issue_type)
        ]
        return stories[:MAX_NEED_MATCHES]  # se filtra antes de cortar

    def _related_to_need(self, text: str) -> list[IssueSummary]:
        """HU que podría modificar una necesidad: ni épicas ni subtareas (PA-166, D-09)."""
        stories = [issue for issue in self._ranked_candidates(text) if is_story(issue.issue_type)]
        return stories[:MAX_NEED_MATCHES]  # se filtra antes de cortar

    def _ranked_candidates(self, text: str, project: str | None = None) -> list[IssueSummary]:
        """Candidatas con alguna palabra clave, reordenadas por coincidencias en el título."""
        words = keywords(text)
        project = project or self._project_key
        if not words or not project:
            return []
        try:
            jql = any_keyword_jql(project, words)
        except ValueError:  # clave de proyecto no válida: sin búsqueda en Jira
            return []
        candidates = self._tracker.search(jql, limit=MAX_NEED_CANDIDATES)

        def overlap(issue: IssueSummary) -> int:
            title = issue.summary.lower()
            return sum(word in title for word in words)

        return sorted(candidates, key=overlap, reverse=True)  # estable: conserva el orden de Jira

    def _safe_get(self, key: str) -> IssueDetail | None:
        try:
            return self._tracker.get_issue(key)
        except NotFoundError:
            return None

    # --- RAG --------------------------------------------------------------------------------

    def _rag_context(self, query: str, excluded: set[str]) -> list[RetrievedChunk]:
        """Las fuentes excluidas se quitan antes del par norma ↔ acta y su hueco se rellena."""
        (vector,) = self._embeddings.embed([query])
        # PA-197: un documento excluido puede tener varios fragmentos; se amplía la búsqueda
        # hasta rellenar `top_k` o agotar los resultados (con un tope).
        k = max(self._top_k, min(self._top_k + len(excluded), MAX_RAG_SEARCH))
        while True:
            found = self._store.search(vector, query, k=k, memory_boost=self._memory_boost)
            results = [r for r in found if not _is_excluded(r, excluded)][: self._top_k]
            if len(results) >= self._top_k or len(found) < k or k >= MAX_RAG_SEARCH:
                break
            k = min(k * 2, MAX_RAG_SEARCH)
        results += self._related_documents(vector, query, results, excluded)
        # Memorias primero (RF-51); después, el resto por puntuación.
        return sorted(
            results,
            key=lambda r: (r.chunk.metadata.get("category") != MEMORY_CATEGORY, -r.score),
        )

    def _related_documents(
        self,
        vector: list[float],
        query: str,
        results: Iterable[RetrievedChunk],
        excluded: Collection[str] = (),
    ) -> list[RetrievedChunk]:
        """Añade el acta citada por una norma recuperada (y viceversa) si aún no está."""
        results = list(results)
        present = {_doc_id(r) for r in results} | set(excluded)
        extra: list[RetrievedChunk] = []
        for result in results:
            wanted = RELATED_PAIRS.get(result.chunk.metadata.get("category", ""))
            if not wanted:
                continue
            for doc_id in _related_ids(result):
                if doc_id in present or len(extra) >= MAX_RELATED_DOCS:
                    continue
                best = self._store.search(
                    vector, query, k=1, filters={"doc_id": doc_id, "category": wanted}
                )
                if best and not _is_excluded(best[0], excluded):
                    extra.append(best[0])
                    present.add(doc_id)
        return extra


def build_context_service(container: "Container", project: str | None) -> ContextService:
    """`ContextService` con la configuración del contenedor; lo usan el grafo y T-53."""
    config = container.config
    return ContextService(
        container.issue_tracker,
        container.embeddings,
        container.vector_store,
        top_k=container.top_k,
        memory_boost=container.memory_boost,
        token_budget=(
            config.models.limits.context_token_budget if config else DEFAULT_TOKEN_BUDGET
        ),
        project_key=project,
    )
