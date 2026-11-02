"""Add user shipping profiles and auction payment records.

Revision ID: 3c8f2d1a6b75
Revises: 91d4a0b7c2ef
"""
from alembic import op
import sqlalchemy as sa


revision = "3c8f2d1a6b75"
down_revision = "91d4a0b7c2ef"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("full_name", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "user",
        sa.Column("phone", sa.String(length=40), nullable=False, server_default=""),
    )
    op.add_column(
        "user",
        sa.Column(
            "shipping_address",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "user",
        sa.Column("city", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "user",
        sa.Column("postal_code", sa.String(length=20), nullable=False, server_default=""),
    )
    op.create_table(
        "auction_payment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auction_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(precision=22, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["auction_id"], ["auction.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("auction_id", name="uq_auction_payment_auction"),
    )
    op.create_index(
        "ix_auction_payment_user_id", "auction_payment", ["user_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_auction_payment_user_id", table_name="auction_payment")
    op.drop_table("auction_payment")
    op.drop_column("user", "postal_code")
    op.drop_column("user", "city")
    op.drop_column("user", "shipping_address")
    op.drop_column("user", "phone")
    op.drop_column("user", "full_name")
