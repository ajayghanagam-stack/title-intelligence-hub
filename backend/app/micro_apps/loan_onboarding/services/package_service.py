"""Service layer for Loan Onboarding packages.

All functions are tenant-scoped: every query filters by org_id.
"""
import logging
import uuid
from typing import Sequence

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.schemas.package import DocTypeSpec, ValidationRuleSpec

logger = logging.getLogger(__name__)

# LO AI-cache stage prefixes under `{org_id}/ai_cache/{stage}/…`.
# Mirrors the stage strings passed to `storage.make_ai_cache_path` by:
#   - classify stage     → "lo_classify"
#   - validate stage     → "lo_validate_rule"
#   - review stage       → "lo_reason"
# Delete-package wipes these stage dirs so the deleted package's LLM outputs
# cannot be replayed (or leaked across packages in the same org via the
# content-hash keyed cache).
_LO_AI_CACHE_STAGES: tuple[str, ...] = ("lo_classify", "lo_validate_rule", "lo_reason")


async def create_package(
    db: AsyncSession,
    org_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
    doc_types: list[DocTypeSpec],
    validation_rules: list[ValidationRuleSpec],
    borrower_name: str | None = None,
    loan_reference: str | None = None,
    hitl_threshold: float = 0.96,
    extraction_enabled: bool = True,
    extraction_fields_by_doc: dict[str, list[str]] | None = None,
) -> LOPackage:
    if not doc_types:
        raise ValidationError("At least one expected document type is required")
    keys = [d.key for d in doc_types]
    if len(set(keys)) != len(keys):
        raise ValidationError("Duplicate doc_type keys in configuration")
    if "others" in {k.lower() for k in keys}:
        raise ValidationError("'Others' is reserved — do not list it explicitly; it is auto-applied to unmatched pages")

    # Drop empty/orphan entries from the extraction map so we don't persist
    # cruft. Keys outside the configured doc_type set are silently filtered
    # — the UI may have left over entries from a previous selection.
    cleaned_extraction: dict[str, list[str]] = {}
    if extraction_fields_by_doc:
        valid_keys = set(keys)
        for k, v in extraction_fields_by_doc.items():
            if k not in valid_keys:
                continue
            if not isinstance(v, list):
                continue
            fields = [str(f).strip() for f in v if str(f).strip()]
            if fields:
                cleaned_extraction[k] = fields

    package = LOPackage(
        org_id=org_id,
        created_by=created_by,
        name=name,
        borrower_name=borrower_name,
        loan_reference=loan_reference,
        hitl_threshold=hitl_threshold,
        status="uploading",
        extraction_enabled=extraction_enabled,
        extraction_fields_by_doc=cleaned_extraction or None,
    )
    db.add(package)
    await db.flush()  # get package.id without committing

    config = LODocTypeConfig(
        org_id=org_id,
        package_id=package.id,
        doc_types=[d.model_dump() for d in doc_types],
    )
    db.add(config)

    for rule in validation_rules:
        db.add(LOValidationRule(
            org_id=org_id,
            package_id=package.id,
            rule_source=rule.rule_source,
            rule_id=rule.rule_id,
            description=rule.description,
            config=rule.config,
            doc_type=rule.doc_type,
            enabled=rule.enabled,
        ))

    await db.commit()
    await db.refresh(package)
    return package


async def get_package(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> LOPackage | None:
    result = await db.execute(
        select(LOPackage).where(LOPackage.id == package_id, LOPackage.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_package_or_raise(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> LOPackage:
    package = await get_package(db, org_id, package_id)
    if package is None:
        raise NotFoundError("LoanPackage", package_id)
    return package


async def list_packages(
    db: AsyncSession,
    org_id: uuid.UUID,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> Sequence[LOPackage]:
    query = select(LOPackage).where(LOPackage.org_id == org_id)
    if status:
        query = query.where(LOPackage.status == status)
    query = query.order_by(LOPackage.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    return list(result.scalars().all())


async def delete_package(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> None:
    package = await get_package_or_raise(db, org_id, package_id)

    # Storage cleanup happens before the DB row is removed so that a storage
    # failure leaves the DB row intact and the delete can be retried. Each
    # prefix is attempted independently — one prefix failing must not skip
    # the others. All errors are logged (no silent swallow).
    from app.services.storage import get_storage
    storage = get_storage()

    if hasattr(storage, "delete_dir"):
        # 1. Package-scoped dir — uploaded PDFs, rendered page images, thumbs,
        #    any cached reports. Everything under `{org_id}/{package_id}/`.
        try:
            await storage.delete_dir(f"{org_id}/{package_id}")
        except Exception as e:
            logger.warning(
                "Failed to delete package storage dir %s/%s: %s",
                org_id, package_id, e,
            )

        # 2. AI caches. These are org-scoped (the cache key embeds a content
        #    hash so two packages with the same PDF share the cache). Wiping
        #    the whole per-stage cache dir is the same nuclear approach used
        #    by Title Intelligence's delete_pack: it guarantees the deleted
        #    package's LLM output can't resurface via a cache-hit when the
        #    same content is re-uploaded. The cache is rebuilt on the next
        #    run at the cost of one round of LLM calls.
        for stage in _LO_AI_CACHE_STAGES:
            try:
                await storage.delete_dir(f"{org_id}/ai_cache/{stage}")
            except Exception as e:
                logger.warning(
                    "Failed to delete AI cache dir %s/ai_cache/%s: %s",
                    org_id, stage, e,
                )

    # DB row delete — FK CASCADE removes lo_package_files, lo_pages,
    # lo_classifications, lo_stacks, lo_validation_results, lo_hitl_reviews,
    # lo_validation_rules, lo_doc_type_configs, lo_pipeline_runs.
    await db.execute(delete(LOPackage).where(LOPackage.id == package.id, LOPackage.org_id == org_id))
    await db.commit()


async def get_doc_type_config(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> LODocTypeConfig | None:
    result = await db.execute(
        select(LODocTypeConfig).where(
            LODocTypeConfig.package_id == package_id,
            LODocTypeConfig.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def list_validation_rules(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> Sequence[LOValidationRule]:
    result = await db.execute(
        select(LOValidationRule).where(
            LOValidationRule.package_id == package_id,
            LOValidationRule.org_id == org_id,
            LOValidationRule.enabled == True,  # noqa: E712
        ).order_by(LOValidationRule.created_at.asc())
    )
    return list(result.scalars().all())


async def mark_pipeline_status(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    *,
    status: str | None = None,
    pipeline_stage: str | None = None,
    pipeline_error: str | None = None,
    progress: dict | None = None,
) -> None:
    pkg = await get_package_or_raise(db, org_id, package_id)
    if status is not None:
        pkg.status = status
    if pipeline_stage is not None:
        pkg.pipeline_stage = pipeline_stage
    if pipeline_error is not None:
        pkg.pipeline_error = pipeline_error
    elif status in ("completed", "awaiting_review"):
        pkg.pipeline_error = None
    if progress is not None:
        pkg.progress = progress
    await db.commit()
