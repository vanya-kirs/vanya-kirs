"""Add score_skip_reason to messages

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("score_skip_reason", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "score_skip_reason")
