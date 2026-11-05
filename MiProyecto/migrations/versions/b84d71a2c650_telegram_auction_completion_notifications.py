"""Track Telegram delivery for auction completion notifications.

Revision ID: b84d71a2c650
Revises: a73f2b9c1d04
"""
from alembic import op
import sqlalchemy as sa


revision = "b84d71a2c650"
down_revision = "a73f2b9c1d04"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("auction_completion_notification") as batch_op:
        batch_op.alter_column(
            "sent_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("telegram_sent_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    op.execute(
        sa.text(
            "UPDATE auction_completion_notification "
            "SET sent_at = COALESCE(telegram_sent_at, CURRENT_TIMESTAMP) "
            "WHERE sent_at IS NULL"
        )
    )
    with op.batch_alter_table("auction_completion_notification") as batch_op:
        batch_op.drop_column("telegram_sent_at")
        batch_op.alter_column(
            "sent_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
