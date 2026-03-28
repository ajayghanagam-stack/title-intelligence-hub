"""add examine_progress to ti_packs

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6g7h8i9"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ti_packs",
        sa.Column("examine_progress", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ti_packs", "examine_progress")
