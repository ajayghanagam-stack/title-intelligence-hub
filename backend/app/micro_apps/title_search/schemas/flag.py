import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Closed-set types matching flag_rules.py + pipeline flags
FlagType = Literal[
    "chain_gap", "name_mismatch", "unreleased_mortgage", "unsatisfied_lien",
    "judgment_match", "easement_conflict", "missing_source", "low_confidence",
    "captcha_blocked",  # Added for CAPTCHA-blocked portals in nationwide pipeline
]
FlagSeverity = Literal["critical", "high", "medium", "low"]
FlagStatus = Literal["open", "resolved", "dismissed"]
ReviewDecision = Literal["approve", "reject", "correct"]


class ReviewCreate(BaseModel):
    decision: ReviewDecision
    notes: str | None = None
    corrected_value: dict | None = None


class ReviewResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    flag_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID
    decision: ReviewDecision
    original_value: dict | None = None
    corrected_value: dict | None = None
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceRef(BaseModel):
    """A single piece of evidence supporting a flag."""
    document_ref: str | None = None
    field_name: str | None = None
    text_snippet: str | None = None
    confidence: float | None = None


class FlagResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    document_id: uuid.UUID | None = None
    chain_link_id: uuid.UUID | None = None
    flag_type: FlagType
    severity: FlagSeverity
    title: str
    description: str
    ai_explanation: str | None = None
    evidence_refs: list[EvidenceRef] = []
    auto_resolved: bool
    status: FlagStatus
    created_at: datetime
    reviews: list[ReviewResponse] = []

    model_config = {"from_attributes": True}


class FlagListResponse(BaseModel):
    flags: list[FlagResponse]
    counts: dict[str, int]
