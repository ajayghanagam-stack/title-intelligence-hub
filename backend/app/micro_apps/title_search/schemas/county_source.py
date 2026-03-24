import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.micro_apps.title_search.schemas.order import US_STATES

# Closed-set types for county source classification
SourceType = Literal["recorder", "clerk", "assessor"]
Availability = Literal["digital", "partial", "non_digital"]
PortalType = Literal["api", "web_scrape", "manual_only"]


class CountySourceCreate(BaseModel):
    county: str = Field(..., min_length=1, max_length=100)
    state_code: str = Field(..., min_length=2, max_length=2)
    source_type: SourceType
    availability: Availability = "digital"
    portal_url: str | None = None
    portal_type: PortalType | None = None
    search_config: dict | None = None
    is_active: bool = True

    @field_validator("state_code")
    @classmethod
    def validate_state_code(cls, v: str) -> str:
        v = v.upper()
        if v not in US_STATES:
            raise ValueError(f"Invalid US state code: {v}")
        return v


class CountySourceUpdate(BaseModel):
    availability: Availability | None = None
    portal_url: str | None = None
    portal_type: PortalType | None = None
    search_config: dict | None = None
    is_active: bool | None = None


class CountySourceResponse(BaseModel):
    id: uuid.UUID
    county: str
    state_code: str
    source_type: SourceType
    availability: Availability
    portal_url: str | None = None
    portal_type: PortalType | None = None
    search_config: dict | None = None
    is_active: bool
    last_verified: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("search_config", mode="before")
    @classmethod
    def mask_credentials(cls, v: dict | None) -> dict | None:
        """Mask sensitive fields in search_config."""
        if not v:
            return v
        masked = dict(v)
        sensitive_keys = {"api_key", "password", "secret", "token", "auth_token", "credentials"}
        for key in masked:
            if key.lower() in sensitive_keys:
                masked[key] = "***MASKED***"
        return masked
