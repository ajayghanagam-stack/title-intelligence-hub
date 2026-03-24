import uuid

from sqlalchemy import String, Integer, Text, ForeignKey, Boolean
from app.models.compat import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin


class TAChainLink(Base, TenantMixin):
    __tablename__ = "ta_chain_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_orders.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_documents.id"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    link_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_party: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    to_party: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_gap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gap_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    order = relationship("TAOrder", back_populates="chain_links")
    document = relationship("TADocument", back_populates="chain_links")
