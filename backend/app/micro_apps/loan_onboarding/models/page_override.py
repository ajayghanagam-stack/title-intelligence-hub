"""Reviewer-authored classification override for a single page.

Separate from `lo_classifications` (which is immutable ML output) so we can:
- Audit who moved what, when, and why
- Undo a move by deleting the override row — the original prediction reappears
- Keep replay/regression tests honest (ML output is never mutated)

One row per (package_id, page_id). Applying a new override to the same page
updates the row in place (upsert) while preserving `previous_doc_type` from
the first time that page was overridden during this review cycle.
"""
import uuid

from sqlalchemy import String, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID


class LOPageOverride(Base, TenantMixin, TimestampMixin):
    __tablename__ = "lo_page_overrides"
    __table_args__ = (
        UniqueConstraint("package_id", "page_id", name="uq_lo_page_overrides_page"),
        Index("ix_lo_page_overrides_package", "package_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_pages.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Target assignment chosen by the reviewer. Must be either one of the
    # package's configured doc-type keys OR the reserved "Others" bucket.
    assigned_doc_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Snapshot of the page's doc_type at the moment the first override was
    # written (copied from LOClassification.predicted_doc_type). Enables the UI
    # to show "AI thought this was X; moved to Y" and drives validation that
    # a no-op move (target == original) is rejected by the service.
    previous_doc_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Optional manual page_role: first_page | continuation | last_page |
    # signature_page. When set, the stacker honors it in place of the ML role
    # (e.g. "this is actually the start of a new paystub run").
    page_role_override: Mapped[str | None] = mapped_column(String(30), nullable=True)

    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    package = relationship("LOPackage", lazy="noload")
