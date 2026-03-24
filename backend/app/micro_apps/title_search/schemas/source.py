import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.micro_apps.title_search.schemas.county_source import SourceType, Availability

# Closed-set type for source assignment status
SourceAssignmentStatus = Literal["pending", "in_progress", "completed", "failed"]


class SourceAssignmentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    source_type: SourceType
    availability: Availability
    portal_config_id: uuid.UUID | None = None
    assigned_to: uuid.UUID | None = None
    status: SourceAssignmentStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
