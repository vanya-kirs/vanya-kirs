"""source status and joined_at

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing sources are already active — default 'active' for them
    op.add_column(
        "sources",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "sources",
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sources_status", "sources", ["status"])


def downgrade() -> None:
    op.drop_index("ix_sources_status", table_name="sources")
    op.drop_column("sources", "joined_at")
    op.drop_column("sources", "status")
