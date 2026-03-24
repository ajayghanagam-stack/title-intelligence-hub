import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.page import PageResponse
from app.micro_apps.title_intelligence.services.storage import StorageProvider, get_storage
from app.micro_apps.title_intelligence.services import page_service

router = APIRouter()


@router.get("/packs/{pack_id}/pages", response_model=list[PageResponse])
async def list_pages(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await page_service.list_pages(db, org_id, pack_id)


@router.get("/packs/{pack_id}/pages/{page_number}/image")
async def get_page_image(
    pack_id: uuid.UUID,
    page_number: int,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    data = await page_service.get_page_image_data_or_raise(db, org_id, pack_id, page_number, storage)
    return Response(content=data, media_type="image/jpeg")


@router.get("/packs/{pack_id}/pages/{page_number}/thumb")
async def get_page_thumb(
    pack_id: uuid.UUID,
    page_number: int,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    data = await page_service.get_page_thumb_data_or_raise(db, org_id, pack_id, page_number, storage)
    return Response(content=data, media_type="image/jpeg")
