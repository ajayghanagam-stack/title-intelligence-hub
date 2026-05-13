"""Supervisor hard-stop override routes (Phase 3.4).

Two-route surface that backs the doc-validation page's "Override hard
stop" affordance:

- ``POST /packages/{pid}/hard-stops/{key}/override`` — admin/owner-only;
  records a closed-enum reason + free-form note + the supervisor's user
  id, plus an ``AuditEvent`` row for the platform-wide audit log.
- ``GET  /packages/{pid}/hard-stops/overrides`` — lists active overrides
  on the package; the doc-validation page calls this to filter
  overridden keys out of the live count and render the
  ``OVERRIDE RECORDED`` badge.

Reversal isn't exposed yet — it's append-only by design (write a
``decision="reversed"`` row instead of mutating the original). That UI
arrives with the admin "audit log" tab in a later batch.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_org_id, require_admin
from app.micro_apps.loan_onboarding.models.hard_stop_override import LOHardStopOverride
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.schemas.hard_stop_override import (
    HardStopOverrideCreate,
    HardStopOverrideResponse,
)
from app.models.user import User
from app.services.audit_service import log_event

router = APIRouter()


@router.post(
    "/packages/{package_id}/hard-stops/{hard_stop_key}/override",
    response_model=HardStopOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_hard_stop_override(
    package_id: uuid.UUID,
    hard_stop_key: str,
    payload: HardStopOverrideCreate,
    org_id: uuid.UUID = Depends(get_org_id),
    member: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HardStopOverrideResponse:
    """Record a supervisor override for a specific hard-stop key.

    Tenant-scoped: the package must belong to ``org_id`` or we 404 to
    avoid leaking package existence across tenants.
    """
    pkg = (
        await db.execute(
            select(LOPackage).where(
                LOPackage.id == package_id,
                LOPackage.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")

    # Reject if an active override for the same key already exists —
    # the model intentionally allows multiple rows (for reversal trail),
    # but the doc-validation surface should only see one *active* row.
    existing = (
        await db.execute(
            select(LOHardStopOverride).where(
                LOHardStopOverride.package_id == package_id,
                LOHardStopOverride.hard_stop_key == hard_stop_key,
                LOHardStopOverride.decision == "active",
                LOHardStopOverride.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An active override already exists for this hard-stop key",
        )

    row = LOHardStopOverride(
        org_id=org_id,
        package_id=package_id,
        hard_stop_key=hard_stop_key,
        supervisor_id=member.id,
        reason=payload.reason,
        note=payload.note,
        decision="active",
    )
    db.add(row)
    await db.flush()

    await log_event(
        db=db,
        org_id=org_id,
        action="lo.hard_stop.override_recorded",
        target_type="lo_package",
        target_id=package_id,
        actor_id=member.id,
        metadata={
            "hard_stop_key": hard_stop_key,
            "reason": payload.reason,
            "override_id": str(row.id),
        },
    )

    await db.commit()
    await db.refresh(row)
    return HardStopOverrideResponse.model_validate(row)


@router.get(
    "/packages/{package_id}/hard-stops/overrides",
    response_model=list[HardStopOverrideResponse],
)
async def list_hard_stop_overrides(
    package_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_org_id),
    db: AsyncSession = Depends(get_db),
) -> list[HardStopOverrideResponse]:
    """List active overrides for a package (doc-validation page consumer)."""
    pkg = (
        await db.execute(
            select(LOPackage).where(
                LOPackage.id == package_id,
                LOPackage.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")

    rows = (
        await db.execute(
            select(LOHardStopOverride)
            .where(
                LOHardStopOverride.package_id == package_id,
                LOHardStopOverride.org_id == org_id,
                LOHardStopOverride.decision == "active",
            )
            .order_by(LOHardStopOverride.created_at.desc())
        )
    ).scalars().all()

    return [HardStopOverrideResponse.model_validate(r) for r in rows]
