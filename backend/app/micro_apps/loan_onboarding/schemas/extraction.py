"""Field-extraction schemas for the Loan Onboarding pipeline.

Shapes the payload produced by the ExtractionAgent and the rows
persisted in `lo_extractions.fields`. The frontend consumes
`ExtractionResponse` directly to render the per-stack panel and to
build downloadable JSON / CSV / MISMO XML feeds.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Field record ───────────────────────────────────────────────────────
# Status taxonomy after Phase 1 vision-grounding refactor:
#   `located`    — value extracted + grounded bbox (passes every validation
#                  gate check + confidence ≥ 0.85)
#   `tentative`  — value extracted + grounded bbox, confidence 0.65..0.85
#                  (UI renders dashed orange outline)
#   `ungrounded` — value extracted but evidence cite failed (no bbox).
#                  UI renders "Click to locate" CTA.
#   `missing`    — explicitly searched for and could not be located.
#
# `low_confidence` is retained as an alias for `tentative` for one
# release of API back-compat; new writes use `tentative`. See
# docs/phase0/grounding-contract.md §8 for the full transition table.
FieldStatus = Literal[
    "located",
    "tentative",
    "ungrounded",
    "missing",
    "low_confidence",  # deprecated alias for tentative; do not write
]


class FieldLocation(BaseModel):
    """Citation tying an extracted value back to a page + bbox.

    After Phase 1, ``bbox`` is computed server-side from
    ``evidence_token_indices`` rather than echoed from the model. The
    indices are persisted alongside so the UI can re-derive a tighter
    bbox if image DPI changes between extraction and render.
    """
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    # Phase 1 additions — empty / None on legacy rows persisted before
    # the v2 extractor shipped.
    evidence_token_indices: list[int] | None = Field(default=None)
    ocr_word_count: int | None = Field(default=None, ge=0)


class ExtractedField(BaseModel):
    """One field/value pair extracted from a stack."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    status: FieldStatus = "missing"
    location: FieldLocation | None = None


class StackExtraction(BaseModel):
    """The full extraction result for one stack — what the agent returns."""
    model_config = ConfigDict(extra="forbid")
    stack_id: str
    doc_type: str
    fields: list[ExtractedField]


# ── API response shape ────────────────────────────────────────────────


class ExtractionFieldOut(BaseModel):
    """Per-field row returned by the API (with derived page/bbox flattened)."""
    name: str
    value: str
    confidence: float
    status: FieldStatus
    page: int | None = None
    bbox: list[float] | None = None
    # Phase 1 — exposed so the operator UI can render the 3-state bbox
    # layer (located / tentative / ungrounded) and re-derive a tighter
    # box from the cited tokens if the page image is re-rendered.
    evidence_token_indices: list[int] | None = None
    ocr_word_count: int | None = None


class StackExtractionOut(BaseModel):
    """Per-stack extraction returned by GET /packages/{id}/extractions."""
    stack_id: str
    stack_index: int
    doc_type: str
    fields: list[ExtractionFieldOut]
    located_count: int
    total_count: int
