import uuid

from sqlalchemy import String, Float, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOValidationResult(Base, TenantMixin, TimestampMixin):
    """Per-stack validation output.

    Mirrors the Validation Schema exactly:
        stack_id, doc_type, rules_evaluated[],
        confidence_breakdown{classification, split_accuracy, validation},
        overall_confidence, requires_hitl
    """
    __tablename__ = "lo_validation_results"

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
        unique=True,
        index=True,
    )
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # [{rule_id, rule_source, passed, evidence, location:{page, bbox}}, ...]
    rules_evaluated: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # {classification: 0.87, split_accuracy: 0.91, validation: 0.66}
    confidence_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    overall_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    requires_hitl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    package = relationship("LOPackage", back_populates="validation_results", lazy="noload")
    stack = relationship("LOStack", back_populates="validation_results", lazy="noload")
