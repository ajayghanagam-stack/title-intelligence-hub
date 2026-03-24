import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class PipelineRun(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ti_pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ti_packs.id", ondelete="CASCADE"), nullable=False
    )

    # Version tracking fields
    input_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(100), nullable=False)
    ingestion_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_tool_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_tool_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ocr_engine: Mapped[str] = mapped_column(String(100), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rules_version: Mapped[str] = mapped_column(String(50), nullable=False)
    pipeline_backend: Mapped[str] = mapped_column(String(50), nullable=False)
    version_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Execution tracking
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    pack = relationship("Pack", back_populates="pipeline_runs")
