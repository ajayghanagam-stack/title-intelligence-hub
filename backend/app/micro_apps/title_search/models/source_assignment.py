import uuid

from sqlalchemy import String, ForeignKey, DateTime
from app.models.compat import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone

from app.models.base import Base, TenantMixin, TimestampMixin


class TASourceAssignment(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ta_source_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_orders.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    availability: Mapped[str] = mapped_column(String(20), nullable=False, default="digital")
    portal_config_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_county_sources.id"), nullable=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    order = relationship("TAOrder", back_populates="source_assignments")
    raw_documents = relationship("TARawDocument", back_populates="source_assignment", lazy="noload")
