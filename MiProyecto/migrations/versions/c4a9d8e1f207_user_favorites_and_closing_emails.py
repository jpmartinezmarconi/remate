"""Add auction favorites and one-time closing reminders for bidders.

Revision ID: c4a9d8e1f207
Revises: 72ac91e0bf43
"""
from alembic import op
import sqlalchemy as sa


revision = "c4a9d8e1f207"
down_revision = "72ac91e0bf43"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auction_favorite",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("auction_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["auction_id"], ["auction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "auction_id", name="uq_auction_favorite_user"
        ),
    )
    op.create_table(
        "auction_closing_reminder",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auction_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["auction_id"], ["auction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "auction_id", "user_id", name="uq_auction_closing_reminder_user"
        ),
    )


def downgrade():
    op.drop_table("auction_closing_reminder")
    op.drop_table("auction_favorite")
