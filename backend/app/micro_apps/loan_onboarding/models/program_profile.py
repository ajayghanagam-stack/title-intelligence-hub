"""Loan Program + Investor Overlay profiles (Phase 2).

Two layers in the resolver stack:
  - ``type=loan_program``     — e.g. "Conventional 30yr", "FHA", "VA"
  - ``type=investor_overlay`` — e.g. "Fannie Mae DU", points at a base
                                program via ``stacks_with``

Each profile carries additive overrides only — checklist additions,
extra fields per doc type, extra rules. Tighten-only invariants are
enforced at write time by ``services/tighten_only.py``.

See ``docs/phase0/resolver-spec.md`` §2.4.
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


PROFILE_TYPE_LOAN_PROGRAM = "loan_program"
PROFILE_TYPE_INVESTOR_OVERLAY = "investor_overlay"


class LOProgramProfile(Base, TenantMixin, TimestampMixin):
    """One row per profile (loan program or investor overlay).

    ``checklist`` shape (JSONB list):
        [{"doc_type_key": "paystub", "required": true,
          "expected_min_pages": 1, "expected_max_pages": 4}, ...]

    ``extraction_overrides`` shape (JSONB dict-of-dict):
        {"paystub": {"borrower_name": {"required": true,
                                       "min_confidence": 0.92}}}

    ``rule_overrides`` shape (JSONB list):
        [{"scope": "doc_type:paystub",
          "rule": "must show YTD",
          "condition": "...",
          "preset_id": null,
          "severity": "hard"}, ...]
    """
    __tablename__ = "lo_program_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # PROFILE_TYPE_LOAN_PROGRAM | PROFILE_TYPE_INVESTOR_OVERLAY
    type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Set on investor_overlay rows only — points at the base loan program
    # the overlay refines. Loan-program rows leave this null.
    stacks_with: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_program_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    checklist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    extraction_overrides: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
    )
    rule_overrides: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
    )

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
