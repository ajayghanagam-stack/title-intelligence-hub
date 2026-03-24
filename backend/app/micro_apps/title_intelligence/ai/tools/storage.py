"""Storage read tools for AI agents, matching V2's tools/storage.ts."""

import json
import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.services.storage import StorageProvider

logger = logging.getLogger(__name__)


# --- Tool definitions ---

READ_PAGE_OCR_TOOL = {
    "name": "read_page_ocr",
    "description": "Read OCR text for a specific page by page number",
    "input_schema": {
        "type": "object",
        "properties": {
            "page_number": {"type": "integer", "description": "The page number to read OCR text for"},
        },
        "required": ["page_number"],
    },
}

READ_PAGE_RANGE_TOOL = {
    "name": "read_page_range",
    "description": "Read OCR text for a range of pages (max 20 pages). Returns concatenated text with page markers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_page": {"type": "integer", "description": "First page number"},
            "end_page": {"type": "integer", "description": "Last page number (inclusive)"},
        },
        "required": ["start_page", "end_page"],
    },
}


def create_storage_tool_handlers(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, storage: StorageProvider
) -> dict:
    """Create storage tool handler functions."""

    async def read_page_ocr(page_number: int, **kwargs):
        result = await db.execute(
            select(Page).where(
                Page.pack_id == pack_id, Page.org_id == org_id,
                Page.page_number == page_number,
            )
        )
        page = result.scalar_one_or_none()
        if not page:
            return {"error": f"Page {page_number} not found"}
        if page.ocr_text:
            return {"page_number": page_number, "text": page.ocr_text}
        if page.ocr_uri:
            try:
                data = await storage.read(page.ocr_uri)
                ocr_data = json.loads(data)
                return {"page_number": page_number, "text": ocr_data.get("text", "")}
            except Exception as e:
                return {"error": f"Failed to read OCR for page {page_number}: {e}"}
        return {"page_number": page_number, "text": ""}

    async def read_page_range(start_page: int, end_page: int, **kwargs):
        # Limit to 20 pages max
        if end_page - start_page + 1 > 20:
            end_page = start_page + 19

        result = await db.execute(
            select(Page).where(
                Page.pack_id == pack_id, Page.org_id == org_id,
                Page.page_number >= start_page,
                Page.page_number <= end_page,
            ).order_by(Page.page_number)
        )
        pages = result.scalars().all()

        text_parts = []
        for page in pages:
            text = page.ocr_text or ""
            if not text and page.ocr_uri:
                try:
                    data = await storage.read(page.ocr_uri)
                    ocr_data = json.loads(data)
                    text = ocr_data.get("text", "")
                except Exception:
                    text = ""
            text_parts.append(f"=== PAGE {page.page_number} ===\n{text}")

        return {"start_page": start_page, "end_page": end_page, "text": "\n\n".join(text_parts)}

    return {
        "read_page_ocr": read_page_ocr,
        "read_page_range": read_page_range,
    }
