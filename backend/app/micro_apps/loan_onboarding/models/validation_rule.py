import uuid

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOValidationRule(Base, TenantMixin, TimestampMixin):
    """A validation rule applied to a loan package.

    Rules are configured per-package when the loan officer creates the order.
    A rule can be a preset (missing_pages, missing_signatures, missing_fields)
    or a custom natural-language rule.
    """
    __tablename__ = "lo_validation_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # preset | custom
    rule_source: Mapped[str] = mapped_column(String(20), nullable=False)
    # preset id (e.g. "missing_signatures") or a slug for custom
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # For preset rules: scope/parameters (e.g. {"doc_types": ["1003"]})
    # For custom rules: natural-language text lives in `description`
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional: scope rule to specific doc_type, or null = all
    doc_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    package = relationship("LOPackage", back_populates="validation_rules", lazy="noload")
