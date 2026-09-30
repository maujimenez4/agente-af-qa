"""Entorno de Alembic: la URL de la base de datos se lee de core/config.py, nunca de alembic.ini."""

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL

from core.config import Settings

config = context.config
# Sin modelos ORM: las migraciones se escriben a mano (SPEC-00 §6).
target_metadata = None


def _database_url() -> URL:
    # Permite que las pruebas inyecten la URL sin pasar por .env.
    injected = config.attributes.get("database_url")
    return injected if injected is not None else Settings().sqlalchemy_url()


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (`alembic upgrade head --sql`)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        output_buffer=config.attributes.get("output_buffer"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
