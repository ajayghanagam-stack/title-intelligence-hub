import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, ForeignKey, DateTime, Boolean, UniqueConstraint
from app.models.compat import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TACountySource(Base, TimestampMixin):
    """Platform-wide county portal configurations. NOT tenant-scoped."""
    __tablename__ = "ta_county_sources"
    __table_args__ = (
        UniqueConstraint("county", "state_code", "source_type", name="uq_county_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    county: Mapped[str] = mapped_column(String(100), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    availability: Mapped[str] = mapped_column(String(20), nullable=False, default="digital")
    portal_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    portal_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    search_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
