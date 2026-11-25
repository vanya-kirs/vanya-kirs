"""Add last_tg_message_id to sources for incremental parsing

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("last_tg_message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "last_tg_message_id")
