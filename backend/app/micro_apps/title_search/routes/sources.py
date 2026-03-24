import uuid

from fastapi import APIRouter, Depends, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_db, get_current_member, get_org_id
from app.core.exceptions import ValidationError
from app.models.user import User
from app.micro_apps.title_search.schemas.source import SourceAssignmentResponse
from app.micro_apps.title_search.schemas.document import RawDocumentResponse
from app.micro_apps.title_search.services import source_service, document_service
from app.services.storage import StorageProvider, get_storage
from app.services.audit_service import log_event

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"}


@router.get(
    "/orders/{order_id}/sources",
    response_model=list[SourceAssignmentResponse],
)
async def list_sources(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await source_service.get_source_assignments(db, org_id, order_id)


@router.post(
    "/orders/{order_id}/sources/{source_id}/upload",
    response_model=RawDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    order_id: uuid.UUID,
    source_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Ground abstractor uploads a document for a source assignment."""
    settings = get_settings()

    # Validate source assignment exists and belongs to this order
    source = await source_service.get_source_assignment_or_raise(
        db, org_id, order_id, source_id
    )

    # Validate file extension
    filename = file.filename or "unknown"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read and validate size
    data = await file.read()
    if len(data) > settings.FILE_UPLOAD_MAX_SIZE:
        raise ValidationError(f"File too large: {filename}")

    # Validate file content via magic bytes
    MAGIC_BYTES = {
        ".pdf": b"%PDF-",
        ".jpg": b"\xff\xd8\xff",
        ".jpeg": b"\xff\xd8\xff",
        ".png": b"\x89PNG",
        ".tiff": (b"II\x2a\x00", b"MM\x00\x2a"),  # little-endian / big-endian
        ".tif": (b"II\x2a\x00", b"MM\x00\x2a"),
    }
    expected = MAGIC_BYTES.get(ext)
    if expected is not None:
        if isinstance(expected, tuple):
            if not any(data.startswith(m) for m in expected):
                raise ValidationError(f"File content does not match expected {ext} format")
        elif not data.startswith(expected):
            raise ValidationError(f"File content does not match expected {ext} format")

    # Determine content format
    content_format = "pdf" if ext == ".pdf" else "image"

    # Save to storage
    rel_path = f"{org_id}/{order_id}/uploads/{filename}"
    await storage.save(rel_path, data)

    raw_doc = await document_service.create_raw_document(
        db, org_id, order_id, source_id,
        storage_path=rel_path,
        content_format=content_format,
    )

    # Update source assignment status
    source.status = "completed"
    await log_event(
        db, org_id,
        action="document_uploaded",
        target_type="ta_raw_document",
        target_id=raw_doc.id,
        actor_id=member.id,
        metadata={"order_id": str(order_id), "filename": filename},
    )
    await db.commit()

    return raw_doc
