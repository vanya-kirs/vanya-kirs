"""Add sender_phone to messages

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("sender_phone", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "sender_phone")
