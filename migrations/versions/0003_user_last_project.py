"""Último proyecto de Jira usado por cada persona, para preseleccionarlo (T-50).

Revision ID: 0003_user_last_project
Revises: 0002_artifact_state
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_user_last_project"
down_revision: str | None = "0002_artifact_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sin clave foránea a `users`: es una preferencia, no un dato del usuario (D-01).
    op.create_table(
        "user_last_project",
        sa.Column("username", sa.String(), primary_key=True),
        sa.Column("project_key", sa.String(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("user_last_project")
