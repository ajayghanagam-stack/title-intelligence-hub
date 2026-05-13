"""Org-level validation rule library (Phase 2).

Rules live at the *highest-precedence* layer; per-loan rule rows
(``LOValidationRule``) become additive overrides at the lowest layer.
Tighten-only invariants forbid disabling an org rule from a profile or
a per-loan override — operators must edit the org rule itself.

See ``docs/phase0/resolver-spec.md`` §2.3.
"""
import uuid

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID


class LOValidationRuleOrg(Base, TenantMixin, TimestampMixin):
    """One row per (org, scope, rule).

    ``scope`` is either ``"package"`` (cross-doc check) or
    ``"doc_type:{key}"`` (single-doc check). ``preset_id`` non-null
    routes the rule through ``services/validation_presets.py``
    (deterministic); null sends it to the StackValidatorAgent (LLM).
    """
    __tablename__ = "lo_validation_rules_org"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "scope", "rule",
            name="uq_lo_validation_rules_org_scope_rule",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # "package" | "doc_type:{key}"
    scope: Mapped[str] = mapped_column(String(50), nullable=False)

    # Short label shown in the admin UI.
    rule: Mapped[str] = mapped_column(String(255), nullable=False)

    # Sub-line shown under the rule name in the admin UI — plain-English
    # description of what the rule checks (no thresholds). Optional; some
    # presets ship without explanatory copy.
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Comma-separated doc-type labels or umbrella categories like
    # "All Documents", "W-2, Pay Stub, VOE", "Program Checklist".
    # Free-form so platform-admin can express scopes the resolver can't
    # express as a single doc_type key.
    applies_to: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Natural-language rule body. For preset rules the catalog of valid
    # IDs lives in ``services/validation_presets.py``; for custom rules
    # this string is fed verbatim to the StackValidatorAgent.
    condition: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # If non-null, evaluated deterministically. Otherwise LLM-evaluated.
    preset_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # "hard" — blocks pipeline auto-accept; "soft" — surfaces in HITL only.
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="hard")

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
