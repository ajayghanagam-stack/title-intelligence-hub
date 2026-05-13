"""Phase 4 operator-flow endpoints on the ``/loans/*`` prefix.

These are the *new* endpoints the LogikIntake operator UI needs that don't
have a direct ``/packages/*`` analogue, so they aren't pure aliases. Each
section maps to a Phase 4 batch:

- 4.3 ``POST /loans/{id}/documents/{doc_id}/classify``  — confirm/override stack doc_type
- 4.4 ``GET  /loans/{id}/checklist``                    — program-resolved doc checklist
- 4.5 ``GET  /loans/{id}/extractions/{doc_id}``         — per-doc fields with overrides merged
- 4.5 ``PATCH /loans/{id}/extractions/{doc_id}/fields/{field_id}`` — single-field operator edit
- 4.6 ``POST /loans/{id}/validations/{check_id}/acknowledge`` — soft-flag ack
- 4.7 ``POST /loans/{id}/advance``                     — monotonic advance to decision_ready
- 4.8 ``GET  /loans/{id}/pipeline/stream``             — SSE stream replacing 3s polling
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.core.deps import (
    get_current_member,
    get_db,
    get_org_id,
    get_session_factory,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.extraction import LOExtraction
from app.micro_apps.loan_onboarding.models.extraction_override import (
    LOExtractionOverride,
)
from app.micro_apps.loan_onboarding.models.hard_stop_override import LOHardStopOverride
from app.micro_apps.loan_onboarding.models.hitl_review import LOHITLReview
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import (
    LOValidationResult,
)
from app.micro_apps.loan_onboarding.services import (
    file_service,
    package_service,
    remediation_service,
)
from app.micro_apps.loan_onboarding.services.config_resolver import (
    effective_config,
)
from app.models.audit_event import AuditEvent
from app.models.user import User
from app.services.audit_service import log_event
from app.services.storage import StorageProvider, get_storage

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 4.3  POST /loans/{id}/documents/{doc_id}/classify ─────────────────


class ConfirmClassificationBody(BaseModel):
    """Body for the operator-driven ``classify`` action.

    ``doc_type`` is optional. When omitted, the operator is confirming the
    stack's currently-predicted doc_type (records ``decision="accept"``).
    When provided and different from the current value, the stack is
    re-typed (``decision="reclassify"``) and the corrected value persisted.
    """
    model_config = ConfigDict(extra="forbid")
    doc_type: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.post(
    "/loans/{loan_id}/documents/{doc_id}/classify",
    status_code=status.HTTP_201_CREATED,
)
async def confirm_loan_document_classification(
    loan_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: ConfirmClassificationBody,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Confirm or override a stack's classification.

    Mirrors the HITL ``record_review_decision`` semantics but exposed on
    the Documents tab so operators can confirm a stack outside the HITL
    queue. Always records an ``LOHITLReview`` row for audit. ``doc_id``
    in the LogikIntake contract is the stack id.
    """
    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == doc_id,
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise NotFoundError("LoanDocument", doc_id)

    target_doc_type = (body.doc_type or "").strip() or None
    if target_doc_type is None or target_doc_type == stack.doc_type:
        decision: Literal["accept", "reclassify"] = "accept"
        corrected_doc_type = None
    else:
        decision = "reclassify"
        corrected_doc_type = target_doc_type

    review = LOHITLReview(
        org_id=org_id,
        package_id=loan_id,
        stack_id=stack.id,
        reviewer_id=member.id,
        decision=decision,
        corrected_doc_type=corrected_doc_type,
        notes=body.notes,
    )
    db.add(review)

    if decision == "reclassify":
        stack.doc_type = corrected_doc_type
    stack.status = "accepted"
    stack.requires_hitl = False

    # Mirror the auto-advance semantics from review.record_review_decision
    # so operator-confirmation can drain the awaiting_review queue.
    remaining_hitl = (await db.execute(
        select(LOStack).where(
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
            LOStack.requires_hitl == True,  # noqa: E712
        )
    )).scalars().all()
    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == loan_id, LOPackage.org_id == org_id
        )
    )).scalar_one()
    if not remaining_hitl and pkg.status == "awaiting_review":
        pkg.status = "completed"

    await log_event(
        db, org_id,
        action="lo_document_classified",
        target_type="lo_stack",
        target_id=stack.id,
        actor_id=member.id,
        metadata={"decision": decision, "doc_type": stack.doc_type},
    )
    await db.commit()
    await db.refresh(review)
    return {
        "stack_id": str(stack.id),
        "decision": decision,
        "doc_type": stack.doc_type,
        "review_id": str(review.id),
    }


# ── 4.4  GET /loans/{id}/checklist ────────────────────────────────────


class LoanChecklistItem(BaseModel):
    doc_type: str
    label: str
    requirement: Literal["Required", "Optional", "Conditional"]
    received: bool
    stack_count: int
    needs_review: bool


@router.get("/loans/{loan_id}/checklist", response_model=list[LoanChecklistItem])
async def get_loan_checklist(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return the per-package doc checklist with received/missing state.

    Source of truth is ``LODocTypeConfig.doc_types`` (the loan officer's
    expected list at upload time). For each entry, count matching stacks
    by ``doc_type`` and surface whether any need review. Program-profile
    overlay resolution happens at config-creation time, so this endpoint
    just reports what the package was configured with.
    """
    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    config = await package_service.get_doc_type_config(db, org_id, loan_id)
    doc_types = list(config.doc_types) if config is not None else []

    stacks = (await db.execute(
        select(LOStack).where(
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalars().all()
    by_type: dict[str, list[LOStack]] = {}
    for s in stacks:
        by_type.setdefault(s.doc_type, []).append(s)

    out: list[LoanChecklistItem] = []
    for entry in doc_types:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "")
        if not key:
            continue
        label = str(entry.get("label") or key)
        # `required` in the config is bool; map to the LogikIntake tri-state
        # ("Conditional" lands when the program profile sets a condition,
        # which we don't currently surface — fall back to required/optional).
        is_required = bool(entry.get("required"))
        condition = entry.get("condition")
        if condition:
            requirement: Literal["Required", "Optional", "Conditional"] = "Conditional"
        elif is_required:
            requirement = "Required"
        else:
            requirement = "Optional"

        matched = by_type.get(key, [])
        out.append(LoanChecklistItem(
            doc_type=key,
            label=label,
            requirement=requirement,
            received=bool(matched),
            stack_count=len(matched),
            needs_review=any(s.requires_hitl for s in matched),
        ))
    return out


# ── 4.5  GET /loans/{id}/extractions/{doc_id}  + PATCH .../fields/{field_id} ─


def _flatten_field(f: dict) -> dict:
    """Mirror the per-field shape used by /packages/{id}/extractions."""
    loc = f.get("location") if isinstance(f, dict) else None
    page = None
    bbox = None
    if isinstance(loc, dict):
        try:
            page = int(loc.get("page")) if loc.get("page") is not None else None
        except (TypeError, ValueError):
            page = None
        box = loc.get("bbox")
        if isinstance(box, list) and len(box) == 4:
            try:
                bbox = [float(x) for x in box]
            except (TypeError, ValueError):
                bbox = None
    return {
        "name": str(f.get("name", "")),
        "value": str(f.get("value") or ""),
        "confidence": float(f.get("confidence", 0.0) or 0.0),
        "status": str(f.get("status") or "missing"),
        "page": page,
        "bbox": bbox,
    }


@router.get("/loans/{loan_id}/extractions/{doc_id}")
async def get_loan_doc_extraction(
    loan_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return the single LOExtraction for a stack with operator overrides
    merged in. ``doc_id`` == stack id. Each field gets a ``grounded`` flag
    (true when the AI emitted a page+bbox) and an ``edited`` flag (true
    when an operator override is active for that field+stack)."""
    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == doc_id,
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise NotFoundError("LoanDocument", doc_id)

    extraction = (await db.execute(
        select(LOExtraction).where(
            LOExtraction.stack_id == doc_id,
            LOExtraction.org_id == org_id,
        )
    )).scalar_one_or_none()

    overrides = (await db.execute(
        select(LOExtractionOverride).where(
            LOExtractionOverride.package_id == loan_id,
            LOExtractionOverride.org_id == org_id,
            LOExtractionOverride.stack_id == str(doc_id),
        )
    )).scalars().all()
    override_by_field = {o.field_name: o for o in overrides}

    raw_fields = (extraction.fields if extraction else []) or []

    # Schema-driven row order: render every configured field for this stack's
    # doc_type, even when the extractor didn't return a value. Otherwise
    # fields the AI missed (or fields promoted into the schema after this
    # loan was processed) are invisible in the UI — operators have no way
    # to fill them in or see what was expected. We resolve the *current*
    # effective config so fresh admin edits surface immediately; rows
    # without an extracted value get status="missing" and an empty value.
    doc_type_key = (extraction.doc_type if extraction else stack.doc_type) or ""
    try:
        cfg = await effective_config(db, loan_id)
        resolved_schema = cfg.schema(doc_type_key) if doc_type_key else None
    except Exception:  # pragma: no cover — never block review on resolver failure
        logger.exception("effective_config failed for loan=%s", loan_id)
        resolved_schema = None

    # Index extracted rows by the label the agent emitted (name == label).
    extracted_by_name: dict[str, dict] = {}
    for f in raw_fields:
        if not isinstance(f, dict):
            continue
        flat = _flatten_field(f)
        flat["grounded"] = flat["page"] is not None and flat["bbox"] is not None
        extracted_by_name[flat["name"]] = flat

    def _apply_override(row: dict) -> dict:
        ov = override_by_field.get(row["name"])
        if ov is not None:
            row["value"] = ov.value
            row["status"] = "located" if ov.value else row.get("status", "missing")
            row["edited"] = True
            row["edited_at"] = ov.edited_at.isoformat()
        else:
            row["edited"] = row.get("edited", False)
            row["edited_at"] = row.get("edited_at", None)
        return row

    out_fields: list[dict] = []
    seen_names: set[str] = set()

    if resolved_schema is not None:
        for sf in resolved_schema.fields:
            label = (sf.label or sf.key or "").strip()
            if not label:
                continue
            existing = extracted_by_name.get(label)
            if existing is not None:
                row = dict(existing)
            else:
                row = {
                    "name": label,
                    "value": "",
                    "confidence": 0.0,
                    "status": "missing",
                    "page": None,
                    "bbox": None,
                    "grounded": False,
                    "edited": False,
                    "edited_at": None,
                }
            row["key"] = sf.key
            row["label"] = label
            row["required"] = bool(sf.required)
            row["data_type"] = sf.data_type
            out_fields.append(_apply_override(row))
            seen_names.add(label)

    # Tail: any extracted fields that no longer appear in the resolved schema
    # (renamed/removed since the run). Surface them so operators can still see
    # what the agent produced rather than silently dropping data.
    for name, row in extracted_by_name.items():
        if name in seen_names:
            continue
        row = dict(row)
        row.setdefault("key", name)
        row.setdefault("label", name)
        row.setdefault("required", False)
        row.setdefault("data_type", "string")
        out_fields.append(_apply_override(row))

    schema_version = resolved_schema.schema_version if resolved_schema else None
    total_count = len(out_fields)
    located_count = sum(
        1 for r in out_fields
        if (r.get("value") or "").strip() and r.get("status") != "missing"
    )
    # Drive the UI's "Re-run Extraction" prompt. The right side panel can't
    # distinguish "AI didn't find this field" from "extraction never ran for
    # this stack" without this flag — both look like empty values otherwise.
    schema_field_count = (
        len(resolved_schema.fields) if resolved_schema is not None else 0
    )

    return {
        "stack_id": str(doc_id),
        "doc_type": doc_type_key,
        "fields": out_fields,
        "located_count": located_count,
        "total_count": total_count,
        "schema_version": schema_version,
        "extraction_present": extraction is not None,
        "schema_field_count": schema_field_count,
    }


class FieldEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., max_length=4000)


@router.patch("/loans/{loan_id}/extractions/{doc_id}/fields/{field_id}")
async def patch_loan_extraction_field(
    loan_id: uuid.UUID,
    doc_id: uuid.UUID,
    field_id: str,
    body: FieldEditBody,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Persist a single-field operator edit as an extraction override.

    ``field_id`` is the field name as URL-safe slug (matches the ``name``
    emitted by the agent). The override service is keyed by
    ``(package_id, doc_type, field_name, stack_id)`` so we look up the
    stack's doc_type from the LOExtraction row (or fall back to the stack
    itself if no extraction has run yet — keeps the endpoint usable
    pre-extract).
    """
    from app.micro_apps.loan_onboarding.services import (
        extraction_override_service,
    )

    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == doc_id,
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise NotFoundError("LoanDocument", doc_id)

    extraction = (await db.execute(
        select(LOExtraction).where(
            LOExtraction.stack_id == doc_id,
            LOExtraction.org_id == org_id,
        )
    )).scalar_one_or_none()
    doc_type = extraction.doc_type if extraction else stack.doc_type

    row = await extraction_override_service.upsert_override(
        db, org_id, loan_id,
        doc_type=doc_type,
        field_name=field_id,
        stack_id=str(doc_id),
        value=body.value,
        edited_by_id=member.id,
    )
    await log_event(
        db, org_id,
        action="lo_extraction_field_edited",
        target_type="lo_extraction_override",
        target_id=row.id,
        actor_id=member.id,
        metadata={
            "package_id": str(loan_id),
            "stack_id": str(doc_id),
            "field_name": field_id,
            "doc_type": doc_type,
        },
    )
    await db.commit()
    await db.refresh(row)
    return {
        "stack_id": str(doc_id),
        "field_name": field_id,
        "value": row.value,
        "edited_at": row.edited_at.isoformat(),
    }


# ── Re-run extraction for one stack ───────────────────────────────────
#
# The pipeline-time extraction stage only fires once. When the operator
# adds or promotes fields in Admin → Extraction Schemas *after* a loan has
# been processed, those new fields have no values in ``LOExtraction.fields``
# — the review screen surfaces them as schema-driven placeholders. This
# endpoint lets the operator manually re-run extraction for a single stack
# against the *current* resolver schema, so the new fields get populated
# without re-uploading the loan.


@router.post(
    "/loans/{loan_id}/extractions/{doc_id}/rerun",
    status_code=status.HTTP_200_OK,
)
async def rerun_loan_doc_extraction(
    loan_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Re-run extraction on a single stack using the current resolver schema.

    Delegates to ``remediation_service.extract_single_doc`` which is now
    resolver-aware (prefers ``effective_config().schemas_by_doc_type`` over
    the per-loan snapshot). Returns the same summary the review endpoint
    consumes, so the frontend can refetch immediately.
    """
    from app.micro_apps.loan_onboarding.services import remediation_service

    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == doc_id,
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise NotFoundError("LoanDocument", doc_id)

    result = await remediation_service.extract_single_doc(
        db, org_id, loan_id, doc_id, storage, force=True,
    )
    await log_event(
        db, org_id,
        action="lo_extraction_rerun",
        target_type="lo_stack",
        target_id=doc_id,
        actor_id=member.id,
        metadata={
            "package_id": str(loan_id),
            "stack_id": str(doc_id),
            "doc_type": stack.doc_type,
            "fields_extracted": result.fields_extracted,
            "status": result.status,
        },
    )
    await db.commit()
    return {
        "stack_id": str(doc_id),
        "fields_extracted": int(result.fields_extracted),
        "status": result.status,
    }


# ── 4.6  POST /loans/{id}/validations/{check_id}/acknowledge ──────────


class AcknowledgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    override_note: str | None = Field(default=None, max_length=2000)


def _parse_check_id(check_id: str) -> tuple[uuid.UUID, str, str]:
    """``{stack_id}__{rule_source}__{rule_id}`` → tuple, or 400.

    Double-underscore is the separator because rule_id slugs use single
    underscores (e.g. ``missing_signatures``).
    """
    parts = check_id.split("__", 2)
    if len(parts) != 3:
        raise ValidationError(
            "check_id must be '{stack_id}__{rule_source}__{rule_id}'"
        )
    stack_str, rule_source, rule_id = parts
    try:
        stack_id = uuid.UUID(stack_str)
    except ValueError as e:
        raise ValidationError(f"check_id stack component invalid: {e}")
    if not rule_source or not rule_id:
        raise ValidationError("check_id rule_source / rule_id missing")
    return stack_id, rule_source, rule_id


@router.post(
    "/loans/{loan_id}/validations/{check_id}/acknowledge",
    status_code=status.HTTP_200_OK,
)
async def acknowledge_loan_validation(
    loan_id: uuid.UUID,
    check_id: str,
    body: AcknowledgeBody,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Mark a soft-flag rule as acknowledged.

    Mutates the matching ``rules_evaluated[]`` entry on the stack's
    LOValidationResult in-place — no new table needed for this surface.
    Idempotent: re-acking is a no-op for state but updates the note +
    timestamp.
    """
    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    stack_id, rule_source, rule_id = _parse_check_id(check_id)

    vr = (await db.execute(
        select(LOValidationResult).where(
            LOValidationResult.stack_id == stack_id,
            LOValidationResult.org_id == org_id,
        )
    )).scalar_one_or_none()
    if vr is None:
        raise NotFoundError("LoanValidationResult", stack_id)

    rules = list(vr.rules_evaluated or [])
    target = None
    for r in rules:
        if not isinstance(r, dict):
            continue
        if (str(r.get("rule_source") or "") == rule_source
                and str(r.get("rule_id") or "") == rule_id):
            target = r
            break
    if target is None:
        raise NotFoundError("LoanValidationCheck", check_id)

    if bool(target.get("passed")):
        # The PRD only allows ack on failing soft flags. Acking a passing
        # rule is meaningless and likely a bug in the caller.
        raise ValidationError(
            "Cannot acknowledge a passing rule (only failing soft flags)"
        )

    target["acknowledged"] = True
    target["acknowledged_by"] = str(member.id)
    target["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
    if body.override_note is not None:
        target["override_note"] = body.override_note

    vr.rules_evaluated = rules
    flag_modified(vr, "rules_evaluated")

    await log_event(
        db, org_id,
        action="lo_validation_acknowledged",
        target_type="lo_validation_result",
        target_id=vr.id,
        actor_id=member.id,
        metadata={
            "stack_id": str(stack_id),
            "rule_source": rule_source,
            "rule_id": rule_id,
        },
    )
    await db.commit()
    return {
        "stack_id": str(stack_id),
        "rule_source": rule_source,
        "rule_id": rule_id,
        "acknowledged": True,
        "override_note": target.get("override_note"),
    }


# ── 4.7  POST /loans/{id}/advance ─────────────────────────────────────


class LoanAdvanceResponse(BaseModel):
    advanced: bool
    from_status: str
    to_status: str
    blocked_reason: str | None = None
    open_hard_stops: int
    open_soft_flags: int


def _is_failing_soft_flag(rule: dict) -> bool:
    """A soft-flag entry that's still actionable (failed + not acked)."""
    if not isinstance(rule, dict):
        return False
    if rule.get("passed"):
        return False
    # Treat ``hard_stop`` rules as hard stops, not soft flags. Preset rules
    # without an explicit type default to soft (PRD §6.4 — only custom
    # rules carry a hard/soft tag today).
    if str(rule.get("severity") or rule.get("type") or "").lower() == "hard":
        return False
    return not bool(rule.get("acknowledged"))


def _is_failing_hard_stop(rule: dict) -> bool:
    if not isinstance(rule, dict) or rule.get("passed"):
        return False
    return str(rule.get("severity") or rule.get("type") or "").lower() == "hard"


@router.post("/loans/{loan_id}/advance", response_model=LoanAdvanceResponse)
async def advance_loan(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Operator-driven monotonic stage advance to ``decision_ready``.

    Per PRD §3.5: advance is one-way. Gates:
      - no remaining HITL stacks
      - no unresolved hard-stop rule failures (overridden ones are OK)
      - no unacknowledged soft-flag rule failures

    Returns 409-style ``advanced=False`` with a ``blocked_reason`` when
    any gate fails — preserves the current status. On success the package
    transitions to ``status="decision_ready"``.
    """
    pkg = await package_service.get_visible_package_or_raise(
        db, org_id, loan_id, member
    )
    from_status = pkg.status

    if from_status == "decision_ready":
        # Idempotent: already there, return advanced=False but happy.
        return LoanAdvanceResponse(
            advanced=False,
            from_status=from_status,
            to_status=from_status,
            blocked_reason="already_decision_ready",
            open_hard_stops=0,
            open_soft_flags=0,
        )

    if from_status not in ("awaiting_review", "completed"):
        raise ValidationError(
            f"Cannot advance from status '{from_status}' — package must be "
            f"'awaiting_review' or 'completed' first"
        )

    # Gate 1 — no HITL stacks left.
    hitl = (await db.execute(
        select(LOStack).where(
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
            LOStack.requires_hitl == True,  # noqa: E712
        )
    )).scalars().all()
    if hitl:
        return LoanAdvanceResponse(
            advanced=False,
            from_status=from_status,
            to_status=from_status,
            blocked_reason=f"{len(hitl)} stack(s) still need HITL review",
            open_hard_stops=0,
            open_soft_flags=0,
        )

    # Gate 2 + 3 — scan validation results.
    results = (await db.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == loan_id,
            LOValidationResult.org_id == org_id,
        )
    )).scalars().all()
    overrides = (await db.execute(
        select(LOHardStopOverride).where(
            LOHardStopOverride.package_id == loan_id,
            LOHardStopOverride.org_id == org_id,
            LOHardStopOverride.decision == "active",
        )
    )).scalars().all()
    overridden_keys = {o.hard_stop_key for o in overrides}

    open_hard = 0
    open_soft = 0
    for vr in results:
        for rule in vr.rules_evaluated or []:
            if _is_failing_hard_stop(rule):
                key = f"{rule.get('rule_source')}:{rule.get('rule_id')}:{vr.stack_id}"
                if key not in overridden_keys:
                    open_hard += 1
            elif _is_failing_soft_flag(rule):
                open_soft += 1

    if open_hard or open_soft:
        return LoanAdvanceResponse(
            advanced=False,
            from_status=from_status,
            to_status=from_status,
            blocked_reason=(
                f"{open_hard} open hard-stop(s), {open_soft} unacknowledged "
                f"soft flag(s)"
            ),
            open_hard_stops=open_hard,
            open_soft_flags=open_soft,
        )

    pkg.status = "decision_ready"
    await log_event(
        db, org_id,
        action="lo_loan_advanced",
        target_type="lo_package",
        target_id=loan_id,
        actor_id=member.id,
        metadata={"from_status": from_status, "to_status": "decision_ready"},
    )
    await db.commit()
    return LoanAdvanceResponse(
        advanced=True,
        from_status=from_status,
        to_status="decision_ready",
        blocked_reason=None,
        open_hard_stops=0,
        open_soft_flags=0,
    )


# ── 4.8  GET /loans/{id}/pipeline/stream ──────────────────────────────


# Terminal package statuses — once the package lands here the SSE stream
# emits its final frame and closes. ``awaiting_review`` is intentionally
# *not* terminal (the operator may still drive HITL → decision_ready), so
# the stream stays open and tracks any subsequent transitions.
_TERMINAL_LO_STATUSES = {"completed", "failed", "decision_ready"}
_STREAM_POLL_SECONDS = 2.0


@router.get("/loans/{loan_id}/pipeline/stream")
async def stream_loan_pipeline(
    loan_id: uuid.UUID,
    request: Request,
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    session_factory=Depends(get_session_factory),
):
    """SSE stream of pipeline status — replaces the 3s frontend poll.

    Mirrors the TI ``/packs/{id}/pipeline/stream`` shape: pushes a frame
    whenever the rendered status payload changes, closes on terminal
    statuses or client disconnect. Uses a fresh session per tick so the
    pool isn't held for the duration of the stream.
    """
    # One-shot membership/visibility check up front so we 404/403 before
    # the streaming response starts (FastAPI can't change status mid-stream).
    async with session_factory() as preflight_db:
        await package_service.get_visible_package_or_raise(
            preflight_db, org_id, loan_id, member
        )

    async def event_stream():
        prev_payload = ""
        while True:
            if await request.is_disconnected():
                return
            async with session_factory() as db:
                pkg = (await db.execute(
                    select(LOPackage).where(
                        LOPackage.id == loan_id, LOPackage.org_id == org_id
                    )
                )).scalar_one_or_none()
                if pkg is None:
                    yield f"data: {json.dumps({'error': 'Loan not found'})}\n\n"
                    return
                progress = pkg.progress or {}
                payload = {
                    "package_id": str(pkg.id),
                    "status": pkg.status,
                    "pipeline_stage": pkg.pipeline_stage,
                    "pipeline_error": pkg.pipeline_error,
                    "progress": progress,
                    "processed": int(progress.get("processed") or 0),
                    "total": int(progress.get("total") or 0),
                    "hitl_count": int(progress.get("hitl_count") or 0),
                }
                terminal = pkg.status in _TERMINAL_LO_STATUSES

            current = json.dumps(payload, default=str, sort_keys=True)
            if current != prev_payload:
                yield f"data: {current}\n\n"
                prev_payload = current
            if terminal:
                return
            await asyncio.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Reject + Re-upload (remediation modal — Phase 5 closing) ──────────


class RejectDocumentBody(BaseModel):
    """Body for ``POST /loans/{id}/documents/{doc_id}/reject``."""
    model_config = ConfigDict(extra="forbid")
    notes: str | None = Field(default=None, max_length=2000)


def _auto_advance_after_resolution(
    pkg: LOPackage,
    remaining_hitl: list[LOStack],
) -> None:
    """If no stacks still need review, drain ``awaiting_review`` to ``completed``.

    Mirrors the contract in ``review.record_review_decision`` /
    ``loans_operator.confirm_loan_document_classification`` so reject + re-upload
    behave consistently with the other operator-facing review actions.
    """
    if not remaining_hitl and pkg.status == "awaiting_review":
        pkg.status = "completed"


@router.post(
    "/loans/{loan_id}/documents/{doc_id}/reject",
    status_code=status.HTTP_201_CREATED,
)
async def reject_loan_document(
    loan_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: RejectDocumentBody,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Drop a stack from the loan file.

    Records an ``LOHITLReview`` row with ``decision="reject"``, marks the
    stack ``status="rejected"``, clears its HITL flag (the operator has
    resolved it — keeping it open would leave the queue stuck), and
    auto-advances the package status if this was the last open review.

    Wires the "Mark rejected" action in the LogikIntake remediation modal.
    """
    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == doc_id,
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise NotFoundError("LoanDocument", doc_id)

    review = LOHITLReview(
        org_id=org_id,
        package_id=loan_id,
        stack_id=stack.id,
        reviewer_id=member.id,
        decision="reject",
        corrected_doc_type=None,
        notes=body.notes,
    )
    db.add(review)

    stack.status = "rejected"
    # Reject is a *resolution* of the HITL ask — operator chose to drop the
    # doc — so clear the HITL flag. (review.record_review_decision keeps the
    # flag set because it expects the operator to follow up with re-upload;
    # the LogikIntake operator surface treats reject as terminal instead.)
    stack.requires_hitl = False

    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == loan_id, LOPackage.org_id == org_id
        )
    )).scalar_one()
    remaining_hitl = (await db.execute(
        select(LOStack).where(
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
            LOStack.requires_hitl == True,  # noqa: E712
        )
    )).scalars().all()
    _auto_advance_after_resolution(pkg, remaining_hitl)

    await log_event(
        db, org_id,
        action="lo_document_rejected",
        target_type="lo_stack",
        target_id=stack.id,
        actor_id=member.id,
        metadata={
            "doc_type": stack.doc_type,
            "first_page": stack.first_page,
            "last_page": stack.last_page,
        },
    )
    await db.commit()
    await db.refresh(review)
    return {
        "stack_id": str(stack.id),
        "decision": "reject",
        "review_id": str(review.id),
        "package_status": pkg.status,
    }


@router.post(
    "/loans/{loan_id}/documents/{doc_id}/reupload",
    status_code=status.HTTP_202_ACCEPTED,
)
async def reupload_loan_document(
    loan_id: uuid.UUID,
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    notes: str | None = None,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Replace a flagged stack with a fresh PDF.

    Combines reject + remediation upload in one round-trip:
      1. Persist the new PDF and ingest its pages (appends to the package).
      2. Mark the old stack ``status="rejected"`` + write an HITL review row
         (``decision="reject"``, ``notes="reupload: <user notes>"``) so the
         audit trail records why the old stack was dropped.
      3. Dispatch the same Variant-A remediation workflow used by
         ``/remediate-missing-doc`` (classify → doc-validate → extract →
         data-validate the new file) — Temporal or inline, per
         ``PIPELINE_BACKEND``.

    Pre-commit ordering matters: if ingest fails mid-way, the rejection is
    rolled back too, so the operator sees a clean error rather than a
    half-applied state.
    """
    settings = get_settings()
    package = await package_service.get_visible_package_or_raise(
        db, org_id, loan_id, member,
    )

    # The remediation pipeline expects awaiting_review or completed — same
    # gate the existing /remediate-missing-doc route enforces. Re-upload is
    # only meaningful once the pipeline has flagged something for review.
    _OK = frozenset({"awaiting_review", "completed"})
    if package.status not in _OK:
        raise ValidationError(
            f"Loan cannot accept a re-upload from status '{package.status}'. "
            f"Allowed: {sorted(_OK)}"
        )

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == doc_id,
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise NotFoundError("LoanDocument", doc_id)

    data = await file.read()
    max_size = settings.LO_FILE_UPLOAD_MAX_SIZE
    if len(data) > max_size:
        raise ValidationError(
            f"File '{file.filename}' exceeds max size of {max_size} bytes"
        )

    # Phase 1 — persist the new file (commits internally to flush before
    # ingest reads it back via storage).
    file_row = await file_service.store_uploaded_file(
        db, storage,
        org_id=org_id, package_id=loan_id,
        filename=file.filename or "reupload.pdf",
        content=data, content_type=file.content_type,
    )

    # Phase 2 — append pages for the new file to the package's global numbering.
    ingest_result = await remediation_service.ingest_single_file(
        db, org_id, loan_id, file_row.id, storage,
    )

    # Phase 3 — mark old stack rejected in the same txn as ingest so we
    # commit them together.
    note_body = f"reupload: {notes}" if notes else "reupload"
    review = LOHITLReview(
        org_id=org_id,
        package_id=loan_id,
        stack_id=stack.id,
        reviewer_id=member.id,
        decision="reject",
        corrected_doc_type=None,
        notes=note_body[:2000],
    )
    db.add(review)
    stack.status = "rejected"
    stack.requires_hitl = False

    await log_event(
        db, org_id,
        action="lo_document_reuploaded",
        target_type="lo_stack",
        target_id=stack.id,
        actor_id=member.id,
        metadata={
            "old_doc_type": stack.doc_type,
            "new_file_id": str(file_row.id),
            "filename": file_row.filename,
            "pages_added": ingest_result.pages_added,
            "first_page_number": ingest_result.first_page_number,
            "last_page_number": ingest_result.last_page_number,
        },
    )
    await db.commit()

    # Phase 4 — dispatch the Variant-A workflow. Reuse remediation.py's
    # helpers verbatim so the workflow id naming + step ordering stays
    # consistent across both entry points (remediate-missing-doc + reupload).
    from app.micro_apps.loan_onboarding.routes.remediation import (
        _run_remediation_inline,
        _start_temporal_workflow,
    )

    workflow_id: str | None = None
    backend = settings.PIPELINE_BACKEND
    if backend == "temporal":
        workflow_id = await _start_temporal_workflow(
            settings, loan_id, org_id, file_row.id,
        )
    else:
        session_factory = get_session_factory()
        background_tasks.add_task(
            _run_remediation_inline,
            org_id, loan_id, file_row.id,
            session_factory, storage,
        )

    return {
        "stack_id": str(stack.id),
        "review_id": str(review.id),
        "file_id": str(file_row.id),
        "pages_added": ingest_result.pages_added,
        "first_page_number": ingest_result.first_page_number,
        "last_page_number": ingest_result.last_page_number,
        "workflow_id": workflow_id,
        "backend": backend,
    }


# ── Audit events (replaces the synthesized timeline in audit-drawer.tsx) ─


class AuditEventOut(BaseModel):
    """Wire shape for ``GET /loans/{id}/audit-events``.

    Mirrors the ``audit_events`` table 1:1 — the frontend maps ``action`` +
    ``target_type`` to a UI-facing kind/title in `audit-drawer.tsx`. We
    keep the wire shape low-level so future actions (e.g. compliance
    overrides) surface automatically without a schema change.
    """
    id: str
    action: str
    target_type: str
    target_id: str | None
    actor_id: str | None
    metadata: dict
    created_at: datetime


@router.get(
    "/loans/{loan_id}/audit-events",
    response_model=list[AuditEventOut],
)
async def list_loan_audit_events(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return the audit-event timeline for a loan, newest first.

    Different LO actions log to ``audit_events`` with different
    ``target_id`` values:
      - package-scoped (created/deleted/remediated): target_id = loan_id
      - stack-scoped (HITL review, classify, reject, reupload): target_id ∈ stack_ids
      - page-scoped (page override apply/remove): target_id ∈ page_ids
      - extraction-override: target_id = override id; metadata.package_id ties it back

    To capture the package + stack + page events without a JSONB filter
    (SQLite tests don't support JSONB ops), we fetch the stack + page id
    sets up-front and OR them into the where clause. Extraction-override
    events fall outside this set today; we'll include them when the
    audit-event schema gains a ``package_id`` first-class field.
    """
    await package_service.get_visible_package_or_raise(db, org_id, loan_id, member)

    stack_ids = (await db.execute(
        select(LOStack.id).where(
            LOStack.package_id == loan_id,
            LOStack.org_id == org_id,
        )
    )).scalars().all()
    page_ids = (await db.execute(
        select(LOPage.id).where(
            LOPage.package_id == loan_id,
            LOPage.org_id == org_id,
        )
    )).scalars().all()

    # Build the OR'd target_id filter. ``target_id IN ([])`` is a no-op in
    # SQLAlchemy (always false), so the empty-stack / empty-page case is
    # handled gracefully.
    target_filters = [AuditEvent.target_id == loan_id]
    if stack_ids:
        target_filters.append(AuditEvent.target_id.in_(stack_ids))
    if page_ids:
        target_filters.append(AuditEvent.target_id.in_(page_ids))

    rows = (await db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.org_id == org_id,
            or_(*target_filters),
        )
        .order_by(AuditEvent.created_at.desc())
    )).scalars().all()

    return [
        AuditEventOut(
            id=str(r.id),
            action=r.action,
            target_type=r.target_type,
            target_id=str(r.target_id) if r.target_id else None,
            actor_id=str(r.actor_id) if r.actor_id else None,
            metadata=r.metadata_ or {},
            created_at=r.created_at,
        )
        for r in rows
    ]
