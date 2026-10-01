"""Estado de trabajo por artefacto: aprobaciones y versión de partida de Jira (T-25).

Revision ID: 0002_artifact_state
Revises: 0001_initial
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_artifact_state"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sin clave foránea: el registro de aprobaciones se crea al ofrecer la primera versión.
    op.create_table(
        "artifact_state",
        sa.Column("artifact_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("artifact_state")
