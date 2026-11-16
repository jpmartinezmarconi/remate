"""Support Telegram links and outbid notifications.

Revision ID: 9c2a7f4e1b63
Revises: b84d71a2c650
"""
from alembic import op
import sqlalchemy as sa


revision = "9c2a7f4e1b63"
down_revision = "b84d71a2c650"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user", sa.Column("telegram_chat_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "user", sa.Column("telegram_link_token", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "user",
        sa.Column(
            "telegram_link_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_user_telegram_chat_id",
        "user",
        ["telegram_chat_id"],
        unique=True,
    )
    op.add_column(
        "auction_outbid_notification",
        sa.Column("telegram_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("auction_outbid_notification", "telegram_sent_at")
    op.drop_index("uq_user_telegram_chat_id", table_name="user")
    op.drop_column("user", "telegram_link_token_expires_at")
    op.drop_column("user", "telegram_link_token")
    op.drop_column("user", "telegram_chat_id")
