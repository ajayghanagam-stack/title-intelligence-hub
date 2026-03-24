import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, Text, ForeignKey, DateTime, Numeric, Float, Boolean
from app.models.compat import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin


class TADocument(Base, TenantMixin):
    __tablename__ = "ta_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_orders.id", ondelete="CASCADE"), nullable=False
    )
    raw_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_raw_documents.id"), nullable=True
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    recording_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recording_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    consideration: Mapped[float | None] = mapped_column(Float, nullable=True)
    grantor: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    grantee: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    order = relationship("TAOrder", back_populates="documents")
    raw_document = relationship("TARawDocument", back_populates="document")
    chain_links = relationship("TAChainLink", back_populates="document", lazy="noload")
