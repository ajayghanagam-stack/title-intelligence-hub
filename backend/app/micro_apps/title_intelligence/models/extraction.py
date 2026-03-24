import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, Float, Text, ForeignKey, DateTime
from app.models.compat import UUID
from app.models.compat import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin


class Extraction(Base, TenantMixin):
    __tablename__ = "ti_extractions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False
    )
    extraction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ti_sections.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    pack = relationship("Pack", back_populates="extractions")
    section = relationship("Section", back_populates="extractions")
