import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_search.schemas.flag import (
    FlagResponse,
    FlagListResponse,
    ReviewCreate,
    ReviewResponse,
)
from app.micro_apps.title_search.services import flag_service
from app.services.audit_service import log_event

router = APIRouter()


@router.get("/orders/{order_id}/flags", response_model=FlagListResponse)
async def get_flags(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    flags, counts = await flag_service.list_flags(db, org_id, order_id)
    return FlagListResponse(flags=flags, counts=counts)


@router.post(
    "/orders/{order_id}/flags/{flag_id}/review",
    response_model=ReviewResponse,
)
async def submit_review(
    order_id: uuid.UUID,
    flag_id: uuid.UUID,
    body: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    await flag_service.get_flag_or_raise(db, org_id, order_id, flag_id)

    review = await flag_service.create_flag_review(
        db, org_id, order_id, flag_id, member.id,
        body.decision, body.notes, body.corrected_value,
    )
    await log_event(
        db, org_id,
        action=f"ta_flag_{body.decision}",
        target_type="ta_flag",
        target_id=flag_id,
        actor_id=member.id,
        metadata={"order_id": str(order_id)},
    )
    await db.commit()
    return review
