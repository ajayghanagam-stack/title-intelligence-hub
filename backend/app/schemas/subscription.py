import uuid
from datetime import datetime
from pydantic import BaseModel

from app.schemas.micro_app import MicroAppResponse


class SubscriptionCreate(BaseModel):
    app_id: uuid.UUID


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    app_id: uuid.UUID
    status: str
    purchased_at: datetime
    enabled_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    micro_app: MicroAppResponse | None = None

    model_config = {"from_attributes": True}
