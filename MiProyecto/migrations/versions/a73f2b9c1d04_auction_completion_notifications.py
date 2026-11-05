"""Track sent auction completion emails.

Revision ID: a73f2b9c1d04
Revises: 4f2a9c7d1e63
"""
from alembic import op
import sqlalchemy as sa


revision = "a73f2b9c1d04"
down_revision = "4f2a9c7d1e63"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auction_completion_notification",
        sa.Column("auction_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["auction_id"], ["auction.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("auction_id"),
    )


def downgrade():
    op.drop_table("auction_completion_notification")
