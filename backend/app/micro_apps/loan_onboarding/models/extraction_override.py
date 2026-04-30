"""Reviewer-authored override for a single extracted field value.

Stored separately from `lo_extractions` (immutable AI output) so we can:
- Track who edited which field, when
- Undo by deleting the row — the original AI value reappears
- Keep replay/regression tests honest (extraction output is never mutated)

One row per (package_id, doc_type, field_name, stack_id). Re-saving the
same field upserts in place. `stack_id` is stored as an opaque string
rather than a UUID FK because the dashboard can edit fields belonging to
"placeholder" rows — configured doc types whose stack hasn't been
classified yet (e.g. `placeholder-W2`). Such overrides outlive the
synthetic id and are not auto-migrated when a real stack later appears.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID


class LOExtractionOverride(Base, TenantMixin, TimestampMixin):
    __tablename__ = "lo_extraction_overrides"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "doc_type",
            "field_name",
            "stack_id",
            name="uq_lo_extraction_overrides_field",
        ),
        Index("ix_lo_extraction_overrides_package", "package_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Doc-type key from the package's extraction config (e.g. "W2", "1003").
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Field name as it appears in `extraction_fields_by_doc` — case-sensitive
    # match required so the dashboard can look up the override per row.
    field_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Opaque stack identifier — UUID string for real stacks,
    # "placeholder-{doc_type}" for configured-but-unmatched rows.
    stack_id: Mapped[str] = mapped_column(String(80), nullable=False)

    # Reviewer-edited value. Stored as text to preserve formatting (e.g.
    # "$1,234.56") since downstream LOS systems often expect the original
    # presentation rather than a normalized form.
    value: Mapped[str] = mapped_column(Text, nullable=False)

    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    package = relationship("LOPackage", lazy="noload")
