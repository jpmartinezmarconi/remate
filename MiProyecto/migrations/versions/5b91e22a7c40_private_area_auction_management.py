"""Add private auction management fields and persistent auction photos.

Revision ID: 5b91e22a7c40
Revises: fa6c621eaef3
"""
from alembic import op
import sqlalchemy as sa


revision = "5b91e22a7c40"
down_revision = "fa6c621eaef3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("auction", sa.Column("lot_number", sa.String(length=40), nullable=True))
    op.add_column(
        "auction",
        sa.Column(
            "commission_percent",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "auction",
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "auction",
        sa.Column("sale_mode", sa.String(length=12), nullable=False, server_default="lot"),
    )
    op.add_column(
        "auction",
        sa.Column(
            "group_name",
            sa.String(length=100),
            nullable=False,
            server_default="General",
        ),
    )
    op.add_column(
        "auction",
        sa.Column(
            "featured_on_home",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    with op.batch_alter_table("auction") as batch_op:
        batch_op.alter_column(
            "seller_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    op.create_table(
        "auction_image",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auction_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["auction_id"], ["auction.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auction_image_auction_id", "auction_image", ["auction_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_auction_image_auction_id", table_name="auction_image")
    op.drop_table("auction_image")
    with op.batch_alter_table("auction") as batch_op:
        batch_op.alter_column(
            "seller_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    op.drop_column("auction", "featured_on_home")
    op.drop_column("auction", "group_name")
    op.drop_column("auction", "sale_mode")
    op.drop_column("auction", "quantity")
    op.drop_column("auction", "commission_percent")
    op.drop_column("auction", "lot_number")
