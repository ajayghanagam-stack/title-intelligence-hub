import uuid
import asyncio
import logging
from functools import lru_cache
from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.pack import PackFile
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

# In-memory cache for PDF bytes to avoid re-reading from storage
# Key: (org_id, pack_id), Value: (pdf_bytes, page_count)
_pdf_cache: Dict[Tuple[str, str], Tuple[bytes, int]] = {}
_pdf_cache_lock = asyncio.Lock()


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
    
    cache_key = (str(org_id), str(pack_id))
    
    # Check if PDF is already in memory cache
    async with _pdf_cache_lock:
        if cache_key in _pdf_cache:
            pdf_bytes, total_pages = _pdf_cache[cache_key]
        else:
            # Get pack files to find the PDF
            result = await db.execute(
                select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
            )
            pack_files = list(result.scalars().all())
            
            if not pack_files:
                raise NotFoundError("PackFile", pack_id)
            
            # For now, use the first file (most packs have one PDF)
            target_file = pack_files[0]
            
            # Read PDF from storage and cache it
            pdf_bytes = await storage.read(target_file.storage_path)
            
            # Get page count
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_pages = len(doc)
            doc.close()
            
            # Cache for subsequent requests (limit cache size)
            if len(_pdf_cache) > 10:
                # Remove oldest entry
                oldest_key = next(iter(_pdf_cache))
                del _pdf_cache[oldest_key]
            
            _pdf_cache[cache_key] = (pdf_bytes, total_pages)
    
    # Calculate page index (0-based)
    page_in_file = page_number - 1
    
    # Render the page
    def _render():
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if page_in_file >= len(doc):
            page_idx = len(doc) - 1
        else:
            page_idx = max(0, page_in_file)
        
        page = doc[page_idx]
        dpi = 72 if thumbnail else 150
        pix = page.get_pixmap(dpi=dpi)
        img_data = pix.tobytes("jpeg")
        doc.close()
        return img_data
    
    img_data = await asyncio.to_thread(_render)
    
    # Cache the rendered image for future requests (fire and forget)
    asyncio.create_task(_cache_rendered_image(
        db, org_id, pack_id, page_number, storage, img_data, thumbnail
    ))
    
    return img_data


async def _cache_rendered_image(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    page_number: int, storage: StorageProvider, img_data: bytes, thumbnail: bool
):
    """Cache rendered image in background."""
    try:
        if thumbnail:
            cache_path = storage.make_thumb_path(org_id, pack_id, page_number)
        else:
            cache_path = storage.make_page_path(org_id, pack_id, page_number)
        
        await storage.save(cache_path, img_data)
    except Exception as e:
        logger.debug(f"Failed to cache rendered page {page_number}: {e}")


async def prerender_pages(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    storage: StorageProvider, start_page: int = 1, count: int = 10
) -> int:
    """Pre-render a batch of pages for faster viewing. Returns number of pages rendered."""
    import fitz
    
    # Get pages that need rendering
    result = await db.execute(
        select(Page)
        .where(
            Page.pack_id == pack_id,
            Page.org_id == org_id,
            Page.page_number >= start_page,
            Page.page_number < start_page + count
        )
        .order_by(Page.page_number)
    )
    pages = list(result.scalars().all())
    
    # Filter to pages that need rendering
    pages_to_render = [p for p in pages if not p.image_uri]
    
    if not pages_to_render:
        return 0
    
    # Get PDF from cache or storage
    cache_key = (str(org_id), str(pack_id))
    
    async with _pdf_cache_lock:
        if cache_key in _pdf_cache:
            pdf_bytes, _ = _pdf_cache[cache_key]
        else:
            result = await db.execute(
                select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
            )
            pack_files = list(result.scalars().all())
            if not pack_files:
                return 0
            
            pdf_bytes = await storage.read(pack_files[0].storage_path)
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_pages = len(doc)
            doc.close()
            
            if len(_pdf_cache) > 10:
                oldest_key = next(iter(_pdf_cache))
                del _pdf_cache[oldest_key]
            _pdf_cache[cache_key] = (pdf_bytes, total_pages)
    
    # Render pages in parallel
    def _render_batch():
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        results = []
        for page in pages_to_render:
            page_idx = page.page_number - 1
            if page_idx < 0 or page_idx >= len(doc):
                continue
            
            pdf_page = doc[page_idx]
            
            # Render full image
            pix = pdf_page.get_pixmap(dpi=150)
            img_data = pix.tobytes("jpeg")
            
            # Render thumbnail
            thumb_pix = pdf_page.get_pixmap(dpi=72)
            thumb_data = thumb_pix.tobytes("jpeg")
            
            results.append((page.page_number, img_data, thumb_data))
        
        doc.close()
        return results
    
    rendered = await asyncio.to_thread(_render_batch)
    
    # Save all rendered images
    for page_num, img_data, thumb_data in rendered:
        img_path = storage.make_page_path(org_id, pack_id, page_num)
        thumb_path = storage.make_thumb_path(org_id, pack_id, page_num)
        
        try:
            await asyncio.gather(
                storage.save(img_path, img_data),
                storage.save(thumb_path, thumb_data),
            )
            
            # Update page record
            page = await get_page(db, org_id, pack_id, page_num)
            if page:
                page.image_uri = img_path
                page.thumb_uri = thumb_path
        except Exception as e:
            logger.warning(f"Failed to save pre-rendered page {page_num}: {e}")
    
    try:
        await db.commit()
    except Exception:
        pass
    
    return len(rendered)
