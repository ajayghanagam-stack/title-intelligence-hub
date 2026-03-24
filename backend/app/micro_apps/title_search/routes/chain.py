import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id
from app.models.user import User
from app.micro_apps.title_search.schemas.chain import ChainResponse
from app.micro_apps.title_search.services import chain_service

router = APIRouter()


@router.get("/orders/{order_id}/chain", response_model=ChainResponse)
async def get_chain(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await chain_service.get_chain(db, org_id, order_id)
