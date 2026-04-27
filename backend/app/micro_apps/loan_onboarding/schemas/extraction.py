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
# `located` — the agent found the field with usable confidence
# `low_confidence` — found but below the dashboard threshold
# `missing` — explicitly searched for and could not be located
FieldStatus = Literal["located", "low_confidence", "missing"]


class FieldLocation(BaseModel):
    """Optional citation tying an extracted value back to a page."""
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)


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


class StackExtractionOut(BaseModel):
    """Per-stack extraction returned by GET /packages/{id}/extractions."""
    stack_id: str
    stack_index: int
    doc_type: str
    fields: list[ExtractionFieldOut]
    located_count: int
    total_count: int
