import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PackCreate(BaseModel):
    name: str = Field(..., max_length=255)


class PackFileResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_size: int
    page_count: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PackResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    status: str
    current_stage: str | None = None
    readiness_score: int | None = None
    readiness_summary: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    files: list[PackFileResponse] = []

    model_config = {"from_attributes": True}


class PackListResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    current_stage: str | None = None
    readiness_score: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PipelineStageStatus(BaseModel):
    stage: str
    status: str  # pending, running, completed, failed


class PipelineStatusResponse(BaseModel):
    pack_id: uuid.UUID
    status: str
    current_stage: str | None
    stages: list[PipelineStageStatus]
    error_message: str | None = None
