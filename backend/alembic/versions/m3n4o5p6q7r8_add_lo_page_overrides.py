"""add lo_page_overrides table

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lo_page_overrides",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_doc_type", sa.String(length=100), nullable=False),
        sa.Column("previous_doc_type", sa.String(length=100), nullable=False),
        sa.Column("page_role_override", sa.String(length=30), nullable=True),
        sa.Column("reviewer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["lo_packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["lo_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_id", "page_id", name="uq_lo_page_overrides_page"),
    )
    op.create_index(
        "ix_lo_page_overrides_package", "lo_page_overrides", ["package_id"], unique=False
    )
    op.create_index(
        "ix_lo_page_overrides_org_id", "lo_page_overrides", ["org_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_lo_page_overrides_org_id", table_name="lo_page_overrides")
    op.drop_index("ix_lo_page_overrides_package", table_name="lo_page_overrides")
    op.drop_table("lo_page_overrides")
