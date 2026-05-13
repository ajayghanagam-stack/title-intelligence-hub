"""Phase 3 hard stop overrides

Revision ID: 6eb14b88b282
Revises: s0t1u2v3w4x5
Create Date: 2026-05-09 20:21:53.372091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.compat


# revision identifiers, used by Alembic.
revision: str = '6eb14b88b282'
down_revision: Union[str, None] = 's0t1u2v3w4x5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lo_hard_stop_overrides',
        sa.Column('id', app.models.compat.UUID(as_uuid=True), nullable=False),
        sa.Column('package_id', app.models.compat.UUID(as_uuid=True), nullable=False),
        sa.Column('hard_stop_key', sa.String(length=255), nullable=False),
        sa.Column('supervisor_id', app.models.compat.UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('org_id', app.models.compat.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['package_id'], ['lo_packages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['supervisor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'package_id', 'hard_stop_key', 'created_at',
            name='uq_lo_hard_stop_overrides_pkg_key_created',
        ),
    )
    op.create_index(
        op.f('ix_lo_hard_stop_overrides_hard_stop_key'),
        'lo_hard_stop_overrides', ['hard_stop_key'], unique=False,
    )
    op.create_index(
        op.f('ix_lo_hard_stop_overrides_org_id'),
        'lo_hard_stop_overrides', ['org_id'], unique=False,
    )
    op.create_index(
        op.f('ix_lo_hard_stop_overrides_package_id'),
        'lo_hard_stop_overrides', ['package_id'], unique=False,
    )
    op.create_index(
        op.f('ix_lo_hard_stop_overrides_supervisor_id'),
        'lo_hard_stop_overrides', ['supervisor_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_lo_hard_stop_overrides_supervisor_id'),
        table_name='lo_hard_stop_overrides',
    )
    op.drop_index(
        op.f('ix_lo_hard_stop_overrides_package_id'),
        table_name='lo_hard_stop_overrides',
    )
    op.drop_index(
        op.f('ix_lo_hard_stop_overrides_org_id'),
        table_name='lo_hard_stop_overrides',
    )
    op.drop_index(
        op.f('ix_lo_hard_stop_overrides_hard_stop_key'),
        table_name='lo_hard_stop_overrides',
    )
    op.drop_table('lo_hard_stop_overrides')
