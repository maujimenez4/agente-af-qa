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
    "user_last_project",  # 0003 (T-50)
    "conversations",  # 0004 (T-52)
    "qa_handoffs",  # 0005 (T-54)
    "quality_reviews",  # 0006 (PA-272)
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


# --- 0005 · qa_handoffs (T-54) --------------------------------------------------------------


def _qa_handoffs_sql(offline_sql: str) -> str:
    start = offline_sql.index("CREATE TABLE qa_handoffs")
    return offline_sql[start : offline_sql.index(");", start)]


def test_qa_handoffs_table_columns_and_nullability(offline_sql: str) -> None:
    """T-54 · criterio 10: qa_handoffs con la HU en JSONB y solo las claves opcionales nulas."""
    table = _qa_handoffs_sql(offline_sql)
    for column in (
        "id VARCHAR(32) NOT NULL",
        "artifact_id UUID NOT NULL",
        "version INTEGER NOT NULL",
        "project_key VARCHAR NOT NULL",
        "published BOOLEAN NOT NULL",
        "title VARCHAR NOT NULL",
        "story JSONB NOT NULL",
        "from_user VARCHAR NOT NULL",
        "from_thread_id VARCHAR(64) NOT NULL",
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
        "status VARCHAR DEFAULT 'pending' NOT NULL",
    ):
        assert column in table
    for nullable in ("story_key", "taken_by", "taken_at", "qa_thread_id"):
        (line,) = [x for x in table.splitlines() if x.strip().startswith(nullable + " ")]
        assert "NOT NULL" not in line
    assert "PRIMARY KEY (id)" in table


def test_qa_handoffs_constraints_and_index(offline_sql: str) -> None:
    """T-54 · criterio 10: única por versión y publicación, CHECK de clave, estado y recogida."""
    table = _qa_handoffs_sql(offline_sql)
    assert (
        "CONSTRAINT uq_qa_handoffs_artifact_version UNIQUE (artifact_id, version, published)"
        in table
    )
    assert "CONSTRAINT ck_qa_handoffs_key CHECK (published = (story_key IS NOT NULL))" in table
    assert "CONSTRAINT ck_qa_handoffs_status CHECK (status IN ('pending', 'taken'))" in table
    # Recogida exige quién, cuándo y en qué conversación; pendiente, ninguno de los tres.
    assert "CONSTRAINT ck_qa_handoffs_taken CHECK ((status = 'taken') = (taken_by IS NOT NULL" in (
        table
    )
    for column in ("taken_by", "taken_at", "qa_thread_id"):
        assert f"{column} IS NOT NULL" in table and f"{column} IS NULL" in table
    assert (
        "CREATE INDEX ix_qa_handoffs_status_created ON qa_handoffs (status, created_at)"
        in offline_sql
    )


def test_qa_handoffs_migration_follows_conversations(offline_sql: str) -> None:
    """T-54: 0005 se aplica justo después de 0004."""
    assert "-- Running upgrade 0004_conversations -> 0005_qa_handoffs" in offline_sql


def test_qa_handoffs_model_matches_migration_columns(offline_sql: str) -> None:
    """T-54: la tabla de SQLAlchemy de core/handoff.py tiene las columnas de la migración."""
    from core.handoff import QA_HANDOFFS

    table = _qa_handoffs_sql(offline_sql)
    migrated = set(re.findall(r"^\s{4}(\w+) [A-Z]", table, flags=re.MULTILINE))
    assert {c.name for c in QA_HANDOFFS.columns} == migrated - {"PRIMARY", "CONSTRAINT"}


def _insert_handoff(conn: sa.Connection, **values: object) -> None:
    row: dict[str, object] = {
        "id": "a" * 32,
        "artifact_id": "00000000-0000-0000-0000-000000000001",
        "version": 1,
        "project_key": "DEMO",
        "story_key": "DEMO-3",
        "published": True,
        "title": "Renovar un préstamo",
        "story": "{}",
        "from_user": "ana-ficticia",
        "from_thread_id": "hilo-ficticio",
        "status": "pending",
        "taken_by": None,
    }
    row |= values
    conn.execute(
        sa.text(
            "INSERT INTO qa_handoffs (id, artifact_id, version, project_key, story_key, "
            "published, title, story, from_user, from_thread_id, status, taken_by) VALUES "
            "(:id, :artifact_id, :version, :project_key, :story_key, :published, :title, "
            "CAST(:story AS JSONB), :from_user, :from_thread_id, :status, :taken_by)"
        ),
        row,
    )


@pytest.mark.integration
def test_migration_0005_constraints_against_postgres(database_url: URL) -> None:
    """T-54 · criterio 10 (PostgreSQL): restricciones de qa_handoffs y downgrade a 0004."""
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            _insert_handoff(conn)
            # Misma versión sin publicar: admitida (otra fila).
            _insert_handoff(conn, id="b" * 32, story_key=None, published=False)
        bad_rows = [
            {"id": "c" * 32},  # duplicada (artifact_id, version, published)
            {"id": "d" * 32, "version": 2, "story_key": None},  # published sin clave
            {"id": "e" * 32, "version": 3, "published": False},  # clave sin published
            {"id": "f" * 32, "version": 4, "status": "otro"},
            {"id": "1" * 32, "version": 5, "status": "taken"},  # recogida sin taken_by
            {"id": "2" * 32, "version": 6, "taken_by": "quim-ficticio"},  # pendiente con taken_by
        ]
        for bad in bad_rows:
            with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
                _insert_handoff(conn, **bad)
        indexes = {ix["name"] for ix in sa.inspect(engine).get_indexes("qa_handoffs")}
        assert "ix_qa_handoffs_status_created" in indexes
        command.downgrade(config, "0004_conversations")
        tables = set(sa.inspect(engine).get_table_names())
        assert "qa_handoffs" not in tables
        assert "conversations" in tables
    finally:
        engine.dispose()


# --- 0006 · quality_reviews (PA-272, PA-103) ------------------------------------------------


def _quality_reviews_sql(offline_sql: str) -> str:
    start = offline_sql.index("CREATE TABLE quality_reviews")
    return offline_sql[start : offline_sql.index(");", start)]


def _columns(table: str) -> set[str]:
    return set(re.findall(r"^\s{4}(\w+) [A-Z]", table, flags=re.MULTILINE)) - {
        "PRIMARY",
        "CONSTRAINT",
    }


def test_quality_reviews_table_columns_and_nullability(offline_sql: str) -> None:
    """PA-272 · criterio 3: quality_reviews con el informe en JSONB y los opcionales nulos."""
    table = _quality_reviews_sql(offline_sql)
    for column in (
        "id UUID NOT NULL",
        "username VARCHAR NOT NULL",
        "issue_key VARCHAR NOT NULL",
        "project_key VARCHAR NOT NULL",
        "state VARCHAR NOT NULL",
        "input_tokens INTEGER DEFAULT '0' NOT NULL",
        "output_tokens INTEGER DEFAULT '0' NOT NULL",
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
        "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL",
    ):
        assert column in table
    for nullable in (
        "report",
        "model",
        "prompt_version",
        "error_code",
        "error_message",
        "retry_after",
    ):
        (line,) = [x for x in table.splitlines() if x.strip().startswith(nullable + " ")]
        assert "NOT NULL" not in line
    assert "report JSONB" in table
    assert "PRIMARY KEY (id)" in table


def test_quality_reviews_never_store_story_or_prompts(offline_sql: str) -> None:
    """PA-272 · criterio 3: la tabla no tiene columnas para la HU ni para los prompts."""
    columns = _columns(_quality_reviews_sql(offline_sql))
    assert not columns & {"story", "prompt", "messages", "context", "description"}


def test_quality_reviews_check_constraints_and_index(offline_sql: str) -> None:
    """PA-272 · criterio 3: CHECK de state, de report (done) y de error; índice por persona."""
    table = _quality_reviews_sql(offline_sql)
    assert (
        "CONSTRAINT ck_quality_reviews_state CHECK (state IN ('running', 'done', 'error'))" in table
    )
    assert (
        "CONSTRAINT ck_quality_reviews_report CHECK ((state = 'done') = (report IS NOT NULL))"
        in table
    )
    assert (
        "CONSTRAINT ck_quality_reviews_error CHECK ((state = 'error') = "
        "(error_code IS NOT NULL AND error_message IS NOT NULL))" in table
    )
    assert (
        "CREATE INDEX ix_quality_reviews_username_updated ON quality_reviews "
        "(username, updated_at)" in offline_sql
    )


def test_quality_reviews_migration_follows_qa_handoffs(offline_sql: str) -> None:
    """PA-272 · criterio 3: 0006 se aplica justo después de 0005 y es la cabeza."""
    from alembic.script import ScriptDirectory

    assert "-- Running upgrade 0005_qa_handoffs -> 0006_quality_reviews" in offline_sql
    assert offline_sql.index("CREATE TABLE qa_handoffs") < offline_sql.index(
        "CREATE TABLE quality_reviews"
    )
    script = ScriptDirectory.from_config(_alembic_config(OFFLINE_URL))
    revision = script.get_revision("0006_quality_reviews")
    assert revision is not None and revision.down_revision == "0005_qa_handoffs"
    assert script.get_heads() == ["0006_quality_reviews"]


def test_quality_reviews_model_matches_migration_columns(offline_sql: str) -> None:
    """PA-272 · criterio 3: la tabla de core/quality.py tiene las columnas de la migración."""
    from core.quality import QUALITY_REVIEWS

    migrated = _columns(_quality_reviews_sql(offline_sql))
    assert {c.name for c in QUALITY_REVIEWS.columns} == migrated


def _insert_review(conn: sa.Connection, **values: object) -> None:
    row: dict[str, object] = {
        "id": "00000000-0000-0000-0000-00000000000a",
        "username": "ana-ficticia",
        "issue_key": "DEMO-3",
        "project_key": "DEMO",
        "state": "running",
        "report": None,
        "error_code": None,
        "error_message": None,
    }
    row |= values
    conn.execute(
        sa.text(
            "INSERT INTO quality_reviews (id, username, issue_key, project_key, state, report, "
            "error_code, error_message) VALUES (:id, :username, :issue_key, :project_key, "
            ":state, CAST(:report AS JSONB), :error_code, :error_message)"
        ),
        row,
    )


@pytest.mark.integration
def test_migration_0006_constraints_upgrade_and_downgrade(database_url: URL) -> None:
    """PA-272 · criterio 3 (PostgreSQL): CHECKs de quality_reviews y downgrade a 0005."""
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            _insert_review(conn)
            _insert_review(
                conn, id="00000000-0000-0000-0000-00000000000b", state="done", report="{}"
            )
            _insert_review(
                conn,
                id="00000000-0000-0000-0000-00000000000c",
                state="error",
                error_code="operation_failed",
                error_message="Error ficticio.",
            )
        bad_rows = [
            {"state": "otro"},
            {"state": "done"},  # terminada sin informe
            {"state": "running", "report": "{}"},  # en marcha con informe
            {"state": "error", "error_code": "operation_failed"},  # error sin mensaje
            {"state": "running", "error_code": "x", "error_message": "y"},  # en marcha con error
        ]
        for number, bad in enumerate(bad_rows, start=1):
            with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
                _insert_review(conn, id=f"00000000-0000-0000-0000-0000000001{number:02d}", **bad)
        indexes = {ix["name"] for ix in sa.inspect(engine).get_indexes("quality_reviews")}
        assert "ix_quality_reviews_username_updated" in indexes
        command.downgrade(config, "0005_qa_handoffs")
        tables = set(sa.inspect(engine).get_table_names())
        assert "quality_reviews" not in tables
        assert "qa_handoffs" in tables
        command.upgrade(config, "head")
        assert "quality_reviews" in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
