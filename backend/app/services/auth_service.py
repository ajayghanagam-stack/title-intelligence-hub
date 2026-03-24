import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta

import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.user import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: uuid.UUID,
    email: str,
    settings: Settings,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def change_password(
    db: AsyncSession, user_id: str, current_password: str, new_password: str
) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.password_hash is None:
        raise ValueError("User not found")
    if not verify_password(current_password, user.password_hash):
        raise ValueError("Current password is incorrect")
    user.password_hash = hash_password(new_password)
    await db.commit()


async def request_password_reset(db: AsyncSession, email: str) -> str | None:
    """Generate a password reset token for the user.

    Returns the token if user found, None otherwise (callers should not
    reveal whether the email exists).
    """
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None

    token = secrets.token_urlsafe(32)
    user.password_reset_token = token
    user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()

    # In production, send this token via email. For now, log it.
    logger.info("Password reset token for %s: %s", email, token)
    return token


async def reset_password_with_token(
    db: AsyncSession, token: str, new_password: str
) -> None:
    """Reset password using a valid reset token."""
    result = await db.execute(
        select(User).where(
            User.password_reset_token == token,
            User.is_active == True,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("Invalid or expired reset token")

    if (
        user.password_reset_expires is None
        or user.password_reset_expires < datetime.now(timezone.utc)
    ):
        user.password_reset_token = None
        user.password_reset_expires = None
        await db.commit()
        raise ValueError("Invalid or expired reset token")

    user.password_hash = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()


async def authenticate_user(
    db: AsyncSession, email: str, password: str
) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None or user.password_hash is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
