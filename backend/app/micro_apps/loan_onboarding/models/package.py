import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOPackage(Base, TenantMixin, TimestampMixin):
    """Loan onboarding package — container for uploaded PDFs + per-order config.

    Status transitions: uploading → processing → completed | failed | awaiting_review
    """
    __tablename__ = "lo_packages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    borrower_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    loan_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Per-package HITL threshold override (defaults to LO_HITL_THRESHOLD)
    hitl_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.96)

    # Pipeline status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="uploading")
    pipeline_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pipeline_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Progress tracking (e.g. "{stage: classify, processed: 12, total: 40, hitl: 2}")
    progress: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Field extraction config — independent of validation. When enabled, the
    # downstream extraction stage pulls the listed field names out of each
    # document stack and emits a downloadable feed for LOS systems. The map
    # is keyed by doc_type key (matches `LODocTypeConfig.doc_types[].key`)
    # and stores a list of human-readable field labels per doc type.
    extraction_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extraction_fields_by_doc: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Loan context — drives the persona-aware compliance engine. Captured on
    # the upload form (program/purpose/occupancy/state/scenarioFlags/ausEngine/
    # ausWaivers/loanAmount/propertyValue) and consumed by the compliance
    # service. Stored as a single JSONB blob so the schema can evolve without
    # migrations as new scenario flags or AUS waivers are added.
    loan_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Phase 2 — Selected program profile (loan_program or investor_overlay).
    # Nullable: when null, the resolver falls back to Global + per-loan
    # overrides only. The frontend captures this as a (loan_program,
    # investor_overlay) tuple but persists only the overlay's id when
    # present (since overlays carry stacks_with → loan_program).
    program_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_program_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    files = relationship("LOPackageFile", back_populates="package", lazy="noload", passive_deletes=True)
    pages = relationship("LOPage", back_populates="package", lazy="noload", passive_deletes=True)
    doc_type_config = relationship(
        "LODocTypeConfig",
        back_populates="package",
        uselist=False,
        lazy="noload",
        passive_deletes=True,
    )
    classifications = relationship("LOClassification", back_populates="package", lazy="noload", passive_deletes=True)
    stacks = relationship("LOStack", back_populates="package", lazy="noload", passive_deletes=True)
    validation_rules = relationship("LOValidationRule", back_populates="package", lazy="noload", passive_deletes=True)
    validation_results = relationship("LOValidationResult", back_populates="package", lazy="noload", passive_deletes=True)
    hitl_reviews = relationship("LOHITLReview", back_populates="package", lazy="noload", passive_deletes=True)
    pipeline_runs = relationship("LOPipelineRun", back_populates="package", lazy="noload", passive_deletes=True)
    extractions = relationship("LOExtraction", back_populates="package", lazy="noload", passive_deletes=True)
    compliance_runs = relationship(
        "LOComplianceRun",
        back_populates="package",
        lazy="noload",
        passive_deletes=True,
        order_by="LOComplianceRun.created_at.desc()",
    )
