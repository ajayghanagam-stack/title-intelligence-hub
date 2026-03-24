import hashlib
import uuid

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File, BackgroundTasks, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.core.deps import get_db, get_current_member, get_org_id, require_admin, get_session_factory
from app.models.user import User
from app.micro_apps.title_intelligence.schemas.pack import (
    PackCreate,
    PackResponse,
    PackListResponse,
    PipelineStatusResponse,
)
from app.micro_apps.title_intelligence.services import pack_service, pipeline_service
from app.micro_apps.title_intelligence.services.storage import StorageProvider, get_storage
from app.micro_apps.title_intelligence.pipeline.orchestrator import trigger_pipeline
from app.services.audit_service import log_event

router = APIRouter()


@router.post("/packs", response_model=PackResponse, status_code=status.HTTP_201_CREATED)
async def create_pack(
    body: PackCreate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    pack = await pack_service.create_pack(db, org_id, body.name)
    await log_event(
        db, org_id,
        action="pack_created",
        target_type="ti_pack",
        target_id=pack.id,
        actor_id=member.id,
    )
    await db.commit()
    return pack


@router.get("/packs", response_model=list[PackListResponse])
async def list_packs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await pack_service.list_packs(db, org_id, limit=limit, offset=offset)


@router.get("/packs/{pack_id}", response_model=PackResponse)
async def get_pack(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await pack_service.get_pack_or_raise(db, org_id, pack_id)


@router.delete("/packs/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pack(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(require_admin),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    await pack_service.delete_pack_or_raise(db, org_id, pack_id, storage)
    await log_event(
        db, org_id,
        action="pack_deleted",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
    )
    await db.commit()


@router.post("/packs/{pack_id}/files", response_model=PackResponse)
async def upload_files(
    pack_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    settings = get_settings()
    pack = await pack_service.get_pack_or_raise(db, org_id, pack_id)

    for upload in files:
        data = await upload.read()
        pack_service.validate_pdf_upload(upload.filename, data, settings.FILE_UPLOAD_MAX_SIZE)

        rel_path = storage.make_pack_path(org_id, pack_id, upload.filename)
        await storage.save(rel_path, data)

        content_hash = hashlib.sha256(data).hexdigest()
        await pack_service.add_file(
            db, org_id, pack_id, upload.filename, rel_path, len(data),
            content_hash=content_hash,
        )

    await log_event(
        db, org_id,
        action="files_uploaded",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
        metadata={"file_count": len(files), "filenames": [f.filename for f in files]},
    )
    # Re-fetch with files loaded for PackResponse serialization
    return await pack_service.get_pack_or_raise(db, org_id, pack_id)


@router.post("/packs/{pack_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def trigger_process(
    pack_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    pack = await pack_service.require_pack_for_processing(db, org_id, pack_id)

    # Set status to processing immediately so the frontend can start polling
    # before the background pipeline begins its first stage
    pack.status = "processing"
    # Clear stale readiness data from any previous run so the frontend
    # doesn't show outdated scores/summary while pipeline is running
    pack.readiness_score = None
    pack.readiness_summary = None
    pack.error_message = None

    await log_event(
        db, org_id,
        action="pipeline_started",
        target_type="ti_pack",
        target_id=pack_id,
        actor_id=member.id,
    )
    await db.commit()

    session_factory = get_session_factory()
    storage = get_storage()

    await trigger_pipeline(pack_id, org_id, session_factory, storage, background_tasks=background_tasks)
    return {"message": "Processing started", "pack_id": str(pack_id)}


@router.get("/packs/{pack_id}/pipeline", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    pack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await pipeline_service.get_pipeline_status_or_raise(db, org_id, pack_id)


@router.get("/packs/{pack_id}/files/{file_id}/download")
async def download_file(
    pack_id: uuid.UUID,
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    data, filename = await pack_service.get_file_download_data_or_raise(db, org_id, pack_id, file_id, storage)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
