import uuid

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID


class LOHITLReview(Base, TenantMixin, TimestampMixin):
    """Human decision on a stack flagged for review.

    decision: "accept" | "reject" | "reclassify"
    """
    __tablename__ = "lo_hitl_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_stacks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    corrected_doc_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    package = relationship("LOPackage", back_populates="hitl_reviews", lazy="noload")
    stack = relationship("LOStack", back_populates="hitl_reviews", lazy="noload")
