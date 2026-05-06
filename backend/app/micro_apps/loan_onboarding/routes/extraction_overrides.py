"""Reviewer-authored extracted-field override routes.

- GET    /packages/{pid}/extractions/overrides       → list saved overrides
- PUT    /packages/{pid}/extractions/overrides       → upsert one
- DELETE /packages/{pid}/extractions/overrides       → reset one

The dashboard merges these on top of the AI-emitted extractions before
download, so JSON / CSV / MISMO XML feeds carry the reviewer's values.
"""
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.micro_apps.loan_onboarding.schemas.extraction_override import (
    ExtractionOverrideDelete,
    ExtractionOverrideResponse,
    ExtractionOverrideUpsert,
)
from app.micro_apps.loan_onboarding.services import (
    extraction_override_service,
    package_service,
)
from app.models.user import User
from app.services.audit_service import log_event

router = APIRouter()


@router.get(
    "/packages/{package_id}/extractions/overrides",
    response_model=list[ExtractionOverrideResponse],
)
async def list_extraction_overrides(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """List every reviewer override on a package."""
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    return await extraction_override_service.list_overrides(db, org_id, package_id)


@router.put(
    "/packages/{package_id}/extractions/overrides",
    response_model=ExtractionOverrideResponse,
    status_code=status.HTTP_200_OK,
)
async def upsert_extraction_override(
    package_id: uuid.UUID,
    body: ExtractionOverrideUpsert,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Insert or update one reviewer-edited field value."""
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    row = await extraction_override_service.upsert_override(
        db,
        org_id,
        package_id,
        doc_type=body.doc_type,
        field_name=body.field_name,
        stack_id=body.stack_id,
        value=body.value,
        edited_by_id=member.id,
    )
    await log_event(
        db,
        org_id,
        action="lo_extraction_override_upserted",
        target_type="lo_extraction_override",
        target_id=row.id,
        actor_id=member.id,
        metadata={
            "package_id": str(package_id),
            "doc_type": body.doc_type,
            "field_name": body.field_name,
            "stack_id": body.stack_id,
        },
    )
    await db.commit()
    await db.refresh(row)
    return row


@router.delete(
    "/packages/{package_id}/extractions/overrides",
    status_code=status.HTTP_200_OK,
)
async def delete_extraction_override(
    package_id: uuid.UUID,
    body: ExtractionOverrideDelete,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Reset one reviewer override (restore the AI-emitted value).

    No-op deletes (no existing override) succeed silently — the UI calls
    this on every Reset click without first checking, so idempotence
    matters.
    """
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    removed = await extraction_override_service.delete_override(
        db,
        org_id,
        package_id,
        doc_type=body.doc_type,
        field_name=body.field_name,
        stack_id=body.stack_id,
    )
    if removed:
        await log_event(
            db,
            org_id,
            action="lo_extraction_override_removed",
            target_type="lo_extraction_override",
            target_id=None,
            actor_id=member.id,
            metadata={
                "package_id": str(package_id),
                "doc_type": body.doc_type,
                "field_name": body.field_name,
                "stack_id": body.stack_id,
            },
        )
    await db.commit()
    return {"removed": bool(removed)}
