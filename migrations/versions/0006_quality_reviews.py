"""Revisiones de calidad guardadas (PA-272, PA-103).

«Revisar la calidad» (T-48) no pasa por el grafo ni escribe en Jira; hasta ahora vivía en la
memoria del proceso. Cada fila es una revisión de una persona: estado, informe validado
(`QualityReport`) y error en la forma común. Nunca guarda la HU ni los prompts.

Revision ID: 0006_quality_reviews
Revises: 0005_qa_handoffs
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_quality_reviews"
down_revision: str | None = "0005_qa_handoffs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("issue_key", sa.String(), nullable=False),
        sa.Column("project_key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("report", postgresql.JSONB()),
        sa.Column("model", sa.String()),
        sa.Column("prompt_version", sa.String()),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.String()),
        sa.Column("retry_after", sa.Float()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "state IN ('running', 'done', 'error')", name="ck_quality_reviews_state"
        ),
        # Terminada = con informe; con error = con código y mensaje.
        sa.CheckConstraint(
            "(state = 'done') = (report IS NOT NULL)", name="ck_quality_reviews_report"
        ),
        sa.CheckConstraint(
            "(state = 'error') = (error_code IS NOT NULL AND error_message IS NOT NULL)",
            name="ck_quality_reviews_error",
        ),
    )
    op.create_index(
        "ix_quality_reviews_username_updated", "quality_reviews", ["username", "updated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_quality_reviews_username_updated", table_name="quality_reviews")
    op.drop_table("quality_reviews")
