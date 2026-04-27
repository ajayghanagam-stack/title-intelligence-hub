"""add extraction config to lo_packages

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-27

Adds the per-package field-extraction configuration columns:
  - extraction_enabled (bool, default True) — master toggle for the
    "D · Field Extraction" section of the new-package form. When False,
    the downstream extraction stage is skipped.
  - extraction_fields_by_doc (JSONB) — map of doc_type key →
    list[str] of field labels to pull out of each stack of that doc type.

`extraction_enabled` is NOT NULL with a server-side default so existing
rows are backfilled to True (matches the prototype's default-on behavior).
`extraction_fields_by_doc` is nullable; an empty/None value means no
fields are configured (extraction may still be enabled but produces an
empty payload).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lo_packages",
        sa.Column(
            "extraction_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "lo_packages",
        sa.Column(
            "extraction_fields_by_doc",
            JSONB(),
            nullable=True,
        ),
    )
    # Drop the server_default once existing rows are backfilled. New rows
    # get their default from the SQLAlchemy model (mapped_column default=True).
    op.alter_column("lo_packages", "extraction_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("lo_packages", "extraction_fields_by_doc")
    op.drop_column("lo_packages", "extraction_enabled")
