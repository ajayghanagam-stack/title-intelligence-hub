"""HITL review schemas."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


HITLDecisionType = Literal["accept", "reject", "reclassify"]


class HITLDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: HITLDecisionType
    corrected_doc_type: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class HITLReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    stack_id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: str
    corrected_doc_type: str | None
    notes: str | None
    created_at: datetime


class ReviewQueueItem(BaseModel):
    """One row in the HITL review queue."""
    model_config = ConfigDict(extra="forbid")
    stack_id: uuid.UUID
    doc_type: str
    first_page: int
    last_page: int
    page_count: int
    classification_confidence: float
    overall_confidence: float
    rules_failed: int
    rules_total: int
