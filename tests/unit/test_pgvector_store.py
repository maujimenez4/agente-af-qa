"""Pruebas de `PgVectorStore` (T-16 · RF-10, RF-11, RF-51, RNF-09, CA-00-03).

Las unitarias no abren conexión: el engine apunta a un puerto cerrado y nunca se usa.
Las de integración crean una BD temporal `<db>_pgvector_test`, aplican `alembic upgrade head`
y se saltan si PostgreSQL no está disponible (docker compose up -d db).
"""

import io
import time
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, Engine

from adapters.base import Chunk, VectorStore
from adapters.errors import ExternalServiceError
from adapters.vectorstore.pgvector import EXCERPT_CHARS, PgVectorStore, to_uuid
from core.config import ROOT_DIR, Settings, load_models_config
from tests.fakes.embeddings import FakeEmbeddingProvider

DIMS = load_models_config().embeddings.dimensions  # 1024 (bge-m3)
MODEL = "bge-m3"
UNUSED_URL = "postgresql+psycopg://x@localhost:1/x"


def _unused_engine() -> Engine:
    return sa.create_engine(UNUSED_URL, poolclass=sa.pool.NullPool)


def _chunk(
    chunk_id: str = "doc-ficticio-1#0",
    document_id: str = "doc-ficticio-1",
    *,
    ordinal: int = 0,
    content: str = "Texto ficticio de prueba.",
    embedding: list[float] | None = None,
    metadata: dict[str, str] | None = None,
    dims: int = DIMS,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=document_id,
        ordinal=ordinal,
        content=content,
        embedding=embedding if embedding is not None else [0.1] * dims,
        metadata=metadata if metadata is not None else {"category": "normativa"},
    )


# --- Unitarias sin BD ----------------------------------------------------------------


def test_to_uuid_is_deterministic_when_same_key() -> None:
    """RF-10: el id de texto se convierte siempre en el mismo UUID."""
    assert to_uuid("memoria-DEMO-3") == to_uuid("memoria-DEMO-3")


def test_to_uuid_differs_when_keys_differ() -> None:
    """RF-10: claves distintas → UUID distintos."""
    assert to_uuid("doc-ficticio-1") != to_uuid("doc-ficticio-2")


def test_implements_vector_store_protocol_when_built() -> None:
    """CA-00-03: cumple el protocolo VectorStore."""
    assert isinstance(PgVectorStore(_unused_engine(), MODEL, DIMS), VectorStore)


def test_upsert_rejects_chunk_without_embedding() -> None:
    """RF-10 (negativo): un fragmento sin embedding → ValueError sin tocar la BD."""
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    chunk = _chunk().model_copy(update={"embedding": None})
    with pytest.raises(ValueError, match="embedding"):
        store.upsert([chunk])


def test_upsert_rejects_chunk_when_dimension_mismatch() -> None:
    """RF-10 / DT-03 (negativo): dimensión distinta → ValueError."""
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    with pytest.raises(ValueError, match="dimensiones"):
        store.upsert([_chunk(embedding=[0.1] * (DIMS - 1))])


@pytest.mark.parametrize("metadata", [{}, {"category": ""}, {"title": "Sin categoría"}])
def test_upsert_rejects_chunk_without_category(metadata: dict[str, str]) -> None:
    """RF-10 (negativo): metadata['category'] es obligatoria."""
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    with pytest.raises(ValueError, match="category"):
        store.upsert([_chunk(metadata=metadata)])


@pytest.mark.parametrize("reserved", ["_chunk_id", "_document_id"])
def test_upsert_rejects_reserved_metadata_keys(reserved: str) -> None:
    """RF-10 (negativo): las claves reservadas de metadata → ValueError."""
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    with pytest.raises(ValueError, match="reservadas"):
        store.upsert([_chunk(metadata={"category": "normativa", reserved: "x"})])


def test_upsert_validates_all_chunks_before_writing() -> None:
    """RF-10: un fragmento inválido al final del lote aborta antes de conectar."""
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    with pytest.raises(ValueError):
        store.upsert([_chunk(), _chunk("doc-ficticio-1#1", ordinal=1, metadata={})])


def test_upsert_empty_list_does_nothing() -> None:
    """RF-10 (límite): lista vacía → no conecta ni falla."""
    PgVectorStore(_unused_engine(), MODEL, DIMS).upsert([])


@pytest.mark.parametrize("k", [0, -3])
def test_search_returns_empty_when_k_not_positive(k: int) -> None:
    """RF-11 (límite): k <= 0 → [] sin consultar la BD."""
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    assert store.search([0.1] * DIMS, "empadronamiento", k) == []


def test_search_rejects_query_vector_when_dimension_mismatch() -> None:
    """RF-11 (negativo): vector de consulta con dimensión distinta → ValueError."""
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    with pytest.raises(ValueError, match="dimensiones"):
        store.search([0.1] * 3, "empadronamiento", 5)


# --- Integración ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    """BD temporal migrada; nunca toca la base de datos configurada."""
    server_url: URL = Settings().sqlalchemy_url()
    test_db = f"{server_url.database}_pgvector_test"
    admin = sa.create_engine(
        server_url,
        poolclass=sa.pool.NullPool,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
            conn.execute(sa.text(f'CREATE DATABASE "{test_db}"'))
    except sa.exc.OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL no disponible (docker compose up -d db)")
    url = server_url.set(database=test_db)
    config = Config(str(ROOT_DIR / "alembic.ini"), stdout=io.StringIO())
    config.attributes["database_url"] = url
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def engine(pg_engine: Engine) -> Engine:
    with pg_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE documents CASCADE"))
    return pg_engine


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(model_name=MODEL, dimensions=DIMS)


@pytest.fixture
def store(engine: Engine) -> PgVectorStore:
    return PgVectorStore(engine, MODEL, DIMS)


def _doc_chunks(
    embedder: FakeEmbeddingProvider,
    document_id: str,
    contents: list[str],
    metadata: dict[str, str],
) -> list[Chunk]:
    vectors = embedder.embed(contents)
    return [
        Chunk(
            id=f"{document_id}#{i}",
            document_id=document_id,
            ordinal=i,
            section=f"Sección {i + 1}",
            content=content,
            embedding=vector,
            metadata=metadata,
        )
        for i, (content, vector) in enumerate(zip(contents, vectors, strict=True))
    ]


CORPUS = {
    "doc-padron": (
        ["El empadronamiento de vecinos en Villaficticia requiere el formulario de alta."],
        {"category": "normativa", "title": "Padrón ficticio", "related_key": "DEMO-1"},
    ),
    "doc-obras": (
        ["La licencia de obra menor se tramita en la sede electrónica ficticia."],
        {"category": "procedimiento", "title": "Obras ficticias", "related_key": "DEMO-2"},
    ),
    "doc-tasas": (
        ["El pago de la tasa de basuras se domicilia en una cuenta de prueba."],
        {"category": "normativa", "title": "Tasas ficticias", "related_key": "DEMO-3"},
    ),
}


def _load_corpus(store: PgVectorStore, embedder: FakeEmbeddingProvider) -> None:
    chunks: list[Chunk] = []
    for doc_id, (contents, meta) in CORPUS.items():
        chunks += _doc_chunks(embedder, doc_id, contents, meta)
    store.upsert(chunks)


_COUNT_SQL = {
    "documents": sa.text("SELECT count(*) FROM documents"),
    "chunks": sa.text("SELECT count(*) FROM chunks"),
}


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(_COUNT_SQL[table]).scalar_one())


@pytest.mark.integration
def test_upsert_creates_document_and_chunk_rows(
    engine: Engine, store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-10: se guardan title, category, related_key, embedding_model y los fragmentos."""
    meta = {"category": "normativa", "title": "Padrón ficticio", "related_key": "DEMO-1"}
    store.upsert(_doc_chunks(embedder, "doc-padron", ["Parte uno ficticia.", "Parte dos."], meta))
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT title, category, related_key, embedding_model FROM documents WHERE id = :id"
            ),
            {"id": to_uuid("doc-padron")},
        ).one()
        chunks = conn.execute(
            sa.text("SELECT count(*) FROM chunks WHERE document_id = :id"),
            {"id": to_uuid("doc-padron")},
        ).scalar_one()
    assert tuple(row) == ("Padrón ficticio", "normativa", "DEMO-1", MODEL)
    assert chunks == 2


@pytest.mark.integration
def test_upsert_is_idempotent_when_repeated(
    engine: Engine, store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-10: repetir el upsert no duplica documentos ni fragmentos."""
    _load_corpus(store, embedder)
    _load_corpus(store, embedder)
    assert _count(engine, "documents") == 3
    assert _count(engine, "chunks") == 3


@pytest.mark.integration
def test_search_returns_text_ids_and_clean_metadata(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-10 / RF-11: ids de texto intactos; metadata sin claves reservadas ni embedding."""
    _load_corpus(store, embedder)
    query = "empadronamiento de vecinos"
    results = store.search(embedder.embed([query])[0], query, k=3)
    top = results[0].chunk
    assert top.id == "doc-padron#0"
    assert top.document_id == "doc-padron"
    assert top.section == "Sección 1"
    assert top.embedding is None
    assert top.metadata == CORPUS["doc-padron"][1]
    assert not {"_chunk_id", "_document_id"} & top.metadata.keys()


@pytest.mark.integration
def test_hybrid_search_ranks_relevant_document_first(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-11: la consulta con palabras de un documento lo devuelve primero."""
    _load_corpus(store, embedder)
    query = "licencia de obra menor"
    results = store.search(embedder.embed([query])[0], query, k=3)
    assert results[0].chunk.document_id == "doc-obras"
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)


@pytest.mark.integration
def test_lexical_part_ranks_match_when_vector_uninformative(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-11: con un vector uniforme, la parte de texto completo decide el primero."""
    _load_corpus(store, embedder)
    uniform = [1.0] * DIMS
    results = store.search(uniform, "tasa de basuras", k=3)
    assert results[0].chunk.document_id == "doc-tasas"


@pytest.mark.integration
def test_lexical_match_beats_vector_only_match_when_vector_points_elsewhere(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-11: el vector apunta a otro documento, pero la fusión premia la coincidencia léxica."""
    _load_corpus(store, embedder)
    misleading = embedder.embed([CORPUS["doc-obras"][0][0]])[0]
    results = store.search(misleading, "tasa de basuras", k=3)
    assert results[0].chunk.document_id == "doc-tasas"


@pytest.mark.integration
def test_search_applies_metadata_filters(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-11: el filtro por category solo devuelve documentos de esa categoría."""
    _load_corpus(store, embedder)
    query = "licencia de obra menor"
    results = store.search(
        embedder.embed([query])[0], query, k=5, filters={"category": "normativa"}
    )
    assert results
    assert {r.chunk.metadata["category"] for r in results} == {"normativa"}
    assert "doc-obras" not in {r.chunk.document_id for r in results}


@pytest.mark.integration
def test_search_returns_empty_when_filter_matches_nothing(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-11 (límite): filtro sin coincidencias → []."""
    _load_corpus(store, embedder)
    query = "empadronamiento"
    assert store.search(embedder.embed([query])[0], query, 5, {"category": "inexistente"}) == []


@pytest.mark.integration
def test_memory_boost_promotes_memory_and_sets_source_kind(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-51 / RF-11: memory_boost > 1 sube la memoria; source indica memory/rag y la cita."""
    _load_corpus(store, embedder)
    long_memory = "Memoria sintética de la HU DEMO-9 sobre el padrón ficticio. " + "relleno " * 60
    store.upsert(
        _doc_chunks(
            embedder,
            "memoria-DEMO-9",
            [long_memory],
            {"category": "memoria", "related_key": "DEMO-9"},
        )
    )
    query = "empadronamiento de vecinos en Villaficticia formulario de alta"
    vector = embedder.embed([query])[0]

    baseline = store.search(vector, query, k=4)
    assert baseline[0].chunk.document_id == "doc-padron"

    boosted = store.search(vector, query, k=4, memory_boost=3.0)
    assert boosted[0].chunk.document_id == "memoria-DEMO-9"
    for result in boosted:
        expected_kind = "memory" if result.chunk.document_id.startswith("memoria-") else "rag"
        assert result.source.kind == expected_kind
        assert result.source.ref == result.chunk.document_id
        assert result.source.excerpt is not None
        assert len(result.source.excerpt) <= EXCERPT_CHARS
    assert len(boosted[0].source.excerpt or "") == EXCERPT_CHARS  # memoria larga recortada


@pytest.mark.integration
def test_delete_by_document_cascades_to_chunks(
    engine: Engine, store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-10: borrar un documento elimina su fila y sus fragmentos en cascada."""
    _load_corpus(store, embedder)
    store.delete_by_document("doc-padron")
    assert _count(engine, "documents") == 2
    assert _count(engine, "chunks") == 2
    query = "empadronamiento"
    results = store.search(embedder.embed([query])[0], query, k=5)
    assert "doc-padron" not in {r.chunk.document_id for r in results}


@pytest.mark.integration
def test_delete_by_document_is_noop_when_missing(engine: Engine, store: PgVectorStore) -> None:
    """RF-10 (límite): borrar un documento inexistente no falla."""
    store.delete_by_document("doc-inexistente")
    assert _count(engine, "documents") == 0


@pytest.mark.integration
def test_has_document_reflects_upsert_and_delete(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """T-33: has_document consulta `documents` por el id de texto, sin embeddings."""
    assert not store.has_document("doc-padron")
    _load_corpus(store, embedder)
    assert store.has_document("doc-padron")
    store.delete_by_document("doc-padron")
    assert not store.has_document("doc-padron")


@pytest.mark.integration
def test_reindex_leaves_no_stale_chunks(
    engine: Engine, store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-10 / RF-38: delete + upsert con menos fragmentos no deja fragmentos antiguos."""
    meta = {"category": "normativa"}
    store.upsert(_doc_chunks(embedder, "doc-reindex", ["uno viejo", "dos viejo", "tres"], meta))
    store.delete_by_document("doc-reindex")
    store.upsert(_doc_chunks(embedder, "doc-reindex", ["contenido nuevo ficticio"], meta))
    with engine.connect() as conn:
        contents = conn.execute(sa.text("SELECT content FROM chunks")).scalars().all()
    assert contents == ["contenido nuevo ficticio"]


@pytest.mark.integration
def test_search_ignores_documents_from_other_embedding_model(
    engine: Engine, store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RF-11 / DT-03: documentos de otro embedding_model no aparecen en la búsqueda."""
    other = PgVectorStore(engine, "otro-modelo-ficticio", DIMS)
    other.upsert(
        _doc_chunks(embedder, "doc-otro-modelo", ["empadronamiento ajeno"], {"category": "x"})
    )
    _load_corpus(store, embedder)
    query = "empadronamiento"
    ours = store.search(embedder.embed([query])[0], query, k=10)
    assert "doc-otro-modelo" not in {r.chunk.document_id for r in ours}
    theirs = other.search(embedder.embed([query])[0], query, k=10)
    assert {r.chunk.document_id for r in theirs} == {"doc-otro-modelo"}


@pytest.mark.integration
def test_search_latency_below_three_seconds(
    store: PgVectorStore, embedder: FakeEmbeddingProvider
) -> None:
    """RNF-09: una búsqueda híbrida tarda menos de 3 s."""
    _load_corpus(store, embedder)
    query = "licencia de obra menor"
    vector = embedder.embed([query])[0]
    start = time.perf_counter()
    store.search(vector, query, k=5)
    assert time.perf_counter() - start < 3.0


@pytest.mark.integration
def test_raises_external_error_without_url_when_database_down() -> None:
    """CA-00-03: BD inaccesible → ExternalServiceError sin la URL en el mensaje."""
    engine = sa.create_engine(
        UNUSED_URL, poolclass=sa.pool.NullPool, connect_args={"connect_timeout": 2}
    )
    store = PgVectorStore(engine, MODEL, DIMS)
    for operation in (
        lambda: store.search([0.1] * DIMS, "empadronamiento", 3),
        lambda: store.upsert([_chunk()]),
        lambda: store.delete_by_document("doc-ficticio-1"),
    ):
        with pytest.raises(ExternalServiceError) as info:
            operation()
        message = str(info.value)
        assert "localhost" not in message
        assert "postgresql" not in message
        assert info.value.service == "postgres"
        assert info.value.__cause__ is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_upsert_rejects_non_finite_embedding_values(bad: float) -> None:
    store = PgVectorStore(_unused_engine(), MODEL, DIMS)
    embedding = [0.1] * DIMS
    embedding[5] = bad
    with pytest.raises(ValueError, match="no finitos"):
        store.upsert([_chunk(embedding=embedding)])


@pytest.mark.integration
def test_search_tolerates_rows_written_outside_upsert(engine: Engine, store: PgVectorStore) -> None:
    """Filas sin los ids originales en metadata se devuelven con el UUID como id."""
    document_id = to_uuid("doc-externo")
    vector = "[" + ",".join(["0.1"] * DIMS) + "]"
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, title, category, embedding_model) "
                "VALUES (:id, 'Documento externo ficticio', 'normativa', :model)"
            ),
            {"id": document_id, "model": MODEL},
        )
        conn.execute(
            sa.text(
                "INSERT INTO chunks (id, document_id, ordinal, content, embedding, metadata) "
                "VALUES (:id, :doc, 0, 'Texto externo ficticio', CAST(:v AS vector), '{}'::jsonb)"
            ),
            {"id": to_uuid("externo-0"), "doc": document_id, "v": vector},
        )
    (result,) = store.search([0.1] * DIMS, "externo", k=1)
    assert result.chunk.document_id == str(document_id)
    assert result.chunk.id == str(to_uuid("externo-0"))
