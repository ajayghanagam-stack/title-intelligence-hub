import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.readiness import ReadinessResponse
from app.micro_apps.title_intelligence.services.readiness_service import calculate_readiness

router = APIRouter()


@router.get("/packs/{pack_id}/readiness", response_model=ReadinessResponse)
async def get_readiness(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await calculate_readiness(db, org_id, pack_id)
