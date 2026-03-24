"""Structured logging with tenant/pipeline context.

Provides a LoggerAdapter that injects org_id, pack_id, and stage into every
log message as a structured prefix. This makes production logs filterable
by tenant and pipeline stage without requiring a JSON log framework.

Usage:
    from app.core.logging import get_logger

    logger = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="render")
    logger.info("Created 50 page images")
    # Output: [org=abc123 pack=def456 stage=render] Created 50 page images
"""

import logging
import uuid
from typing import Any


class ContextLogger(logging.LoggerAdapter):
    """Logger that prepends structured context fields to every message."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        parts = []
        for key in ("request_id", "org_id", "pack_id", "stage"):
            val = self.extra.get(key)
            if val is not None:
                # Shorten UUIDs to first 8 chars for readability
                display = str(val)[:8] if isinstance(val, uuid.UUID) else str(val)
                parts.append(f"{key}={display}")
        prefix = f"[{' '.join(parts)}] " if parts else ""
        return f"{prefix}{msg}", kwargs


def get_logger(
    name: str,
    request_id: str | None = None,
    org_id: uuid.UUID | None = None,
    pack_id: uuid.UUID | None = None,
    stage: str | None = None,
) -> ContextLogger:
    """Create a logger with bound context fields.

    Args:
        name: Logger name (typically __name__)
        request_id: Request correlation ID
        org_id: Organization ID for tenant context
        pack_id: Pack ID for pipeline context
        stage: Current pipeline stage name
    """
    base = logging.getLogger(name)
    return ContextLogger(base, {
        "request_id": request_id, "org_id": org_id,
        "pack_id": pack_id, "stage": stage,
    })
