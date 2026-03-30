import uuid
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.core.auth import AuthenticatedUser, get_current_user
from app.models.user import User

_engine = None
_session_factory = None


def get_engine(settings: Settings = Depends(get_settings)):
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.effective_database_url, echo=False, pool_size=5)
    return _engine


def get_session_factory(settings: Settings | None = None):
    global _session_factory
    if _session_factory is None:
        if settings is None:
            settings = get_settings()
        engine = create_async_engine(settings.effective_database_url, echo=False, pool_size=5)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def get_db(
    settings: Settings = Depends(get_settings),
) -> AsyncGenerator[AsyncSession, None]:
    global _session_factory
    if _session_factory is None:
        engine = create_async_engine(settings.effective_database_url, echo=False, pool_size=5)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with _session_factory() as session:
        yield session


def get_org_id(request: Request) -> uuid.UUID:
    """Extract org_id from request state (set by TenantContextMiddleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required. Provide X-Org-Id header.",
        )
    return org_id


async def get_current_member(
    db: AsyncSession = Depends(get_db),
    auth_user: AuthenticatedUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> User:
    """Get the current user's membership in the active organization."""
    result = await db.execute(
        select(User).where(
            User.auth_user_id == auth_user.auth_user_id,
            User.org_id == org_id,
            User.is_active == True,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    return user


async def require_admin(member: User = Depends(get_current_member)) -> User:
    """Require admin or owner role."""
    if member.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or owner role required",
        )
    return member


async def require_owner(member: User = Depends(get_current_member)) -> User:
    """Require owner role."""
    if member.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required",
        )
    return member


async def require_platform_admin(
    db: AsyncSession = Depends(get_db),
    auth_user: AuthenticatedUser = Depends(get_current_user),
) -> User:
    """Require platform admin. No org context needed."""
    result = await db.execute(
        select(User).where(
            User.auth_user_id == auth_user.auth_user_id,
            User.is_active == True,
            User.is_platform_admin == True,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return user
