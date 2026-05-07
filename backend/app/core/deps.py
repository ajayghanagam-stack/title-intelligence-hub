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

# Connection pool sizing. The previous defaults (pool_size=5, the SQLAlchemy
# default max_overflow=10) capped us at 15 concurrent DB connections — far
# too few for a multi-user dashboard. The Loan Onboarding dashboard alone
# fires ~5 list queries (stacks, page-overrides, extractions, extraction-
# overrides, validation) plus a polling status query plus per-page
# thumb/image fetches that each hold a session through the storage call.
# Open one large packet on a slow link and the pool exhausts: queries time
# out after 30s with QueuePool TimeoutError, which surfaces in the UI as a
# 500 on /stacks → empty pageIdByNumber → page viewer never loads.
#
# 20+40 = 60 max connections matches what RDS db.t4g.large can comfortably
# handle (default max_connections ≈ 100 with overhead for psql/Temporal).
# pool_pre_ping detects connections silently dropped by RDS idle-eviction;
# pool_recycle=300 recycles every 5 minutes to stay well under any
# server-side idle timeout.
_POOL_KWARGS = {
    "echo": False,
    "pool_size": 20,
    "max_overflow": 40,
    "pool_pre_ping": True,
    "pool_recycle": 300,
}


def get_engine(settings: Settings = Depends(get_settings)):
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.effective_database_url, **_POOL_KWARGS)
    return _engine


def get_session_factory(settings: Settings | None = None):
    global _session_factory
    if _session_factory is None:
        if settings is None:
            settings = get_settings()
        engine = create_async_engine(settings.effective_database_url, **_POOL_KWARGS)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def get_db(
    settings: Settings = Depends(get_settings),
) -> AsyncGenerator[AsyncSession, None]:
    global _session_factory
    if _session_factory is None:
        engine = create_async_engine(settings.effective_database_url, **_POOL_KWARGS)
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
