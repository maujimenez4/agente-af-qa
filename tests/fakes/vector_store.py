"""Fake de VectorStore en memoria: coseno + filtros por metadatos + prioridad de memorias."""

import math
from dataclasses import dataclass, field

from adapters.base import Chunk, RetrievedChunk
from schemas.common import SourceRef

MEMORY_CATEGORY = "memoria"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


@dataclass
class FakeVectorStore:
    chunks: dict[str, Chunk] = field(default_factory=dict)

    def upsert(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"El fragmento {chunk.id} no tiene embedding.")
            self.chunks[chunk.id] = chunk.model_copy(deep=True)

    def delete_by_document(self, document_id: str) -> None:
        self.chunks = {k: c for k, c in self.chunks.items() if c.document_id != document_id}

    def has_document(self, document_id: str) -> bool:
        return any(c.document_id == document_id for c in self.chunks.values())

    def replace_document(self, document_id: str, chunks: list[Chunk]) -> None:
        """Como `PgVectorStore.replace_document` (PA-216): todo o nada."""
        for chunk in chunks:
            if chunk.document_id != document_id:
                raise ValueError(f"El fragmento {chunk.id} no es del documento {document_id}.")
        previous = dict(self.chunks)
        try:
            self.delete_by_document(document_id)
            self.upsert(chunks)
        except Exception:
            self.chunks = previous
            raise

    def search(
        self,
        query_vector: list[float],
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
        memory_boost: float = 1.0,
    ) -> list[RetrievedChunk]:
        words = {w for w in query_text.lower().split() if len(w) > 2}
        results = []
        for chunk in self.chunks.values():
            if filters and any(chunk.metadata.get(key) != value for key, value in filters.items()):
                continue
            score = _cosine(query_vector, chunk.embedding or [])
            # Componente léxica mínima, como la parte tsvector de la búsqueda híbrida.
            if words and words & set(chunk.content.lower().split()):
                score += 0.1
            is_memory = chunk.metadata.get("category") == MEMORY_CATEGORY
            if is_memory:
                score *= memory_boost  # RF-51
            source = SourceRef(
                kind="memory" if is_memory else "rag",
                ref=chunk.document_id,
                excerpt=chunk.content[:120],
            )
            results.append(RetrievedChunk(chunk=chunk, score=score, source=source))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]
