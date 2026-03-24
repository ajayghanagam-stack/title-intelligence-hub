import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.extraction import Extraction


async def list_extractions(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    limit: int = 100, offset: int = 0,
) -> list[Extraction]:
    result = await db.execute(
        select(Extraction)
        .where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
        .order_by(Extraction.extraction_type, Extraction.label)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
