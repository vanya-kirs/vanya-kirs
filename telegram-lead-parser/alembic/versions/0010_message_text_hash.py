"""Add text_hash to messages

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("text_hash", sa.String(32), nullable=True))
    op.create_index("ix_messages_text_hash", "messages", ["text_hash"])


def downgrade() -> None:
    op.drop_index("ix_messages_text_hash", table_name="messages")
    op.drop_column("messages", "text_hash")
