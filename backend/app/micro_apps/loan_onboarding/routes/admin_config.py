"""Org-admin CRUD for the Phase 2 resolver-feeding tables.

Mounted at ``/api/v1/apps/loan-onboarding/admin/config/...``. All four
resources are admin-or-owner gated (``require_admin``); platform-admin
elevation is not required because each org curates its own catalog.

The two write surfaces with non-trivial invariants — extraction schemas
and program profiles — call into ``services/tighten_only.py`` *before*
persisting. Violations bubble up as ``400 Bad Request`` with the exact
operator-facing message preserved verbatim (the admin UI surfaces it as
the inline tooltip text).

The resolver's process-local LRU is not invalidated explicitly here:
``LOPackage.updated_at`` is the cache-key axis, and editing org-level
config does not touch packages. Within a 60-second TTL the resolver may
return slightly-stale config; this is documented in
``services/config_resolver.py``. To force-flush in dev, restart the
worker (or call ``clear_cache()`` from a test).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_org_id, require_admin
from app.micro_apps.loan_onboarding.models.doc_type_catalog import LODocTypeCatalog
from app.micro_apps.loan_onboarding.models.extraction_schema import LOExtractionSchema
from app.micro_apps.loan_onboarding.models.global_settings import LOGlobalSettings
from app.micro_apps.loan_onboarding.models.program_profile import LOProgramProfile
from app.micro_apps.loan_onboarding.models.validation_rule_org import (
    LOValidationRuleOrg,
)
from app.micro_apps.loan_onboarding.schemas.admin_config import (
    DocTypeCatalogCreate,
    DocTypeCatalogResponse,
    DocTypeCatalogUpdate,
    ExtractionSchemaCreate,
    ExtractionSchemaResponse,
    ExtractionSchemaUpdate,
    OrgValidationRuleCreate,
    OrgValidationRuleResponse,
    OrgValidationRuleUpdate,
    ProgramProfileCreate,
    ProgramProfileResponse,
    ProgramProfileUpdate,
)
from app.micro_apps.loan_onboarding.schemas.global_settings import (
    GlobalSettingsResponse,
    GlobalSettingsUpdate,
)
from app.micro_apps.loan_onboarding.services.tighten_only import (
    TightenOnlyViolation,
    check_field_overrides_tighten,
    check_profile_shape,
)
from app.models.user import User

router = APIRouter(prefix="/admin/config", dependencies=[Depends(require_admin)])


# ── Doc-type catalog ──────────────────────────────────────────────────


@router.get("/doc-types", response_model=list[DocTypeCatalogResponse])
async def list_doc_types(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    from sqlalchemy import func
    from app.micro_apps.loan_onboarding.models.stack import LOStack

    rows = (await db.execute(
        select(LODocTypeCatalog)
        .where(LODocTypeCatalog.org_id == org_id)
        .order_by(LODocTypeCatalog.key.asc())
    )).scalars().all()

    # Count how many classified stacks exist per doc_type for this org.
    # Used to fill the "Processed" column on the Document Types admin UI
    # (mirrors the prototype's per-row documentsProcessed counter).
    counts_rows = (await db.execute(
        select(LOStack.doc_type, func.count(LOStack.id))
        .where(LOStack.org_id == org_id)
        .group_by(LOStack.doc_type)
    )).all()
    counts = {doc_type: int(n) for doc_type, n in counts_rows}

    return [
        DocTypeCatalogResponse(
            id=r.id,
            key=r.key,
            name=r.name,
            category=r.category,
            auto_classify_enabled=r.auto_classify_enabled,
            expected_min_pages=r.expected_min_pages,
            expected_max_pages=r.expected_max_pages,
            active=r.active,
            documents_processed=counts.get(r.key, 0),
        )
        for r in rows
    ]


@router.post(
    "/doc-types", response_model=DocTypeCatalogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_doc_type(
    payload: DocTypeCatalogCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    # Uniqueness is enforced by ``uq_lo_doc_type_catalog_org_key`` —
    # surface the constraint explicitly so the admin UI can show it.
    existing = (await db.execute(
        select(LODocTypeCatalog).where(
            LODocTypeCatalog.org_id == org_id,
            LODocTypeCatalog.key == payload.key,
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Doc-type with key '{payload.key}' already exists",
        )
    row = LODocTypeCatalog(org_id=org_id, **payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/doc-types/{doc_type_id}", response_model=DocTypeCatalogResponse)
async def update_doc_type(
    doc_type_id: UUID,
    payload: DocTypeCatalogUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    row = await _get_or_404(db, LODocTypeCatalog, doc_type_id, org_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


# ── Extraction schemas ────────────────────────────────────────────────


@router.get("/extraction-schemas", response_model=list[ExtractionSchemaResponse])
async def list_extraction_schemas(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    rows = (await db.execute(
        select(LOExtractionSchema)
        .where(LOExtractionSchema.org_id == org_id)
        .order_by(LOExtractionSchema.created_at.asc())
    )).scalars().all()
    return rows


@router.post(
    "/extraction-schemas", response_model=ExtractionSchemaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_extraction_schema(
    payload: ExtractionSchemaCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    # Doc-type must belong to this org — guard against cross-tenant FK
    # smuggling via the API surface.
    doc_type = await _get_or_404(
        db, LODocTypeCatalog, payload.doc_type_id, org_id,
        not_found_msg="Referenced doc_type_id not found",
    )
    existing = (await db.execute(
        select(LOExtractionSchema).where(
            LOExtractionSchema.org_id == org_id,
            LOExtractionSchema.doc_type_id == doc_type.id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Extraction schema already exists for this doc type — PATCH it instead",
        )
    row = LOExtractionSchema(
        org_id=org_id,
        doc_type_id=doc_type.id,
        fields=payload.fields,
        version=1,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch(
    "/extraction-schemas/{schema_id}", response_model=ExtractionSchemaResponse,
)
async def update_extraction_schema(
    schema_id: UUID,
    payload: ExtractionSchemaUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    row = await _get_or_404(db, LOExtractionSchema, schema_id, org_id)
    data = payload.model_dump(exclude_unset=True)
    if "fields" in data:
        row.fields = data["fields"]
        # Bump version on every fields edit so the resolver hash flips
        # and dependent extract caches miss.
        row.version = (row.version or 1) + 1
    if "active" in data:
        row.active = data["active"]
    await db.commit()
    await db.refresh(row)
    return row


# ── Org validation rules ──────────────────────────────────────────────


@router.get(
    "/validation-rules", response_model=list[OrgValidationRuleResponse],
)
async def list_org_rules(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    rows = (await db.execute(
        select(LOValidationRuleOrg)
        .where(LOValidationRuleOrg.org_id == org_id)
        .order_by(LOValidationRuleOrg.scope.asc(), LOValidationRuleOrg.rule.asc())
    )).scalars().all()
    return rows


@router.post(
    "/validation-rules", response_model=OrgValidationRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_org_rule(
    payload: OrgValidationRuleCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    existing = (await db.execute(
        select(LOValidationRuleOrg).where(
            LOValidationRuleOrg.org_id == org_id,
            LOValidationRuleOrg.scope == payload.scope,
            LOValidationRuleOrg.rule == payload.rule,
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Rule '{payload.rule}' already exists at scope '{payload.scope}'",
        )
    row = LOValidationRuleOrg(org_id=org_id, **payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch(
    "/validation-rules/{rule_id}", response_model=OrgValidationRuleResponse,
)
async def update_org_rule(
    rule_id: UUID,
    payload: OrgValidationRuleUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    row = await _get_or_404(db, LOValidationRuleOrg, rule_id, org_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


# ── Program profiles ──────────────────────────────────────────────────


@router.get("/profiles", response_model=list[ProgramProfileResponse])
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    rows = (await db.execute(
        select(LOProgramProfile)
        .where(LOProgramProfile.org_id == org_id)
        .order_by(LOProgramProfile.type.asc(), LOProgramProfile.name.asc())
    )).scalars().all()
    return rows


@router.post(
    "/profiles", response_model=ProgramProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile(
    payload: ProgramProfileCreate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    # Profile-shape invariant — overlay must point at a base, loan-program
    # must not.
    try:
        check_profile_shape(
            type_=payload.type, stacks_with=payload.stacks_with,
        )
    except TightenOnlyViolation as e:
        raise HTTPException(status_code=400, detail=e.message)

    if payload.stacks_with is not None:
        # Cross-tenant + dangling-FK guard.
        await _get_or_404(
            db, LOProgramProfile, payload.stacks_with, org_id,
            not_found_msg="stacks_with profile not found in this org",
        )

    # Extraction-overrides tighten check against the resolver's current
    # upstream view (Global org schemas).
    await _check_profile_writes_tighten(
        db, org_id,
        proposed_overrides=payload.extraction_overrides,
    )

    row = LOProgramProfile(org_id=org_id, **payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch(
    "/profiles/{profile_id}", response_model=ProgramProfileResponse,
)
async def update_profile(
    profile_id: UUID,
    payload: ProgramProfileUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    row = await _get_or_404(db, LOProgramProfile, profile_id, org_id)
    data = payload.model_dump(exclude_unset=True)

    # ``type`` is immutable post-create — flipping it would invert the
    # ``stacks_with`` relationship in ways the resolver doesn't model.
    if "extraction_overrides" in data:
        await _check_profile_writes_tighten(
            db, org_id,
            proposed_overrides=data["extraction_overrides"] or {},
        )
    if "stacks_with" in data and data["stacks_with"] is not None:
        await _get_or_404(
            db, LOProgramProfile, data["stacks_with"], org_id,
            not_found_msg="stacks_with profile not found in this org",
        )

    # Re-validate shape with the (possibly-new) stacks_with.
    proposed_stacks_with = data.get("stacks_with", row.stacks_with)
    try:
        check_profile_shape(type_=row.type, stacks_with=proposed_stacks_with)
    except TightenOnlyViolation as e:
        raise HTTPException(status_code=400, detail=e.message)

    for k, v in data.items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


# ── Helpers ───────────────────────────────────────────────────────────


async def _get_or_404(
    db: AsyncSession,
    model,
    pk: UUID,
    org_id: UUID,
    not_found_msg: str | None = None,
):
    """Tenant-scoped fetch-or-404."""
    row = (await db.execute(
        select(model).where(model.id == pk, model.org_id == org_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_msg or f"{model.__name__} {pk} not found",
        )
    return row


async def _check_profile_writes_tighten(
    db: AsyncSession,
    org_id: UUID,
    *,
    proposed_overrides: dict[str, Any],
) -> None:
    """Enforce field-level tighten-only against current Global schemas.

    The upstream view is Global only at MVP — profiles do not stack on
    each other for extraction overrides (overlays only refine
    checklist + rules). When the design opens up profile-on-profile
    extraction stacking, this view should expand to include the base
    program's resolved fields too.
    """
    if not proposed_overrides:
        return

    # Map (catalog.key → catalog.id) and pull the matching schemas.
    catalog_rows = (await db.execute(
        select(LODocTypeCatalog).where(
            LODocTypeCatalog.org_id == org_id,
            LODocTypeCatalog.active.is_(True),
        )
    )).scalars().all()
    cat_id_by_key = {c.key: c.id for c in catalog_rows}

    schema_rows = (await db.execute(
        select(LOExtractionSchema).where(
            LOExtractionSchema.org_id == org_id,
            LOExtractionSchema.active.is_(True),
        )
    )).scalars().all()
    cat_by_id = {c.id: c for c in catalog_rows}

    upstream_mc: dict[tuple[str, str], float] = {}
    upstream_required: dict[tuple[str, str], bool] = {}
    for s in schema_rows:
        cat = cat_by_id.get(s.doc_type_id)
        if cat is None:
            continue
        for f in (s.fields or []):
            if not isinstance(f, dict):
                continue
            fk = f.get("key")
            if not isinstance(fk, str):
                continue
            mc = f.get("min_confidence")
            if isinstance(mc, (int, float)):
                upstream_mc[(cat.key, fk)] = float(mc)
            if f.get("required") is True:
                upstream_required[(cat.key, fk)] = True

    try:
        check_field_overrides_tighten(
            upstream_min_confidence=upstream_mc,
            upstream_required=upstream_required,
            proposed_overrides=proposed_overrides,
        )
    except TightenOnlyViolation as e:
        raise HTTPException(status_code=400, detail=e.message)


# ── Global settings ───────────────────────────────────────────────────


def _settings_to_response_dict(row: LOGlobalSettings) -> dict[str, Any]:
    """Hydrate a row into the GlobalSettingsResponse shape, falling back
    to prototype defaults when JSONB columns are empty (covers rows
    seeded before a section was added or after a shape migration)."""
    from scripts.lo_prototype_data import build_default_global_settings

    defaults = build_default_global_settings()
    return {
        "id": row.id,
        "ai_thresholds": row.ai_thresholds or defaults["ai_thresholds"],
        "stp_targets": row.stp_targets or defaults["stp_targets"],
        "exception_defaults": row.exception_defaults or defaults["exception_defaults"],
        "audit": row.audit or defaults["audit"],
        "roles": row.roles or defaults["roles"],
        "notifications": row.notifications or defaults["notifications"],
        "integrations": row.integrations or defaults["integrations"],
        "tenant": row.tenant or defaults["tenant"],
    }


async def _load_or_create_settings(
    db: AsyncSession, org_id: UUID
) -> LOGlobalSettings:
    """Singleton-per-org loader. Creates a row with prototype defaults
    the first time an org opens the admin page."""
    from scripts.lo_prototype_data import build_default_global_settings

    row = (await db.execute(
        select(LOGlobalSettings).where(LOGlobalSettings.org_id == org_id)
    )).scalar_one_or_none()
    if row is not None:
        return row

    defaults = build_default_global_settings()
    row = LOGlobalSettings(org_id=org_id, **defaults)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/global-settings", response_model=GlobalSettingsResponse)
async def get_global_settings(
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    row = await _load_or_create_settings(db, org_id)
    return _settings_to_response_dict(row)


@router.patch("/global-settings", response_model=GlobalSettingsResponse)
async def update_global_settings(
    payload: GlobalSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: UUID = Depends(get_org_id),
):
    row = await _load_or_create_settings(db, org_id)

    # PATCH semantics: only update sections the client explicitly sent.
    # Each section column is replaced wholesale.
    data = payload.model_dump(exclude_unset=True)
    if "ai_thresholds" in data:
        row.ai_thresholds = data["ai_thresholds"]
    if "stp_targets" in data:
        row.stp_targets = data["stp_targets"]
    if "exception_defaults" in data:
        row.exception_defaults = data["exception_defaults"]
    if "audit" in data:
        row.audit = data["audit"]
    if "roles" in data:
        row.roles = data["roles"]
    if "notifications" in data:
        row.notifications = data["notifications"]
    if "integrations" in data:
        row.integrations = data["integrations"]
    if "tenant" in data:
        row.tenant = data["tenant"]

    await db.commit()
    await db.refresh(row)
    return _settings_to_response_dict(row)
