import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationUpdate


async def create_organization(
    db: AsyncSession,
    data: OrganizationCreate,
    auth_user_id: uuid.UUID,
    email: str,
) -> Organization:
    """Create an organization and add the creator as owner."""
    org = Organization(name=data.name, slug=data.slug, logo_url=data.logo_url)
    db.add(org)
    await db.flush()

    # Add creator as owner
    owner = User(
        auth_user_id=auth_user_id,
        org_id=org.id,
        email=email,
        role="owner",
    )
    db.add(owner)
    await db.commit()
    await db.refresh(org)
    return org


async def get_organization(db: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    return result.scalar_one_or_none()


async def update_organization(
    db: AsyncSession, org_id: uuid.UUID, data: OrganizationUpdate
) -> Organization | None:
    org = await get_organization(db, org_id)
    if org is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(org, key, value)
    await db.commit()
    await db.refresh(org)
    return org


async def list_org_users(db: AsyncSession, org_id: uuid.UUID) -> list[User]:
    result = await db.execute(
        select(User).where(User.org_id == org_id, User.is_active == True)
    )
    return list(result.scalars().all())


async def get_organization_by_slug(
    db: AsyncSession, slug: str
) -> Organization | None:
    result = await db.execute(
        select(Organization).where(
            Organization.slug == slug, Organization.is_active == True
        )
    )
    return result.scalar_one_or_none()


async def get_user_orgs(
    db: AsyncSession, auth_user_id: uuid.UUID
) -> list[Organization]:
    """Get all organizations a user belongs to."""
    result = await db.execute(
        select(Organization)
        .join(User, User.org_id == Organization.id)
        .where(User.auth_user_id == auth_user_id, User.is_active == True)
    )
    return list(result.scalars().all())
