"""Admin service — business logic for platform admin operations."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.organization import Organization
from app.models.user import User
from app.models.micro_app import MicroApp
from app.models.subscription import Subscription
from app.services.auth_service import hash_password


# ── Account operations ─────────────────────────────────────────


async def create_account(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    org_name: str,
    org_slug: str,
    app_slugs: list[str],
) -> dict:
    """Create a customer org with an owner user and optional subscriptions.

    Returns a dict with org_id, org_name, org_slug, user_id, email, full_name, subscriptions.
    """
    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("Email already registered")

    # Check slug uniqueness
    existing_org = await db.execute(select(Organization).where(Organization.slug == org_slug))
    if existing_org.scalar_one_or_none() is not None:
        raise ConflictError("Organization slug already taken")

    # Create org
    org = Organization(name=org_name, slug=org_slug)
    db.add(org)
    await db.flush()

    # Create owner user
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        auth_user_id=user_id,
        org_id=org.id,
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role="owner",
    )
    db.add(user)

    # Subscribe to requested apps
    subscribed_slugs: list[str] = []
    if app_slugs:
        result = await db.execute(
            select(MicroApp).where(
                MicroApp.slug.in_(app_slugs),
                MicroApp.is_active == True,
            )
        )
        apps = result.scalars().all()
        now = datetime.now(timezone.utc)
        for app in apps:
            sub = Subscription(
                org_id=org.id,
                app_id=app.id,
                status="active",
                purchased_at=now,
                enabled_at=now,
            )
            db.add(sub)
            subscribed_slugs.append(app.slug)

    await db.commit()

    return {
        "org_id": str(org.id),
        "org_name": org.name,
        "org_slug": org.slug,
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "subscriptions": subscribed_slugs,
    }


async def list_accounts(
    db: AsyncSession, exclude_org_id: uuid.UUID,
) -> list[dict]:
    """List all organizations excluding the given org (admin's own)."""
    result = await db.execute(
        select(Organization).where(Organization.id != exclude_org_id).order_by(Organization.created_at.desc())
    )
    orgs = result.scalars().all()

    return [
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "is_active": org.is_active,
            "user_count": len([u for u in org.users if u.is_active]),
            "created_at": org.created_at,
        }
        for org in orgs
    ]


async def get_account(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Get a customer account with users and subscriptions."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise NotFoundError("Organization", org_id)

    users = [
        {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active}
        for u in org.users
    ]

    result = await db.execute(
        select(Subscription, MicroApp)
        .join(MicroApp, Subscription.app_id == MicroApp.id)
        .where(Subscription.org_id == org_id, MicroApp.is_active == True)
    )
    subs = [
        {
            "id": str(sub.id),
            "app_id": str(app.id),
            "app_name": app.name,
            "app_slug": app.slug,
            "status": sub.status,
        }
        for sub, app in result.all()
    ]

    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "is_active": org.is_active,
        "created_at": org.created_at,
        "users": users,
        "subscriptions": subs,
    }


async def add_subscription(
    db: AsyncSession, org_id: uuid.UUID, app_id: uuid.UUID,
) -> None:
    """Add a micro app subscription to an org."""
    result = await db.execute(
        select(Subscription).where(Subscription.org_id == org_id, Subscription.app_id == app_id)
    )
    if result.scalar_one_or_none() is not None:
        raise ConflictError("Already subscribed")

    now = datetime.now(timezone.utc)
    sub = Subscription(org_id=org_id, app_id=app_id, status="active", purchased_at=now, enabled_at=now)
    db.add(sub)
    await db.commit()


async def remove_subscription(
    db: AsyncSession, org_id: uuid.UUID, sub_id: uuid.UUID,
) -> None:
    """Remove a subscription."""
    result = await db.execute(
        select(Subscription).where(Subscription.id == sub_id, Subscription.org_id == org_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise NotFoundError("Subscription", sub_id)

    await db.delete(sub)
    await db.commit()


async def reset_user_password(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, new_password: str,
) -> None:
    """Reset a customer user's password."""
    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User", user_id)

    user.password_hash = hash_password(new_password)
    await db.commit()


async def delete_account(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Delete a customer organization and all associated data."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise NotFoundError("Organization", org_id)

    # Delete subscriptions, then users, then org
    subs = (await db.execute(
        select(Subscription).where(Subscription.org_id == org_id)
    )).scalars().all()
    for sub in subs:
        await db.delete(sub)

    users = (await db.execute(
        select(User).where(User.org_id == org_id)
    )).scalars().all()
    for user in users:
        await db.delete(user)

    await db.delete(org)
    await db.commit()


async def delete_account_user(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID,
) -> None:
    """Delete a user from a customer organization (platform admin action)."""
    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User", user_id)

    await db.delete(user)
    await db.commit()


# ── App management ─────────────────────────────────────────────


async def list_apps(db: AsyncSession) -> list[MicroApp]:
    """List all micro apps."""
    result = await db.execute(select(MicroApp).order_by(MicroApp.created_at.desc()))
    return list(result.scalars().all())


async def create_app(
    db: AsyncSession, name: str, slug: str, description: str | None, icon: str | None,
) -> MicroApp:
    """Create a new micro app."""
    existing = await db.execute(select(MicroApp).where(MicroApp.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("App slug already exists")

    app = MicroApp(name=name, slug=slug, description=description, icon=icon)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


async def update_app(
    db: AsyncSession, app_id: uuid.UUID, updates: dict,
) -> MicroApp:
    """Update a micro app."""
    result = await db.execute(select(MicroApp).where(MicroApp.id == app_id))
    app = result.scalar_one_or_none()
    if app is None:
        raise NotFoundError("App", app_id)

    for key, value in updates.items():
        setattr(app, key, value)

    await db.commit()
    await db.refresh(app)
    return app
