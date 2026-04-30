"""CRUD for `LOExtractionOverride` rows.

Used by the package dashboard to persist reviewer-edited extracted field
values. Overrides are merged into the extraction payload client-side
before downloads, so the JSON / CSV / MISMO XML feeds reflect the saved
values.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.extraction_override import (
    LOExtractionOverride,
)


async def list_overrides(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> list[LOExtractionOverride]:
    rows = (
        await db.execute(
            select(LOExtractionOverride)
            .where(
                LOExtractionOverride.package_id == package_id,
                LOExtractionOverride.org_id == org_id,
            )
            .order_by(
                LOExtractionOverride.doc_type.asc(),
                LOExtractionOverride.field_name.asc(),
                LOExtractionOverride.stack_id.asc(),
            )
        )
    ).scalars().all()
    return list(rows)


async def upsert_override(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    *,
    doc_type: str,
    field_name: str,
    stack_id: str,
    value: str,
    edited_by_id: uuid.UUID | None,
) -> LOExtractionOverride:
    """Insert or update a single field override.

    Lookups by (package_id, doc_type, field_name, stack_id). Re-saves
    update `value`, `edited_by`, and `edited_at` in place.
    """
    existing = (
        await db.execute(
            select(LOExtractionOverride).where(
                LOExtractionOverride.package_id == package_id,
                LOExtractionOverride.org_id == org_id,
                LOExtractionOverride.doc_type == doc_type,
                LOExtractionOverride.field_name == field_name,
                LOExtractionOverride.stack_id == stack_id,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.value = value
        existing.edited_by = edited_by_id
        existing.edited_at = now
        await db.flush()
        return existing

    row = LOExtractionOverride(
        org_id=org_id,
        package_id=package_id,
        doc_type=doc_type,
        field_name=field_name,
        stack_id=stack_id,
        value=value,
        edited_by=edited_by_id,
        edited_at=now,
    )
    db.add(row)
    await db.flush()
    return row


async def delete_override(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    *,
    doc_type: str,
    field_name: str,
    stack_id: str,
) -> bool:
    """Remove a single override row. Returns True if a row was deleted."""
    result = await db.execute(
        delete(LOExtractionOverride).where(
            LOExtractionOverride.package_id == package_id,
            LOExtractionOverride.org_id == org_id,
            LOExtractionOverride.doc_type == doc_type,
            LOExtractionOverride.field_name == field_name,
            LOExtractionOverride.stack_id == stack_id,
        )
    )
    return (result.rowcount or 0) > 0
