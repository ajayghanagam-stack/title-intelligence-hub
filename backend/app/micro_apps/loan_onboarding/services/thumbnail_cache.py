"""Pre-render every page's thumbnail to storage at the end of the pipeline.

Without this warm-up, the first user to open a freshly-completed packet
pays the per-page PyMuPDF render cost on the `/thumb` endpoint — for a
100-page packet that meant a multi-second wait while the strip filled.
By rendering thumbs proactively at the end of `run_pipeline` (after the
package status is already marked completed), we make the first-ever
open as fast as every subsequent open.

Best-effort by design: failures are logged but never raised. The
`/thumb` route still has a render-on-miss fallback, so a missed warm-up
just degrades to the previous behavior — never worse.
"""
import asyncio
import io
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.services.storage import StorageProvider

logger = logging.getLogger(__name__)

# PyMuPDF is CPU-bound; 4 parallel renders saturates a typical t4g.xlarge
# without starving live API traffic. Tuned to match the per-host browser
# concurrency cap so we don't pre-render faster than a real user would
# request thumbs anyway.
WARMUP_CONCURRENCY = 4

# Match the on-demand /thumb handler so warmed and on-demand outputs are
# byte-identical (lets the cache key stay stable if we ever need to
# version-bump thumb format).
WARMUP_DPI = 30
WARMUP_TARGET_WIDTH = 150
WARMUP_JPEG_QUALITY = 70


def _render_thumb(pdf_bytes: bytes, source_page_number: int) -> bytes | None:
    """Render one page to a 150px-wide JPEG. Returns None on render failure
    or if the PDF has zero pages (defensive: empty test PDFs shouldn't
    crash the warm-up loop)."""
    import fitz  # PyMuPDF
    from PIL import Image

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if len(doc) == 0:
            return None
        idx = max(0, min(source_page_number - 1, len(doc) - 1))
        pix = doc[idx].get_pixmap(dpi=WARMUP_DPI, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        if img.width > WARMUP_TARGET_WIDTH:
            ratio = WARMUP_TARGET_WIDTH / float(img.width)
            target_h = max(1, int(img.height * ratio))
            img = img.resize((WARMUP_TARGET_WIDTH, target_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=WARMUP_JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    finally:
        doc.close()


async def warm_package_thumbnails(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
) -> dict:
    """Pre-render every page thumbnail for a package and write to storage.

    Idempotent: pages whose thumb already exists in storage are skipped,
    so a re-run after a partial warm-up only fills the gaps. Returns a
    summary `{rendered, skipped, failed}` for logging.

    PDFs are downloaded from storage at most once per file (the typical
    packet has 1-3 source PDFs but many pages); rendering is dispatched
    in parallel up to `WARMUP_CONCURRENCY`.
    """
    rendered = 0
    skipped = 0
    failed = 0

    async with session_factory() as db:
        pages = (await db.execute(
            select(LOPage)
            .where(LOPage.package_id == package_id, LOPage.org_id == org_id)
            .order_by(LOPage.page_number.asc())
        )).scalars().all()
        files = (await db.execute(
            select(LOPackageFile).where(
                LOPackageFile.package_id == package_id,
                LOPackageFile.org_id == org_id,
            )
        )).scalars().all()

    if not pages:
        return {"rendered": 0, "skipped": 0, "failed": 0}

    file_by_id = {f.id: f for f in files}
    pages_by_file: dict[uuid.UUID, list[LOPage]] = {}
    for p in pages:
        pages_by_file.setdefault(p.file_id, []).append(p)

    sem = asyncio.Semaphore(WARMUP_CONCURRENCY)

    async def _warm_one(page: LOPage, pdf_bytes: bytes):
        nonlocal rendered, skipped, failed
        cache_key = f"{org_id}/{package_id}/thumbs/{page.id}.jpg"

        # Cheap existence check — most storage backends raise on missing
        # keys, so we treat any error as "not cached" and proceed to render.
        try:
            existing = await storage.get_object(cache_key)
            if existing:
                skipped += 1
                return
        except Exception:
            pass

        async with sem:
            try:
                jpeg = await asyncio.to_thread(
                    _render_thumb, pdf_bytes, page.source_page_number
                )
            except Exception as e:
                logger.warning(
                    "lo thumb warmup render failed package=%s page=%s source=%s: %s",
                    package_id, page.id, page.source_page_number, e,
                )
                failed += 1
                return

            if jpeg is None:
                # Empty PDF or unrenderable page — skip silently.
                failed += 1
                return

            try:
                await storage.put_object(cache_key, jpeg, content_type="image/jpeg")
                rendered += 1
            except Exception as e:
                logger.warning(
                    "lo thumb warmup write failed package=%s page=%s: %s",
                    package_id, page.id, e,
                )
                failed += 1

    tasks: list[asyncio.Task] = []
    for file_id, file_pages in pages_by_file.items():
        file_row = file_by_id.get(file_id)
        if not file_row:
            failed += len(file_pages)
            continue
        try:
            pdf_bytes = await storage.get_object(file_row.storage_path)
        except Exception as e:
            logger.warning(
                "lo thumb warmup: PDF download failed file=%s path=%s: %s",
                file_row.id, file_row.storage_path, e,
            )
            failed += len(file_pages)
            continue
        for page in file_pages:
            tasks.append(asyncio.create_task(_warm_one(page, pdf_bytes)))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    return {"rendered": rendered, "skipped": skipped, "failed": failed}
