"""rejected_sources table

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rejected_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(500), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovery_method", sa.String(30), nullable=False, server_default=""),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_rejected_sources_reason", "rejected_sources", ["reason"])
    op.create_index("ix_rejected_sources_member_count", "rejected_sources", ["member_count"])


def downgrade() -> None:
    op.drop_index("ix_rejected_sources_member_count", table_name="rejected_sources")
    op.drop_index("ix_rejected_sources_reason", table_name="rejected_sources")
    op.drop_table("rejected_sources")
