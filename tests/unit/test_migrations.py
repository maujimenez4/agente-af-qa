"""Pruebas de la migración inicial (T-04 · CA-00-06).

La prueba offline genera el SQL sin base de datos. La de integración aplica y revierte la
migración contra el PostgreSQL de `docker compose up -d db` y se salta si no está disponible.
"""

import io
import re
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from core.config import ROOT_DIR, Settings, load_models_config

TABLES = {
    "users",
    "artifacts",
    "artifact_versions",
    "audit_log",
    "documents",
    "chunks",
    "llm_usage",
}

OFFLINE_URL = URL.create("postgresql+psycopg", username="agente", host="localhost", database="x")


def _alembic_config(url: URL, stdout: io.StringIO | None = None) -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"), stdout=stdout or io.StringIO())
    config.attributes["database_url"] = url
    config.attributes["output_buffer"] = stdout
    return config


@pytest.fixture(scope="module")
def offline_sql() -> str:
    buffer = io.StringIO()
    command.upgrade(_alembic_config(OFFLINE_URL, buffer), "head", sql=True)
    return buffer.getvalue()


def test_creates_vector_extension(offline_sql: str) -> None:
    assert "CREATE EXTENSION IF NOT EXISTS vector" in offline_sql


def test_creates_all_spec_tables(offline_sql: str) -> None:
    created = set(re.findall(r"CREATE TABLE (\w+)", offline_sql))
    assert created >= TABLES


def test_embedding_dimension_comes_from_config(offline_sql: str) -> None:
    dimensions = load_models_config().embeddings.dimensions
    assert f"embedding VECTOR({dimensions})" in offline_sql


def test_embedding_and_fulltext_indexes(offline_sql: str) -> None:
    assert re.search(r"CREATE INDEX ix_chunks_embedding ON chunks USING hnsw", offline_sql)
    assert "vector_cosine_ops" in offline_sql
    assert re.search(r"CREATE INDEX ix_chunks_tsv ON chunks USING gin", offline_sql)


def test_status_and_action_constraints(offline_sql: str) -> None:
    for value in ("draft", "in_review", "approved", "published", "discarded"):
        assert f"'{value}'" in offline_sql
    for value in ("create", "iterate", "approve", "publish", "discard"):
        assert f"'{value}'" in offline_sql
    for role in ("functional", "qa", "admin"):
        assert f"'{role}'" in offline_sql


def test_alembic_ini_has_no_database_url() -> None:
    ini = (ROOT_DIR / "alembic.ini").read_text(encoding="utf-8")
    assert not re.search(r"^sqlalchemy\.url\s*=", ini, flags=re.MULTILINE)


def test_sqlalchemy_url_is_built_from_postgres_vars(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("POSTGRES_PASSWORD", "clave-ficticia-ñ@1")
    url = Settings(_env_file=None).sqlalchemy_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "clave-ficticia-ñ@1"
    assert "clave-ficticia" not in str(url)  # str() oculta la contraseña


# --- Integración ------------------------------------------------------------------------


@pytest.fixture
def database_url() -> Iterator[URL]:
    """BD temporal `<db>_migrations_test`: la prueba nunca toca la base de datos configurada."""
    server_url = Settings().sqlalchemy_url()
    test_db = f"{server_url.database}_migrations_test"
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
    try:
        yield server_url.set(database=test_db)
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.integration
def test_upgrade_and_downgrade_against_postgres(database_url: URL) -> None:
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)
    try:
        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names()) >= TABLES
        indexes = {ix["name"] for ix in inspector.get_indexes("chunks")}
        assert {"ix_chunks_embedding", "ix_chunks_tsv"} <= indexes
        with engine.connect() as conn:
            assert conn.execute(
                sa.text("SELECT 1 FROM pg_extension WHERE extname='vector'")
            ).scalar()
            dims = conn.execute(
                sa.text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
                )
            ).scalar()
            assert dims == load_models_config().embeddings.dimensions
        command.downgrade(config, "base")
        assert not set(sa.inspect(engine).get_table_names()) & TABLES
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_tsv_is_stored_generated_column(offline_sql: str) -> None:
    assert re.search(
        r"tsv TSVECTOR GENERATED ALWAYS AS \(to_tsvector\('spanish'.*\) STORED", offline_sql
    )
