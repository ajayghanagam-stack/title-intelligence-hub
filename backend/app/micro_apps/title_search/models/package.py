import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, ForeignKey, DateTime, Boolean
from app.models.compat import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin


class TAPackage(Base, TenantMixin):
    __tablename__ = "ta_packages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    package_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    search_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    years_covered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_documents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chain_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    open_flags_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    property_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    storage_path_pdf: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issuer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    order = relationship("TAOrder", back_populates="package")
