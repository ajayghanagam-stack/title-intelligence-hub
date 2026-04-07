from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=6)
    new_password: str = Field(min_length=6)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


class UserInfo(BaseModel):
    id: str
    email: str
    full_name: str | None

    model_config = {"from_attributes": True}


class OrgInfo(BaseModel):
    id: str
    name: str
    slug: str
    logo_url: str | None = None

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo
    orgs: list[OrgInfo]
    is_platform_admin: bool = False
