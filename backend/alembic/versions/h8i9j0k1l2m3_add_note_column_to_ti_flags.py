"""add note column to ti_flags

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-03-31
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column('ti_flags', sa.Column('note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('ti_flags', 'note')
