"""BD temporal de PostgreSQL para las pruebas de integración de T-25.

Crea `<db>_<sufijo>` en el servidor de `docker compose up -d db`, aplica las migraciones y la
borra al terminar. Nunca toca la base de datos configurada; si el servidor no responde, la prueba
se salta.
"""

import io
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, Engine

from core.config import ROOT_DIR, Settings


def alembic_config(url: URL) -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"), stdout=io.StringIO())
    config.attributes["database_url"] = url
    return config


@contextmanager
def temporary_database(suffix: str, revision: str | None = "head") -> Iterator[tuple[URL, Engine]]:
    """BD vacía migrada hasta `revision` (None: sin migrar)."""
    server_url: URL = Settings().sqlalchemy_url()
    test_db = f"{server_url.database}_{suffix}"
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
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        if revision is not None:
            command.upgrade(alembic_config(url), revision)
        yield url, engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
        admin.dispose()


def truncate_t25_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE artifacts, artifact_state CASCADE"))
