"""lead_signals table

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "found_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("lead_id", "message_id", name="uq_lead_signals_lead_message"),
    )
    op.create_index("ix_lead_signals_lead_id", "lead_signals", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_signals_lead_id", table_name="lead_signals")
    op.drop_table("lead_signals")
