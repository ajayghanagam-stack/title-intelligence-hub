"""Parallel ``/loans/*`` route prefix — Phase 4 Batch 4.1.

Read-only ``/loans/{loan_id}/*`` aliases that delegate into the existing
``/packages/{package_id}/*`` handlers. This is the LogikIntake naming the
PRD §3.2 / §6.4 settled on ("Loan File", "Documents", "Validations") and is
what the Phase-5 frontend will consume.

During Phase 4 both prefixes stay live so the existing frontend keeps
working unchanged. The legacy ``/packages/*`` paths will be deprecated /
redirected once Phase 5 ports the UI fully to ``/loans/*``.

These aliases are pure delegations — zero new business logic. Tenant
scoping, per-user visibility, and response shape come from the underlying
handlers verbatim.
"""
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id, require_admin
from app.micro_apps.loan_onboarding.routes import documents as _documents
from app.micro_apps.loan_onboarding.routes import hard_stop_overrides as _hard_stops
from app.micro_apps.loan_onboarding.routes import packages as _packages
from app.micro_apps.loan_onboarding.routes import remediation as _remediation
from app.micro_apps.loan_onboarding.routes import validation as _validation
from app.micro_apps.loan_onboarding.schemas.hard_stop_override import (
    HardStopOverrideCreate,
    HardStopOverrideResponse,
)
from app.micro_apps.loan_onboarding.schemas.package import (
    PackageCreate,
    PackageFileResponse,
    PackageListResponse,
    PackageResponse,
    PipelineStatusResponse,
)
from app.models.user import User
from app.services.storage import StorageProvider, get_storage

router = APIRouter()


@router.get("/loans", response_model=list[PackageListResponse])
async def list_loans(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await _packages.list_packages(
        status_filter=status_filter,
        page=page,
        size=size,
        db=db,
        member=member,
        org_id=org_id,
    )


@router.get("/loans/{loan_id}", response_model=PackageResponse)
async def get_loan(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await _packages.get_package(
        package_id=loan_id, db=db, member=member, org_id=org_id,
    )


@router.get("/loans/{loan_id}/pipeline", response_model=PipelineStatusResponse)
async def get_loan_pipeline(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await _packages.get_pipeline_status(
        package_id=loan_id, db=db, member=member, org_id=org_id,
    )


@router.get("/loans/{loan_id}/pages")
async def list_loan_pages(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await _documents.list_pages(
        package_id=loan_id, db=db, member=member, org_id=org_id,
    )


@router.get("/loans/{loan_id}/documents")
async def list_loan_documents(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Alias for ``/packages/{id}/stacks`` — LogikIntake calls a stack a
    "document" so the operator-facing surface uses that label."""
    return await _documents.list_stacks(
        package_id=loan_id, db=db, member=member, org_id=org_id,
    )


@router.get("/loans/{loan_id}/validations")
async def list_loan_validations(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Alias for ``/packages/{id}/validation-results`` — operator UI calls
    these "validations" (PRD §6.4 Doc/Data Validation tabs)."""
    return await _validation.list_validation_results(
        package_id=loan_id, db=db, member=member, org_id=org_id,
    )


# ── Phase 4 Batch 4.2 — mutation aliases ──────────────────────────────
# Same delegation pattern as the read aliases above. No new business logic.


@router.post(
    "/loans",
    response_model=PackageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_loan(
    body: PackageCreate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await _packages.create_package(
        body=body, db=db, member=member, org_id=org_id,
    )


@router.delete(
    "/loans/{loan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_loan(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await _packages.delete_package(
        package_id=loan_id, db=db, member=member, org_id=org_id,
    )


@router.post(
    "/loans/{loan_id}/files",
    response_model=list[PackageFileResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_loan_files(
    loan_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    return await _packages.upload_files(
        package_id=loan_id,
        files=files,
        db=db,
        member=member,
        org_id=org_id,
        storage=storage,
    )


@router.post(
    "/loans/{loan_id}/process",
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_loan(
    loan_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await _packages.process_package(
        package_id=loan_id,
        background_tasks=background_tasks,
        db=db,
        member=member,
        org_id=org_id,
    )


@router.get("/loans/{loan_id}/final-packet.pdf")
async def download_loan_final_packet(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    return await _packages.download_final_packet(
        package_id=loan_id,
        db=db,
        member=member,
        org_id=org_id,
        storage=storage,
    )


@router.get("/loans/{loan_id}/per-stack.zip")
async def download_loan_per_stack_zip(
    loan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    return await _packages.download_per_stack_zip(
        package_id=loan_id,
        db=db,
        member=member,
        org_id=org_id,
        storage=storage,
    )


@router.post(
    "/loans/{loan_id}/remediate-missing-doc",
    status_code=status.HTTP_202_ACCEPTED,
)
async def remediate_loan_missing_doc(
    loan_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    return await _remediation.remediate_missing_doc(
        package_id=loan_id,
        background_tasks=background_tasks,
        file=file,
        db=db,
        member=member,
        org_id=org_id,
        storage=storage,
    )


@router.post(
    "/loans/{loan_id}/remediate-missing-pages",
    status_code=status.HTTP_202_ACCEPTED,
)
async def remediate_loan_missing_pages(
    loan_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    target_stack_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    return await _remediation.remediate_missing_pages(
        package_id=loan_id,
        background_tasks=background_tasks,
        target_stack_id=target_stack_id,
        file=file,
        db=db,
        member=member,
        org_id=org_id,
        storage=storage,
    )


@router.post(
    "/loans/{loan_id}/hard-stops/{hard_stop_key}/override",
    response_model=HardStopOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_loan_hard_stop_override(
    loan_id: uuid.UUID,
    hard_stop_key: str,
    payload: HardStopOverrideCreate,
    org_id: uuid.UUID = Depends(get_org_id),
    member: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _hard_stops.create_hard_stop_override(
        package_id=loan_id,
        hard_stop_key=hard_stop_key,
        payload=payload,
        org_id=org_id,
        member=member,
        db=db,
    )


@router.get(
    "/loans/{loan_id}/hard-stops/overrides",
    response_model=list[HardStopOverrideResponse],
)
async def list_loan_hard_stop_overrides(
    loan_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_org_id),
    db: AsyncSession = Depends(get_db),
):
    return await _hard_stops.list_hard_stop_overrides(
        package_id=loan_id, org_id=org_id, db=db,
    )
