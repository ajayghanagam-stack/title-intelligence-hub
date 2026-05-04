"""FastAPI routes for Loan Onboarding packages.

All endpoints are tenant-scoped via `get_org_id` (set by TenantContextMiddleware).
"""
import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_member, get_db, get_org_id, get_session_factory
from app.core.exceptions import ValidationError
from app.micro_apps.loan_onboarding.pipeline.orchestrator import trigger_pipeline
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.schemas.package import (
    PackageCreate,
    PackageFileResponse,
    PackageListResponse,
    PackageResponse,
    PipelineStatusResponse,
)
from sqlalchemy import func, select
from app.micro_apps.loan_onboarding.services import file_service, package_service
from app.models.user import User
from app.services.audit_service import log_event
from app.services.storage import StorageProvider, get_storage

router = APIRouter()
logger = logging.getLogger(__name__)


async def _serialize_package(
    db: AsyncSession, org_id: uuid.UUID, package: LOPackage
) -> dict:
    """Build a PackageResponse payload with doc_types and hitl_count joined in."""
    config = await package_service.get_doc_type_config(db, org_id, package.id)
    doc_types = config.doc_types if config is not None else []
    hitl_count_result = await db.execute(
        select(func.count(LOStack.id)).where(
            LOStack.package_id == package.id,
            LOStack.org_id == org_id,
            LOStack.requires_hitl == True,  # noqa: E712
        )
    )
    hitl_count = hitl_count_result.scalar() or 0
    return {
        "id": package.id,
        "org_id": package.org_id,
        "created_by": package.created_by,
        "name": package.name,
        "borrower_name": package.borrower_name,
        "loan_reference": package.loan_reference,
        "hitl_threshold": package.hitl_threshold,
        "doc_types": doc_types,
        "status": package.status,
        "pipeline_stage": package.pipeline_stage,
        "pipeline_error": package.pipeline_error,
        "progress": package.progress,
        "hitl_count": hitl_count,
        "extraction_enabled": package.extraction_enabled,
        "extraction_fields_by_doc": package.extraction_fields_by_doc or {},
        "loan_context": package.loan_context or None,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
    }


@router.post("/packages", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    body: PackageCreate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    settings = get_settings()
    hitl = body.hitl_threshold if body.hitl_threshold is not None else settings.LO_HITL_THRESHOLD

    package = await package_service.create_package(
        db,
        org_id=org_id,
        created_by=member.id,
        name=body.name,
        doc_types=body.doc_types,
        validation_rules=body.validation_rules,
        borrower_name=body.borrower_name,
        loan_reference=body.loan_reference,
        hitl_threshold=hitl,
        extraction_enabled=body.extraction_enabled,
        extraction_fields_by_doc=body.extraction_fields_by_doc,
        loan_context=(
            body.loan_context.model_dump() if body.loan_context is not None else None
        ),
    )
    await log_event(
        db, org_id,
        action="lo_package_created",
        target_type="lo_package",
        target_id=package.id,
        actor_id=member.id,
        metadata={"name": package.name, "doc_type_count": len(body.doc_types)},
    )
    await db.commit()
    return await _serialize_package(db, org_id, package)


@router.get("/packages", response_model=list[PackageListResponse])
async def list_packages(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await package_service.list_packages(db, org_id, status=status_filter, page=page, size=size)


@router.get("/packages/{package_id}", response_model=PackageResponse)
async def get_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    package = await package_service.get_package_or_raise(db, org_id, package_id)
    return await _serialize_package(db, org_id, package)


@router.delete("/packages/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    # Allow the uploader to delete their own package; admins/owners can delete any.
    package = await package_service.get_package_or_raise(db, org_id, package_id)
    if member.role not in ("admin", "owner") and package.created_by != member.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete packages you uploaded",
        )
    await package_service.delete_package(db, org_id, package_id)
    # delete_package commits on its own; emit audit event in a fresh txn
    await log_event(
        db, org_id,
        action="lo_package_deleted",
        target_type="lo_package",
        target_id=package_id,
        actor_id=member.id,
    )
    await db.commit()


@router.post(
    "/packages/{package_id}/files",
    response_model=list[PackageFileResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_files(
    package_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    settings = get_settings()
    t_handler_entered = time.perf_counter()
    package = await package_service.get_package_or_raise(db, org_id, package_id)
    max_size = settings.LO_FILE_UPLOAD_MAX_SIZE
    logger.info(
        "lo_upload: handler entered package_id=%s file_count=%d (parsing already complete by this point)",
        package_id, len(files),
    )

    saved = []
    for upload in files:
        t0 = time.perf_counter()
        data = await upload.read()
        t_read = time.perf_counter() - t0
        size_mb = len(data) / 1024 / 1024
        if len(data) > max_size:
            raise ValidationError(
                f"File '{upload.filename}' exceeds max size of {max_size} bytes"
            )
        t1 = time.perf_counter()
        row = await file_service.store_uploaded_file(
            db,
            storage,
            org_id=org_id,
            package_id=package.id,
            filename=upload.filename,
            content=data,
            content_type=upload.content_type,
        )
        t_store = time.perf_counter() - t1
        logger.info(
            "lo_upload: file=%s size=%.1fMB read=%.2fs store=%.2fs (sha256+disk+pdf+db)",
            upload.filename, size_mb, t_read, t_store,
        )
        saved.append(row)

    t2 = time.perf_counter()
    await log_event(
        db, org_id,
        action="lo_files_uploaded",
        target_type="lo_package",
        target_id=package_id,
        actor_id=member.id,
        metadata={"file_count": len(saved), "filenames": [f.filename for f in saved]},
    )
    await db.commit()
    logger.info(
        "lo_upload: audit+commit=%.2fs total_handler=%.2fs",
        time.perf_counter() - t2, time.perf_counter() - t_handler_entered,
    )
    return saved


@router.post("/packages/{package_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def process_package(
    package_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Trigger the Loan Onboarding pipeline (ingest → classify → stack → validate → review)."""
    package = await package_service.get_package_or_raise(db, org_id, package_id)

    if package.status not in ("uploading", "failed"):
        raise ValidationError(
            f"Package cannot be processed from status '{package.status}'"
        )

    await package_service.mark_pipeline_status(
        db, org_id, package_id,
        status="processing",
        pipeline_stage="ingest",
        pipeline_error=None,
        progress={"stage": "ingest", "processed": 0, "total": 0, "hitl_count": 0},
    )

    await log_event(
        db, org_id,
        action="lo_pipeline_started",
        target_type="lo_package",
        target_id=package_id,
        actor_id=member.id,
    )
    await db.commit()

    session_factory = get_session_factory()
    storage = get_storage()
    await trigger_pipeline(
        package_id, org_id, session_factory, storage,
        background_tasks=background_tasks,
    )
    return {"message": "Processing queued", "package_id": str(package_id)}


PIPELINE_STAGE_ORDER = ("ingest", "classify", "stack", "validate", "review")


def _derive_stage_states(package: LOPackage) -> list[dict]:
    """Build a per-stage {stage, status} list from LOPackage state.

    Drives the frontend pipeline-progress UI. Rules:
      - Stages present in progress.stage_timings are "completed"
      - The stage matching package.pipeline_stage is "running" while status="processing"
      - If package.status == "failed", the current pipeline_stage is "failed"
      - If package.status in ("completed", "awaiting_review"), all stages are "completed"
      - Everything else is "pending"
    """
    progress = package.progress or {}
    timings = progress.get("stage_timings") or {}
    current = package.pipeline_stage
    pkg_status = package.status

    out: list[dict] = []
    for stage in PIPELINE_STAGE_ORDER:
        if pkg_status in ("completed", "awaiting_review"):
            status = "completed"
        elif stage in timings:
            status = "completed"
        elif stage == current and pkg_status == "processing":
            status = "running"
        elif stage == current and pkg_status == "failed":
            status = "failed"
        else:
            status = "pending"
        out.append({"stage": stage, "status": status})
    return out


def _derive_stage_timings(package: LOPackage) -> list[dict]:
    progress = package.progress or {}
    timings = progress.get("stage_timings") or {}
    return [
        {
            "stage": stage,
            "elapsed_seconds": float(elapsed) if elapsed is not None else None,
            "started_at": None,
            "completed_at": None,
        }
        for stage, elapsed in timings.items()
    ]


def _safe_filename_stem(value: str | None, fallback: str) -> str:
    """Strip path separators and collapse whitespace for a download filename."""
    if not value:
        return fallback
    cleaned = "".join(c for c in value if c not in '/\\?%*:|"<>')
    cleaned = "-".join(cleaned.split())
    return (cleaned[:80] or fallback)


@router.get("/packages/{package_id}/final-packet.pdf")
async def download_final_packet(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Stream the reorganized final packet as a downloadable PDF.

    Pages are emitted in `stack_index` order using current `lo_stacks` /
    `lo_pages` state — so any reviewer "Move to…" overrides are reflected
    immediately. Top-level bookmarks label each stack with its doc-type and
    page span. The PDF is regenerated on every request because the operation
    is cheap (PyMuPDF page copy, no re-rastering) and avoids stale-cache
    bugs after overrides.
    """
    from app.micro_apps.loan_onboarding.services.final_packet import (
        build_final_packet_pdf,
    )

    package = await package_service.get_package_or_raise(db, org_id, package_id)
    pdf_bytes = await build_final_packet_pdf(db, org_id, package_id, storage)
    stem = _safe_filename_stem(
        package.loan_reference or package.name, fallback=str(package.id)
    )
    filename = f"{stem}-final-packet.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/packages/{package_id}/per-stack.zip")
async def download_per_stack_zip(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Stream one PDF per stack bundled in a ZIP archive.

    Mirrors the same `lo_stacks` ordering as the final-packet PDF, so
    reviewer "Move to…" overrides are reflected immediately. Filenames are
    zero-padded by stack_index so the archive sorts naturally.
    """
    from app.micro_apps.loan_onboarding.services.final_packet import (
        build_per_stack_zip,
    )

    package = await package_service.get_package_or_raise(db, org_id, package_id)
    zip_bytes = await build_per_stack_zip(db, org_id, package_id, storage)
    stem = _safe_filename_stem(
        package.loan_reference or package.name, fallback=str(package.id)
    )
    filename = f"{stem}-per-stack.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/packages/{package_id}/pipeline", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    package = await package_service.get_package_or_raise(db, org_id, package_id)
    progress = package.progress or {}
    return PipelineStatusResponse(
        package_id=package.id,
        status=package.status,
        pipeline_stage=package.pipeline_stage,
        pipeline_error=package.pipeline_error,
        progress=package.progress,
        stages=_derive_stage_states(package),
        stage_timings=_derive_stage_timings(package),
        processed=int(progress.get("processed") or 0),
        total=int(progress.get("total") or 0),
        hitl_count=int(progress.get("hitl_count") or 0),
    )
