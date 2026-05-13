"""add ocr_words + ocr_engine to lo_pages

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-05-09

Phase 1 of the Loan Onboarding refactor (vision-grounded extraction).
Adds two columns to ``lo_pages``:

  - ``ocr_words`` JSONB — tokenized OCR output, list of
    ``{index, text, bbox, line, confidence}``. Bboxes normalized to
    0..1. Populated by ``services/ocr_words.py`` at ingest time
    (Tesseract primary, Gemini Vision fallback when conf < 70%).
  - ``ocr_engine`` String(32) — which engine produced the words
    (``"tesseract"`` | ``"gemini_vision"``). Folded into the stack
    content hash so re-OCR with a different engine produces a fresh
    extract cache slot.

Both columns are nullable for back-compat with existing rows; the
extract stage triggers a JIT OCR pass when ``ocr_words IS NULL``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "r9s0t1u2v3w4"
down_revision: Union[str, None] = "q8r9s0t1u2v3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lo_pages",
        sa.Column("ocr_words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "lo_pages",
        sa.Column("ocr_engine", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lo_pages", "ocr_engine")
    op.drop_column("lo_pages", "ocr_words")
