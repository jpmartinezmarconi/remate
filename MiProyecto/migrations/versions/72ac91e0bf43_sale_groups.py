"""Create persistent sales groups and link existing auctions.

Revision ID: 72ac91e0bf43
Revises: 3c8f2d1a6b75
"""
from alembic import op
import sqlalchemy as sa


revision = "72ac91e0bf43"
down_revision = "3c8f2d1a6b75"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auction_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.execute(
        sa.text(
            "INSERT INTO auction_group (name) "
            "SELECT DISTINCT group_name FROM auction"
        )
    )
    with op.batch_alter_table("auction") as batch_op:
        batch_op.add_column(sa.Column("group_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_auction_group_id_auction_group",
            "auction_group",
            ["group_id"],
            ["id"],
        )
    groups = op.get_bind().execute(
        sa.text("SELECT id, name FROM auction_group")
    ).all()
    for group_id, name in groups:
        op.execute(
            sa.text("UPDATE auction SET group_id = :group_id WHERE group_name = :name")
            .bindparams(group_id=group_id, name=name)
        )
    with op.batch_alter_table("auction") as batch_op:
        batch_op.alter_column(
            "group_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    op.create_index("ix_auction_group_id", "auction", ["group_id"], unique=False)


def downgrade():
    op.drop_index("ix_auction_group_id", table_name="auction")
    with op.batch_alter_table("auction") as batch_op:
        batch_op.drop_constraint("fk_auction_group_id_auction_group", type_="foreignkey")
        batch_op.drop_column("group_id")
    op.drop_table("auction_group")
