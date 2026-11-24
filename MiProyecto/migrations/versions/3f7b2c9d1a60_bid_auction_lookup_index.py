"""Index bid lookups by auction."""

from alembic import op


revision = "3f7b2c9d1a60"
down_revision = "d6e0a1f2c3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_bid_auction_id", "bid", ["auction_id"], unique=False)


def downgrade():
    op.drop_index("ix_bid_auction_id", table_name="bid")
