import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_search.schemas.document import (
    DocumentResponse,
    DocumentUpdate,
    DOC_TYPE_LABELS,
)
from app.micro_apps.title_search.services import document_service
from app.services.audit_service import log_event

router = APIRouter()


@router.get("/orders/{order_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    order_id: uuid.UUID,
    doc_type: str | None = Query(None),
    needs_review: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await document_service.list_documents(
        db, org_id, order_id, doc_type=doc_type, needs_review=needs_review
    )


@router.get("/orders/{order_id}/documents/{doc_id}/download")
async def download_document(
    order_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    doc = await document_service.get_document_or_raise(db, org_id, order_id, doc_id)
    data = DocumentResponse.model_validate(doc).model_dump(mode="json")

    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError("fpdf2 is required for PDF generation")

    doc_type_label = DOC_TYPE_LABELS.get(data["doc_type"], data["doc_type"])

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Document: {doc_type_label}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)

    # Recording info
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Recording Information", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Type: {doc_type_label}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Recording Ref: {data.get('recording_ref') or 'N/A'}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Recording Date: {data.get('recording_date') or 'N/A'}", new_x="LMARGIN", new_y="NEXT")
    if data.get("confidence") is not None:
        pdf.cell(0, 6, f"Confidence: {round(data['confidence'] * 100)}%", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Parties
    grantor = data.get("grantor")
    grantee = data.get("grantee")
    if grantor or grantee:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Parties", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if grantor and grantor.get("names"):
            pdf.cell(0, 6, f"Grantor: {', '.join(grantor['names'])}", new_x="LMARGIN", new_y="NEXT")
        if grantee and grantee.get("names"):
            pdf.cell(0, 6, f"Grantee: {', '.join(grantee['names'])}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    # Financial
    if data.get("consideration"):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Financial", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Consideration: ${data['consideration']:,.2f}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    # Legal description
    if data.get("legal_description"):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Legal Description", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, data["legal_description"], new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    # Summary
    if data.get("summary"):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, data["summary"], new_x="LMARGIN", new_y="NEXT")

    pdf_bytes = bytes(pdf.output())
    filename = f"{data['doc_type']}_{data.get('recording_ref') or str(doc_id)[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/orders/{order_id}/documents/{doc_id}", response_model=DocumentResponse)
async def correct_document(
    order_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    updates = body.model_dump(exclude_unset=True)
    doc = await document_service.correct_document(
        db, org_id, order_id, doc_id, member.id, updates
    )
    await log_event(
        db, org_id,
        action="document_corrected",
        target_type="ta_document",
        target_id=doc_id,
        actor_id=member.id,
        metadata={"order_id": str(order_id)},
    )
    await db.commit()
    return doc
