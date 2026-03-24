import uuid
from datetime import datetime
from pydantic import BaseModel


class MicroAppResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    icon: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
