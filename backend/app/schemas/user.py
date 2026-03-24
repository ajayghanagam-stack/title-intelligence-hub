import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserInvite(BaseModel):
    email: str
    full_name: str | None = None
    role: str = "member"


class UserUpdate(BaseModel):
    role: str | None = None
    full_name: str | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    auth_user_id: uuid.UUID
    org_id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InviteResponse(UserResponse):
    """Returned after inviting a user — includes the temporary password."""
    temporary_password: str
