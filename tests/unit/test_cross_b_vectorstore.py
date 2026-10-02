"""Prueba cruzada T-34 (RNF-19): el área A prueba `adapters.vectorstore.pgvector` del área B.

RF-10, RF-11, RF-37, RF-38, RF-51 y SPEC-00 §11 («VectorStore sobre Postgres»). Las unitarias
usan un engine falso que captura cada sentencia y sus parámetros: no abren conexión. Las de
integración usan una BD temporal propia `<db>_cross_b_test` y se saltan sin PostgreSQL.
Datos 100 % ficticios.
"""

import io
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pydantic
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, Engine

from adapters.base import Chunk
from adapters.errors import ExternalServiceError
from adapters.vectorstore.pgvector import (
    EXCERPT_CHARS,
    MEMORY_CATEGORY,
    PgVectorStore,
    to_uuid,
)
from core.config import ROOT_DIR, Settings

DIMS = 3
MODEL = "bge-m3"
SECRET_URL = "postgresql+psycopg://usuario_ficticio:clave_ficticia@db-ficticia.invalid:5432/x"


# --- engine falso ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)


@dataclass
class FakeConnection:
    rows: list[dict[str, Any]]
    error: Exception | None
    executed: list[tuple[str, dict[str, Any]]]

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:
        self.executed.append((str(statement), dict(params or {})))
        if self.error is not None:
            raise self.error
        return FakeResult(self.rows)


@dataclass
class FakeEngine:
    """Imita `Engine.begin()`; `executed` guarda (SQL, parámetros) en orden."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None  # lo lanza `execute`
    begin_error: Exception | None = None  # lo lanza `begin` (sin conexión)
    begins: int = 0
    executed: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @contextmanager
    def begin(self) -> Iterator[FakeConnection]:
        self.begins += 1
        if self.begin_error is not None:
            raise self.begin_error
        yield FakeConnection(self.rows, self.error, self.executed)

    def statements(self, keyword: str) -> list[dict[str, Any]]:
        return [params for sql, params in self.executed if keyword in sql]


def _store(engine: FakeEngine, **kwargs: Any) -> PgVectorStore:
    return PgVectorStore(engine, MODEL, DIMS, **kwargs)  # type: ignore[arg-type]


def _chunk(
    chunk_id: str = "doc-a#0",
    document_id: str = "doc-a",
    *,
    ordinal: int = 0,
    content: str = "Texto ficticio.",
    metadata: dict[str, str] | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=document_id,
        ordinal=ordinal,
        section="Sección ficticia",
        content=content,
        embedding=[0.25, 0.5, 1.0],
        metadata=metadata if metadata is not None else {"category": "normativa"},
    )


def _row(**update: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "chunk_uuid": to_uuid("doc-a#0"),
        "document_uuid": to_uuid("doc-a"),
        "ordinal": 0,
        "section": "Sección ficticia",
        "content": "Texto ficticio.",
        "metadata": {"category": "normativa", "_chunk_id": "doc-a#0", "_document_id": "doc-a"},
        "category": "normativa",
        "score": 0.5,
    }
    return base | update


# --- 1 · parámetros de search (RF-11, RF-51) -------------------------------------------------


def test_search_params_follow_k_factor_model_and_boost() -> None:
    """RF-11 · RF-51: candidates = k·factor, modelo de la colección, boost y categoría memoria."""
    engine = FakeEngine()

    _store(engine, rrf_k=30, candidate_factor=5).search(
        [0.1, 0.2, 0.3], "renovación", 4, memory_boost=1.7
    )

    (params,) = engine.statements("websearch_to_tsquery")
    assert params["candidates"] == 20
    assert params["k"] == 4
    assert params["rrf_k"] == 30
    assert params["embedding_model"] == MODEL
    assert params["memory_boost"] == 1.7
    assert params["memory_category"] == MEMORY_CATEGORY == "memoria"
    assert params["query_text"] == "renovación"
    assert params["query_vector"] == "[0.1,0.2,0.3]"
    assert engine.begins == 1


@pytest.mark.parametrize("filters", [None, {}])
def test_search_filters_are_null_when_missing_or_empty(filters: dict[str, str] | None) -> None:
    """RF-11 (límite): sin filtros o con {} → NULL (sin `@>` efectivo)."""
    engine = FakeEngine()

    _store(engine).search([0.1, 0.2, 0.3], "x", 1, filters=filters)

    assert engine.statements("websearch_to_tsquery")[0]["filters"] is None


def test_search_filters_are_json_without_ascii_escapes() -> None:
    """RF-11: los filtros van como JSON con tildes y eñes sin escapar."""
    engine = FakeEngine()

    _store(engine).search([0.1, 0.2, 0.3], "x", 1, filters={"category": "reseña-pública"})

    filters = engine.statements("websearch_to_tsquery")[0]["filters"]
    assert filters == '{"category": "reseña-pública"}'
    assert json.loads(filters) == {"category": "reseña-pública"}


@pytest.mark.parametrize("text", ["", None])
def test_search_query_text_is_empty_string_when_missing(text: str | None) -> None:
    """RF-11 (límite): sin texto de consulta se envía «» (la parte léxica no aporta)."""
    engine = FakeEngine()

    _store(engine).search([0.1, 0.2, 0.3], text, 1)  # type: ignore[arg-type]

    assert engine.statements("websearch_to_tsquery")[0]["query_text"] == ""


def test_search_default_boost_and_factor() -> None:
    """RF-51 (límite): por defecto memory_boost=1.0, rrf_k=60 y candidates=4·k."""
    engine = FakeEngine()

    _store(engine).search([0.1, 0.2, 0.3], "x", 3)

    params = engine.statements("websearch_to_tsquery")[0]
    assert (params["memory_boost"], params["rrf_k"], params["candidates"]) == (1.0, 60, 12)


# --- 2 · upsert (RF-10, RF-37, RF-38) --------------------------------------------------------


def test_upsert_title_defaults_to_document_key() -> None:
    """SPEC-00 §11: sin metadata['title'], documents.title es el id de texto del documento."""
    engine = FakeEngine()

    _store(engine).upsert([_chunk()])

    (doc,) = engine.statements("INSERT INTO documents")
    assert doc["title"] == "doc-a"
    assert doc["id"] == to_uuid("doc-a")
    assert doc["embedding_model"] == MODEL
    assert doc["source_path"] is None and doc["related_key"] is None


def test_upsert_document_row_takes_metadata_fields() -> None:
    """RF-10: title, source_path, related_key y content_hash salen de la metadata."""
    engine = FakeEngine()
    meta = {
        "category": "normativa",
        "title": "Reglamento ficticio",
        "source_path": "data/seed/corpus/reglamento-ficticio.md",
        "related_key": "DEMO-3",
        "content_hash": "hash-ficticio-0001",
    }

    _store(engine).upsert([_chunk(metadata=meta)])

    (doc,) = engine.statements("INSERT INTO documents")
    assert {k: doc[k] for k in meta} == meta


def test_upsert_chunk_metadata_is_json_with_original_ids_and_accents() -> None:
    """SPEC-00 §11: metadata en JSON con `_chunk_id`/`_document_id` y sin escapar tildes."""
    engine = FakeEngine()

    _store(engine).upsert([_chunk(metadata={"category": "normativa", "tema": "préstamo"})])

    (row,) = engine.statements("INSERT INTO chunks")
    assert "préstamo" in row["metadata"]
    assert json.loads(row["metadata"]) == {
        "category": "normativa",
        "tema": "préstamo",
        "_chunk_id": "doc-a#0",
        "_document_id": "doc-a",
    }
    assert row["id"] == to_uuid("doc-a#0")
    assert row["document_id"] == to_uuid("doc-a")
    assert row["embedding"] == "[0.25,0.5,1.0]"
    assert (row["ordinal"], row["section"], row["content"]) == (
        0,
        "Sección ficticia",
        "Texto ficticio.",
    )


def test_upsert_groups_interleaved_chunks_by_document_in_one_transaction() -> None:
    """RF-10: fragmentos intercalados de dos documentos → una fila de documento por cada uno."""
    engine = FakeEngine()
    chunks = [
        _chunk("doc-a#0", "doc-a", ordinal=0),
        _chunk("doc-b#0", "doc-b", ordinal=0),
        _chunk("doc-a#1", "doc-a", ordinal=1),
    ]

    _store(engine).upsert(chunks)

    kinds = [
        ("doc" if "INSERT INTO documents" in sql else "chunk", params["id"])
        for sql, params in engine.executed
    ]
    assert kinds == [
        ("doc", to_uuid("doc-a")),
        ("chunk", to_uuid("doc-a#0")),
        ("chunk", to_uuid("doc-a#1")),
        ("doc", to_uuid("doc-b")),
        ("chunk", to_uuid("doc-b#0")),
    ]
    assert engine.begins == 1


def test_upsert_does_not_mutate_chunk_metadata() -> None:
    """RF-10: las claves reservadas se añaden a una copia, no al fragmento del llamador."""
    chunk = _chunk()

    _store(FakeEngine()).upsert([chunk])

    assert chunk.metadata == {"category": "normativa"}


def test_memory_chunk_is_indexed_with_related_key_and_category() -> None:
    """RF-37: la memoria se indexa como `memoria` con related_key = clave de Jira."""
    engine = FakeEngine()
    memory = _chunk(
        "memoria-DEMO-3-0",
        "memoria-DEMO-3",
        content="# Memoria · DEMO-3 (v1)",
        metadata={"category": "memoria", "related_key": "DEMO-3"},
    )

    _store(engine).upsert([memory])

    (doc,) = engine.statements("INSERT INTO documents")
    assert (doc["category"], doc["related_key"], doc["title"]) == (
        "memoria",
        "DEMO-3",
        "memoria-DEMO-3",
    )


def test_reindex_deletes_the_same_document_uuid_that_upsert_writes() -> None:
    """RF-38: delete_by_document + upsert apuntan al mismo UUID (sin duplicar la memoria)."""
    engine = FakeEngine()
    store = _store(engine)

    store.delete_by_document("memoria-DEMO-3")
    store.upsert([_chunk("memoria-DEMO-3-0", "memoria-DEMO-3", metadata={"category": "memoria"})])

    (deleted,) = engine.statements("DELETE FROM documents")
    (doc,) = engine.statements("INSERT INTO documents")
    assert deleted["id"] == doc["id"] == to_uuid("memoria-DEMO-3")
    assert engine.begins == 2  # dos transacciones: el llamador decide el orden


# --- 3 · delete_by_document ----------------------------------------------------------------


def test_delete_by_document_uses_uuid5_of_text_id() -> None:
    """SPEC-00 §11: el borrado convierte el id de texto con `to_uuid`."""
    engine = FakeEngine()

    _store(engine).delete_by_document("doc-ficticio-9")

    ((sql, params),) = engine.executed
    assert "DELETE FROM documents" in sql
    assert params == {"id": to_uuid("doc-ficticio-9")}
    assert isinstance(params["id"], UUID)


# --- 4 · errores de BD → ExternalServiceError sin URL ----------------------------------------


def _db_errors() -> list[Exception]:
    orig = Exception(f"could not connect to {SECRET_URL}")
    return [
        sa.exc.OperationalError("SELECT 1", {}, orig),
        sa.exc.DBAPIError("SELECT 1", {}, orig),
        sa.exc.IntegrityError("INSERT", {}, orig),
        sa.exc.DataError("SELECT", {}, orig),
    ]


def _operations(store: PgVectorStore) -> list[Any]:
    return [
        lambda: store.search([0.1, 0.2, 0.3], "x", 2),
        lambda: store.upsert([_chunk()]),
        lambda: store.delete_by_document("doc-a"),
    ]


def _assert_safe(exc: ExternalServiceError) -> None:
    message = str(exc)
    for fragment in ("db-ficticia", "clave_ficticia", "usuario_ficticio", "postgresql", "5432"):
        assert fragment not in message
    assert exc.service == "postgres"
    assert exc.__cause__ is None


@pytest.mark.parametrize("error", _db_errors(), ids=lambda e: type(e).__name__)
def test_db_error_on_execute_maps_to_external_error_without_url(error: Exception) -> None:
    """CA-00-03 · Principio 2: errores de SQLAlchemy → ExternalServiceError sin la URL."""
    store = _store(FakeEngine(error=error))

    for operation in _operations(store):
        with pytest.raises(ExternalServiceError) as info:
            operation()
        _assert_safe(info.value)


def test_operational_error_on_connect_says_unreachable() -> None:
    """CA-00-03: si `begin()` falla al conectar → «No se pudo acceder…»."""
    error = sa.exc.OperationalError("connect", {}, Exception(SECRET_URL))
    store = _store(FakeEngine(begin_error=error))

    for operation in _operations(store):
        with pytest.raises(ExternalServiceError, match="No se pudo acceder") as info:
            operation()
        _assert_safe(info.value)


def test_integrity_error_says_rejected() -> None:
    """CA-00-03: un DBAPIError que no es de conexión → «rechazó la operación»."""
    error = sa.exc.IntegrityError("INSERT", {}, Exception(SECRET_URL))

    with pytest.raises(ExternalServiceError, match="rechazó la operación"):
        _store(FakeEngine(error=error)).upsert([_chunk()])


def test_non_database_error_is_not_wrapped() -> None:
    """CA-00-03 (comportamiento fijado): un error ajeno a la BD se propaga sin envolver."""
    with pytest.raises(RuntimeError, match="fallo-ficticio"):
        _store(FakeEngine(error=RuntimeError("fallo-ficticio"))).delete_by_document("doc-a")


# --- 5 · vector de consulta no finito -------------------------------------------------------


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_search_rejects_non_finite_query_vector(bad: float) -> None:
    """RF-11 (negativo): un vector de consulta con NaN o inf → ValueError sin consultar."""
    engine = FakeEngine()

    with pytest.raises(ValueError, match="no finitos"):
        _store(engine).search([0.1, bad, 0.3], "x", 2)

    assert engine.begins == 0


# --- 6 · memory_boost y rrf_k no positivos --------------------------------------------------


@pytest.mark.parametrize("boost", [0.0, -1.0])
def test_non_positive_memory_boost_is_passed_through(boost: float) -> None:
    """RF-51 (comportamiento fijado): search no valida el boost; lo acota `PositiveFloat`."""
    engine = FakeEngine()

    _store(engine).search([0.1, 0.2, 0.3], "x", 1, memory_boost=boost)

    assert engine.statements("websearch_to_tsquery")[0]["memory_boost"] == boost


@pytest.mark.parametrize(("rrf_k", "factor"), [(-1, 4), (0, 4), (60, 0), (60, -2)])
def test_constructor_accepts_invalid_rrf_k_and_factor(rrf_k: int, factor: int) -> None:
    """RF-11 (comportamiento fijado): el constructor no valida rrf_k ni candidate_factor.

    Con rrf_k=-1 la fusión divide por cero en el rango 1; con factor ≤ 0 no hay candidatos.
    `build_vector_store` no los pasa (usa 60 y 4), así que solo es alcanzable por código.
    """
    engine = FakeEngine()

    _store(engine, rrf_k=rrf_k, candidate_factor=factor).search([0.1, 0.2, 0.3], "x", 2)

    params = engine.statements("websearch_to_tsquery")[0]
    assert (params["rrf_k"], params["candidates"]) == (rrf_k, 2 * factor)


# --- 7 · categorías distintas en un mismo documento ----------------------------------------


def test_upsert_rejects_mixed_categories_in_one_document() -> None:
    """RF-10 · RF-51 (negativo): un documento con dos categorías → ValueError sin escribir."""
    engine = FakeEngine()
    chunks = [
        _chunk("doc-a#0", ordinal=0, metadata={"category": "normativa"}),
        _chunk("doc-a#1", ordinal=1, metadata={"category": "memoria"}),
    ]

    with pytest.raises(ValueError):
        _store(engine).upsert(chunks)

    assert engine.executed == []


def test_document_fields_come_from_first_chunk_only() -> None:
    """RF-10 (comportamiento fijado): title y related_key del documento salen del 1.er fragmento."""
    engine = FakeEngine()
    chunks = [
        _chunk("doc-a#0", ordinal=0, metadata={"category": "normativa", "title": "Primero"}),
        _chunk(
            "doc-a#1",
            ordinal=1,
            metadata={"category": "normativa", "title": "Segundo", "related_key": "DEMO-9"},
        ),
    ]

    _store(engine).upsert(chunks)

    (doc,) = engine.statements("INSERT INTO documents")
    assert (doc["title"], doc["related_key"]) == ("Primero", None)


# --- 8 · _to_retrieved con metadata no textual ----------------------------------------------


def test_search_fails_with_validation_error_when_metadata_is_not_text() -> None:
    """RF-11 (comportamiento fijado, riesgo): metadata JSON no textual escrita fuera de
    `upsert` rompe la búsqueda con un ValidationError de pydantic, no con un error del dominio."""
    rows = [_row(metadata={"category": "normativa", "paginas": 12})]

    with pytest.raises(pydantic.ValidationError):
        _store(FakeEngine(rows=rows)).search([0.1, 0.2, 0.3], "x", 1)


def test_search_uses_uuids_when_metadata_is_null() -> None:
    """SPEC-00 §11: sin metadata (NULL) se devuelven los UUID como ids y metadata vacía."""
    rows = [_row(metadata=None)]

    (result,) = _store(FakeEngine(rows=rows)).search([0.1, 0.2, 0.3], "x", 1)

    assert result.chunk.id == str(to_uuid("doc-a#0"))
    assert result.chunk.document_id == str(to_uuid("doc-a"))
    assert result.chunk.metadata == {}


def test_search_removes_reserved_keys_and_restores_text_ids() -> None:
    """SPEC-00 §11: `_chunk_id`/`_document_id` se quitan y dan los ids de texto originales."""
    (result,) = _store(FakeEngine(rows=[_row()])).search([0.1, 0.2, 0.3], "x", 1)

    assert result.chunk.id == "doc-a#0"
    assert result.chunk.document_id == "doc-a"
    assert result.chunk.metadata == {"category": "normativa"}
    assert result.chunk.embedding is None


# --- 9 · extracto, kind y score -------------------------------------------------------------


def test_excerpt_is_cut_at_200_chars() -> None:
    """RF-11 · RF-21: el extracto de la fuente tiene como mucho 200 caracteres."""
    content = "á" * (EXCERPT_CHARS + 50)

    (result,) = _store(FakeEngine(rows=[_row(content=content)])).search([0.1, 0.2, 0.3], "x", 1)

    assert EXCERPT_CHARS == 200
    assert result.source.excerpt == content[:200]
    assert result.chunk.content == content


@pytest.mark.parametrize(
    ("category", "kind"),
    [
        ("memoria", "memory"),
        ("Memoria", "rag"),
        ("memorias", "rag"),
        ("normativa", "rag"),
        (None, "rag"),
    ],
)
def test_source_kind_is_memory_only_for_exact_memoria(category: str | None, kind: str) -> None:
    """RF-51: solo la categoría exacta «memoria» se marca como fuente `memory`."""
    (result,) = _store(FakeEngine(rows=[_row(category=category)])).search([0.1, 0.2, 0.3], "x", 1)

    assert result.source.kind == kind
    assert result.source.ref == "doc-a"


def test_score_is_float_when_db_returns_decimal() -> None:
    """RF-11: la puntuación de Postgres (numeric) se devuelve como float."""
    from decimal import Decimal

    (result,) = _store(FakeEngine(rows=[_row(score=Decimal("0.0325"))])).search(
        [0.1, 0.2, 0.3], "x", 1
    )

    assert result.score == pytest.approx(0.0325) and isinstance(result.score, float)


def test_search_keeps_db_order() -> None:
    """RF-11: el orden de las filas (ORDER BY score) se conserva."""
    rows = [
        _row(metadata={"category": "n", "_chunk_id": "b", "_document_id": "doc-b"}, score=0.9),
        _row(metadata={"category": "n", "_chunk_id": "a", "_document_id": "doc-a"}, score=0.1),
    ]

    results = _store(FakeEngine(rows=rows)).search([0.1, 0.2, 0.3], "x", 2)

    assert [r.chunk.id for r in results] == ["b", "a"]


# --- Integración (BD temporal propia; no se ejecutan sin PostgreSQL) -----------------------


@pytest.fixture(scope="module")
def cross_engine() -> Iterator[Engine]:
    """BD temporal migrada `<db>_cross_b_test`; nunca toca la BD configurada."""
    server_url: URL = Settings().sqlalchemy_url()
    test_db = f"{server_url.database}_cross_b_test"
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
def real_store(cross_engine: Engine) -> PgVectorStore:
    from core.config import load_models_config

    with cross_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE documents CASCADE"))
    return PgVectorStore(cross_engine, MODEL, load_models_config().embeddings.dimensions)


def _real_chunk(store: PgVectorStore, chunk_id: str, ordinal: int, category: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id="doc-mixto",
        ordinal=ordinal,
        content=f"Texto ficticio de renovación {ordinal}.",
        embedding=[0.1] * store.dimensions,
        metadata={"category": category},
    )


@pytest.mark.integration
def test_negative_rrf_k_fails_as_rejected_operation(real_store: PgVectorStore) -> None:
    """RF-11 (comportamiento fijado): rrf_k=-1 divide por cero en Postgres → error del dominio."""
    real_store.upsert([_real_chunk(real_store, "doc-mixto#0", 0, "normativa")])
    broken = PgVectorStore(real_store._engine, MODEL, real_store.dimensions, rrf_k=-1)

    with pytest.raises(ExternalServiceError, match="rechazó la operación"):
        broken.search([0.1] * real_store.dimensions, "renovación", 1)


@pytest.mark.integration
def test_mixed_category_document_is_rejected_without_writing(
    real_store: PgVectorStore,
) -> None:
    """RF-51 · PA-221: un documento con fragmentos de categorías distintas se rechaza antes de
    escribir, así que el filtro y la prioridad de la memoria no pueden discrepar."""
    with pytest.raises(ValueError, match="mezcla categorías"):
        real_store.upsert(
            [
                _real_chunk(real_store, "doc-mixto#0", 0, "normativa"),
                _real_chunk(real_store, "doc-mixto#1", 1, "memoria"),
            ]
        )

    assert (
        real_store.search(
            [0.1] * real_store.dimensions, "renovación", 5, filters={"category": "memoria"}
        )
        == []
    )


# --- PA-216 · replace_document: borrar e insertar en una sola transacción -------------------


def test_replace_document_deletes_and_upserts_in_one_transaction() -> None:
    """PA-216: un solo `begin()`: primero el borrado del documento y después sus fragmentos."""
    engine = FakeEngine()
    _store(engine).replace_document("doc-a", [_chunk(), _chunk("doc-a#1", ordinal=1)])
    assert engine.begins == 1
    kinds = [sql.split()[0].upper() for sql, _ in engine.executed]
    assert kinds[0] == "DELETE" and len(kinds) == 4  # borrado, documento y 2 fragmentos
    assert engine.executed[0][1] == {"id": to_uuid("doc-a")}


def test_replace_document_with_no_chunks_only_deletes() -> None:
    """PA-216: un documento que se queda sin fragmentos se borra, sin insertar nada."""
    engine = FakeEngine()
    _store(engine).replace_document("doc-a", [])
    assert engine.begins == 1 and len(engine.executed) == 1


def test_replace_document_validates_before_opening_a_transaction() -> None:
    """PA-216: un fragmento inválido o de otro documento no abre conexión ni borra nada."""
    engine = FakeEngine()
    with pytest.raises(ValueError):
        _store(engine).replace_document("doc-a", [_chunk("doc-b#0", "doc-b")])
    bad = _chunk().model_copy(update={"embedding": [float("nan"), 0.5, 1.0]})
    with pytest.raises(ValueError):
        _store(engine).replace_document("doc-a", [bad])
    assert engine.begins == 0 and engine.executed == []


def test_replace_document_maps_db_errors_without_url() -> None:
    """PA-216: un fallo dentro de la transacción sale como ExternalServiceError sin la URL."""
    engine = FakeEngine(error=sa.exc.DBAPIError("INSERT", {}, Exception(SECRET_URL)))
    with pytest.raises(ExternalServiceError) as info:
        _store(engine).replace_document("doc-a", [_chunk()])
    assert SECRET_URL not in str(info.value)
