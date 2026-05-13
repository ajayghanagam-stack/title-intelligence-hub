"""Phase 2 read-time resolver: ``effective_config(loan_id) → EffectiveConfig``.

Stacks four layers — Global → loan_program → investor_overlay → per-loan
— into one frozen, hashable value object that downstream pipeline +
routes consume. Tighten-only invariants are enforced at *write* time
(see ``services/tighten_only.py``); the read path trusts its inputs and
only computes a deterministic hash so dependent AI caches invalidate
correctly when any layer changes.

See ``docs/phase0/resolver-spec.md`` §3 for the full algorithm.
"""
from __future__ import annotations

import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.doc_type_catalog import LODocTypeCatalog
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.extraction_schema import LOExtractionSchema
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.program_profile import (
    LOProgramProfile,
    PROFILE_TYPE_INVESTOR_OVERLAY,
    PROFILE_TYPE_LOAN_PROGRAM,
)
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.models.validation_rule_org import (
    LOValidationRuleOrg,
)
from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
    GROUNDING_CONTRACT_VERSION,
)
from app.micro_apps.loan_onboarding.schemas.resolved_config import EffectiveConfig
from app.micro_apps.loan_onboarding.services._resolver_stacking import (
    compute_config_hash,
    stack_doc_types,
    stack_rules,
    stack_schemas,
)


# ── Process-local LRU ────────────────────────────────────────────────


# Hard 60-second TTL (defense in depth against a missed updated_at bump);
# also keyed by ``package.updated_at`` so legitimate edits invalidate
# without waiting for the TTL.
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 256

_cache: dict[tuple[UUID, float], tuple[float, EffectiveConfig]] = {}


def _cache_get(loan_id: UUID, updated_at_ts: float) -> EffectiveConfig | None:
    entry = _cache.get((loan_id, updated_at_ts))
    if entry is None:
        return None
    inserted_at, cfg = entry
    if (time.monotonic() - inserted_at) > _CACHE_TTL_SECONDS:
        _cache.pop((loan_id, updated_at_ts), None)
        return None
    return cfg


def _cache_put(loan_id: UUID, updated_at_ts: float, cfg: EffectiveConfig) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        # Drop the oldest entry. Cheap O(n) scan — n ≤ 256.
        oldest_key = min(_cache.items(), key=lambda kv: kv[1][0])[0]
        _cache.pop(oldest_key, None)
    _cache[(loan_id, updated_at_ts)] = (time.monotonic(), cfg)


def clear_cache() -> None:
    """Test hook — wipe the process-local cache."""
    _cache.clear()


# ── Public entry point ───────────────────────────────────────────────


async def effective_config(
    session: AsyncSession,
    loan_id: UUID,
    *,
    use_cache: bool = True,
) -> EffectiveConfig:
    """Resolve the effective config for one loan.

    The single read path for org-level + per-loan config across the
    pipeline + routes. No caller may read ``lo_doc_type_catalog``,
    ``lo_extraction_schemas``, ``lo_validation_rules_org``, or
    ``lo_program_profiles`` directly — go through here so the cache
    stays consistent.
    """
    pkg = (await session.execute(
        select(LOPackage).where(LOPackage.id == loan_id)
    )).scalar_one_or_none()
    if pkg is None:
        raise ValueError(f"Package {loan_id} not found")

    # Cache key folds in ``updated_at`` — any column edit (incl. profile
    # FK swap) bumps it via SQLAlchemy onupdate.
    ua_ts = pkg.updated_at.timestamp() if pkg.updated_at else 0.0
    if use_cache:
        cached = _cache_get(loan_id, ua_ts)
        if cached is not None:
            return cached

    cfg = await _resolve_uncached(session, pkg)
    if use_cache:
        _cache_put(loan_id, ua_ts, cfg)
    return cfg


# ── Uncached resolution ──────────────────────────────────────────────


async def _resolve_uncached(
    session: AsyncSession, pkg: LOPackage,
) -> EffectiveConfig:
    org_id = pkg.org_id
    loan_id = pkg.id

    # Layer 1 — Global org defaults.
    catalog_rows = (await session.execute(
        select(LODocTypeCatalog).where(
            LODocTypeCatalog.org_id == org_id,
            LODocTypeCatalog.active.is_(True),
        )
    )).scalars().all()
    schema_rows = (await session.execute(
        select(LOExtractionSchema).where(
            LOExtractionSchema.org_id == org_id,
            LOExtractionSchema.active.is_(True),
        )
    )).scalars().all()
    org_rule_rows = (await session.execute(
        select(LOValidationRuleOrg).where(
            LOValidationRuleOrg.org_id == org_id,
            LOValidationRuleOrg.active.is_(True),
        )
    )).scalars().all()

    # Layers 2/3 — program profile chain.
    loan_program: LOProgramProfile | None = None
    investor_overlay: LOProgramProfile | None = None
    if pkg.program_profile_id:
        selected = (await session.execute(
            select(LOProgramProfile).where(
                LOProgramProfile.id == pkg.program_profile_id,
                LOProgramProfile.org_id == org_id,
            )
        )).scalar_one_or_none()
        if selected is not None and selected.active:
            if selected.type == PROFILE_TYPE_INVESTOR_OVERLAY:
                investor_overlay = selected
                if selected.stacks_with:
                    base = (await session.execute(
                        select(LOProgramProfile).where(
                            LOProgramProfile.id == selected.stacks_with,
                            LOProgramProfile.org_id == org_id,
                        )
                    )).scalar_one_or_none()
                    if base is not None and base.active:
                        loan_program = base
            elif selected.type == PROFILE_TYPE_LOAN_PROGRAM:
                loan_program = selected

    # Layer 4 — per-loan overrides.
    loan_doc_cfg = (await session.execute(
        select(LODocTypeConfig).where(LODocTypeConfig.package_id == loan_id)
    )).scalar_one_or_none()
    loan_rule_rows = (await session.execute(
        select(LOValidationRule).where(
            LOValidationRule.package_id == loan_id,
            LOValidationRule.enabled.is_(True),
        )
    )).scalars().all()

    # Stack each axis independently.
    doc_types = stack_doc_types(
        catalog_rows, loan_program, investor_overlay, loan_doc_cfg,
    )
    schemas = stack_schemas(
        catalog_rows, schema_rows, loan_program, investor_overlay,
    )
    rules = stack_rules(
        org_rule_rows, loan_program, investor_overlay, loan_rule_rows,
    )

    cfg_hash = compute_config_hash(
        doc_types=doc_types,
        schemas=schemas,
        rules=rules,
        program_profile_id=loan_program.id if loan_program else None,
        investor_overlay_id=investor_overlay.id if investor_overlay else None,
        grounding_contract_version=GROUNDING_CONTRACT_VERSION,
    )

    return EffectiveConfig(
        loan_id=loan_id,
        org_id=org_id,
        program_profile_id=loan_program.id if loan_program else None,
        investor_overlay_id=investor_overlay.id if investor_overlay else None,
        doc_types=doc_types,
        schemas_by_doc_type=schemas,
        rules=rules,
        config_hash=cfg_hash,
        grounding_contract_version=GROUNDING_CONTRACT_VERSION,
    )
