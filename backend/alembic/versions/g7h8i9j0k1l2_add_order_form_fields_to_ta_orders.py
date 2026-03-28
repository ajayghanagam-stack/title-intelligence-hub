"""add order form fields to ta_orders

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-03-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ta_orders', sa.Column('city', sa.String(100), nullable=True))
    op.add_column('ta_orders', sa.Column('zip_code', sa.String(20), nullable=True))
    op.add_column('ta_orders', sa.Column('borrower_name', sa.String(500), nullable=True))
    op.add_column('ta_orders', sa.Column('order_reference', sa.String(200), nullable=True))
    op.add_column('ta_orders', sa.Column('effective_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('ta_orders', 'effective_date')
    op.drop_column('ta_orders', 'order_reference')
    op.drop_column('ta_orders', 'borrower_name')
    op.drop_column('ta_orders', 'zip_code')
    op.drop_column('ta_orders', 'city')
