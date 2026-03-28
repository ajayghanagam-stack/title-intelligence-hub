import uuid
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.pack import PackFile
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)


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
    
    # If image_uri is empty (native_pdf mode), generate on-demand
    if not page.image_uri:
        return await _render_page_on_demand(db, org_id, pack_id, page_number, storage, thumbnail=False)
    
    return await storage.read(page.image_uri)


async def get_page_thumb_data_or_raise(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    page_number: int, storage: StorageProvider,
) -> bytes:
    page = await get_page(db, org_id, pack_id, page_number)
    if not page:
        raise NotFoundError("Page", page_number)
    
    # If thumb_uri is empty (native_pdf mode), generate on-demand
    if not page.thumb_uri:
        return await _render_page_on_demand(db, org_id, pack_id, page_number, storage, thumbnail=True)
    
    return await storage.read(page.thumb_uri)


async def _render_page_on_demand(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    page_number: int, storage: StorageProvider, thumbnail: bool = False,
) -> bytes:
    """Render a single page from PDF on-demand for native_pdf mode."""
    import fitz  # PyMuPDF
    
    # Get pack files to find the PDF
    result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    pack_files = list(result.scalars().all())
    
    if not pack_files:
        raise NotFoundError("PackFile", pack_id)
    
    # Find which file contains this page
    cumulative_pages = 0
    target_file = None
    page_in_file = 0
    
    for pf in pack_files:
        if pf.page_count and cumulative_pages + pf.page_count >= page_number:
            target_file = pf
            page_in_file = page_number - cumulative_pages - 1  # 0-indexed
            break
        cumulative_pages += pf.page_count or 0
    
    if not target_file:
        # Fallback: use first file
        target_file = pack_files[0]
        page_in_file = page_number - 1
    
    # Read PDF from storage
    pdf_bytes = await storage.read(target_file.storage_path)
    
    # Render the page
    def _render():
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if page_in_file >= len(doc):
            page_in_file_adjusted = min(page_in_file, len(doc) - 1)
        else:
            page_in_file_adjusted = page_in_file
        
        page = doc[page_in_file_adjusted]
        dpi = 72 if thumbnail else 150
        pix = page.get_pixmap(dpi=dpi)
        img_data = pix.tobytes("jpeg")
        doc.close()
        return img_data
    
    img_data = await asyncio.to_thread(_render)
    
    # Cache the rendered image for future requests
    if thumbnail:
        cache_path = storage.make_thumb_path(org_id, pack_id, page_number)
    else:
        cache_path = storage.make_page_path(org_id, pack_id, page_number)
    
    try:
        await storage.save(cache_path, img_data)
        # Update the page record with the cached path
        page = await get_page(db, org_id, pack_id, page_number)
        if page:
            if thumbnail:
                page.thumb_uri = cache_path
            else:
                page.image_uri = cache_path
            await db.commit()
    except Exception as e:
        logger.warning(f"Failed to cache rendered page {page_number}: {e}")
    
    return img_data
