"""Compliance routes — persona-aware compliance engine.

Endpoints:
  GET    /packages/{package_id}/compliance           — latest run (auto-evaluate
                                                       if none exists)
  POST   /packages/{package_id}/compliance/evaluate  — force a fresh run
  PATCH  /packages/{package_id}/compliance/context   — update loan context
  GET    /packages/{package_id}/compliance/report.pdf — downloadable PDF

All routes are tenant-scoped via `org_id` injected from `X-Org-Id`. The
service layer enforces FK + org filters on every query.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.core.exceptions import NotFoundError, ValidationError
from app.micro_apps.loan_onboarding.schemas.compliance import (
    ComplianceRunOut,
    LoanContextIn,
    LoanContextOut,
)
from app.micro_apps.loan_onboarding.services import (
    compliance_service,
    package_service,
)
from app.models.user import User

router = APIRouter()


@router.get(
    "/packages/{package_id}/compliance",
    response_model=ComplianceRunOut,
)
async def get_compliance(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return the most recent compliance run, evaluating once if absent."""
    try:
        return await compliance_service.get_or_evaluate(db, org_id, package_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/packages/{package_id}/compliance/evaluate",
    response_model=ComplianceRunOut,
)
async def evaluate_compliance(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Force a fresh evaluation; persists and returns the new run.

    Returns the full `evaluate()` payload (includes live-state projections —
    regulations + doc_checks + package identity) rather than re-rendering
    from the stored snapshot, so the frontend gets the same shape it gets
    from `GET /compliance`.
    """
    try:
        _, payload = await compliance_service.evaluate(
            db, org_id, package_id, persist=True
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return payload


@router.patch(
    "/packages/{package_id}/compliance/context",
    response_model=LoanContextOut,
)
async def update_loan_context(
    package_id: uuid.UUID,
    body: LoanContextIn,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Update the loan context. Closed-set enums are validated server-side."""
    try:
        pkg = await compliance_service.update_loan_context(
            db, org_id, package_id, body.model_dump()
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Echo the persisted snapshot — keeps the client and server in sync.
    return pkg.loan_context or {}


@router.get("/packages/{package_id}/compliance/report.pdf")
async def download_compliance_report(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Render the compliance report as a downloadable PDF.

    Always evaluates fresh (no caching) — the PDF is small and the rule engine
    is pure-Python; spending the few ms to recompute keeps the file aligned
    with the package's current loan-context + stack inventory.
    """
    try:
        pkg = await package_service.get_package_or_raise(db, org_id, package_id)
        run, payload = await compliance_service.evaluate(
            db, org_id, package_id, persist=True
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Lazy import to keep route module light + avoid fpdf2 import at app boot.
    from app.micro_apps.loan_onboarding.services.compliance_pdf import (
        build_compliance_report_pdf,
    )

    pdf_bytes = build_compliance_report_pdf(
        package_name=pkg.name,
        borrower_name=pkg.borrower_name,
        loan_reference=pkg.loan_reference,
        loan_context=pkg.loan_context or {},
        findings=payload["findings"],
        summary=payload["summary"],
        rules_version=payload["rules_version"],
        rule_set_hash=payload["rule_set_hash"],
    )
    filename = f"compliance-{pkg.loan_reference or pkg.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
