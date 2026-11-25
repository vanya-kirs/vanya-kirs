"""Add auth fields to users: email, password_hash, make telegram_id nullable

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Make telegram_id nullable (users registered via email won't have one)
    op.alter_column("users", "telegram_id", nullable=True)

    # Add email (unique, indexed)
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Add password_hash
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email")
    op.alter_column("users", "telegram_id", nullable=False)
