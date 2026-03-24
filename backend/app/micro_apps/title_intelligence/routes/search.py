import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.services.search_service import search_chunks

router = APIRouter()


@router.get("/packs/{pack_id}/search")
async def search(
    pack_id: uuid.UUID,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    chunks = await search_chunks(db, org_id, pack_id, q, limit=limit, offset=offset)
    return {
        "query": q,
        "results": [
            {
                "id": str(c.id),
                "page_number": c.page_number,
                "section_type": c.section_type,
                "content": c.content,
            }
            for c in chunks
        ],
    }
