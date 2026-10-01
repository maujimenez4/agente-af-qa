"""Índice de conversaciones por usuario para la barra lateral (T-52).

Las tablas del checkpointer de LangGraph no van aquí: `PostgresSaver.setup()` las crea al
arrancar la aplicación porque usa `CREATE INDEX CONCURRENTLY`, que no admite transacción.

Revision ID: 0004_conversations
Revises: 0003_user_last_project
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_conversations"
down_revision: str | None = "0003_user_last_project"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("project_key", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("origin_kind", sa.String(), nullable=False),
        sa.Column("origin_key", sa.String()),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.Uuid()),
        sa.Column("version", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("mode IN ('functional', 'qa')", name="ck_conversations_mode"),
        sa.CheckConstraint(
            "status IN ('started', 'in_review', 'approved', 'published', 'simulated', 'discarded')",
            name="ck_conversations_status",
        ),
    )
    op.create_index(
        "ix_conversations_username_updated", "conversations", ["username", "updated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_username_updated", table_name="conversations")
    op.drop_table("conversations")
