"""Queue email notifications when a bidder is outbid.

Revision ID: e8b61c9d2a40
Revises: c4a9d8e1f207
"""
from alembic import op
import sqlalchemy as sa


revision = "e8b61c9d2a40"
down_revision = "c4a9d8e1f207"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auction_outbid_notification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outbid_bid_id", sa.Integer(), nullable=False),
        sa.Column("replacement_bid_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["outbid_bid_id"], ["bid.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["replacement_bid_id"], ["bid.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbid_bid_id"),
    )


def downgrade():
    op.drop_table("auction_outbid_notification")
