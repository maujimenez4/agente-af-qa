"""Comportamiento de FakeEmbeddingProvider y FakeVectorStore (CA-00-03)."""

import math

import pytest

from adapters.base import Chunk
from tests.fakes import FakeEmbeddingProvider, FakeVectorStore, dataset

EMBEDDER = FakeEmbeddingProvider()


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _chunk(chunk_id: str, document_id: str, content: str, **metadata: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=document_id,
        ordinal=0,
        content=content,
        embedding=EMBEDDER.embed([content])[0],
        metadata=metadata,
    )


# --- Embeddings -------------------------------------------------------------------------


def test_embed_is_deterministic() -> None:
    """CA-00-03: el mismo texto produce el mismo vector, también entre instancias."""
    text = dataset.DOCUMENTS["doc-reglamento"]["content"]
    assert EMBEDDER.embed([text]) == FakeEmbeddingProvider().embed([text])


def test_embed_returns_one_vector_per_text_with_dimension() -> None:
    """CA-00-03: un vector por texto con la dimensión declarada."""
    vectors = EMBEDDER.embed(["reserva de libros", "renovación de préstamos", "glosario"])
    assert len(vectors) == 3
    assert all(len(v) == EMBEDDER.dimensions for v in vectors)


def test_embed_respects_custom_dimension() -> None:
    """CA-00-03 (límite): la dimensión es configurable."""
    assert len(FakeEmbeddingProvider(dimensions=8).embed(["texto ficticio"])[0]) == 8


def test_embed_returns_empty_list_for_no_texts() -> None:
    """CA-00-03 (límite): lista vacía → lista vacía."""
    assert EMBEDDER.embed([]) == []


def test_embed_is_normalized() -> None:
    """CA-00-03: los vectores de textos con palabras tienen norma 1."""
    for vector in EMBEDDER.embed(["renovar un préstamo", "reserva temporal de ejemplar"]):
        assert math.isclose(math.sqrt(_dot(vector, vector)), 1.0)


def test_embed_similar_texts_are_closer() -> None:
    """CA-00-03: textos que comparten palabras quedan más cerca (coseno)."""
    query, similar, different = EMBEDDER.embed(
        [
            "renovar préstamo activo",
            "renovar un préstamo activo desde la web",
            "glosario ejemplar bloqueo horas",
        ]
    )
    assert _dot(query, similar) > _dot(query, different)


# --- VectorStore ------------------------------------------------------------------------


@pytest.fixture
def store() -> FakeVectorStore:
    fake = FakeVectorStore()
    fake.upsert(
        [
            _chunk(
                "reg-0",
                "doc-reglamento",
                dataset.DOCUMENTS["doc-reglamento"]["content"],
                category="normativa",
            ),
            _chunk(
                "glo-0",
                "doc-glosario",
                dataset.DOCUMENTS["doc-glosario"]["content"],
                category="glosario",
            ),
        ]
    )
    return fake


def test_upsert_without_embedding_fails() -> None:
    """CA-00-03 (error): un fragmento sin embedding no se admite."""
    fake = FakeVectorStore()
    chunk = Chunk(id="x-0", document_id="doc-x", ordinal=0, content="Texto ficticio")
    with pytest.raises(ValueError, match="x-0"):
        fake.upsert([chunk])
    assert fake.chunks == {}


def test_upsert_is_idempotent_by_id(store: FakeVectorStore) -> None:
    """CA-00-03: repetir el upsert con el mismo id reemplaza, no duplica."""
    updated = _chunk("reg-0", "doc-reglamento", "Artículo 4 modificado (ficticio).")
    store.upsert([updated])
    store.upsert([updated])
    assert len(store.chunks) == 2
    assert store.chunks["reg-0"].content == "Artículo 4 modificado (ficticio)."


def test_delete_by_document_removes_only_that_document(store: FakeVectorStore) -> None:
    """CA-00-03: delete_by_document borra solo los fragmentos del documento."""
    store.delete_by_document("doc-reglamento")
    assert set(store.chunks) == {"glo-0"}
    store.delete_by_document("doc-inexistente")
    assert set(store.chunks) == {"glo-0"}


def test_search_returns_most_similar_first(store: FakeVectorStore) -> None:
    """CA-00-03: la búsqueda ordena por puntuación e informa la fuente RAG."""
    query = "renovaciones del préstamo"
    results = store.search(EMBEDDER.embed([query])[0], query, k=2)
    assert [r.chunk.id for r in results] == ["reg-0", "glo-0"]
    assert results[0].score >= results[1].score
    assert results[0].source.kind == "rag"
    assert results[0].source.ref == "doc-reglamento"


def test_search_respects_k(store: FakeVectorStore) -> None:
    """CA-00-03 (límite): k recorta el número de resultados."""
    vector = EMBEDDER.embed(["reserva"])[0]
    assert len(store.search(vector, "reserva", k=1)) == 1
    assert store.search(vector, "reserva", k=0) == []
    assert len(store.search(vector, "reserva", k=10)) == 2


def test_search_applies_metadata_filters(store: FakeVectorStore) -> None:
    """CA-00-03: los filtros por metadatos excluyen los fragmentos que no coinciden."""
    vector = EMBEDDER.embed(["renovación"])[0]
    results = store.search(vector, "renovación", k=5, filters={"category": "glosario"})
    assert [r.chunk.id for r in results] == ["glo-0"]
    assert store.search(vector, "renovación", k=5, filters={"category": "otra"}) == []


def test_memory_boost_prioritizes_memory_chunks(store: FakeVectorStore) -> None:
    """CA-00-03 (RF-51): memory_boost antepone los chunks category=memoria (source.kind=memory)."""
    store.upsert(
        [_chunk("mem-0", "mem-DEMO-3", "Memoria ficticia de reservas", category="memoria")]
    )
    query = dataset.DOCUMENTS["doc-reglamento"]["content"]
    vector = EMBEDDER.embed([query])[0]
    without_boost = store.search(vector, query, k=3)
    assert without_boost[0].chunk.id == "reg-0"
    with_boost = store.search(vector, query, k=3, memory_boost=100.0)
    assert with_boost[0].chunk.id == "mem-0"
    assert with_boost[0].source.kind == "memory"
    assert {r.source.kind for r in with_boost[1:]} == {"rag"}


def test_search_returns_copies_not_affected_by_caller_mutation() -> None:
    """CA-00-03: el almacén guarda una copia del fragmento insertado."""
    fake = FakeVectorStore()
    chunk = _chunk("c-0", "doc-x", "Texto ficticio de ejemplo")
    fake.upsert([chunk])
    chunk.content = "mutado"
    assert fake.chunks["c-0"].content == "Texto ficticio de ejemplo"
