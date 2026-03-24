"""add ti_pipeline_runs table

Revision ID: bc088a9a84de
Revises: bbf2099bc58b
Create Date: 2026-03-23 15:16:32.087181

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = 'bc088a9a84de'
down_revision: Union[str, None] = 'bbf2099bc58b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ti_pipeline_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('pack_id', UUID(as_uuid=True), sa.ForeignKey('ti_packs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id'), nullable=False, index=True),
        sa.Column('input_file_hash', sa.String(64), nullable=True),
        sa.Column('ai_platform', sa.String(50), nullable=False),
        sa.Column('ai_model', sa.String(100), nullable=False),
        sa.Column('ingestion_prompt_hash', sa.String(64), nullable=False),
        sa.Column('risk_prompt_hash', sa.String(64), nullable=False),
        sa.Column('ocr_engine', sa.String(100), nullable=False),
        sa.Column('chunker_version', sa.String(50), nullable=False),
        sa.Column('rules_version', sa.String(50), nullable=False),
        sa.Column('pipeline_backend', sa.String(50), nullable=False),
        sa.Column('version_metadata', JSONB, nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default=sa.text("'running'")),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.execute("ALTER TABLE ti_pipeline_runs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table('ti_pipeline_runs')
