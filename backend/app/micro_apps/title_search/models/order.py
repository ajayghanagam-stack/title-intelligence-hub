import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, ForeignKey, DateTime
from app.models.compat import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class TAOrder(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ta_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    property_address: Mapped[str] = mapped_column(Text, nullable=False)
    parcel_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    county: Mapped[str] = mapped_column(String(100), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    legal_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="full"
    )
    search_years: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    pipeline_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pipeline_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ti_packs.id"), nullable=True
    )

    source_assignments = relationship("TASourceAssignment", back_populates="order", lazy="noload")
    raw_documents = relationship("TARawDocument", back_populates="order", lazy="noload")
    documents = relationship("TADocument", back_populates="order", lazy="noload")
    chain_links = relationship("TAChainLink", back_populates="order", lazy="noload")
    flags = relationship("TAFlag", back_populates="order", lazy="noload")
    reviews = relationship("TAReview", back_populates="order", lazy="noload")
    package = relationship("TAPackage", back_populates="order", uselist=False, lazy="noload")
    pipeline_runs = relationship("TAPipelineRun", back_populates="order", lazy="noload")
