import uuid

from sqlalchemy import String, Integer, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOStack(Base, TenantMixin, TimestampMixin):
    """A stack = contiguous pages classified as the same document type.

    Status transitions: pending → classified → validated → needs_review | accepted | rejected
    """
    __tablename__ = "lo_stacks"
    __table_args__ = (
        Index("ix_lo_stacks_package_order", "package_id", "stack_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Order of this stack within the package (0-indexed)
    stack_index: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Global package page numbers that make up this stack
    page_numbers: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    first_page: Mapped[int] = mapped_column(Integer, nullable=False)
    last_page: Mapped[int] = mapped_column(Integer, nullable=False)

    # Avg classification confidence across the stack's pages
    classification_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Post-validate overall confidence (blend of classification + split + validation)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    requires_hitl: Mapped[bool] = mapped_column(default=False, nullable=False)

    package = relationship("LOPackage", back_populates="stacks", lazy="noload")
    validation_results = relationship("LOValidationResult", back_populates="stack", lazy="noload", passive_deletes=True)
    hitl_reviews = relationship("LOHITLReview", back_populates="stack", lazy="noload", passive_deletes=True)
    extractions = relationship("LOExtraction", back_populates="stack", lazy="noload", passive_deletes=True)
