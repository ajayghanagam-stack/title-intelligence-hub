import uuid
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOPipelineRun(Base, TenantMixin, TimestampMixin):
    """Version tracking for every pipeline execution of a loan package.

    Mirrors the ti_pipeline_runs / ta_pipeline_runs contract in CLAUDE.md:
    any change to models, prompts, schemas, or rules produces a new hash →
    automatic cache miss. `version_metadata` carries per-stage timings.
    """
    __tablename__ = "lo_pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    input_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Models in use for this run
    ai_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    classifier_model: Mapped[str] = mapped_column(String(100), nullable=False)
    validator_model: Mapped[str] = mapped_column(String(100), nullable=False)
    reasoner_model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Prompt + schema hashes
    classify_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validate_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classify_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validate_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Deterministic rules version (bump on change to preset validators / stacker)
    rules_version: Mapped[str] = mapped_column(String(50), nullable=False)
    pipeline_backend: Mapped[str] = mapped_column(String(30), nullable=False, default="background_tasks")

    version_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    package = relationship("LOPackage", back_populates="pipeline_runs", lazy="noload")
