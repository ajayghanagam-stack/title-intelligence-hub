"""Report generation and download routes."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.report import ReportRequest, ReportResponse
from app.micro_apps.title_intelligence.services.report_service import generate_report, get_report_by_uri_or_raise
from app.micro_apps.title_intelligence.services.storage import StorageProvider, get_storage
from app.services.audit_service import log_event

router = APIRouter()


@router.post("/packs/{pack_id}/reports", response_model=ReportResponse)
async def create_report(
    pack_id: uuid.UUID,
    body: ReportRequest,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    result = await generate_report(
        db, org_id, pack_id, body.audience, body.format, storage=storage
    )
    await log_event(
        db, org_id,
        action="report_generated",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
        metadata={"audience": body.audience, "format": body.format},
    )
    await db.commit()
    return ReportResponse(
        audience=body.audience,
        format=body.format,
        content=result["content"],
        uri=result.get("uri"),
    )


@router.post("/packs/{pack_id}/reports/download")
async def download_report(
    pack_id: uuid.UUID,
    body: ReportRequest,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    result = await generate_report(
        db, org_id, pack_id, body.audience, body.format, storage=storage
    )
    await log_event(
        db, org_id,
        action="report_downloaded",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
        metadata={"audience": body.audience, "format": body.format},
    )
    await db.commit()

    if body.format == "pdf":
        # If PDF was stored, read it back; otherwise use in-memory bytes
        if result.get("uri"):
            pdf_data = await storage.read(result["uri"])
        elif "_pdf_bytes" in result:
            pdf_data = result["_pdf_bytes"]
        else:
            pdf_data = result["content"].encode("utf-8")

        filename = f"report_{body.audience}.pdf"
        return Response(
            content=pdf_data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    elif body.format == "json":
        filename = f"report_{body.audience}.json"
        return Response(
            content=result["content"].encode("utf-8"),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    else:
        ext = "md" if body.format == "markdown" else "txt"
        filename = f"report_{body.audience}.{ext}"
        return Response(
            content=result["content"].encode("utf-8"),
            media_type="text/plain; charset=utf-8",
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
