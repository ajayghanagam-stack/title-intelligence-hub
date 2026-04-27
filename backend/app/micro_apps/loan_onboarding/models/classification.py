import uuid

from sqlalchemy import String, Integer, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOClassification(Base, TenantMixin, TimestampMixin):
    """Per-page classification result.

    Mirrors the Classification Schema exactly:
        page_number, predicted_doc_type, predicted_doc_type_alternatives,
        confidence, page_role, detected_fields[]
    """
    __tablename__ = "lo_classifications"
    __table_args__ = (
        Index("ix_lo_classifications_package_page", "package_id", "page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lo_pages.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)

    predicted_doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # [{"type": "1003", "confidence": 0.82}, ...]
    predicted_doc_type_alternatives: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # first_page | continuation | last_page | signature_page | unknown
    page_role: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    # [{"field_name": "Borrower Name", "value": "John Doe", "bbox": [x1,y1,x2,y2]}, ...]
    detected_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    package = relationship("LOPackage", back_populates="classifications", lazy="noload")
