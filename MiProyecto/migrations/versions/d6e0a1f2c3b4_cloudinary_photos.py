"""Store photo references in Cloudinary.

Revision ID: d6e0a1f2c3b4
Revises: 9c2a7f4e1b63
"""
from alembic import op
import sqlalchemy as sa


revision = "d6e0a1f2c3b4"
down_revision = "9c2a7f4e1b63"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("auction_image") as batch_op:
        batch_op.add_column(sa.Column("cloud_url", sa.String(2048), nullable=True))
        batch_op.add_column(sa.Column("cloud_public_id", sa.String(255), nullable=True))
        batch_op.alter_column("data", existing_type=sa.LargeBinary(), nullable=True)


def downgrade():
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT COUNT(*) FROM auction_image WHERE data IS NULL")
    ).scalar():
        raise RuntimeError("Restore the photo data before downgrading.")
    with op.batch_alter_table("auction_image") as batch_op:
        batch_op.alter_column("data", existing_type=sa.LargeBinary(), nullable=False)
        batch_op.drop_column("cloud_public_id")
        batch_op.drop_column("cloud_url")
