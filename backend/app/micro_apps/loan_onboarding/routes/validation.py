"""Validation routes — list rules + per-stack validation results."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.services import package_service
from app.models.user import User

router = APIRouter()


# Preset label/description metadata — kept in lockstep with routes/rules.py::_PRESET_CATALOG
# (duplicated here to avoid a cross-route import; both lists derive from PRESET_IDS).
_PRESET_META: dict[str, dict[str, str]] = {
    "missing_signatures": {
        "label": "Missing signatures",
        "description": "Flag stacks that do not contain a signature page.",
    },
    "missing_pages": {
        "label": "Missing first/last page",
        "description": "Flag stacks that don't have both a first_page and a last_page marker.",
    },
    "missing_fields": {
        "label": "Missing required fields",
        "description": "Flag stacks where named fields are absent from detected_fields.",
    },
}


def _enrich_rule_row(
    row: dict,
    rule_lookup: dict[tuple[str, str], LOValidationRule],
) -> dict:
    """Shape a stored rules_evaluated entry into the frontend `LoanRuleEvaluation` contract.

    Backend writes `{rule_id, rule_source, passed, evidence, location}`; the
    frontend expects `{rule_id, rule_source, label, description, passed, detail, config}`.
    Map `evidence → detail`, and look up `label`/`description`/`config` from either
    the preset metadata (for preset rules) or the LOValidationRule row (for custom).
    """
    rule_id = str(row.get("rule_id") or "")
    rule_source = str(row.get("rule_source") or "")
    label: str | None = None
    description: str | None = None
    config: dict = {}

    if rule_source == "preset":
        meta = _PRESET_META.get(rule_id)
        if meta:
            label = meta["label"]
            description = meta["description"]
        configured = rule_lookup.get((rule_source, rule_id))
        if configured is not None:
            # Preset rules can still carry per-package config (e.g. required_fields).
            config = dict(configured.config or {})
            if configured.description:
                description = configured.description
    else:
        configured = rule_lookup.get((rule_source, rule_id))
        if configured is not None:
            # Custom NL rules: the NL text lives in `description`; surface it as
            # both the rule label (falling back to the rule_id slug) and the
            # description shown in the table.
            description = configured.description
            label = (configured.description or "").strip().split("\n", 1)[0][:80] or rule_id
            config = dict(configured.config or {})

    if not label:
        label = rule_id.replace("_", " ").strip().capitalize() or rule_id

    return {
        "rule_id": rule_id,
        "rule_source": rule_source,
        "label": label,
        "description": description,
        "passed": bool(row.get("passed")),
        "detail": row.get("evidence"),
        "config": config,
    }


@router.get("/packages/{package_id}/rules")
async def list_rules(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    await package_service.get_package_or_raise(db, org_id, package_id)
    rules = (await db.execute(
        select(LOValidationRule)
        .where(
            LOValidationRule.package_id == package_id,
            LOValidationRule.org_id == org_id,
        )
        .order_by(LOValidationRule.created_at.asc())
    )).scalars().all()
    return [
        {
            "id": str(r.id),
            "rule_source": r.rule_source,
            "rule_id": r.rule_id,
            "description": r.description,
            "doc_type": r.doc_type,
            "config": r.config,
            "enabled": r.enabled,
        }
        for r in rules
    ]


@router.get("/packages/{package_id}/validation-results")
async def list_validation_results(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    await package_service.get_package_or_raise(db, org_id, package_id)
    rows = (await db.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == package_id,
            LOValidationResult.org_id == org_id,
        )
    )).scalars().all()

    # Load the package's configured rules once so we can attach label/description/config
    # to each per-stack rules_evaluated row without an N+1 query.
    configured_rules = (await db.execute(
        select(LOValidationRule).where(
            LOValidationRule.package_id == package_id,
            LOValidationRule.org_id == org_id,
        )
    )).scalars().all()
    rule_lookup: dict[tuple[str, str], LOValidationRule] = {
        (r.rule_source, r.rule_id): r for r in configured_rules
    }

    return [
        {
            "id": str(r.id),
            "stack_id": str(r.stack_id),
            "doc_type": r.doc_type,
            "rules_evaluated": [
                _enrich_rule_row(row, rule_lookup)
                for row in (r.rules_evaluated or [])
            ],
            "confidence_breakdown": r.confidence_breakdown,
            "overall_confidence": r.overall_confidence,
            "requires_hitl": r.requires_hitl,
        }
        for r in rows
    ]
