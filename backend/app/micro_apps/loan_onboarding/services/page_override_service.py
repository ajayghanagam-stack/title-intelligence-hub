"""Reviewer-authored page overrides: upsert, remove, and re-run downstream.

Phase 1/2 of the "Move to…" flow. Every override:
1. Validates the target doc_type against the package's configured set (+ Others).
2. Rejects no-op moves (target == current effective doc_type).
3. Upserts an LOPageOverride row (preserving `previous_doc_type` from the ML
   classification the first time the page is overridden in this cycle).
4. Re-runs the deterministic `stage_stack` and then `stage_validate` so the
   Documents/Validation/Review tabs all reflect the new grouping immediately.

The review stage (Claude Opus reasoning) is **not** re-run — that stays the
human's call. Package status also stays where it is (typically `awaiting_review`);
the frontend can observe stack-level `requires_hitl` to know what's left.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.page_override import LOPageOverride
from app.micro_apps.loan_onboarding.models.pipeline_run import LOPipelineRun
from app.micro_apps.loan_onboarding.services import package_service
from app.micro_apps.loan_onboarding.services.page_assignment import (
    load_effective_classifications,
    override_set_hash,
)
from app.services.storage import StorageProvider


async def _load_allowed_doc_types(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> set[str]:
    """Return the set of doc_type keys a reviewer may move a page to.

    Always includes the reserved OTHERS_KEY bucket.
    """
    config = (
        await db.execute(
            select(LODocTypeConfig).where(
                LODocTypeConfig.package_id == package_id,
                LODocTypeConfig.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if config is None or not config.doc_types:
        # A package without a configured doc-type set should never reach
        # the review stage — guarding here to produce a clear error instead
        # of silently allowing anything.
        raise ValidationError("Package has no doc-type configuration")
    keys = {
        d["key"] for d in config.doc_types if isinstance(d, dict) and d.get("key")
    }
    keys.add(OTHERS_KEY)
    return keys


async def _find_page(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    page_id: uuid.UUID,
) -> LOPage:
    page = (
        await db.execute(
            select(LOPage).where(
                LOPage.id == page_id,
                LOPage.package_id == package_id,
                LOPage.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if page is None:
        raise NotFoundError("LoanPage", page_id)
    return page


async def _find_classification(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    page_id: uuid.UUID,
) -> LOClassification:
    clf = (
        await db.execute(
            select(LOClassification).where(
                LOClassification.page_id == page_id,
                LOClassification.package_id == package_id,
                LOClassification.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if clf is None:
        # If there's no classification row the classify stage never ran for
        # this page — overriding makes no sense yet.
        raise ValidationError(
            "Page has no classification; run the pipeline first before overriding"
        )
    return clf


async def apply_override(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    page_id: uuid.UUID,
    *,
    assigned_doc_type: str,
    page_role_override: str | None,
    reviewer_id: uuid.UUID,
    note: str | None,
) -> LOPageOverride:
    """Upsert an override for a single page. Caller must run re-stack/re-validate."""
    await package_service.get_package_or_raise(db, org_id, package_id)
    await _find_page(db, org_id, package_id, page_id)
    clf = await _find_classification(db, org_id, package_id, page_id)

    allowed = await _load_allowed_doc_types(db, org_id, package_id)
    if assigned_doc_type not in allowed:
        raise ValidationError(
            f"Target doc_type '{assigned_doc_type}' is not in this package's "
            f"configured set. Allowed: {sorted(allowed)}"
        )

    # Compare against current *effective* assignment, not the raw ML output —
    # moving a page back to what the ML originally predicted (by deleting the
    # override) is handled via `remove_override`, not by applying a no-op.
    existing = (
        await db.execute(
            select(LOPageOverride).where(
                LOPageOverride.page_id == page_id,
                LOPageOverride.package_id == package_id,
                LOPageOverride.org_id == org_id,
            )
        )
    ).scalar_one_or_none()

    current_doc_type = existing.assigned_doc_type if existing else clf.predicted_doc_type
    # Resolve both sides to effective roles for the comparison: a role override
    # of `None` means "fall back to the ML role", so it equals the current
    # effective role only when the ML role is itself what's in force.
    current_effective_role = (
        existing.page_role_override if existing and existing.page_role_override
        else clf.page_role
    )
    proposed_effective_role = page_role_override or clf.page_role
    if (
        assigned_doc_type == current_doc_type
        and proposed_effective_role == current_effective_role
    ):
        raise ValidationError(
            "No-op: target doc_type and page_role match the current assignment"
        )

    if existing is not None:
        existing.assigned_doc_type = assigned_doc_type
        existing.page_role_override = page_role_override
        existing.reviewer_id = reviewer_id
        existing.note = note
        # `previous_doc_type` is preserved from the first-ever override so the
        # audit trail keeps the ML's original call, not the last reviewer pick.
        await db.flush()
        await db.refresh(existing)
        return existing

    override = LOPageOverride(
        org_id=org_id,
        package_id=package_id,
        page_id=page_id,
        assigned_doc_type=assigned_doc_type,
        previous_doc_type=clf.predicted_doc_type,
        page_role_override=page_role_override,
        reviewer_id=reviewer_id,
        note=note,
    )
    db.add(override)
    await db.flush()
    await db.refresh(override)
    return override


async def remove_override(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    page_id: uuid.UUID,
) -> bool:
    """Delete a page's override if one exists. Returns True if one was removed."""
    await package_service.get_package_or_raise(db, org_id, package_id)
    result = await db.execute(
        delete(LOPageOverride).where(
            LOPageOverride.page_id == page_id,
            LOPageOverride.package_id == package_id,
            LOPageOverride.org_id == org_id,
        )
    )
    await db.flush()
    return (result.rowcount or 0) > 0


async def rebuild_stacks_and_validation(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    storage: StorageProvider,
) -> dict:
    """Re-run stack + validate stages. Returns the validate stage's summary.

    The stages are both idempotent (delete-then-insert), so calling them here
    gives the same result as re-running the pipeline from classify onward —
    minus the LLM-backed stages (classify, review), which are intentionally
    skipped: classifications are the frozen ML output, and the reasoning
    stage stays pinned to whatever the human is actively reviewing.
    """
    # Imported locally to avoid circular import (stages → services →
    # stages).
    from app.micro_apps.loan_onboarding.pipeline.stages import (
        stage_stack,
        stage_validate,
    )

    # Fail fast if there's nothing to rebuild against — matches the pipeline
    # stages' own guard.
    effective = await load_effective_classifications(db, org_id, package_id)
    if not effective:
        raise ValidationError(
            "No classifications to re-stack; run the pipeline before overriding"
        )

    stack_result = await stage_stack(package_id, org_id, db, storage)
    validate_result = await stage_validate(package_id, org_id, db, storage)

    # Stamp the latest pipeline-run with the current override-set hash. This
    # keeps `LOPipelineRun.version_metadata` honest about reviewer state so
    # cache-key computation and replay can factor it in — any future cache
    # lookup that includes this hash will miss when overrides change.
    await _record_override_set_hash(db, org_id, package_id)

    return {
        "pages": stack_result.get("pages", 0),
        "stacks": validate_result.get("stacks", 0),
        "hitl_stacks": validate_result.get("hitl_stacks", 0),
        "preset_rules": validate_result.get("preset_rules", 0),
        "custom_rules": validate_result.get("custom_rules", 0),
    }


async def _record_override_set_hash(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> None:
    """Write the current override-set hash into the latest pipeline run.

    Silently no-ops if no `LOPipelineRun` row exists yet for this package —
    the orchestrator doesn't write them in every backend, and we don't want
    override moves to fail simply because no run record is available.
    """
    overrides = (
        await db.execute(
            select(LOPageOverride).where(
                LOPageOverride.package_id == package_id,
                LOPageOverride.org_id == org_id,
            )
        )
    ).scalars().all()
    digest = override_set_hash(overrides)

    latest_run = (
        await db.execute(
            select(LOPipelineRun)
            .where(
                LOPipelineRun.package_id == package_id,
                LOPipelineRun.org_id == org_id,
            )
            .order_by(LOPipelineRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_run is None:
        return

    # JSONB columns returned as dict — mutate a copy to trigger SQLAlchemy
    # change detection even on nested updates.
    metadata = dict(latest_run.version_metadata or {})
    metadata["override_set_hash"] = digest
    metadata["override_count"] = len(overrides)
    latest_run.version_metadata = metadata


async def list_overrides(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
) -> list[LOPageOverride]:
    await package_service.get_package_or_raise(db, org_id, package_id)
    rows = (
        await db.execute(
            select(LOPageOverride)
            .where(
                LOPageOverride.package_id == package_id,
                LOPageOverride.org_id == org_id,
            )
            .order_by(LOPageOverride.created_at.asc())
        )
    ).scalars().all()
    return list(rows)
