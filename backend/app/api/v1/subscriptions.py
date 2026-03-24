import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_org_id, require_admin, get_current_member
from app.core.exceptions import NotFoundError
from app.models.user import User
from app.schemas.subscription import SubscriptionCreate, SubscriptionResponse
from app.services import subscription_service

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    db: AsyncSession = Depends(get_db),
):
    return await subscription_service.list_subscriptions(db, org_id)


@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    data: SubscriptionCreate,
    admin: User = Depends(require_admin),
    org_id: uuid.UUID = Depends(get_org_id),
    db: AsyncSession = Depends(get_db),
):
    return await subscription_service.create_subscription(db, org_id, data)


@router.patch("/{sub_id}/enable", response_model=SubscriptionResponse)
async def enable_subscription(
    sub_id: uuid.UUID,
    admin: User = Depends(require_admin),
    org_id: uuid.UUID = Depends(get_org_id),
    db: AsyncSession = Depends(get_db),
):
    sub = await subscription_service.enable_subscription(db, sub_id, org_id)
    if sub is None:
        raise NotFoundError("Subscription", sub_id)
    return sub


@router.patch("/{sub_id}/disable", response_model=SubscriptionResponse)
async def disable_subscription(
    sub_id: uuid.UUID,
    admin: User = Depends(require_admin),
    org_id: uuid.UUID = Depends(get_org_id),
    db: AsyncSession = Depends(get_db),
):
    sub = await subscription_service.disable_subscription(db, sub_id, org_id)
    if sub is None:
        raise NotFoundError("Subscription", sub_id)
    return sub
