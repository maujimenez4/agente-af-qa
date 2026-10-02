"""Entregas de HU aprobadas a QA para el flujo unido HU → QA (T-54).

Cada fila es una versión aprobada o publicada que el analista funcional pasa a QA. La HU se
copia del servidor al crear la entrega (`story`); la recoge una sola persona con rol QA.

Revision ID: 0005_qa_handoffs
Revises: 0004_conversations
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_qa_handoffs"
down_revision: str | None = "0004_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "qa_handoffs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("project_key", sa.String(), nullable=False),
        sa.Column("story_key", sa.String()),
        # Una versión aprobada en simulación y la misma versión ya publicada son entregas
        # distintas: la segunda lleva la clave de Jira y sus casos sí se pueden publicar.
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("story", postgresql.JSONB(), nullable=False),
        sa.Column("from_user", sa.String(), nullable=False),
        sa.Column("from_thread_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("taken_by", sa.String()),
        sa.Column("taken_at", sa.DateTime(timezone=True)),
        sa.Column("qa_thread_id", sa.String(64)),
        sa.UniqueConstraint(
            "artifact_id", "version", "published", name="uq_qa_handoffs_artifact_version"
        ),
        sa.CheckConstraint("published = (story_key IS NOT NULL)", name="ck_qa_handoffs_key"),
        sa.CheckConstraint("status IN ('pending', 'taken')", name="ck_qa_handoffs_status"),
        # Recogida = quién, cuándo y en qué conversación; pendiente = nada de eso.
        sa.CheckConstraint(
            "(status = 'taken') = (taken_by IS NOT NULL AND taken_at IS NOT NULL "
            "AND qa_thread_id IS NOT NULL) "
            "AND (status = 'pending') = (taken_by IS NULL AND taken_at IS NULL "
            "AND qa_thread_id IS NULL)",
            name="ck_qa_handoffs_taken",
        ),
    )
    op.create_index("ix_qa_handoffs_status_created", "qa_handoffs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_qa_handoffs_status_created", table_name="qa_handoffs")
    op.drop_table("qa_handoffs")
