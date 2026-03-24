"""Full-text search tool for AI agents, matching V2's tools/search.ts."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.services.search_service import search_chunks

logger = logging.getLogger(__name__)


# --- Tool definition ---

SEARCH_TEXT_TOOL = {
    "name": "search_text",
    "description": "Full-text search over the document text chunks. Returns matching passages with page numbers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query text"},
            "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
        },
        "required": ["query"],
    },
}


def create_search_tool_handlers(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID
) -> dict:
    """Create search tool handler functions."""

    async def search_text(query: str, limit: int = 10, **kwargs):
        chunks = await search_chunks(db, org_id, pack_id, query, limit=limit)
        return [
            {"page_number": c.page_number, "content": c.content[:500]}
            for c in chunks
        ]

    return {
        "search_text": search_text,
    }
