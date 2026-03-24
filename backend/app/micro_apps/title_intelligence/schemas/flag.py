import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject|escalate)$")
    reason_code: str = ""
    notes: str | None = None


class ReviewResponse(BaseModel):
    id: uuid.UUID
    flag_id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: str
    reason_code: str
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FlagResponse(BaseModel):
    id: uuid.UUID
    pack_id: uuid.UUID
    flag_type: str
    severity: str
    title: str
    description: str
    ai_explanation: str
    evidence_refs: list[dict] = []
    status: str
    created_at: datetime
    reviews: list[ReviewResponse] = []

    model_config = {"from_attributes": True}


class FlagListResponse(BaseModel):
    flags: list[FlagResponse]
    counts: dict[str, int]  # severity → count


class RecommendationResponse(BaseModel):
    decision: str
    reasoning: str
    confidence: float
