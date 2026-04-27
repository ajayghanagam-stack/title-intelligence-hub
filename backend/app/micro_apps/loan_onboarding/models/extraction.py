import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOExtraction(Base, TenantMixin, TimestampMixin):
    """Per-stack field-extraction output for the Loan Onboarding pipeline.

    One row per stack. `fields` is the ordered list of extracted records,
    each shaped like:
        {"name": "Borrower Name", "value": "Jane Doe",
         "confidence": 0.94, "status": "located",
         "page": 1, "bbox": [0.1, 0.2, 0.4, 0.25]}

    `status` is one of "located" | "missing" | "low_confidence". Pages and
    bboxes are optional — agents emit them when they have a citation,
    otherwise they're omitted (the UI just won't render the page link).

    The row is keyed by `stack_id` (one extraction per stack) so the
    extract stage is idempotent via simple delete-then-insert.
    """
    __tablename__ = "lo_extractions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_stacks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # [{name, value, confidence, status, page?, bbox?}, ...] — see docstring
    fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Rollups for cheap dashboard summaries (avoid scanning fields[] in SQL).
    located_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    package = relationship("LOPackage", back_populates="extractions", lazy="noload")
    stack = relationship("LOStack", back_populates="extractions", lazy="noload")
