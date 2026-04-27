"""add content_signal to lo_pages

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-04-23

Adds the hybrid-ingest `content_signal` column to `lo_pages`. Values:
  - "text"  — embedded text length ≥ threshold (fast path)
  - "image" — no text but page bears an image XObject / rasterized content
              (scanned page — route to vision classifier)
  - "blank" — no text AND no meaningful image content (auto-Others)

Nullable so pre-existing rows remain valid; the classify stage treats NULL
as a derived signal from text_length for backwards compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lo_pages",
        sa.Column("content_signal", sa.String(length=16), nullable=True),
    )
    # Backfill existing rows from text_length so downstream code can rely on
    # the column being populated for rows ingested after this migration.
    # Rows ingested before this point keep NULL and fall through to the
    # legacy text-length heuristic in stage_classify.
    op.execute(
        "UPDATE lo_pages SET content_signal = "
        "CASE WHEN text_length >= 20 THEN 'text' ELSE 'blank' END "
        "WHERE content_signal IS NULL"
    )


def downgrade() -> None:
    op.drop_column("lo_pages", "content_signal")
