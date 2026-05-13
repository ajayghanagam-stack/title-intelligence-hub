"""Vision-grounded extraction schemas (Phase 1 of LO refactor).

The new extractor returns the *value* and *which OCR tokens it copied
from* as a single atomic unit. Bboxes are computed server-side from the
cited tokens by ``services/grounding_validator.py`` — the model never
returns coordinates, which makes hallucinated bboxes structurally
impossible.

See docs/phase0/grounding-contract.md for the full contract and a
worked W-2 example.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Per-token OCR record ───────────────────────────────────────────────


class OcrWord(BaseModel):
    """One token from the OCR pass with normalized 0..1 bbox.

    Persisted on ``LOPage.ocr_words`` JSONB (one row per page) and fed
    into the vision extractor as a compact token table. Position is
    normalized so renders at different DPI produce stable indices.
    """

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, description="Global index within the page")
    text: str = Field(min_length=1, max_length=200)
    bbox: tuple[float, float, float, float] = Field(
        description="(x1, y1, x2, y2) in 0..1 normalized space"
    )
    line: int = Field(ge=0, description="Reading-order line group")
    confidence: float = Field(ge=0.0, le=1.0)


# ── Evidence citation ─────────────────────────────────────────────────


class EvidenceCitation(BaseModel):
    """Which OCR tokens (by index) the model copied from.

    Returned by the model. The validation gate checks that every index
    exists on the cited page; the bbox is computed by taking the union
    of cited tokens' positions.
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="1-indexed page within the stack")
    token_indices: tuple[int, ...] = Field(
        min_length=1, description="OCR token indices the value was copied from"
    )


# ── 3-state grounding status (replaces 2-state low_confidence/located) ─
#
# `located`    — passes every gate check; render with solid teal outline
# `tentative`  — passes structural checks but confidence is in the band
#                0.65..0.85; render with dashed orange outline
# `ungrounded` — fails any gate check; persist with bbox=None and render
#                a "Click to locate" CTA
# `missing`    — model returned empty value; same render as ungrounded
GroundingStatus = Literal["located", "tentative", "ungrounded", "missing"]


# ── Model output (what the LLM returns) ────────────────────────────────


class GroundedFieldRaw(BaseModel):
    """One field as the model returns it — never includes a bbox.

    The ``evidence`` field is the model's citation; the validation gate
    in ``services/grounding_validator.py`` converts it into a bbox or
    rejects it as ``ungrounded``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence: EvidenceCitation | None = None


class GroundedExtractionRaw(BaseModel):
    """Full vision-grounded extractor response (pre-validation gate)."""

    model_config = ConfigDict(extra="forbid")

    fields: list[GroundedFieldRaw]
