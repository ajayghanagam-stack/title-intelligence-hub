"""add lo_extractions table

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-04-27

Creates the `lo_extractions` table — one row per stack per package that
holds the structured field-extraction output produced by the new
`extract` pipeline stage. The `fields` JSONB column carries the ordered
list of {name, value, confidence, status, page?, bbox?} records that the
ResultsScreen and Dashboard consume.

`stack_id` is unique so the extract stage can use simple delete-then-
insert for idempotent retries (mirrors how validation_results works).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = "p6q7r8s9t0u1"
down_revision: Union[str, None] = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lo_extractions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "package_id",
            UUID(as_uuid=True),
            sa.ForeignKey("lo_packages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "stack_id",
            UUID(as_uuid=True),
            sa.ForeignKey("lo_stacks.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("doc_type", sa.String(length=100), nullable=False),
        sa.Column("fields", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("located_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Drop server_defaults that are only there to backfill safely; new
    # rows pick up defaults from the SQLAlchemy model layer.
    op.alter_column("lo_extractions", "fields", server_default=None)
    op.alter_column("lo_extractions", "located_count", server_default=None)
    op.alter_column("lo_extractions", "total_count", server_default=None)


def downgrade() -> None:
    op.drop_table("lo_extractions")
