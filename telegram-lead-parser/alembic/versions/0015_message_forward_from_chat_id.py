"""message forward_from_chat_id

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("forward_from_chat_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_messages_forward_from_chat_id",
        "messages",
        ["forward_from_chat_id"],
        postgresql_where=sa.text("forward_from_chat_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_messages_forward_from_chat_id", table_name="messages")
    op.drop_column("messages", "forward_from_chat_id")
