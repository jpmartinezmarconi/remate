"""Track password reset request cooldowns.

Revision ID: 4f2a9c7d1e63
Revises: e8b61c9d2a40
"""
from alembic import op
import sqlalchemy as sa


revision = "4f2a9c7d1e63"
down_revision = "e8b61c9d2a40"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("password_reset_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("user", "password_reset_requested_at")
