import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.deps import get_db, get_org_id, require_admin, require_owner, get_current_member, require_platform_admin
from app.core.exceptions import NotFoundError
from app.models.user import User
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationPublicResponse,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.schemas.user import UserInvite, UserResponse, UserUpdate, InviteResponse
from app.services import organization_service, user_service

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/by-slug/{slug}", response_model=OrganizationPublicResponse)
async def get_org_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — no auth required. Returns basic org info for branded login pages."""
    org = await organization_service.get_organization_by_slug(db, slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    data: OrganizationCreate,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Only the platform admin can create organizations."""
    org = await organization_service.create_organization(
        db, data, admin.auth_user_id, admin.email
    )
    return org


@router.get("/me", response_model=list[OrganizationResponse])
async def list_my_orgs(
    auth_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await organization_service.get_user_orgs(db, auth_user.auth_user_id)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_org(
    org_id: uuid.UUID,
    member: User = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    org = await organization_service.get_organization(db, org_id)
    if org is None:
        raise NotFoundError("Organization", org_id)
    return org


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_org(
    org_id: uuid.UUID,
    data: OrganizationUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    org = await organization_service.update_organization(db, org_id, data)
    if org is None:
        raise NotFoundError("Organization", org_id)
    return org


@router.get("/{org_id}/users", response_model=list[UserResponse])
async def list_users(
    org_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await organization_service.list_org_users(db, org_id)


@router.post(
    "/{org_id}/users/invite",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_user(
    org_id: uuid.UUID,
    data: UserInvite,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user, temp_password = await user_service.invite_user(db, org_id, data)
    user_data = UserResponse.model_validate(user, from_attributes=True).model_dump()
    user_data["temporary_password"] = temp_password
    return InviteResponse(**user_data)


@router.delete("/{org_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        deleted = await user_service.delete_user(
            db, user_id, org_id, requesting_user_id=admin.id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not deleted:
        raise NotFoundError("User", user_id)


@router.patch("/{org_id}/users/{user_id}", response_model=UserResponse)
async def update_user(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: UserUpdate,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    user = await user_service.update_user(db, user_id, data)
    if user is None:
        raise NotFoundError("User", user_id)
    return user
