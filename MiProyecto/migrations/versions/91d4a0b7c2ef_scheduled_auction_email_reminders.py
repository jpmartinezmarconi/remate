"""Schedule auction start times and add email reminder subscriptions.

Revision ID: 91d4a0b7c2ef
Revises: 5b91e22a7c40
"""
from alembic import op
import sqlalchemy as sa


revision = "91d4a0b7c2ef"
down_revision = "5b91e22a7c40"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "auction",
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("UPDATE auction SET starts_at = created_at"))
    with op.batch_alter_table("auction") as batch_op:
        batch_op.alter_column(
            "starts_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.create_index("ix_auction_starts_at", "auction", ["starts_at"], unique=False)
    op.create_table(
        "auction_reminder",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auction_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["auction_id"], ["auction.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "auction_id", "user_id", name="uq_auction_reminder_user"
        ),
    )
    op.create_index(
        "ix_auction_reminder_sent_at", "auction_reminder", ["sent_at"], unique=False
    )


def downgrade():
    op.drop_index("ix_auction_reminder_sent_at", table_name="auction_reminder")
    op.drop_table("auction_reminder")
    op.drop_index("ix_auction_starts_at", table_name="auction")
    op.drop_column("auction", "starts_at")
