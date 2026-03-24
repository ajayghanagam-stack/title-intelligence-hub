import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, Integer, Text, ForeignKey, DateTime, Column
from sqlalchemy.types import TypeDecorator, Text as TextType
from app.models.compat import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin


class TSVector(TypeDecorator):
    """TSVECTOR on PostgreSQL, ignored (Text) on other databases."""
    impl = TextType
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import TSVECTOR
            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(TextType())


class TextChunk(Base, TenantMixin):
    __tablename__ = "ti_text_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Server-managed by PostgreSQL trigger; not used on SQLite
    search_vector = Column(TSVector(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    pack = relationship("Pack", back_populates="text_chunks")
