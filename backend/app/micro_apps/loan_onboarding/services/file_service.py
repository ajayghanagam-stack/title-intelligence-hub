"""File upload + content hashing service for Loan Onboarding."""
import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.services.storage import StorageProvider


MAX_FILENAME_LEN = 500
PDF_MIME = "application/pdf"


async def store_uploaded_file(
    db: AsyncSession,
    storage: StorageProvider,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> LOPackageFile:
    if not filename or len(filename) > MAX_FILENAME_LEN:
        raise ValidationError(f"Invalid filename (must be 1-{MAX_FILENAME_LEN} chars)")
    if not (filename.lower().endswith(".pdf") or (content_type or "").lower() == PDF_MIME):
        raise ValidationError("Only PDF uploads are supported")
    if not content:
        raise ValidationError("Uploaded file is empty")

    # Use the platform-wide path convention shared with TI
    storage_path = storage.make_pack_path(org_id, package_id, filename)
    await storage.put_object(storage_path, content, content_type=PDF_MIME)

    content_hash = hashlib.sha256(content).hexdigest()

    page_count = _count_pdf_pages(content)

    file_row = LOPackageFile(
        org_id=org_id,
        package_id=package_id,
        filename=filename,
        storage_path=storage_path,
        content_hash=content_hash,
        size_bytes=len(content),
        page_count=page_count,
    )
    db.add(file_row)
    await db.commit()
    await db.refresh(file_row)
    return file_row


def _count_pdf_pages(content: bytes) -> int:
    """Return the page count of a PDF without rendering. Returns 0 on failure."""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=content, filetype="pdf")
        try:
            return doc.page_count
        finally:
            doc.close()
    except Exception:
        return 0
