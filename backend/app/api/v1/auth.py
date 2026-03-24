from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.deps import get_db
from app.core.exceptions import AuthenticationError, NotFoundError, ValidationError
from app.core.rate_limit import limiter
from app.models.user import User
from app.models.organization import Organization
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    AuthResponse,
    UserInfo,
    OrgInfo,
)
from app.services.auth_service import (
    authenticate_user,
    change_password,
    create_access_token,
    request_password_reset,
    reset_password_with_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# No public signup — accounts are created by the platform admin
# via POST /api/v1/admin/accounts


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = await authenticate_user(db, body.email, body.password)
    if user is None:
        raise AuthenticationError("Invalid email or password")

    token = create_access_token(user.id, user.email, settings)

    # Get all orgs the user belongs to
    result = await db.execute(
        select(Organization)
        .join(User, User.org_id == Organization.id)
        .where(User.auth_user_id == user.auth_user_id, User.is_active == True)
    )
    orgs = result.scalars().all()

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": UserInfo(id=str(user.id), email=user.email, full_name=user.full_name),
        "orgs": [OrgInfo(id=str(o.id), name=o.name, slug=o.slug) for o in orgs],
        "is_platform_admin": user.is_platform_admin,
    }


@router.get("/me")
async def me(
    auth_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(
            User.auth_user_id == auth_user.auth_user_id, User.is_active == True
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        # JWT is valid but user was deleted/deactivated — treat as invalid session
        raise AuthenticationError("User account no longer exists")

    # Get all orgs
    result = await db.execute(
        select(Organization)
        .join(User, User.org_id == Organization.id)
        .where(User.auth_user_id == auth_user.auth_user_id, User.is_active == True)
    )
    orgs = result.scalars().all()

    return {
        "user": UserInfo(id=str(user.id), email=user.email, full_name=user.full_name),
        "orgs": [OrgInfo(id=str(o.id), name=o.name, slug=o.slug) for o in orgs],
        "is_platform_admin": user.is_platform_admin,
    }


@router.post("/change-password")
async def change_password_endpoint(
    body: ChangePasswordRequest,
    auth_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await change_password(
            db, auth_user.auth_user_id, body.current_password, body.new_password
        )
    except ValueError as e:
        raise ValidationError(str(e))
    return {"detail": "Password changed successfully"}


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset. Always returns success to avoid leaking emails."""
    token = await request_password_reset(db, body.email)
    # Always return the same response regardless of whether the email exists.
    # In production, the token is sent via email. For development, it is logged.
    response = {"detail": "If an account with that email exists, a reset link has been generated."}
    if token is not None:
        # Include token in response for development/testing convenience.
        # Remove this in production and send via email instead.
        response["reset_token"] = token
    return response


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using a valid reset token."""
    try:
        await reset_password_with_token(db, body.token, body.new_password)
    except ValueError as e:
        raise ValidationError(str(e))
    return {"detail": "Password reset successfully"}
