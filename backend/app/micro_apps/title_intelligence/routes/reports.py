"""Report generation and download routes."""

import uuid
import json
import re

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.services.report_service import generate_report_pdf, get_report_by_uri_or_raise
from app.micro_apps.title_intelligence.services.storage import StorageProvider, get_storage
from app.services.audit_service import log_event

router = APIRouter()


def sanitize_filename(name: str) -> str:
    """Remove invalid characters from filename."""
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Limit length
    return sanitized[:100]


@router.post("/packs/{pack_id}/reports/download")
async def download_report(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Generate or retrieve cached PDF report and return as download."""
    pdf_bytes = await generate_report_pdf(db, org_id, pack_id, storage)
    
    # Get property address for filename
    filename = "title_intelligence_report.pdf"
    try:
        result = await db.execute(
            select(Extraction.value)
            .where(
                Extraction.pack_id == pack_id,
                Extraction.label.in_(["Insured Property", "Subject Property"])
            )
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            data = json.loads(row) if isinstance(row, str) else row
            if isinstance(data, dict):
                address = data.get("address")
                if address and address != "Not specified":
                    filename = f"{sanitize_filename(address)}_Report.pdf"
    except Exception:
        pass  # Fall back to default filename
    
    await log_event(
        db, org_id,
        action="report_downloaded",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
        metadata={"format": "pdf"},
    )
    await db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/packs/{pack_id}/reports")
async def get_report_by_uri(
    pack_id: uuid.UUID,
    uri: str = Query(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Download a previously generated report by its storage URI."""
    data = await get_report_by_uri_or_raise(org_id, pack_id, uri, storage)

    if uri.endswith(".pdf"):
        media_type = "application/pdf"
    elif uri.endswith(".json"):
        media_type = "application/json"
    else:
        media_type = "text/plain"

    filename = uri.split("/")[-1]
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
