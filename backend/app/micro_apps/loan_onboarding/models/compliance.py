"""LOComplianceRun — audit log for every compliance evaluation.

One row per `compliance_service.evaluate(package_id, …)` call. The row captures
the rules version, the rule_set content fingerprint, a snapshot of the loan
context, the doc inventory the engine saw, and the resulting findings (and
summary). The combination of `(rules_version, rule_set_hash, loan_context_snapshot,
doc_inventory_snapshot)` is the determinism contract — re-running with the same
inputs must produce the same `findings` JSONB byte-for-byte.

Mirrors the `TAPipelineRun` / `LOPipelineRun` pattern used elsewhere in the
codebase. Tenant-scoped (TenantMixin) and timestamped (TimestampMixin); FK to
LOPackage cascades on package delete.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import JSONB, UUID


class LOComplianceRun(Base, TenantMixin, TimestampMixin):
    __tablename__ = "lo_compliance_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Determinism inputs
    rules_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Snapshots — frozen at evaluation time so the row is interpretable in
    # isolation even if the package's loan_context or stack inventory changes
    # later (e.g. new HITL override appended).
    loan_context_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    doc_inventory_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)

    # Output — full findings list + summary tiles. The frontend reads these
    # directly; the LO/QC personas are render-time projections of the same
    # findings list.
    findings: Mapped[list] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)

    package = relationship("LOPackage", back_populates="compliance_runs", lazy="noload")
