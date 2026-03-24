import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.subscription import Subscription
from app.models.micro_app import MicroApp
from app.schemas.subscription import SubscriptionCreate


async def list_subscriptions(
    db: AsyncSession, org_id: uuid.UUID
) -> list[Subscription]:
    result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.micro_app))
        .where(Subscription.org_id == org_id)
    )
    return list(result.scalars().all())


async def create_subscription(
    db: AsyncSession, org_id: uuid.UUID, data: SubscriptionCreate
) -> Subscription:
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        org_id=org_id,
        app_id=data.app_id,
        status="active",
        purchased_at=now,
        enabled_at=now,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def enable_subscription(
    db: AsyncSession, sub_id: uuid.UUID, org_id: uuid.UUID
) -> Subscription | None:
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == sub_id, Subscription.org_id == org_id
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return None
    sub.status = "active"
    sub.enabled_at = datetime.now(timezone.utc)
    sub.disabled_at = None
    await db.commit()
    await db.refresh(sub)
    return sub


async def disable_subscription(
    db: AsyncSession, sub_id: uuid.UUID, org_id: uuid.UUID
) -> Subscription | None:
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == sub_id, Subscription.org_id == org_id
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return None
    sub.status = "disabled"
    sub.disabled_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sub)
    return sub
