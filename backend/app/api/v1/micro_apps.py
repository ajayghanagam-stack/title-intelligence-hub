from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.deps import get_db
from app.models.micro_app import MicroApp
from app.schemas.micro_app import MicroAppResponse

router = APIRouter(prefix="/micro-apps", tags=["micro-apps"])


@router.get("", response_model=list[MicroAppResponse])
async def list_micro_apps(
    auth_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MicroApp).where(MicroApp.is_active == True)
    )
    return list(result.scalars().all())
