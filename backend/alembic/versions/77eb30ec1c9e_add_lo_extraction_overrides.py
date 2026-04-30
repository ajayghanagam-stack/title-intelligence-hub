"""add lo_extraction_overrides

Revision ID: 77eb30ec1c9e
Revises: p6q7r8s9t0u1
Create Date: 2026-04-28 15:40:02.251316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "77eb30ec1c9e"
down_revision: Union[str, None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lo_extraction_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "package_id",
            UUID(as_uuid=True),
            sa.ForeignKey("lo_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(length=100), nullable=False),
        sa.Column("field_name", sa.String(length=200), nullable=False),
        sa.Column("stack_id", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "edited_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "package_id",
            "doc_type",
            "field_name",
            "stack_id",
            name="uq_lo_extraction_overrides_field",
        ),
    )
    op.create_index(
        op.f("ix_lo_extraction_overrides_org_id"),
        "lo_extraction_overrides",
        ["org_id"],
    )
    op.create_index(
        "ix_lo_extraction_overrides_package",
        "lo_extraction_overrides",
        ["package_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lo_extraction_overrides_package", table_name="lo_extraction_overrides"
    )
    op.drop_index(
        op.f("ix_lo_extraction_overrides_org_id"),
        table_name="lo_extraction_overrides",
    )
    op.drop_table("lo_extraction_overrides")
