import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.section import SectionResponse
from app.micro_apps.title_intelligence.services.section_service import list_sections

router = APIRouter()


@router.get("/packs/{pack_id}/sections", response_model=list[SectionResponse])
async def get_sections(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await list_sections(db, org_id, pack_id)
