"""Per-doc-type field schema at the org-level (Phase 2).

One row per (org, doc_type). Stores the field list the extractor will
request when a stack of this doc type is validated. ``version`` is
bumped on every save and folded into the extract cache key (so a schema
edit busts cached extractions for that doc type without touching
others).

See ``docs/phase0/resolver-spec.md`` §2.2.
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOExtractionSchema(Base, TenantMixin, TimestampMixin):
    """Org-level per-doc-type field schema.

    ``fields`` shape (JSONB list):
        [{
          "key": "borrower_name",        # snake_case canonical
          "label": "Borrower Name",
          "data_type": "string"|"currency"|"date"|"ssn"|"phone"|"email"
                       |"address"|"boolean",
          "required": true,
          "min_confidence": 0.85,        # 0..1 floor before HITL
          "regex": null|"...",            # optional client-side hint
          "alias": ["full name", ...]    # historical pull-through
        }, ...]
    """
    __tablename__ = "lo_extraction_schemas"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "doc_type_id",
            name="uq_lo_extraction_schemas_org_doc_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    doc_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_doc_type_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Bumped on every save so a schema edit busts the extract cache for
    # this doc type only. The resolver folds this into ``config_hash``
    # alongside the rest of the resolved config.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
