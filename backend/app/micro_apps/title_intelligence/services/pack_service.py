import uuid
import json

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.core.exceptions import NotFoundError, ConflictError, ValidationError

# Values that indicate "no real data" — used to filter both property_address and pack name
_SENTINEL_NAME_VALUES = frozenset({
    "not specified", "n/a", "na", "none", "unknown",
    "not available", "not provided",
})


async def create_pack(db: AsyncSession, org_id: uuid.UUID, name: str) -> Pack:
    pack = Pack(org_id=org_id, name=name, status="uploading")
    db.add(pack)
    await db.commit()
    # Re-fetch with files loaded (PackResponse needs files)
    result = await db.execute(
        select(Pack)
        .where(Pack.id == pack.id)
        .options(selectinload(Pack.files))
    )
    return result.scalar_one()


async def get_pack(db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID) -> Pack | None:
    result = await db.execute(
        select(Pack)
        .where(Pack.id == pack_id, Pack.org_id == org_id)
        .options(selectinload(Pack.files))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_pack_with_extractions(db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID) -> dict | None:
    """Get pack with title company and property address from extractions."""
    pack = await get_pack(db, org_id, pack_id)
    if not pack:
        return None
    
    # Fetch title company (Underwriter) and property address
    extraction_result = await db.execute(
        select(Extraction.label, Extraction.value)
        .where(
            Extraction.pack_id == pack_id,
            Extraction.label.in_([
                "Underwriter", "Insured Property", "Subject Property",
                "Property 1", "Property Location", "Property Address"
            ])
        )
    )
    
    title_company = None
    property_address = None
    
    for label, value in extraction_result.fetchall():
        try:
            if isinstance(value, str):
                data = json.loads(value)
            else:
                data = value
            
            if label == "Underwriter" and isinstance(data, dict):
                name = data.get("field_value") or data.get("name")
                if name:
                    title_company = name.split(",")[0].strip()
            
            elif label in ("Insured Property", "Subject Property", "Property 1", "Property Location", "Property Address") and isinstance(data, dict):
                if not property_address:  # Only set if not already found
                    addr = data.get("address")
                    if addr and addr.strip():
                        normalized = addr.strip().lower()
                        if normalized not in (
                            "not specified", "n/a", "na", "none",
                            "unknown", "not available", "not provided",
                        ):
                            property_address = addr.strip()
        except (json.JSONDecodeError, TypeError):
            pass
    
    # If pack name is a sentinel value, fall back to original filename
    display_name = pack.name
    if display_name and display_name.strip().lower() in _SENTINEL_NAME_VALUES:
        if pack.files:
            fname = pack.files[0].original_filename
            display_name = fname.rsplit(".", 1)[0] if fname and "." in fname else (fname or display_name)

    # Build response dict
    return {
        "id": pack.id,
        "org_id": pack.org_id,
        "name": display_name,
        "status": pack.status,
        "current_stage": pack.current_stage,
        "readiness_score": pack.readiness_score,
        "readiness_summary": pack.readiness_summary,
        "error_message": pack.error_message,
        "created_at": pack.created_at,
        "updated_at": pack.updated_at,
        "files": pack.files,
        "title_company": title_company,
        "property_address": _sanitize_property_address(property_address),
    }


def _sanitize_property_address(addr: str | None) -> str | None:
    """Return None if address is a sentinel value like 'N/A'."""
    if not addr or not addr.strip():
        return None
    return None if addr.strip().lower() in _SENTINEL_NAME_VALUES else addr.strip()


async def get_pack_or_raise(db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID) -> Pack:
    pack = await get_pack(db, org_id, pack_id)
    if not pack:
        raise NotFoundError("Pack", pack_id)
    return pack


async def list_packs(
    db: AsyncSession, org_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[dict]:
    result = await db.execute(
        select(Pack)
        .where(Pack.org_id == org_id)
        .order_by(Pack.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    packs = list(result.scalars().all())
    
    # Fetch property addresses for all packs
    pack_ids = [p.id for p in packs]
    property_addresses = {}
    
    if pack_ids:
        # Look for various property-related extraction labels
        extraction_result = await db.execute(
            select(Extraction.pack_id, Extraction.label, Extraction.value)
            .where(
                Extraction.pack_id.in_(pack_ids),
                Extraction.label.in_([
                    "Insured Property", "Subject Property", "Property 1", 
                    "Property Location", "Property Address"
                ])
            )
        )
        for pack_id, label, value in extraction_result.fetchall():
            if pack_id in property_addresses:
                continue  # Already have address for this pack
            try:
                if isinstance(value, str):
                    data = json.loads(value)
                else:
                    data = value
                if isinstance(data, dict):
                    addr = data.get("address")
                    if addr and addr.strip():
                        normalized = addr.strip().lower()
                        if normalized not in (
                            "not specified", "n/a", "na", "none",
                            "unknown", "not available", "not provided",
                        ):
                            property_addresses[pack_id] = addr.strip()
            except (json.JSONDecodeError, TypeError):
                pass
    
    # For packs whose name is a sentinel, fall back to original filename
    fallback_names = {}
    sentinel_pack_ids = [
        p.id for p in packs
        if p.name and p.name.strip().lower() in _SENTINEL_NAME_VALUES
    ]
    if sentinel_pack_ids:
        fn_result = await db.execute(
            select(PackFile.pack_id, PackFile.original_filename)
            .where(PackFile.pack_id.in_(sentinel_pack_ids))
        )
        for pid, fname in fn_result.fetchall():
            if pid not in fallback_names and fname:
                # Strip file extension for display
                fallback_names[pid] = fname.rsplit(".", 1)[0] if "." in fname else fname

    # Convert to list of dicts with property address
    return [
        {
            "id": p.id,
            "name": fallback_names.get(p.id, p.name) if (
                p.name and p.name.strip().lower() in _SENTINEL_NAME_VALUES
            ) else p.name,
            "status": p.status,
            "current_stage": p.current_stage,
            "readiness_score": p.readiness_score,
            "created_at": p.created_at,
            "property_address": _sanitize_property_address(property_addresses.get(p.id)),
        }
        for p in packs
    ]


async def _cleanup_pack_storage(org_id: uuid.UUID, pack_id: uuid.UUID, storage: StorageProvider) -> None:
    """Delete all storage artifacts for a pack: files, pages, and org-level AI caches."""
    # Pack-scoped files (uploads, pages, thumbs, OCR)
    await storage.delete_dir(f"{org_id}/{pack_id}")
    # Org-level AI caches (examiner, examiner_native, summary)
    for stage in ("examiner", "examiner_native", "summary"):
        try:
            await storage.delete_dir(f"{org_id}/ai_cache/{stage}")
        except Exception:
            pass


async def delete_pack(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, storage: StorageProvider
) -> bool:
    pack = await get_pack(db, org_id, pack_id)
    if not pack:
        return False
    await _cleanup_pack_storage(org_id, pack_id, storage)
    # Use SQL DELETE to let DB ON DELETE CASCADE handle child rows,
    # avoiding SQLAlchemy ORM's attempt to SET NULL on loaded relationships.
    await db.execute(delete(Pack).where(Pack.id == pack_id, Pack.org_id == org_id))
    await db.commit()
    return True


async def delete_pack_or_raise(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, storage: StorageProvider
) -> None:
    await get_pack_or_raise(db, org_id, pack_id)
    await _cleanup_pack_storage(org_id, pack_id, storage)
    await db.execute(delete(Pack).where(Pack.id == pack_id, Pack.org_id == org_id))
    await db.commit()


async def require_pack_for_processing(db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID) -> Pack:
    """Get pack and validate it's ready for processing."""
    pack = await get_pack_or_raise(db, org_id, pack_id)
    if pack.status == "processing":
        raise ConflictError("Pack is already being processed")
    return pack


async def add_file(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    filename: str,
    storage_path: str,
    file_size: int,
    content_hash: str | None = None,
) -> PackFile:
    pack_file = PackFile(
        pack_id=pack_id,
        org_id=org_id,
        filename=filename,
        storage_path=storage_path,
        file_size=file_size,
        content_hash=content_hash,
    )
    db.add(pack_file)
    await db.commit()
    await db.refresh(pack_file)
    return pack_file


async def get_pack_files(db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID) -> list[PackFile]:
    result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    return list(result.scalars().all())


async def get_pack_file(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, file_id: uuid.UUID,
) -> PackFile | None:
    result = await db.execute(
        select(PackFile).where(
            PackFile.id == file_id,
            PackFile.pack_id == pack_id,
            PackFile.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def get_file_download_data(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    file_id: uuid.UUID, storage: StorageProvider,
) -> tuple[bytes, str] | None:
    """Return (file_bytes, filename) or None if not found."""
    pack_file = await get_pack_file(db, org_id, pack_id, file_id)
    if not pack_file:
        return None
    data = await storage.read(pack_file.storage_path)
    return data, pack_file.filename


async def get_file_download_data_or_raise(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID,
    file_id: uuid.UUID, storage: StorageProvider,
) -> tuple[bytes, str]:
    """Return (file_bytes, filename) or raise NotFoundError."""
    pack_file = await get_pack_file(db, org_id, pack_id, file_id)
    if not pack_file:
        raise NotFoundError("File", file_id)
    data = await storage.read(pack_file.storage_path)
    return data, pack_file.filename


def validate_pdf_upload(filename: str | None, data: bytes, max_size: int) -> None:
    """Validate a file upload is a valid PDF within size limits.

    Raises ValidationError if any check fails.
    """
    if not filename or not filename.lower().endswith(".pdf"):
        raise ValidationError(f"Only PDF files are accepted: {filename}")
    if len(data) > max_size:
        raise ValidationError(f"File too large: {filename}")
    if data[:5] != b"%PDF-":
        raise ValidationError(f"File is not a valid PDF: {filename}")
