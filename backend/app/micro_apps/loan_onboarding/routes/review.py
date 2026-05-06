"""HITL review queue + decision persistence.

Routes:
- GET  /packages/{pid}/review-queue — list stacks flagged for human review
- POST /packages/{pid}/stacks/{sid}/review — record accept/reject/reclassify

Decisions:
- accept     → stack.status="accepted", requires_hitl=False
- reject     → stack.status="rejected", requires_hitl remains True (still open)
- reclassify → stack.status="accepted", doc_type swapped to corrected_doc_type

Once every HITL stack in a package has a decision AND no rejected stacks
remain open, the package auto-transitions: awaiting_review → completed.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.core.exceptions import NotFoundError, ValidationError
from app.micro_apps.loan_onboarding.models.hitl_review import LOHITLReview
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from app.micro_apps.loan_onboarding.schemas.review import (
    HITLDecision,
    HITLReviewResponse,
    ReviewQueueItem,
)
from app.micro_apps.loan_onboarding.services import package_service
from app.models.user import User
from app.services.audit_service import log_event

router = APIRouter()


@router.get("/packages/{package_id}/review-queue", response_model=list[ReviewQueueItem])
async def list_review_queue(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return every stack that needs human review, with rule-pass stats."""
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)

    stacks = (await db.execute(
        select(LOStack)
        .where(
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
            LOStack.requires_hitl == True,  # noqa: E712
        )
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()

    validation_rows = (await db.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == package_id,
            LOValidationResult.org_id == org_id,
        )
    )).scalars().all()
    val_by_stack = {v.stack_id: v for v in validation_rows}

    items: list[ReviewQueueItem] = []
    for s in stacks:
        val = val_by_stack.get(s.id)
        rules_total = len(val.rules_evaluated) if val else 0
        rules_failed = sum(
            1 for r in (val.rules_evaluated if val else [])
            if isinstance(r, dict) and not r.get("passed")
        )
        items.append(ReviewQueueItem(
            stack_id=s.id,
            doc_type=s.doc_type,
            first_page=s.first_page,
            last_page=s.last_page,
            page_count=len(s.page_numbers),
            classification_confidence=s.classification_confidence,
            overall_confidence=s.overall_confidence or s.classification_confidence,
            rules_failed=rules_failed,
            rules_total=rules_total,
        ))
    return items


@router.post(
    "/packages/{package_id}/stacks/{stack_id}/review",
    response_model=HITLReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_review_decision(
    package_id: uuid.UUID,
    stack_id: uuid.UUID,
    body: HITLDecision,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Record a human decision on a stack and update stack/package status."""
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == stack_id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise NotFoundError("LoanStack", stack_id)

    if body.decision == "reclassify" and not body.corrected_doc_type:
        raise ValidationError("corrected_doc_type is required when decision=reclassify")

    review = LOHITLReview(
        org_id=org_id,
        package_id=package_id,
        stack_id=stack_id,
        reviewer_id=member.id,
        decision=body.decision,
        corrected_doc_type=body.corrected_doc_type,
        notes=body.notes,
    )
    db.add(review)

    # Apply decision to the stack
    if body.decision == "accept":
        stack.status = "accepted"
        stack.requires_hitl = False
    elif body.decision == "reject":
        stack.status = "rejected"
        # Rejected stacks stay requires_hitl=True until the user takes a
        # follow-up action (re-upload, delete). This keeps them visible in
        # the queue so nothing falls through.
        stack.requires_hitl = True
    elif body.decision == "reclassify":
        stack.status = "accepted"
        stack.doc_type = body.corrected_doc_type
        stack.requires_hitl = False

    # Auto-advance package status if no stacks are still pending review.
    remaining_hitl = (await db.execute(
        select(LOStack).where(
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
            LOStack.requires_hitl == True,  # noqa: E712
        )
    )).scalars().all()
    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == package_id, LOPackage.org_id == org_id
        )
    )).scalar_one()
    if not remaining_hitl and pkg.status == "awaiting_review":
        pkg.status = "completed"

    await log_event(
        db, org_id,
        action="lo_hitl_review_submitted",
        target_type="lo_stack",
        target_id=stack_id,
        actor_id=member.id,
        metadata={
            "decision": body.decision,
            "corrected_doc_type": body.corrected_doc_type,
        },
    )
    await db.commit()
    await db.refresh(review)
    return review


@router.get(
    "/packages/{package_id}/stacks/{stack_id}/reviews",
    response_model=list[HITLReviewResponse],
)
async def list_reviews_for_stack(
    package_id: uuid.UUID,
    stack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    reviews = (await db.execute(
        select(LOHITLReview)
        .where(
            LOHITLReview.package_id == package_id,
            LOHITLReview.stack_id == stack_id,
            LOHITLReview.org_id == org_id,
        )
        .order_by(LOHITLReview.created_at.desc())
    )).scalars().all()
    return reviews
