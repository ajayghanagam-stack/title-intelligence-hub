import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.core.exceptions import NotFoundError


async def list_pages(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
) -> list[Page]:
    result = await db.execute(
        select(Page)
        .where(Page.pack_id == pack_id, Page.org_id == org_id)
        .order_by(Page.page_number)
    )
    return list(result.scalars().all())


async def get_page(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, page_number: int,
) -> Page | None:
    result = await db.execute(
        select(Page).where(
            Page.pack_id == pack_id,
            Page.org_id == org_id,
            Page.page_number == page_number,
        )
    )
    return result.scalar_one_or_none()


async def get_page_image_data(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    page_number: int, storage: StorageProvider,
) -> bytes | None:
    page = await get_page(db, org_id, pack_id, page_number)
    if not page:
        return None
    return await storage.read(page.image_uri)


async def get_page_thumb_data(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    page_number: int, storage: StorageProvider,
) -> bytes | None:
    page = await get_page(db, org_id, pack_id, page_number)
    if not page:
        return None
    return await storage.read(page.thumb_uri)


async def get_page_image_data_or_raise(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    page_number: int, storage: StorageProvider,
) -> bytes:
    page = await get_page(db, org_id, pack_id, page_number)
    if not page:
        raise NotFoundError("Page", page_number)
    return await storage.read(page.image_uri)


async def get_page_thumb_data_or_raise(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    page_number: int, storage: StorageProvider,
) -> bytes:
    page = await get_page(db, org_id, pack_id, page_number)
    if not page:
        raise NotFoundError("Page", page_number)
    return await storage.read(page.thumb_uri)
