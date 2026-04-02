"""Chat routes with SSE streaming support."""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.chat import (
    ChatSend,
    ChatMessageResponse,
)
from app.micro_apps.title_intelligence.services.chat_service import (
    get_chat_history,
    send_message,
    stream_message,
    clear_chat_history,
)
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/packs/{pack_id}/chat", response_model=ChatMessageResponse)
async def send_chat(
    pack_id: uuid.UUID,
    body: ChatSend,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Non-streaming chat endpoint (backward compatible)."""
    result = await send_message(db, org_id, pack_id, member.id, body.message)
    await log_event(
        db, org_id,
        action="chat_message_sent",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
        metadata={"mode": "sync"},
    )
    return result


@router.post("/packs/{pack_id}/chat/stream")
async def stream_chat(
    pack_id: uuid.UUID,
    body: ChatSend,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Streaming chat endpoint via Server-Sent Events.

    Audit logging is deferred to the async generator so it doesn't block
    the HTTP response — the client receives the SSE stream immediately.
    """
    return StreamingResponse(
        stream_message(db, org_id, pack_id, member.id, body.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/packs/{pack_id}/chat", response_model=list[ChatMessageResponse])
async def get_chat(
    pack_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await get_chat_history(db, org_id, pack_id, limit=limit, offset=offset)


@router.delete("/packs/{pack_id}/chat")
async def delete_chat(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Delete all chat messages for a pack."""
    count = await clear_chat_history(db, org_id, pack_id)
    await log_event(
        db, org_id,
        action="chat_history_cleared",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
        metadata={"deleted_count": count},
    )
    return {"deleted": count}
