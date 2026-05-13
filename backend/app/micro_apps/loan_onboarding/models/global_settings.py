"""Org-scoped global settings for the LogikIntake admin console.

One row per org. Backs the 8-tab ``Global Settings`` admin surface
(prototype Phase 5.3). Each tab is persisted as a JSONB blob so new
fields can be added without a schema migration — Pydantic schemas in
``schemas/global_settings.py`` are the authoritative shape contract.

Tenant-scoped via ``TenantMixin``; ``UniqueConstraint(org_id)`` makes
this a singleton per org. Created lazily by the admin GET endpoint
when missing, or up-front by ``scripts/seed.py``.
"""
import uuid

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOGlobalSettings(Base, TenantMixin, TimestampMixin):
    __tablename__ = "lo_global_settings"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_lo_global_settings_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # AI confidence bands + HITL floor.
    # { auto_confirm_min: 0.85, review_band_min: 0.60, review_band_max: 0.84,
    #   manual_max: 0.60, hitl_floor: 0.96 }
    ai_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Day-1 STP targets.
    # { decision_ready_target_pct: 70, hitl_sla_hours: 4, stuck_loan_alert_hours: 24 }
    stp_targets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Hard-stop escalation routing.
    # { initial_owner: "Loan Officer", escalation_after_hours: 2,
    #   escalation_target: "Underwriting" }
    exception_defaults: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Audit & retention.
    # { audit_log_retention_years: 7, document_retention_years: 7,
    #   pii_redaction_enabled: true, hmda_reporting_enabled: true }
    audit: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Role definitions (display-only — auth wires through the platform's
    # user.role enum). Shape: { title, items: [{ role, description, permissions }, ...] }
    roles: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Notification & escalation rules.
    # Shape: { title, items: [{ event, description, threshold, channel }, ...] }
    notifications: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Connected systems / integration registry.
    # Shape: { title, items: [{ system, description, status, status_color }, ...] }
    integrations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Tenant identity + plan info.
    # { tenant_slug, storage_region, logikality_plan }
    tenant: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
