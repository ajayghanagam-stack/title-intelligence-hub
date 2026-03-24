"""Chat service with streaming support."""

import json
import logging
import re
import uuid
from typing import AsyncGenerator

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.chat_message import ChatMessage
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.services.search_service import search_chunks
from app.micro_apps.title_intelligence.services.storage import StorageProvider, get_storage
from app.micro_apps.title_intelligence.ai.chat_agent import ChatAgent

logger = logging.getLogger(__name__)


async def get_chat_history(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    limit: int = 100, offset: int = 0,
) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.pack_id == pack_id, ChatMessage.org_id == org_id)
        .order_by(ChatMessage.created_at)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def clear_chat_history(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
) -> int:
    """Delete all chat messages for a pack. Returns count of deleted messages."""
    result = await db.execute(
        delete(ChatMessage).where(
            ChatMessage.pack_id == pack_id, ChatMessage.org_id == org_id
        )
    )
    await db.commit()
    return result.rowcount


async def send_message(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str,
) -> ChatMessage:
    """Non-streaming message send (backward compatible)."""
    # Save user message
    user_msg = ChatMessage(
        pack_id=pack_id,
        org_id=org_id,
        role="user",
        content=message,
        user_id=user_id,
    )
    db.add(user_msg)
    await db.flush()

    storage = get_storage()
    agent = ChatAgent(org_id)

    # Get recent history for context
    history = await get_chat_history(db, org_id, pack_id)
    recent_history = history[-10:]

    # Use tool-calling answer
    response_text, citations = await agent.answer_with_tools(
        db=db,
        pack_id=pack_id,
        storage=storage,
        question=message,
        history=recent_history,
    )

    # Save assistant message
    assistant_msg = ChatMessage(
        pack_id=pack_id,
        org_id=org_id,
        role="assistant",
        content=response_text,
        citations=[c if isinstance(c, dict) else c.model_dump() for c in citations] if citations else None,
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)
    return assistant_msg


async def stream_message(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str,
) -> AsyncGenerator[str, None]:
    """Streaming message send via SSE.

    Yields SSE-formatted events:
    - data: {"type": "chunk", "content": "..."}
    - data: {"type": "done", "content": ""}
    """
    # Save user message
    user_msg = ChatMessage(
        pack_id=pack_id,
        org_id=org_id,
        role="user",
        content=message,
        user_id=user_id,
    )
    db.add(user_msg)
    await db.flush()

    storage = get_storage()
    agent = ChatAgent(org_id)

    # Get recent history
    history = await get_chat_history(db, org_id, pack_id)
    recent_history = history[-10:]

    full_response = ""
    try:
        async for chunk in agent.stream_answer(
            db=db,
            pack_id=pack_id,
            storage=storage,
            question=message,
            history=recent_history,
        ):
            if chunk["type"] == "chunk":
                full_response += chunk["content"]
            yield f"data: {json.dumps(chunk)}\n\n"
    except Exception as e:
        logger.error("Chat stream error for pack %s: %s", pack_id, e, exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'content': 'An error occurred while generating the response'})}\n\n"

    # Save complete assistant message after stream ends
    citations = []
    seen_pages = set()
    for match in re.finditer(r"\[Page\s+(\d+)\]", full_response):
        page_num = int(match.group(1))
        if page_num not in seen_pages:
            seen_pages.add(page_num)
            citations.append({"page_number": page_num, "text_snippet": ""})

    assistant_msg = ChatMessage(
        pack_id=pack_id,
        org_id=org_id,
        role="assistant",
        content=full_response,
        citations=citations if citations else None,
    )
    db.add(assistant_msg)
    await db.commit()
