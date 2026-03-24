import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class TAPipelineRun(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ta_pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ta_orders.id", ondelete="CASCADE"), nullable=False
    )

    # Version tracking fields
    input_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_tool_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_tool_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_tool_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rules_version: Mapped[str] = mapped_column(String(50), nullable=False)
    pipeline_backend: Mapped[str] = mapped_column(String(50), nullable=False)
    version_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Pipeline-level confidence aggregation
    confidence_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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

    order = relationship("TAOrder", back_populates="pipeline_runs")
