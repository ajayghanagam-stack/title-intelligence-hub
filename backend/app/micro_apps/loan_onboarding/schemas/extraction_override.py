"""Reviewer-authored extracted-field override schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExtractionOverrideUpsert(BaseModel):
    """Body for `PUT /packages/{pid}/extractions/overrides`.

    `stack_id` is an opaque string — UUID for real stacks,
    `placeholder-{doc_type}` for configured-but-unmatched rows. The backend
    treats it as a key, not a foreign key, so synthetic ids are accepted.
    """
    model_config = ConfigDict(extra="forbid")
    doc_type: str = Field(..., max_length=100)
    field_name: str = Field(..., max_length=200)
    stack_id: str = Field(..., max_length=80)
    value: str = Field(..., max_length=4000)


class ExtractionOverrideDelete(BaseModel):
    """Body for `DELETE /packages/{pid}/extractions/overrides`.

    No-op deletes (no existing override) return the same shape so the UI
    can reset its local state unconditionally.
    """
    model_config = ConfigDict(extra="forbid")
    doc_type: str = Field(..., max_length=100)
    field_name: str = Field(..., max_length=200)
    stack_id: str = Field(..., max_length=80)


class ExtractionOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    package_id: uuid.UUID
    doc_type: str
    field_name: str
    stack_id: str
    value: str
    edited_by: uuid.UUID | None
    edited_at: datetime
