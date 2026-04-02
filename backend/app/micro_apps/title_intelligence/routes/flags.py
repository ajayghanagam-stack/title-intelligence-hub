import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.services.audit_service import log_event
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.flag import (
    FlagResponse,
    FlagListResponse,
    NoteUpdate,
    ReviewCreate,
    ReviewResponse,
    RecommendationResponse,
)
from app.micro_apps.title_intelligence.services.flag_service import (
    list_flags,
    get_flag_for_pack_or_raise,
    create_review,
    update_flag_note,
    get_ai_recommendation,
)
from app.micro_apps.title_intelligence.services.storage import StorageProvider, get_storage

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/packs/{pack_id}/flags", response_model=FlagListResponse)
async def get_flags(
    pack_id: uuid.UUID,
    severity: str | None = None,
    status: str | None = None,
    sort_by: str = "severity",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    flags, counts, total = await list_flags(
        db, org_id, pack_id,
        severity=severity, status=status, sort_by=sort_by,
        limit=limit, offset=offset,
    )
    return FlagListResponse(
        flags=flags, counts=counts, total=total, limit=limit, offset=offset,
    )


@router.get("/packs/{pack_id}/flags/{flag_id}", response_model=FlagResponse)
async def get_flag_detail(
    pack_id: uuid.UUID,
    flag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await get_flag_for_pack_or_raise(db, org_id, pack_id, flag_id)


@router.patch("/packs/{pack_id}/flags/{flag_id}/note", response_model=FlagResponse)
async def update_note(
    pack_id: uuid.UUID,
    flag_id: uuid.UUID,
    body: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await update_flag_note(db, org_id, pack_id, flag_id, body.note)


@router.post("/packs/{pack_id}/flags/{flag_id}/review", response_model=ReviewResponse)
async def submit_review(
    pack_id: uuid.UUID,
    flag_id: uuid.UUID,
    body: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    await get_flag_for_pack_or_raise(db, org_id, pack_id, flag_id)

    review = await create_review(
        db, org_id, flag_id, member.id, body.decision, body.reason_code, body.notes
    )
    await log_event(
        db, org_id,
        action=f"flag_{body.decision}",
        target_type="ti_flag",
        target_id=flag_id,
        actor_id=member.id,
        metadata={"reason_code": body.reason_code, "pack_id": str(pack_id)},
    )
    await db.commit()

    # Invalidate cached PDF report so next download reflects the review
    try:
        cache_uri = storage.make_report_path(org_id, pack_id, "report.pdf")
        if await storage.exists(cache_uri):
            await storage.delete(cache_uri)
    except Exception:
        logger.debug("Failed to invalidate report cache (non-fatal)", exc_info=True)

    return review


@router.get("/packs/{pack_id}/flags/{flag_id}/recommend", response_model=RecommendationResponse)
async def get_recommendation(
    pack_id: uuid.UUID,
    flag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    flag = await get_flag_for_pack_or_raise(db, org_id, pack_id, flag_id)
    result = await get_ai_recommendation(db, org_id, pack_id, flag)
    return RecommendationResponse(**result)
