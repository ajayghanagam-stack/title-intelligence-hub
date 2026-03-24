"""add tool hash columns to pipeline runs

Revision ID: a1b2c3d4e5f6
Revises: bc088a9a84de
Create Date: 2026-03-23 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'bc088a9a84de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add with server_default first so existing rows get a value, then drop the default
    op.add_column(
        'ti_pipeline_runs',
        sa.Column('extraction_tool_hash', sa.String(64), nullable=False, server_default=''),
    )
    op.add_column(
        'ti_pipeline_runs',
        sa.Column('risk_tool_hash', sa.String(64), nullable=False, server_default=''),
    )
    # Remove server defaults — new rows must provide values explicitly
    op.alter_column('ti_pipeline_runs', 'extraction_tool_hash', server_default=None)
    op.alter_column('ti_pipeline_runs', 'risk_tool_hash', server_default=None)


def downgrade() -> None:
    op.drop_column('ti_pipeline_runs', 'risk_tool_hash')
    op.drop_column('ti_pipeline_runs', 'extraction_tool_hash')
