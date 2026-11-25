"""messages unique constraint on (source_id, tg_message_id)

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-03 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_messages_source_tg_id",
        "messages",
        ["source_id", "tg_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_messages_source_tg_id", "messages", type_="unique")
