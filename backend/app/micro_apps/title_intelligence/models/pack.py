import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, BigInteger, Text, ForeignKey, DateTime
from app.models.compat import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class Pack(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ti_packs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="uploading")
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    readiness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    readiness_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    files = relationship("PackFile", back_populates="pack", lazy="noload")
    pages = relationship("Page", back_populates="pack", lazy="noload")
    sections = relationship("Section", back_populates="pack", lazy="noload")
    extractions = relationship("Extraction", back_populates="pack", lazy="noload")
    flags = relationship("Flag", back_populates="pack", lazy="noload")
    text_chunks = relationship("TextChunk", back_populates="pack", lazy="noload")
    chat_messages = relationship("ChatMessage", back_populates="pack", lazy="noload")
    pipeline_runs = relationship("PipelineRun", back_populates="pack", lazy="noload")


class PackFile(Base, TenantMixin):
    __tablename__ = "ti_pack_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    pack = relationship("Pack", back_populates="files")
