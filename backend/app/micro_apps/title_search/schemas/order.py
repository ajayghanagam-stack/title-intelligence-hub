import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Closed-set types for order fields
OrderStatus = Literal[
    "pending", "processing", "awaiting_abstractor",
    "review_required", "completed", "failed",
]
SearchScope = Literal["full", "current_owner", "limited"]
PipelineStage = Literal["order", "retrieve", "parse", "chain", "package", "complete"]
StageStatus = Literal["pending", "running", "completed", "failed", "skipped"]

# Valid US state abbreviations
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}


class OrderCreate(BaseModel):
    property_address: str = Field(..., min_length=1, max_length=500)
    city: str | None = Field(None, max_length=100)
    zip_code: str | None = Field(None, max_length=20)
    county: str = Field(..., min_length=1, max_length=100)
    state_code: str = Field(..., min_length=2, max_length=2)
    borrower_name: str | None = Field(None, max_length=500)
    parcel_number: str | None = Field(None, max_length=100)
    legal_description: str | None = None
    search_scope: SearchScope = "full"
    search_years: int = Field(60, ge=1, le=200)
    order_reference: str | None = Field(None, max_length=200)
    effective_date: date | None = None
    linked_pack_id: uuid.UUID | None = None

    @field_validator("state_code")
    @classmethod
    def validate_state_code(cls, v: str) -> str:
        v = v.upper()
        if v not in US_STATES:
            raise ValueError(f"Invalid US state code: {v}")
        return v


class OrderResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    created_by: uuid.UUID
    property_address: str
    city: str | None = None
    zip_code: str | None = None
    parcel_number: str | None = None
    county: str
    state_code: str
    borrower_name: str | None = None
    legal_description: str | None = None
    search_scope: SearchScope
    search_years: int
    order_reference: str | None = None
    effective_date: date | None = None
    status: OrderStatus
    pipeline_stage: PipelineStage | None = None
    pipeline_error: str | None = None
    linked_pack_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    id: uuid.UUID
    property_address: str
    county: str
    state_code: str
    borrower_name: str | None = None
    status: OrderStatus
    pipeline_stage: PipelineStage | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineStageStatusSchema(BaseModel):
    stage: PipelineStage
    status: StageStatus


class PipelineStatusResponse(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus
    pipeline_stage: PipelineStage | None
    stages: list[PipelineStageStatusSchema]
    pipeline_error: str | None = None
