import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, ForeignKey, DateTime
from app.models.compat import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin


class TARawDocument(Base, TenantMixin):
    __tablename__ = "ta_raw_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_orders.id", ondelete="CASCADE"), nullable=False
    )
    source_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_source_assignments.id"), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_format: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    order = relationship("TAOrder", back_populates="raw_documents")
    source_assignment = relationship("TASourceAssignment", back_populates="raw_documents")
    document = relationship("TADocument", back_populates="raw_document", uselist=False, lazy="noload")
