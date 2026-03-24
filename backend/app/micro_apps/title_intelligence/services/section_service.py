import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.section import Section


async def list_sections(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
) -> list[Section]:
    result = await db.execute(
        select(Section)
        .where(Section.pack_id == pack_id, Section.org_id == org_id)
        .order_by(Section.start_page)
    )
    return list(result.scalars().all())
