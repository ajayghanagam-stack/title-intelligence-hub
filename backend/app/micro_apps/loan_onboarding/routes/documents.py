"""Routes exposing pages + stacks for a package.

These feed the Documents tab in the frontend (stack viewer with grouped
pages, classification labels, confidence chips).
"""
import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.services import package_service
from app.models.user import User
from app.services.storage import StorageProvider, get_storage

router = APIRouter()


@router.get("/packages/{package_id}/pages")
async def list_pages(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    await package_service.get_package_or_raise(db, org_id, package_id)
    pages = (await db.execute(
        select(LOPage)
        .where(LOPage.package_id == package_id, LOPage.org_id == org_id)
        .order_by(LOPage.page_number.asc())
    )).scalars().all()
    return [
        {
            "id": str(p.id),
            "page_number": p.page_number,
            "source_page_number": p.source_page_number,
            "text_length": p.text_length,
        }
        for p in pages
    ]


@router.get("/packages/{package_id}/pages/{page_id}/image")
async def get_page_image(
    package_id: uuid.UUID,
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Render a single PDF page as a JPEG on demand.

    LO ingest writes only metadata-only LOPage rows (no `image_path`), so the
    image is rendered from the source PDF via PyMuPDF on each request. Tenant
    isolation is enforced by filtering LOPage on both `org_id` and
    `package_id`.
    """
    page = (await db.execute(
        select(LOPage).where(
            LOPage.id == page_id,
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    file_row = (await db.execute(
        select(LOPackageFile).where(
            LOPackageFile.id == page.file_id,
            LOPackageFile.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not file_row:
        raise HTTPException(status_code=404, detail="Source file not found")

    pdf_bytes = await storage.get_object(file_row.storage_path)

    def _render() -> bytes:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            idx = max(0, min(page.source_page_number - 1, len(doc) - 1))
            pix = doc[idx].get_pixmap(dpi=100)
            return pix.tobytes("jpeg")
        finally:
            doc.close()

    jpeg = await asyncio.to_thread(_render)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/packages/{package_id}/stacks")
async def list_stacks(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return every stack with its classification info.

    Response shape matches the frontend Documents tab requirements —
    grouped list of {stack, pages_with_classification}.
    """
    await package_service.get_package_or_raise(db, org_id, package_id)
    stacks = (await db.execute(
        select(LOStack)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()
    classifications = (await db.execute(
        select(LOClassification).where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
        )
    )).scalars().all()
    clf_by_page = {c.page_number: c for c in classifications}

    # Include page_id per stack page so the Documents tab can call the
    # per-page override endpoint without a separate /pages lookup.
    pages = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id, LOPage.org_id == org_id
        )
    )).scalars().all()
    page_id_by_number = {p.page_number: p.id for p in pages}

    out = []
    for s in stacks:
        pages_payload = []
        for pn in s.page_numbers:
            c = clf_by_page.get(pn)
            pages_payload.append({
                "page_id": str(page_id_by_number[pn]) if pn in page_id_by_number else None,
                "page_number": pn,
                "predicted_doc_type": c.predicted_doc_type if c else None,
                "confidence": c.confidence if c else None,
                "page_role": c.page_role if c else None,
                "detected_fields": c.detected_fields if c else [],
            })
        out.append({
            "id": str(s.id),
            "stack_index": s.stack_index,
            "doc_type": s.doc_type,
            "first_page": s.first_page,
            "last_page": s.last_page,
            "page_count": len(s.page_numbers),
            "classification_confidence": s.classification_confidence,
            "overall_confidence": s.overall_confidence,
            "status": s.status,
            "requires_hitl": s.requires_hitl,
            "pages": pages_payload,
        })
    return out
