import uuid

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.text_chunk import TextChunk


async def search_chunks(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> list[TextChunk]:
    """Full-text search over TextChunks. Uses tsvector on PostgreSQL, LIKE fallback on SQLite."""
    dialect = db.bind.dialect.name if db.bind else "sqlite"

    if dialect == "postgresql":
        stmt = (
            select(TextChunk)
            .where(
                TextChunk.pack_id == pack_id,
                TextChunk.org_id == org_id,
                text("search_vector @@ plainto_tsquery('english', :q)"),
            )
            .params(q=query)
            .limit(limit)
            .offset(offset)
        )
    else:
        # SQLite fallback
        stmt = (
            select(TextChunk)
            .where(
                TextChunk.pack_id == pack_id,
                TextChunk.org_id == org_id,
                TextChunk.content.ilike(f"%{query}%"),
            )
            .limit(limit)
            .offset(offset)
        )

    result = await db.execute(stmt)
    return list(result.scalars().all())
