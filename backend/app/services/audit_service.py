import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent


async def log_event(
    db: AsyncSession,
    org_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Create an audit event record."""
    event = AuditEvent(
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_=metadata or {},
    )
    db.add(event)
    await db.flush()
    return event
