"""Indexación del corpus: ingesta (T-12) → fragmentación (T-13) → embeddings → VectorStore (T-16).

Completa la metadata de cada fragmento con lo que espera el `VectorStore` (SPEC-00 §11):
`source_path` relativo a la raíz, `content_hash`, `doc_id`, `classified_by` e `ingested_at`
(fecha de ingesta, siempre; `date` es la fecha de la fuente cuando la cabecera la trae, RF-10).
Reindexar un documento sustituye sus fragmentos anteriores (`delete_by_document` + `upsert`,
RF-38); los embeddings se calculan antes de borrar, para no perder el documento si falla.

Uso: `uv run python -m core.rag.indexing [carpeta]` (por defecto `data/seed/corpus`).
"""

import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from adapters.base import Chunk, EmbeddingProvider, VectorStore
from adapters.errors import AgentError, ExternalServiceError
from core.rag.documents import IngestedDocument
from core.rag.ingest import Ingestor

# Solo el corpus se indexa: `data/seed/jira/` describe la calidad prevista del seed (PA-10).
DEFAULT_CORPUS = Path("data/seed/corpus")

Chunker = Callable[[IngestedDocument], list[Chunk]]


@runtime_checkable
class ReplacingStore(Protocol):
    """Almacén que sustituye un documento de forma atómica (PA-216).

    Aún no está en `VectorStore` (`adapters/base.py`, congelado): PA-225 propone añadirlo.
    """

    def replace_document(self, document_id: str, chunks: list[Chunk]) -> None: ...


class IndexReport(BaseModel):
    documents: int
    chunks: int
    by_category: dict[str, int]


def relative_source(source_path: str, root: Path) -> str:
    """Ruta relativa a la raíz del corpus: no guarda rutas locales del equipo."""
    path = Path(source_path)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def prepare_chunks(
    doc: IngestedDocument, chunks: list[Chunk], root: Path, today: date | None = None
) -> list[Chunk]:
    """Metadata que espera el `VectorStore`; `source` también pasa a ser relativo."""
    source = relative_source(doc.source_path, root)
    extra = {
        "source_path": source,
        "source": source,
        "content_hash": doc.content_hash,
        "doc_id": doc.id,
        "classified_by": doc.classified_by,
        "ingested_at": (today or date.today()).isoformat(),
    }
    return [chunk.model_copy(update={"metadata": {**chunk.metadata, **extra}}) for chunk in chunks]


def embedding_text(chunk: Chunk) -> str:
    """Texto que se vectoriza: título y sección dan contexto a fragmentos cortos."""
    title = chunk.metadata.get("title", "")
    heading = " · ".join(part for part in (title, chunk.section or "") if part)
    return f"{heading}\n\n{chunk.content}" if heading else chunk.content


class CorpusIndexer:
    def __init__(
        self,
        ingestor: Ingestor,
        chunker: Chunker,
        embeddings: EmbeddingProvider,
        store: VectorStore,
    ) -> None:
        self._ingestor = ingestor
        self._chunker = chunker
        self._embeddings = embeddings
        self._store = store

    def index_dir(self, root: Path) -> IndexReport:
        documents = self._ingestor.ingest_dir(root)
        by_category: dict[str, int] = {}
        total = 0
        for doc in documents:
            chunks = prepare_chunks(doc, self._chunker(doc), root)
            vectors = self._embeddings.embed([embedding_text(c) for c in chunks]) if chunks else []
            if len(vectors) != len(chunks):  # antes de borrar nada (PA-216)
                raise ExternalServiceError(
                    f"El servicio de embeddings devolvió {len(vectors)} vectores para "
                    f"{len(chunks)} fragmentos de «{doc.title[:80]}»; no se ha cambiado el índice.",
                    service="embeddings",
                )
            indexed = [
                chunk.model_copy(update={"embedding": vector})
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            self._replace(doc.id, indexed)  # sin fragmentos antiguos (RF-38)
            if not indexed:
                continue
            by_category[doc.category] = by_category.get(doc.category, 0) + 1
            total += len(indexed)
        return IndexReport(
            documents=sum(by_category.values()), chunks=total, by_category=by_category
        )

    def _replace(self, document_id: str, chunks: list[Chunk]) -> None:
        """Sustituye los fragmentos del documento; atómico si el almacén lo permite (PA-216)."""
        if isinstance(self._store, ReplacingStore):
            self._store.replace_document(document_id, chunks)
            return
        self._store.delete_by_document(document_id)
        if chunks:
            self._store.upsert(chunks)


def main(argv: list[str] | None = None) -> int:
    from core.config import ConfigError, build_config
    from core.factories import build_embeddings, build_llm_provider, build_vector_store
    from core.rag.chunking import chunk_with_config

    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else DEFAULT_CORPUS
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # consolas de Windows en cp1252
    if not root.is_dir():  # PA-217: no se informa de «0 documentos» como si fuera un éxito
        print(f"No existe la carpeta del corpus «{root.name}».", file=sys.stderr)
        return 2
    try:
        config = build_config()
        indexer = CorpusIndexer(
            Ingestor(build_llm_provider(config)),
            lambda doc: chunk_with_config(doc, config),
            build_embeddings(config),
            build_vector_store(config),
        )
        report = indexer.index_dir(root)
    except (AgentError, ConfigError) as exc:  # PA-217: mensaje en español, sin traceback
        print(f"No se ha completado la indexación: {exc}", file=sys.stderr)
        return 1
    categories = ", ".join(f"{k}: {v}" for k, v in sorted(report.by_category.items()))
    print(f"Indexados {report.documents} documentos y {report.chunks} fragmentos ({categories}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
