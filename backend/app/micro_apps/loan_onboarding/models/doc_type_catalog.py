"""Org-level master catalog of doc types (Phase 2).

Replaces the per-package ``LODocTypeConfig.doc_types[]`` JSONB list as
the *highest-precedence* layer in the resolver stack. Per-loan tweaks
remain in ``LODocTypeConfig`` but only as additive overrides.

See ``docs/phase0/resolver-spec.md`` §2.1 for the full spec and
``services/config_resolver.py`` for how rows are stacked into an
``EffectiveConfig``.
"""
import uuid

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID


class LODocTypeCatalog(Base, TenantMixin, TimestampMixin):
    """One row per (org, doc_type_key) — the org's master doc-type list.

    The page-classifier's allowed-types enum is built from
    ``active=true`` rows. ``auto_classify_enabled=false`` forces every
    page predicted as this type into the reserved ``Others`` bucket
    (operator review only).
    """
    __tablename__ = "lo_doc_type_catalog"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_lo_doc_type_catalog_org_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Snake-case key, unique per org. E.g. "paystub", "w2", "urla_1003".
    # Matches the classifier's prediction enum (lowercase, snake_case).
    key: Mapped[str] = mapped_column(String(100), nullable=False)

    # Display label (e.g. "Paystub (most recent)").
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # UI grouping. One of: income, assets, identity, property, disclosures, other.
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")

    # When false, classifier predictions for this key route to the
    # reserved "Others" bucket — useful for retiring a doc type without
    # losing historical extractions.
    auto_classify_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # Soft hints (also fed into preset rules at validate time).
    expected_min_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_max_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Soft delete — profiles + per-loan overrides may still reference
    # rows after deactivation; we never hard-delete.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
