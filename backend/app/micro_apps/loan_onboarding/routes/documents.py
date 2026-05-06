"""Routes exposing pages + stacks for a package.

These feed the Documents tab in the frontend (stack viewer with grouped
pages, classification labels, confidence chips).
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_member, get_db, get_org_id
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.services import package_service
from app.models.user import User
from app.services.storage import StorageProvider, get_storage

logger = logging.getLogger(__name__)

router = APIRouter()

# DPI used when rasterising a scanned page for OCR. 200 is the sweet spot
# for Tesseract on typical paystubs/W-2s — high enough for accurate word
# segmentation, low enough that one page renders in <1s.
_OCR_RENDER_DPI = 200


@router.get("/packages/{package_id}/pages")
async def list_pages(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    pages = (await db.execute(
        select(LOPage)
        .where(LOPage.package_id == package_id, LOPage.org_id == org_id)
        .order_by(LOPage.page_number.asc())
    )).scalars().all()
    return [
        {
            "id": str(p.id),
            "page_number": p.page_number,
            "source_page_number": p.source_page_number,
            "text_length": p.text_length,
        }
        for p in pages
    ]


@router.get("/packages/{package_id}/pages/{page_id}/image")
async def get_page_image(
    package_id: uuid.UUID,
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Render a single PDF page as a JPEG on demand.

    LO ingest writes only metadata-only LOPage rows (no `image_path`), so the
    image is rendered from the source PDF via PyMuPDF on each request. Tenant
    isolation is enforced by filtering LOPage on both `org_id` and
    `package_id`; per-user visibility is enforced by `get_visible_package_or_raise`.
    """
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    page = (await db.execute(
        select(LOPage).where(
            LOPage.id == page_id,
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    file_row = (await db.execute(
        select(LOPackageFile).where(
            LOPackageFile.id == page.file_id,
            LOPackageFile.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not file_row:
        raise HTTPException(status_code=404, detail="Source file not found")

    pdf_bytes = await storage.get_object(file_row.storage_path)

    def _render() -> bytes:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            idx = max(0, min(page.source_page_number - 1, len(doc) - 1))
            pix = doc[idx].get_pixmap(dpi=100)
            return pix.tobytes("jpeg")
        finally:
            doc.close()

    jpeg = await asyncio.to_thread(_render)
    # Page bytes are immutable per (package_id, page_id) — source PDF doesn't
    # change once uploaded, page renders are deterministic. `private` because the
    # path is tenant-scoped; one-year max-age + `immutable` skips revalidation.
    # This is especially valuable here because the current handler re-reads the
    # PDF from S3 and re-renders on every miss.
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/packages/{package_id}/pages/{page_id}/thumb")
async def get_page_thumb(
    package_id: uuid.UUID,
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Render a low-DPI JPEG thumbnail (~150px wide) for the page strip.

    The Results-tab stack viewer shows a vertical thumb strip; full-quality
    `/image` renders would be wasteful (~80KB+ per page at DPI=100). This
    handler renders at DPI=30 with JPEG quality 70 — typically <10KB per
    thumb, fast enough to render the strip on stack expand without lag.
    Same `Cache-Control: immutable` story as `/image`: source PDF doesn't
    change, page renders are deterministic.
    """
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    page = (await db.execute(
        select(LOPage).where(
            LOPage.id == page_id,
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    file_row = (await db.execute(
        select(LOPackageFile).where(
            LOPackageFile.id == page.file_id,
            LOPackageFile.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not file_row:
        raise HTTPException(status_code=404, detail="Source file not found")

    pdf_bytes = await storage.get_object(file_row.storage_path)

    def _render() -> bytes:
        import io
        import fitz  # PyMuPDF
        from PIL import Image

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            idx = max(0, min(page.source_page_number - 1, len(doc) - 1))
            # DPI=30 puts a US Letter page at ~255×330 px; we resample to
            # 150px wide so the thumb strip stays crisp on retina without
            # blowing up payload size. PIL gives us JPEG quality control
            # (PyMuPDF's tobytes("jpeg") doesn't honor quality on all
            # versions), so we route through it.
            pix = doc[idx].get_pixmap(dpi=30, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            target_w = 150
            if img.width > target_w:
                ratio = target_w / float(img.width)
                target_h = max(1, int(img.height * ratio))
                img = img.resize((target_w, target_h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70, optimize=True)
            return buf.getvalue()
        finally:
            doc.close()

    jpeg = await asyncio.to_thread(_render)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/packages/{package_id}/pages/{page_id}/words")
async def get_page_words(
    package_id: uuid.UUID,
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Return per-word bounding boxes for a page, normalized 0..1.

    Used by the extraction-review workbench so the UI can highlight the
    exact text of an extracted field on the rendered page (the AI agent's
    own bbox emission is unreliable). Computed on demand via PyMuPDF
    `page.get_text("words")` and the page's mediabox; not persisted.

    Response shape:
        {
          "page_width": 612.0,        // PDF points, for debugging
          "page_height": 792.0,
          "words": [
            {"text": "Borrower", "x0": 0.105, "y0": 0.082,
                                  "x1": 0.213, "y1": 0.097,
                                  "block": 0, "line": 0, "word": 0},
            ...
          ]
        }
    """
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    page = (await db.execute(
        select(LOPage).where(
            LOPage.id == page_id,
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    file_row = (await db.execute(
        select(LOPackageFile).where(
            LOPackageFile.id == page.file_id,
            LOPackageFile.org_id == org_id,
        )
    )).scalar_one_or_none()
    if not file_row:
        raise HTTPException(status_code=404, detail="Source file not found")

    pdf_bytes = await storage.get_object(file_row.storage_path)

    # Cache key for OCR fallback. Native-text pages are recomputed each call
    # (PyMuPDF is fast, ~ms). Image-only pages run Tesseract once then hit
    # this cache forever — keyed by page_id, so any pipeline re-run that
    # rebuilds page rows (new uuid) misses cleanly.
    ocr_cache_key = f"{org_id}/{package_id}/ocr/{page_id}.json"

    cached_ocr: bytes | None = None
    try:
        cached_ocr = await storage.get_object(ocr_cache_key)
    except Exception:
        # Most storage backends raise on missing keys — treat as cache miss.
        cached_ocr = None

    def _extract_native(pdf_bytes_inner: bytes) -> dict:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes_inner, filetype="pdf")
        try:
            idx = max(0, min(page.source_page_number - 1, len(doc) - 1))
            pdf_page = doc[idx]
            rect = pdf_page.rect
            pw = float(rect.width) or 1.0
            ph = float(rect.height) or 1.0
            # words: [(x0, y0, x1, y1, text, block_no, line_no, word_no), ...]
            raw = pdf_page.get_text("words")
            out = []
            for w in raw:
                x0, y0, x1, y1, text, block_no, line_no, word_no = w
                if not text or not text.strip():
                    continue
                out.append({
                    "text": text,
                    "x0": max(0.0, min(1.0, float(x0) / pw)),
                    "y0": max(0.0, min(1.0, float(y0) / ph)),
                    "x1": max(0.0, min(1.0, float(x1) / pw)),
                    "y1": max(0.0, min(1.0, float(y1) / ph)),
                    "block": int(block_no),
                    "line": int(line_no),
                    "word": int(word_no),
                })
            return {"page_width": pw, "page_height": ph, "words": out}
        finally:
            doc.close()

    def _ocr_fallback(pdf_bytes_inner: bytes) -> dict | None:
        """Render the page to an image and OCR it with Tesseract.

        Returns words in the SAME 0..1 normalized coordinate space as the
        native-text path, so the frontend never has to know which path
        produced them. PDF page dims (in points) are reported as
        page_width/page_height to keep the response shape stable — the
        actual rendered pixel size is an internal detail.

        Returns None on any failure (missing tesseract binary, render
        error, …) so the caller can fall back to empty-words behavior.
        """
        try:
            import fitz  # PyMuPDF
            import pytesseract
            from pytesseract import Output
        except ImportError as e:
            logger.warning(f"OCR unavailable for page {page_id}: {e}")
            return None

        doc = fitz.open(stream=pdf_bytes_inner, filetype="pdf")
        try:
            idx = max(0, min(page.source_page_number - 1, len(doc) - 1))
            pdf_page = doc[idx]
            rect = pdf_page.rect
            pw = float(rect.width) or 1.0
            ph = float(rect.height) or 1.0
            try:
                pix = pdf_page.get_pixmap(dpi=_OCR_RENDER_DPI, alpha=False)
            except Exception as e:
                logger.warning(f"OCR render failed for page {page_id}: {e}")
                return None
            img_w = float(pix.width) or 1.0
            img_h = float(pix.height) or 1.0

            # Tesseract takes a PIL Image. PNG is lossless and small at this
            # DPI for paystub-style pages.
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(pix.tobytes("png")))
            except Exception as e:
                logger.warning(f"OCR image decode failed for page {page_id}: {e}")
                return None

            try:
                data = pytesseract.image_to_data(img, output_type=Output.DICT)
            except pytesseract.TesseractNotFoundError as e:
                logger.warning(
                    f"Tesseract binary not installed; OCR unavailable for "
                    f"page {page_id}: {e}"
                )
                return None
            except Exception as e:
                logger.warning(f"OCR call failed for page {page_id}: {e}")
                return None

            n = len(data.get("text", []))
            out: list[dict] = []
            for i in range(n):
                text = (data["text"][i] or "").strip()
                if not text:
                    continue
                # Tesseract emits pixel coords in the rendered image space.
                # Normalize against the rendered image dims, NOT the PDF
                # mediabox — they differ by the DPI scale factor.
                x = float(data["left"][i])
                y = float(data["top"][i])
                w = float(data["width"][i])
                h = float(data["height"][i])
                out.append({
                    "text": text,
                    "x0": max(0.0, min(1.0, x / img_w)),
                    "y0": max(0.0, min(1.0, y / img_h)),
                    "x1": max(0.0, min(1.0, (x + w) / img_w)),
                    "y1": max(0.0, min(1.0, (y + h) / img_h)),
                    "block": int(data["block_num"][i]),
                    "line": int(data["line_num"][i]),
                    "word": int(data["word_num"][i]),
                })
            return {"page_width": pw, "page_height": ph, "words": out}
        finally:
            doc.close()

    # Cache hit short-circuits the whole pipeline.
    if cached_ocr:
        try:
            return json.loads(cached_ocr.decode("utf-8"))
        except Exception as e:
            logger.warning(f"OCR cache decode failed for page {page_id}: {e}")

    # Native-text path first — fast and authoritative when the PDF carries
    # embedded text.
    native = await asyncio.to_thread(_extract_native, pdf_bytes)
    if native["words"]:
        return native

    # Image-only page — fall back to OCR. Persist the result so the next
    # click is instant.
    ocr = await asyncio.to_thread(_ocr_fallback, pdf_bytes)
    if ocr is None:
        # Tesseract unavailable or rendering failed — return the empty
        # native result so the frontend's "no words" path kicks in.
        return native
    try:
        await storage.put_object(
            ocr_cache_key,
            json.dumps(ocr).encode("utf-8"),
            content_type="application/json",
        )
    except Exception as e:
        logger.warning(f"OCR cache write failed for page {page_id}: {e}")
    return ocr


@router.get("/packages/{package_id}/stacks")
async def list_stacks(
    package_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    """Return every stack with its classification info.

    Response shape matches the frontend Documents tab requirements —
    grouped list of {stack, pages_with_classification}.
    """
    await package_service.get_visible_package_or_raise(db, org_id, package_id, member)
    stacks = (await db.execute(
        select(LOStack)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()
    classifications = (await db.execute(
        select(LOClassification).where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
        )
    )).scalars().all()
    clf_by_page = {c.page_number: c for c in classifications}

    # Include page_id per stack page so the Documents tab can call the
    # per-page override endpoint without a separate /pages lookup.
    pages = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id, LOPage.org_id == org_id
        )
    )).scalars().all()
    page_id_by_number = {p.page_number: p.id for p in pages}

    out = []
    for s in stacks:
        pages_payload = []
        for pn in s.page_numbers:
            c = clf_by_page.get(pn)
            pages_payload.append({
                "page_id": str(page_id_by_number[pn]) if pn in page_id_by_number else None,
                "page_number": pn,
                "predicted_doc_type": c.predicted_doc_type if c else None,
                "confidence": c.confidence if c else None,
                "page_role": c.page_role if c else None,
                "detected_fields": c.detected_fields if c else [],
            })
        out.append({
            "id": str(s.id),
            "stack_index": s.stack_index,
            "doc_type": s.doc_type,
            "first_page": s.first_page,
            "last_page": s.last_page,
            "page_count": len(s.page_numbers),
            "classification_confidence": s.classification_confidence,
            "overall_confidence": s.overall_confidence,
            "status": s.status,
            "requires_hitl": s.requires_hitl,
            "pages": pages_payload,
        })
    return out
