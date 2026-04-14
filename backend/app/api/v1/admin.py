"""
Platform admin routes — only accessible by users with is_platform_admin=True.

The Logikality Admin uses these to:
  - Create customer accounts (org + owner user + subscriptions)
  - List all organizations
  - Manage micro apps (CRUD)
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_platform_admin
from app.models.user import User
from app.services import admin_service, billing_service
from app.services.billing_pdf_service import generate_billing_report_pdf

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Schemas ─────────────────────────────────────────────────────


class CreateAccountRequest(BaseModel):
    """Create a customer org with an owner user and optional app subscriptions."""
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=1, max_length=255)
    org_name: str = Field(min_length=1, max_length=255)
    org_slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    app_slugs: list[str] = []  # micro app slugs to subscribe to


class AccountResponse(BaseModel):
    org_id: str
    org_name: str
    org_slug: str
    user_id: str
    email: str
    full_name: str | None
    subscriptions: list[str]  # list of subscribed app slugs

    model_config = {"from_attributes": True}


class OrgListItem(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
    user_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AppCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    description: str | None = None
    icon: str | None = None


class AppUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    is_active: bool | None = None


class AppResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    icon: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountDetailSubscription(BaseModel):
    id: str
    app_id: str
    app_name: str
    app_slug: str
    status: str


class AccountDetail(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    users: list[dict]
    subscriptions: list[AccountDetailSubscription]


class ToggleSubscriptionRequest(BaseModel):
    app_id: str


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=6)


class UsageItem(BaseModel):
    name: str
    filenames: list[str] | None = None
    status: str
    created_at: str


class AppUsage(BaseModel):
    app_slug: str
    app_name: str
    completed_count: int
    total_count: int
    items: list[UsageItem] = []


class OrgUsageResponse(BaseModel):
    org_id: str
    org_name: str
    start_date: str
    end_date: str
    apps: list[AppUsage]


# ── Account management ──────────────────────────────────────────


@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    body: CreateAccountRequest,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a customer organization with an owner user and optional subscriptions."""
    result = await admin_service.create_account(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        org_name=body.org_name,
        org_slug=body.org_slug,
        app_slugs=body.app_slugs,
    )
    return AccountResponse(**result)


@router.get("/accounts", response_model=list[OrgListItem])
async def list_accounts(
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all organizations (excluding the platform admin's own org)."""
    items = await admin_service.list_accounts(db, exclude_org_id=admin.org_id)
    return [OrgListItem(**item) for item in items]


@router.get("/accounts/{org_id}", response_model=AccountDetail)
async def get_account(
    org_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a customer account with its users and subscriptions."""
    data = await admin_service.get_account(db, org_id)
    return AccountDetail(
        **{k: v for k, v in data.items() if k != "subscriptions"},
        subscriptions=[AccountDetailSubscription(**s) for s in data["subscriptions"]],
    )


@router.delete("/accounts/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    org_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a customer organization and all associated data."""
    await admin_service.delete_account(db, org_id)


@router.delete("/accounts/{org_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account_user(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user from a customer organization."""
    await admin_service.delete_account_user(db, org_id, user_id)


@router.post("/accounts/{org_id}/subscriptions", status_code=status.HTTP_201_CREATED)
async def add_subscription(
    org_id: uuid.UUID,
    body: ToggleSubscriptionRequest,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a micro app subscription to a customer org."""
    await admin_service.add_subscription(db, org_id, uuid.UUID(body.app_id))
    return {"detail": "Subscription added"}


@router.delete("/accounts/{org_id}/subscriptions/{sub_id}")
async def remove_subscription(
    org_id: uuid.UUID,
    sub_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove a micro app subscription from a customer org."""
    await admin_service.remove_subscription(db, org_id, sub_id)
    return {"detail": "Subscription removed"}


@router.patch("/accounts/{org_id}/users/{user_id}/password")
async def reset_user_password(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ResetPasswordRequest,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset a customer user's password."""
    await admin_service.reset_user_password(db, org_id, user_id, body.new_password)
    return {"detail": "Password reset successfully"}


# ── Micro app management ────────────────────────────────────────


@router.get("/apps", response_model=list[AppResponse])
async def list_apps(
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all micro apps."""
    apps = await admin_service.list_apps(db)
    return [
        AppResponse(
            id=str(a.id), name=a.name, slug=a.slug,
            description=a.description, icon=a.icon,
            is_active=a.is_active, created_at=a.created_at,
        )
        for a in apps
    ]


@router.post("/apps", response_model=AppResponse, status_code=status.HTTP_201_CREATED)
async def create_app(
    body: AppCreateRequest,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new micro app."""
    app = await admin_service.create_app(db, body.name, body.slug, body.description, body.icon)
    return AppResponse(
        id=str(app.id), name=app.name, slug=app.slug,
        description=app.description, icon=app.icon,
        is_active=app.is_active, created_at=app.created_at,
    )


@router.patch("/apps/{app_id}", response_model=AppResponse)
async def update_app(
    app_id: uuid.UUID,
    body: AppUpdateRequest,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a micro app."""
    app = await admin_service.update_app(db, app_id, body.model_dump(exclude_unset=True))
    return AppResponse(
        id=str(app.id), name=app.name, slug=app.slug,
        description=app.description, icon=app.icon,
        is_active=app.is_active, created_at=app.created_at,
    )


# ── Billing / Usage reports ────────────────────────────────────


def _default_start() -> date:
    """First day of the current month."""
    today = date.today()
    return today.replace(day=1)


@router.get("/billing/{org_id}", response_model=OrgUsageResponse)
async def get_billing(
    org_id: uuid.UUID,
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get usage data for a single organization within a date range."""
    if start_date is None:
        start_date = _default_start()
    if end_date is None:
        end_date = date.today()

    data = await billing_service.get_org_usage(db, org_id, start_date, end_date)
    return OrgUsageResponse(**data)


@router.get("/billing/{org_id}/pdf")
async def get_billing_pdf(
    org_id: uuid.UUID,
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Download a PDF usage report for a single organization."""
    if start_date is None:
        start_date = _default_start()
    if end_date is None:
        end_date = date.today()

    data = await billing_service.get_org_usage(db, org_id, start_date, end_date)
    pdf_bytes = generate_billing_report_pdf(
        org_name=data["org_name"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        apps_usage=data["apps"],
    )

    filename = f"usage_report_{data['org_name'].replace(' ', '_')}_{start_date}_{end_date}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
