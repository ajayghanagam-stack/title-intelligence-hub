import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.extraction import ExtractionResponse
from app.micro_apps.title_intelligence.services.extraction_service import list_extractions

router = APIRouter()


@router.get("/packs/{pack_id}/extractions", response_model=list[ExtractionResponse])
async def get_extractions(
    pack_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await list_extractions(db, org_id, pack_id, limit=limit, offset=offset)
