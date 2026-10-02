"""VectorStore sobre PostgreSQL + pgvector con búsqueda híbrida (RF-10, RF-11, RF-51).

- Vectorial: similitud coseno sobre `chunks.embedding` (índice HNSW).
- Texto completo: `chunks.tsv` en español con `websearch_to_tsquery`.
- Fusión por *Reciprocal Rank Fusion* y prioridad multiplicativa de las memorias.

El protocolo usa ids de texto (p. ej. `memoria-DEMO-3`) y la base de datos usa UUID: el id se
convierte con `uuid5` y el original se guarda en `metadata` para devolverlo tal cual.
"""

import json
import math
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from adapters.base import Chunk, RetrievedChunk
from adapters.errors import ExternalServiceError
from schemas.common import SourceRef

SERVICE = "postgres"
MEMORY_CATEGORY = "memoria"
_NAMESPACE = uuid.UUID("5b0b6a0e-6f0e-4c63-9a52-7a3f2d8c1e41")  # fijo: no cambiar
_CHUNK_KEY = "_chunk_id"
_DOCUMENT_KEY = "_document_id"
_RESERVED = {_CHUNK_KEY, _DOCUMENT_KEY}
EXCERPT_CHARS = 200

_UPSERT_DOCUMENT = sa.text(
    """
    INSERT INTO documents (id, title, category, source_path, embedding_model, content_hash,
                           related_key)
    VALUES (:id, :title, :category, :source_path, :embedding_model, :content_hash, :related_key)
    ON CONFLICT (id) DO UPDATE SET
        title = EXCLUDED.title, category = EXCLUDED.category,
        source_path = EXCLUDED.source_path, embedding_model = EXCLUDED.embedding_model,
        content_hash = EXCLUDED.content_hash, related_key = EXCLUDED.related_key
    """
)

_UPSERT_CHUNK = sa.text(
    """
    INSERT INTO chunks (id, document_id, ordinal, section, content, embedding, metadata)
    VALUES (:id, :document_id, :ordinal, :section, :content, CAST(:embedding AS vector),
            CAST(:metadata AS jsonb))
    ON CONFLICT (document_id, ordinal) DO UPDATE SET
        id = EXCLUDED.id, section = EXCLUDED.section, content = EXCLUDED.content,
        embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata
    """
)

_DELETE_DOCUMENT = sa.text("DELETE FROM documents WHERE id = :id")

_SEARCH = sa.text(
    """
    WITH q AS (
        SELECT CAST(:query_vector AS vector) AS v, websearch_to_tsquery('spanish', :query_text) AS t
    ),
    candidates AS (
        SELECT c.id, c.embedding, c.tsv
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE d.embedding_model = :embedding_model
          AND (CAST(:filters AS jsonb) IS NULL OR c.metadata @> CAST(:filters AS jsonb))
    ),
    vec AS (
        SELECT id, row_number() OVER (ORDER BY distance) AS rank
        FROM (
            SELECT c.id, c.embedding <=> q.v AS distance
            FROM candidates c, q
            WHERE c.embedding IS NOT NULL
            ORDER BY distance
            LIMIT :candidates
        ) nearest
    ),
    txt AS (
        SELECT id, row_number() OVER (ORDER BY relevance DESC) AS rank
        FROM (
            SELECT c.id, ts_rank_cd(c.tsv, q.t) AS relevance
            FROM candidates c, q
            WHERE c.tsv @@ q.t
            ORDER BY relevance DESC
            LIMIT :candidates
        ) matches
    ),
    fused AS (
        SELECT id, SUM(1.0 / (:rrf_k + rank)) AS score
        FROM (SELECT id, rank FROM vec UNION ALL SELECT id, rank FROM txt) ranked
        GROUP BY id
    )
    SELECT c.id AS chunk_uuid, d.id AS document_uuid, c.ordinal, c.section, c.content,
           c.metadata, d.category,
           f.score * CASE WHEN d.category = :memory_category THEN :memory_boost ELSE 1.0 END
               AS score
    FROM fused f
    JOIN chunks c ON c.id = f.id
    JOIN documents d ON d.id = c.document_id
    ORDER BY score DESC, c.ordinal
    LIMIT :k
    """
)


def to_uuid(key: str) -> uuid.UUID:
    """UUID determinista para un id de texto del protocolo."""
    return uuid.uuid5(_NAMESPACE, key)


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


class PgVectorStore:
    """Implementa `VectorStore`. Una colección usa un único modelo de embeddings (DT-03)."""

    def __init__(
        self,
        engine: Engine,
        embedding_model: str,
        dimensions: int,
        *,
        rrf_k: int = 60,
        candidate_factor: int = 4,
    ) -> None:
        self._engine = engine
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        self._rrf_k = rrf_k
        self._candidate_factor = candidate_factor

    @classmethod
    def from_url(cls, url: sa.URL | str, embedding_model: str, dimensions: int) -> "PgVectorStore":
        engine = sa.create_engine(url, pool_pre_ping=True)
        return cls(engine, embedding_model, dimensions)

    # --- escritura ------------------------------------------------------------------------

    def upsert(self, chunks: list[Chunk]) -> None:
        """Crea o actualiza los fragmentos y la fila de `documents` de cada documento.

        La categoría (`metadata["category"]`) es obligatoria; `title`, `source_path`,
        `related_key` y `content_hash` se toman de `metadata` si existen. Para reindexar un
        documento sin dejar fragmentos antiguos, `replace_document` (atómico, PA-216; RF-38).
        """
        by_document: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            self._validate(chunk)
            by_document.setdefault(chunk.document_id, []).append(chunk)
        if not by_document:
            return
        for document_key, document_chunks in by_document.items():
            self._check_one_category(document_key, document_chunks)
        with self._connection() as conn:
            for document_key, document_chunks in by_document.items():
                self._upsert_document(conn, document_key, document_chunks)

    def delete_by_document(self, document_id: str) -> None:
        with self._connection() as conn:
            conn.execute(_DELETE_DOCUMENT, {"id": to_uuid(document_id)})

    def replace_document(self, document_id: str, chunks: list[Chunk]) -> None:
        """Sustituye los fragmentos de un documento en **una sola transacción** (PA-216).

        Si algo falla, se conservan los fragmentos anteriores. Aún no está en el protocolo
        `VectorStore` (PA-225); `core/rag/indexing.py` lo usa si el almacén lo ofrece.
        """
        for chunk in chunks:
            self._validate(chunk)
            if chunk.document_id != document_id:
                raise ValueError(f"El fragmento {chunk.id} no es del documento {document_id}.")
        if chunks:
            self._check_one_category(document_id, chunks)
        with self._connection() as conn:
            conn.execute(_DELETE_DOCUMENT, {"id": to_uuid(document_id)})
            if chunks:
                self._upsert_document(conn, document_id, chunks)

    def _validate(self, chunk: Chunk) -> None:
        if chunk.embedding is None:
            raise ValueError(f"El fragmento {chunk.id} no tiene embedding.")
        if len(chunk.embedding) != self.dimensions:
            raise ValueError(
                f"El fragmento {chunk.id} tiene {len(chunk.embedding)} dimensiones; "
                f"se esperaban {self.dimensions}."
            )
        if not all(math.isfinite(v) for v in chunk.embedding):
            raise ValueError(f"El fragmento {chunk.id} tiene valores no finitos en el embedding.")
        if not chunk.metadata.get("category"):
            raise ValueError(f"El fragmento {chunk.id} necesita metadata['category'].")
        if _RESERVED & chunk.metadata.keys():
            raise ValueError(f"El fragmento {chunk.id} usa claves reservadas de metadata.")

    @staticmethod
    def _check_one_category(document_key: str, chunks: list[Chunk]) -> None:
        """PA-221: `documents.category` es una; fragmentos con varias darían filtros y prioridad
        de la memoria incoherentes (RF-51)."""
        categories = {chunk.metadata["category"] for chunk in chunks}
        if len(categories) > 1:
            raise ValueError(
                f"El documento {document_key} mezcla categorías: {', '.join(sorted(categories))}."
            )

    def _upsert_document(self, conn: Connection, document_key: str, chunks: list[Chunk]) -> None:
        meta = chunks[0].metadata
        document_id = to_uuid(document_key)
        conn.execute(
            _UPSERT_DOCUMENT,
            {
                "id": document_id,
                "title": meta.get("title") or document_key,
                "category": meta["category"],
                "source_path": meta.get("source_path"),
                "embedding_model": self.embedding_model,
                "content_hash": meta.get("content_hash"),
                "related_key": meta.get("related_key"),
            },
        )
        for chunk in chunks:
            stored_meta = {**chunk.metadata, _CHUNK_KEY: chunk.id, _DOCUMENT_KEY: document_key}
            conn.execute(
                _UPSERT_CHUNK,
                {
                    "id": to_uuid(chunk.id),
                    "document_id": document_id,
                    "ordinal": chunk.ordinal,
                    "section": chunk.section,
                    "content": chunk.content,
                    "embedding": _vector_literal(chunk.embedding or []),
                    "metadata": json.dumps(stored_meta, ensure_ascii=False),
                },
            )

    # --- lectura --------------------------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
        memory_boost: float = 1.0,
    ) -> list[RetrievedChunk]:
        if k <= 0:
            return []
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"El vector de consulta tiene {len(query_vector)} dimensiones; "
                f"se esperaban {self.dimensions}."
            )
        if not all(math.isfinite(v) for v in query_vector):  # PA-221: como en `upsert`
            raise ValueError("El vector de consulta tiene valores no finitos.")
        params = {
            "query_vector": _vector_literal(query_vector),
            "query_text": query_text or "",
            "embedding_model": self.embedding_model,
            "filters": json.dumps(filters, ensure_ascii=False) if filters else None,
            "candidates": k * self._candidate_factor,
            "rrf_k": self._rrf_k,
            "memory_category": MEMORY_CATEGORY,
            "memory_boost": memory_boost,
            "k": k,
        }
        with self._connection() as conn:
            rows = conn.execute(_SEARCH, params).mappings().all()
        return [_to_retrieved(row) for row in rows]

    # --- infraestructura ----------------------------------------------------------------------

    @contextmanager
    def _connection(self) -> Iterator[Connection]:
        try:
            with self._engine.begin() as conn:
                yield conn
        except sa.exc.OperationalError:
            raise ExternalServiceError(
                "No se pudo acceder a la base de datos vectorial.", service=SERVICE
            ) from None
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "La base de datos vectorial rechazó la operación.", service=SERVICE
            ) from None


def _to_retrieved(row: Any) -> RetrievedChunk:
    stored: dict[str, str] = dict(row["metadata"] or {})
    # Filas escritas fuera de `upsert` no guardan los ids originales: se usa el UUID.
    chunk_key = stored.pop(_CHUNK_KEY, None) or str(row["chunk_uuid"])
    document_key = stored.pop(_DOCUMENT_KEY, None) or str(row["document_uuid"])
    content: str = row["content"]
    chunk = Chunk(
        id=chunk_key,
        document_id=document_key,
        ordinal=row["ordinal"],
        section=row["section"],
        content=content,
        metadata=stored,
    )
    kind = "memory" if row["category"] == MEMORY_CATEGORY else "rag"
    source = SourceRef(kind=kind, ref=document_key, excerpt=content[:EXCERPT_CHARS])
    return RetrievedChunk(chunk=chunk, score=float(row["score"]), source=source)
