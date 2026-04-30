"""Reviewer-authored page-override routes.

Phase 1/2 of the "Move to…" flow:
- POST   /packages/{pid}/pages/{page_id}/override  → upsert + re-stack/re-validate
- DELETE /packages/{pid}/pages/{page_id}/override  → undo + re-stack/re-validate
- GET    /packages/{pid}/overrides                 → audit list

Re-stack and re-validate run inline (not as a background task) so the client
sees the updated Documents/Validation state on the POST response. The review
stage (Claude Opus) is intentionally **not** re-run here.
"""
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.micro_apps.loan_onboarding.schemas.override import (
    BatchOverrideRequest,
    BatchOverrideResponse,
    PageOverrideRequest,
    PageOverrideResponse,
    PageOverrideWithRebuild,
    RebuildSummary,
)
from app.micro_apps.loan_onboarding.services import page_override_service
from app.models.user import User
from app.services.audit_service import log_event
from app.services.storage import StorageProvider, get_storage

router = APIRouter()


@router.post(
    "/packages/{package_id}/pages/{page_id}/override",
    response_model=PageOverrideWithRebuild,
    status_code=status.HTTP_200_OK,
)
async def create_or_update_override(
    package_id: uuid.UUID,
    page_id: uuid.UUID,
    body: PageOverrideRequest,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Apply a reviewer's "Move to…" decision and rebuild stacks + validation.

    Response includes both the persisted override row and a summary of the
    rebuild (new stack count, HITL delta, rule pass/fail totals) so the UI
    can refresh its chips without a follow-up fetch.
    """
    override = await page_override_service.apply_override(
        db,
        org_id,
        package_id,
        page_id,
        assigned_doc_type=body.assigned_doc_type,
        page_role_override=body.page_role_override,
        reviewer_id=member.id,
        note=body.note,
    )
    rebuild = await page_override_service.rebuild_stacks_and_validation(
        db, org_id, package_id, storage
    )
    await log_event(
        db,
        org_id,
        action="lo_page_override_applied",
        target_type="lo_page",
        target_id=page_id,
        actor_id=member.id,
        metadata={
            "package_id": str(package_id),
            "assigned_doc_type": body.assigned_doc_type,
            "previous_doc_type": override.previous_doc_type,
            "page_role_override": body.page_role_override,
        },
    )
    await db.commit()
    await db.refresh(override)
    return PageOverrideWithRebuild(
        override=PageOverrideResponse.model_validate(override),
        rebuild=RebuildSummary(**rebuild),
    )


@router.post(
    "/packages/{package_id}/pages/overrides:batch",
    response_model=BatchOverrideResponse,
    status_code=status.HTTP_200_OK,
)
async def batch_apply_overrides(
    package_id: uuid.UUID,
    body: BatchOverrideRequest,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Apply many "Move to…" decisions atomically and rebuild **once**.

    Used by the drag-and-drop thumbnail strip — dragging multiple pages from
    one stack to another emits a single batch instead of N round trips, so
    the user sees the new grouping after only one re-stack/re-validate.

    No-op moves (page already in the target doc_type with the same role) are
    silently skipped. Invalid doc_types fail the whole batch.
    """
    overrides = await page_override_service.apply_overrides_batch(
        db,
        org_id,
        package_id,
        body.overrides,
        reviewer_id=member.id,
    )
    rebuild = await page_override_service.rebuild_stacks_and_validation(
        db, org_id, package_id, storage
    )
    if overrides:
        await log_event(
            db,
            org_id,
            action="lo_page_override_batch_applied",
            target_type="lo_package",
            target_id=package_id,
            actor_id=member.id,
            metadata={
                "package_id": str(package_id),
                "override_count": len(overrides),
                "page_ids": [str(o.page_id) for o in overrides],
            },
        )
    await db.commit()
    return BatchOverrideResponse(
        overrides=[PageOverrideResponse.model_validate(o) for o in overrides],
        rebuild=RebuildSummary(**rebuild),
    )


@router.delete(
    "/packages/{package_id}/pages/{page_id}/override",
    response_model=PageOverrideWithRebuild,
)
async def delete_override(
    package_id: uuid.UUID,
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Remove a reviewer's override (revert to ML classification) and rebuild.

    Returns `override=null` plus the post-rebuild summary. No-op deletes
    (no existing override) still trigger a rebuild — safe because the stages
    are idempotent — but they do not emit an audit event.
    """
    removed = await page_override_service.remove_override(
        db, org_id, package_id, page_id
    )
    rebuild = await page_override_service.rebuild_stacks_and_validation(
        db, org_id, package_id, storage
    )
    if removed:
        await log_event(
            db,
            org_id,
            action="lo_page_override_removed",
            target_type="lo_page",
            target_id=page_id,
            actor_id=member.id,
            metadata={"package_id": str(package_id)},
        )
    await db.commit()
    return PageOverrideWithRebuild(
        override=None,
        rebuild=RebuildSummary(**rebuild),
    )


@router.get(
    "/packages/{package_id}/overrides",
    response_model=list[PageOverrideResponse],
)
async def list_overrides(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """List every active override on a package (audit view for the UI)."""
    return await page_override_service.list_overrides(db, org_id, package_id)
