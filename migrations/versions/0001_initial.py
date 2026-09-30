"""Esquema inicial: tablas de la SPEC-00 §6, extensión vector e índices.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from core.config import load_models_config

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Dimensión del embedding según config/models.yaml. Si cambia, hace falta una migración nueva.
EMBEDDING_DIMENSIONS = load_models_config().embeddings.dimensions

ROLES = ("functional", "qa", "admin")
ARTIFACT_TYPES = ("user_story", "test_suite")
ARTIFACT_STATUSES = ("draft", "in_review", "approved", "published", "discarded")
AUDIT_ACTIONS = ("create", "iterate", "approve", "publish", "discard")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _jsonb(name: str, nullable: bool = False, default: str | None = "'{}'::jsonb") -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(),
        nullable=nullable,
        server_default=sa.text(default) if default else None,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _created_at(),
        sa.CheckConstraint(_in("role", ROLES), name="ck_users_role"),
    )

    op.create_table(
        "artifacts",
        _uuid_pk(),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("origin_key", sa.Text()),
        sa.Column("jira_key", sa.Text()),
        _jsonb("content", default=None),
        _jsonb("impact", nullable=True, default=None),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("model_used", sa.Text()),
        sa.Column("prompt_version", sa.Text()),
        _created_at(),
        _created_at("updated_at"),
        sa.CheckConstraint(_in("type", ARTIFACT_TYPES), name="ck_artifacts_type"),
        sa.CheckConstraint(_in("status", ARTIFACT_STATUSES), name="ck_artifacts_status"),
        sa.CheckConstraint("version >= 1", name="ck_artifacts_version"),
    )
    op.create_index("ix_artifacts_jira_key", "artifacts", ["jira_key"])
    op.create_index("ix_artifacts_origin_key", "artifacts", ["origin_key"])
    op.create_index("ix_artifacts_status", "artifacts", ["status"])

    op.create_table(
        "artifact_versions",
        sa.Column(
            "artifact_id",
            sa.Uuid(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        _jsonb("content", default=None),
        _created_at(),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        # La auditoría se conserva aunque se elimine el artefacto.
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("user", sa.Text(), nullable=False),
        sa.Column(
            "jira_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("model", sa.Text()),
        _jsonb("detail"),
        _created_at("at"),
        sa.CheckConstraint(_in("action", AUDIT_ACTIONS), name="ck_audit_log_action"),
    )
    op.create_index("ix_audit_log_artifact_id", "audit_log", ["artifact_id"])
    op.create_index("ix_audit_log_at", "audit_log", ["at"])

    op.create_table(
        "documents",
        _uuid_pk(),
        sa.Column("title", sa.Text(), nullable=False),
        # 7 categorías + 'memoria'; sin CHECK hasta que se definan las categorías (T-09/T-12).
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text()),
        sa.Column("embedding_model", sa.Text()),
        sa.Column("content_hash", sa.Text()),
        sa.Column("related_key", sa.Text()),
        _created_at(),
    )
    op.create_index("ix_documents_category", "documents", ["category"])
    op.create_index("ix_documents_related_key", "documents", ["related_key"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    op.create_table(
        "chunks",
        _uuid_pk(),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS)),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('spanish', coalesce(section, '') || ' ' || content)", persisted=True
            ),
        ),
        _jsonb("metadata"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_ordinal"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("est_cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id", ondelete="SET NULL")),
        _created_at("at"),
    )
    op.create_index("ix_llm_usage_at", "llm_usage", ["at"])
    op.create_index("ix_llm_usage_task", "llm_usage", ["task"])


def downgrade() -> None:
    for table in (
        "llm_usage",
        "chunks",
        "documents",
        "audit_log",
        "artifact_versions",
        "artifacts",
        "users",
    ):
        op.drop_table(table)
    # La extensión vector se conserva: puede usarla otra base de datos del mismo servidor.
