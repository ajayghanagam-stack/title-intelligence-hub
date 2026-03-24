import uuid
import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserInvite, UserUpdate
from app.services.auth_service import hash_password


def _generate_temp_password(length: int = 12) -> str:
    """Generate a random temporary password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def invite_user(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: UserInvite,
) -> tuple[User, str]:
    """Invite a user to an organization.

    Creates a user record with a temporary password so the user can log in
    immediately. Returns (user, temporary_password).
    """
    temp_password = _generate_temp_password()
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        auth_user_id=user_id,
        org_id=org_id,
        email=data.email,
        full_name=data.full_name,
        role=data.role,
        password_hash=hash_password(temp_password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, temp_password


async def update_user(
    db: AsyncSession, user_id: uuid.UUID, data: UserUpdate
) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    requesting_user_id: uuid.UUID | None = None,
) -> bool:
    """Delete a user from an organization. Returns True if deleted."""
    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False
    if user.role == "owner":
        raise ValueError("Cannot delete the organization owner")
    if requesting_user_id is not None and user.id == requesting_user_id:
        raise ValueError("Cannot delete yourself")
    await db.delete(user)
    await db.commit()
    return True


async def get_user_by_auth_id(
    db: AsyncSession, auth_user_id: uuid.UUID, org_id: uuid.UUID
) -> User | None:
    result = await db.execute(
        select(User).where(
            User.auth_user_id == auth_user_id,
            User.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()
