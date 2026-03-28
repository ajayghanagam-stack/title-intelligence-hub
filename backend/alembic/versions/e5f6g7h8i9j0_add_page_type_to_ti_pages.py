"""add page_type to ti_pages

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6g7h8i9j0"
down_revision = "d4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ti_pages",
        sa.Column("page_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ti_pages", "page_type")
