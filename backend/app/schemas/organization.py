import uuid
from datetime import datetime
from pydantic import BaseModel


class OrganizationCreate(BaseModel):
    name: str
    slug: str
    logo_url: str | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    logo_url: str | None = None
    is_active: bool | None = None


class OrganizationPublicResponse(BaseModel):
    """Public org info for branded login pages — no sensitive data."""
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None

    model_config = {"from_attributes": True}


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
