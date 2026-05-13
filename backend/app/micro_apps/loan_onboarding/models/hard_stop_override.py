"""Supervisor overrides for doc-validation hard stops (Phase 3.4).

Each row records a supervisor's decision to waive a specific hard-stop
key on a loan — e.g. accepting a missing investor-overlay-required
disclosure with a documented business reason. The doc-validation page
filters overridden keys out of the live count and renders an
``OVERRIDE RECORDED`` badge sourced from these rows.

Audit-grade by design: the row is append-only (no PATCH/DELETE routes
expose it) and carries the supervisor's user_id, the operator-facing
reason (chosen from a closed enum), and a free-form note. We never
hard-delete; if a supervisor later decides the override was wrong, they
record a *reversal* row (``decision="reversed"``) rather than mutating
the original.

See ``docs/Loan_Onboarding_Refactoring.md`` §3.4.
"""
import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID


# Closed enum — the admin UI dropdown sources from this list verbatim.
OVERRIDE_REASON_BUSINESS_EXCEPTION = "business_exception"
OVERRIDE_REASON_LATE_DELIVERY = "late_delivery"
OVERRIDE_REASON_DUPLICATE_ELSEWHERE = "duplicate_elsewhere"
OVERRIDE_REASON_INVESTOR_WAIVED = "investor_waived"
OVERRIDE_REASON_OTHER = "other"

OVERRIDE_REASONS = (
    OVERRIDE_REASON_BUSINESS_EXCEPTION,
    OVERRIDE_REASON_LATE_DELIVERY,
    OVERRIDE_REASON_DUPLICATE_ELSEWHERE,
    OVERRIDE_REASON_INVESTOR_WAIVED,
    OVERRIDE_REASON_OTHER,
)


class LOHardStopOverride(Base, TenantMixin, TimestampMixin):
    """One row per supervisor-recorded hard-stop override on a loan.

    ``hard_stop_key`` is a stable string the doc-validation stage emits
    when it produces a Variant A / Variant B hard stop — e.g.
    ``"missing_doc:paystub"`` or ``"missing_pages:stack:1"``. The
    override matches by this exact string so a re-run of doc-validation
    that produces the same key picks up the override automatically.
    """
    __tablename__ = "lo_hard_stop_overrides"
    __table_args__ = (
        # One *active* override per (loan, hard_stop_key). Reversals are
        # written as additional rows; a UNIQUE on package_id + key would
        # block that, so we leave it lax and enforce single-active in the
        # service layer.
        UniqueConstraint(
            "package_id", "hard_stop_key", "created_at",
            name="uq_lo_hard_stop_overrides_pkg_key_created",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Stable string emitted by doc-validation. Re-runs that produce the
    # same key inherit this override automatically.
    hard_stop_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # The supervisor user who recorded the override. FK to ``users``;
    # role is enforced at the route layer (``require_admin``).
    supervisor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True,
    )

    # Closed-enum reason from ``OVERRIDE_REASONS`` above.
    reason: Mapped[str] = mapped_column(String(50), nullable=False)

    # Free-form supervisor note (audit trail).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "active" | "reversed" — the doc-validation page filters by status.
    decision: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
    )
