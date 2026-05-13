import uuid

from sqlalchemy import String, Integer, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin
from app.models.compat import UUID, JSONB


class LOPage(Base, TenantMixin, TimestampMixin):
    """An individual page within an uploaded PDF.

    Page numbering is global across the package (1-indexed) so that classification
    and stacking can reason about continuity without joining through files.
    """
    __tablename__ = "lo_pages"
    __table_args__ = (
        Index("ix_lo_pages_package_page", "package_id", "page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lo_packages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lo_package_files.id", ondelete="CASCADE"), nullable=False
    )
    # Global page number across the whole package (1-indexed)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Page number within the source file (1-indexed)
    source_page_number: Mapped[int] = mapped_column(Integer, nullable=False)

    image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thumb_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    heuristic_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Hybrid ingest signal: "text" (embedded text ≥ threshold), "image" (scanned
    # / image-only page — requires vision to classify), or "blank" (no text, no
    # meaningful image content). Nullable for backwards-compatibility with rows
    # ingested before this column existed; classify treats NULL as "text" when
    # text_length crosses the threshold, else "blank".
    content_signal: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Phase 1 (vision-grounded extraction) — tokenized OCR output for the
    # page, persisted at ingest time and consumed by the v2 extractor.
    # Shape: list[OcrWord] (see schemas/grounding.py) serialized as JSON.
    # Bboxes are normalized to 0..1. Nullable for rows ingested before
    # this column existed; the extract stage triggers a JIT OCR pass when
    # null. See docs/phase0/grounding-contract.md §2.1.
    ocr_words: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # OCR engine used: "tesseract" | "gemini_vision" | None (not run).
    # Folded into the stack content hash so a re-OCR via a different
    # engine produces a fresh extract cache slot.
    ocr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)

    package = relationship("LOPackage", back_populates="pages", lazy="noload")
