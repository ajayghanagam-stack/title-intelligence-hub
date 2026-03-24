import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_search.schemas.package import PackageResponse
from app.micro_apps.title_search.services import package_service
from app.services.audit_service import log_event

router = APIRouter()


@router.get("/orders/{order_id}/package", response_model=PackageResponse)
async def get_package(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await package_service.get_package_or_raise(db, org_id, order_id)


@router.get("/orders/{order_id}/package/pdf")
async def download_package_pdf(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    pdf_bytes = await package_service.generate_package_pdf(db, org_id, order_id)
    pkg = await package_service.get_package_or_raise(db, org_id, order_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pkg.package_number}.pdf"'
        },
    )


@router.post(
    "/orders/{order_id}/package/issue",
    response_model=PackageResponse,
)
async def issue_package(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    pkg = await package_service.issue_package(db, org_id, order_id, member.id)
    await log_event(
        db, org_id,
        action="package_issued",
        target_type="ta_package",
        target_id=pkg.id,
        actor_id=member.id,
        metadata={"order_id": str(order_id), "package_number": pkg.package_number},
    )
    await db.commit()
    return pkg
