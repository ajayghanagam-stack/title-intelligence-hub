import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_platform_admin
from app.models.user import User
from app.micro_apps.title_search.schemas.county_source import (
    CountySourceCreate,
    CountySourceUpdate,
    CountySourceResponse,
)
from app.micro_apps.title_search.services import source_service

router = APIRouter(prefix="/admin/county-sources", tags=["title-search-admin"])


@router.post("", response_model=CountySourceResponse, status_code=status.HTTP_201_CREATED)
async def create_county_source(
    body: CountySourceCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_platform_admin),
):
    return await source_service.create_county_source(
        db,
        county=body.county,
        state_code=body.state_code,
        source_type=body.source_type,
        availability=body.availability,
        portal_url=body.portal_url,
        portal_type=body.portal_type,
        search_config=body.search_config,
        is_active=body.is_active,
    )


@router.get("", response_model=list[CountySourceResponse])
async def list_county_sources(
    state_code: str | None = Query(None),
    source_type: str | None = Query(None),
    availability: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_platform_admin),
):
    return await source_service.list_county_sources(
        db, state_code=state_code, source_type=source_type, availability=availability
    )


@router.patch("/{source_id}", response_model=CountySourceResponse)
async def update_county_source(
    source_id: uuid.UUID,
    body: CountySourceUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_platform_admin),
):
    updates = body.model_dump(exclude_unset=True)
    return await source_service.update_county_source(db, source_id, **updates)
