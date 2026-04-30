"""Compliance service — wires the rule engine to package state + persistence.

Responsibilities:
  - Read the loan context off `LOPackage`.
  - Read the doc inventory from `LOStack` rows (tenant-scoped).
  - Call `compliance_rules.evaluate_compliance` (pure, no I/O).
  - Persist a new `LOComplianceRun` row capturing rules_version, rule_set_hash,
    snapshots, findings, and summary — for determinism + audit.
  - Return a render-ready payload with both LO and QC view derivations baked
    in (frontend just picks the persona to display).

No LLM. No outbound HTTP. Every query filtered by `org_id`.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.micro_apps.loan_onboarding.models.compliance import LOComplianceRun
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.extraction import LOExtraction
from app.micro_apps.loan_onboarding.models.extraction_override import (
    LOExtractionOverride,
)
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import (
    LOValidationResult,
)
from app.micro_apps.loan_onboarding.services import compliance_rules as cr
from app.micro_apps.loan_onboarding.services.package_service import (
    get_package_or_raise,
)

logger = logging.getLogger(__name__)


# ── Loan-context CRUD ──────────────────────────────────────────────────────

async def update_loan_context(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    context_dict: dict,
) -> LOPackage:
    """Persist a new loan context on the package after validating enums.

    Also evaluates compliance against the new context and persists a fresh
    `LOComplianceRun` audit row, so callers of `GET /compliance` (which
    short-circuits to the latest run) never see findings tied to a stale
    snapshot. Raises `ValidationError` if any enum is unknown — the frontend
    should never send these, but the service is the security boundary.
    """
    pkg = await get_package_or_raise(db, org_id, package_id)
    ctx = cr.LoanContext.from_dict(context_dict)
    errors = cr.validate_loan_context(ctx)
    if errors:
        raise ValidationError("; ".join(errors))
    pkg.loan_context = ctx.to_dict()
    await db.commit()
    await db.refresh(pkg)
    # Re-evaluate so the persisted audit trail tracks every context change.
    # `evaluate` opens its own commit; safe to call right after the refresh.
    await evaluate(db, org_id, package_id, persist=True)
    return pkg


# ── Doc inventory + evaluation ─────────────────────────────────────────────

async def _load_doc_inventory(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> list[str]:
    """Resolve the package's stack rows to a sorted list of doc-type labels.

    Sort + dedupe to make the snapshot deterministic — re-runs with the same
    package state must produce byte-identical `doc_inventory_snapshot`.
    """
    result = await db.execute(
        select(LOStack.doc_type)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
    )
    raw = [row for row in result.scalars().all() if row]
    # Stable, deduped — order doesn't affect rule matching but locks the hash.
    return sorted(set(raw))


async def _load_extraction_state(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> tuple[list[dict], list[dict]]:
    """Fetch extractions + overrides as flat dicts for cross-doc rules.

    Pure-data flatten so the rules module stays I/O-free. Tenant-scoped on
    every query.
    """
    extractions_result = await db.execute(
        select(LOExtraction).where(
            LOExtraction.package_id == package_id,
            LOExtraction.org_id == org_id,
        )
    )
    extractions = [
        {
            "stack_id": str(e.stack_id),
            "doc_type": e.doc_type,
            "fields": list(e.fields or []),
        }
        for e in extractions_result.scalars().all()
    ]

    overrides_result = await db.execute(
        select(LOExtractionOverride).where(
            LOExtractionOverride.package_id == package_id,
            LOExtractionOverride.org_id == org_id,
        )
    )
    overrides = [
        {
            "stack_id": o.stack_id,
            "doc_type": o.doc_type,
            "field_name": o.field_name,
            "value": o.value,
        }
        for o in overrides_result.scalars().all()
    ]
    return extractions, overrides


async def _load_validation_state(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> list[dict]:
    """Fetch validation results as flat dicts for derive_validation_findings.

    Pure-data flatten so the rules module stays I/O-free. Tenant-scoped on
    every query.
    """
    result = await db.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == package_id,
            LOValidationResult.org_id == org_id,
        )
    )
    return [
        {
            "stack_id": str(v.stack_id),
            "doc_type": v.doc_type,
            "rules_evaluated": list(v.rules_evaluated or []),
            "overall_confidence": float(v.overall_confidence or 0.0),
            "requires_hitl": bool(v.requires_hitl),
        }
        for v in result.scalars().all()
    ]


async def _load_view_inputs(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> tuple[list[dict], list[dict]]:
    """Fetch + flatten the live state needed to derive `doc_checks`.

    Returns `(stack_data, doc_type_specs)`:
      - `stack_data`: serialized stack rows ordered by `stack_index`. The
        compliance rules module is I/O-free, so we hand it dicts.
      - `doc_type_specs`: `LODocTypeConfig.doc_types` (or `[]` when unset).

    These are *render-time* projections, not part of the determinism contract
    — they reflect current package state, not the run's persisted snapshot.
    """
    stacks_result = await db.execute(
        select(LOStack)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
        .order_by(LOStack.stack_index)
    )
    stacks = list(stacks_result.scalars().all())
    stack_data = [
        {
            "stack_id": str(s.id),
            "doc_type": s.doc_type,
            "page_count": len(s.page_numbers or []),
            "overall_confidence": s.overall_confidence,
            "status": s.status,
            "stack_index": s.stack_index,
        }
        for s in stacks
    ]

    cfg_result = await db.execute(
        select(LODocTypeConfig).where(
            LODocTypeConfig.package_id == package_id,
            LODocTypeConfig.org_id == org_id,
        )
    )
    cfg = cfg_result.scalar_one_or_none()
    doc_type_specs = list(cfg.doc_types or []) if cfg is not None else []
    return stack_data, doc_type_specs


def _findings_from_dicts(items: list[dict]) -> list[cr.Finding]:
    """Rehydrate `Finding` objects from a stored `LOComplianceRun.findings` blob.

    Tolerates missing optional keys so historical rows (written before any
    field was added) still hydrate cleanly.
    """
    return [
        cr.Finding(
            id=f["id"],
            category=f["category"],
            regulation=f["regulation"],
            requirement=f["requirement"],
            requires=tuple(f.get("requires") or ()),
            requires_mode=f.get("requiresMode") or "all",
            severity=f["severity"],
            status=f["status"],
            matched=tuple(f.get("matched") or ()),
            missing_docs=tuple(f.get("missingDocs") or ()),
            details=f.get("details", ""),
            remediation=f.get("remediation", ""),
        )
        for f in items
    ]


def _build_view(
    findings: list[cr.Finding],
    summary: dict,
    ctx: cr.LoanContext,
    stack_data: list[dict],
    doc_type_specs: list[dict],
    hitl_threshold: float,
) -> dict:
    """Compose the LO + QC + regulations + doc-checks render payload."""
    return {
        "rules_version": cr.RULES_VERSION,
        "rule_set_hash": cr.compute_rule_set_hash(),
        "summary": summary,
        "findings": [f.to_dict() for f in findings],
        "lo_view": cr.derive_lo_view(findings),
        "qc_view": cr.derive_qc_view(findings),
        "regulations": cr.derive_regulations(ctx),
        "doc_checks": cr.derive_doc_checks(
            stack_data, doc_type_specs, hitl_threshold
        ),
    }


async def evaluate(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    *,
    persist: bool = True,
) -> tuple[LOComplianceRun | None, dict]:
    """Run the engine end-to-end and (optionally) persist the run.

    Returns `(run_row, payload)`. `run_row` is None when `persist=False`
    (used by tests + dry-run preview). The payload is render-ready.
    """
    pkg = await get_package_or_raise(db, org_id, package_id)
    ctx = cr.LoanContext.from_dict(pkg.loan_context or {})
    inventory = await _load_doc_inventory(db, org_id, package_id)
    stack_data, doc_type_specs = await _load_view_inputs(db, org_id, package_id)
    extractions, overrides = await _load_extraction_state(db, org_id, package_id)
    validation_results = await _load_validation_state(db, org_id, package_id)

    findings = cr.evaluate_compliance(inventory, ctx)
    # Layer in dynamic, data-driven findings (cross-doc consistency, failed
    # validation rules, low-confidence stacks). These aren't in
    # `COMPLIANCE_CHECKS` so they don't affect rule_set_hash; they're appended
    # after the static rule sweep so static rule order is preserved at the head
    # of the list.
    findings.extend(cr.derive_cross_doc_findings(extractions, overrides))
    findings.extend(cr.derive_validation_findings(validation_results))
    findings.extend(
        cr.derive_low_conf_stack_findings(stack_data, pkg.hitl_threshold)
    )
    summary = cr.summarize_compliance(findings)
    payload = _build_view(
        findings, summary, ctx, stack_data, doc_type_specs, pkg.hitl_threshold
    )
    # Package identity — stable across runs, but the frontend wants it in the
    # same response so it can render headers without a second fetch.
    payload.update({
        "package_id": str(pkg.id),
        "package_name": pkg.name,
        "loan_reference": pkg.loan_reference,
        "borrower_name": pkg.borrower_name,
        "loan_context_snapshot": ctx.to_dict(),
        "doc_inventory_snapshot": inventory,
    })

    run: LOComplianceRun | None = None
    if persist:
        run = LOComplianceRun(
            org_id=org_id,
            package_id=pkg.id,
            rules_version=cr.RULES_VERSION,
            rule_set_hash=payload["rule_set_hash"],
            loan_context_snapshot=ctx.to_dict(),
            doc_inventory_snapshot=inventory,
            findings=payload["findings"],
            summary=summary,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        payload["run_id"] = str(run.id)
        payload["created_at"] = (
            run.created_at.isoformat() if run.created_at else None
        )
    return run, payload


# ── Read-side helpers (used by routes) ─────────────────────────────────────

async def get_latest_run(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> LOComplianceRun | None:
    """Return the most recent compliance run for a package, or None."""
    result = await db.execute(
        select(LOComplianceRun)
        .where(
            LOComplianceRun.package_id == package_id,
            LOComplianceRun.org_id == org_id,
        )
        .order_by(LOComplianceRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def render_run(run: LOComplianceRun) -> dict:
    """Project a stored run row into a render payload — stored data only.

    Findings + LO view + QC view come from the persisted snapshot (cheap to
    re-derive, and lets us update the projection logic without rewriting DB
    rows). Live-state projections (`regulations`, `doc_checks`, package
    identity) are NOT included here — they require DB access and are layered
    on by `get_or_evaluate`. Callers that need them must use the async path.
    """
    findings = _findings_from_dicts(run.findings or [])
    return {
        "run_id": str(run.id),
        "package_id": str(run.package_id),
        "rules_version": run.rules_version,
        "rule_set_hash": run.rule_set_hash,
        "loan_context_snapshot": run.loan_context_snapshot,
        "doc_inventory_snapshot": run.doc_inventory_snapshot,
        "summary": run.summary,
        "findings": run.findings,
        "lo_view": cr.derive_lo_view(findings),
        "qc_view": cr.derive_qc_view(findings),
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


async def get_or_evaluate(
    db: AsyncSession, org_id: uuid.UUID, package_id: uuid.UUID
) -> dict:
    """Return latest run if present; otherwise evaluate now (and persist).

    For a stored run: stored fields come from the snapshot; `regulations` and
    `doc_checks` are recomputed live from current package state — these are
    render-time projections, not part of the determinism contract.
    """
    pkg = await get_package_or_raise(db, org_id, package_id)
    existing = await get_latest_run(db, org_id, package_id)
    if existing is None:
        _, payload = await evaluate(db, org_id, package_id, persist=True)
        return payload

    payload = render_run(existing)
    ctx = cr.LoanContext.from_dict(existing.loan_context_snapshot or {})
    stack_data, doc_type_specs = await _load_view_inputs(db, org_id, package_id)
    payload.update({
        "regulations": cr.derive_regulations(ctx),
        "doc_checks": cr.derive_doc_checks(
            stack_data, doc_type_specs, pkg.hitl_threshold
        ),
        "package_name": pkg.name,
        "loan_reference": pkg.loan_reference,
        "borrower_name": pkg.borrower_name,
    })
    return payload
