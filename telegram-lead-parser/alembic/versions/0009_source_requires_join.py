"""Add requires_join and join_queued_at to sources

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("requires_join", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "sources",
        sa.Column("join_queued_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "join_queued_at")
    op.drop_column("sources", "requires_join")
