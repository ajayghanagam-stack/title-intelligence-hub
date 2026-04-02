import json
import re
import uuid
import asyncio
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.section import Section
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.text_chunk import TextChunk
from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.core.logging import get_logger

# Minimum chars of embedded text to consider a page "text-based"
MIN_EMBEDDED_TEXT_LEN = 50

# Pages with this much text skip JPEG rendering entirely (text sent directly to LLM)
TEXT_SKIP_RENDER_THRESHOLD = 200

# Pages with fewer chars than this are heuristically classified as "blank"
HEURISTIC_BLANK_THRESHOLD = 20

# Clone concurrency for file copies
CLONE_BATCH_SIZE = 10

# ── Deterministic section detection from page text headings ──────────────
# Ordered by specificity: more specific patterns first (e.g., B-1 before B)
# All patterns require the heading to appear at the start of a line (^\s*).
_SECTION_HEADING_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("schedule_b1", re.compile(
        r"^\s*SCHEDULE\s+B[\s\-–—]*(?:(?:SECTION|PART)\s*)?(?:1|I(?!\w))",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("schedule_b2", re.compile(
        r"^\s*SCHEDULE\s+B[\s\-–—]*(?:(?:SECTION|PART)\s*)?(?:2|II(?!\w))",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("schedule_b", re.compile(
        r"^\s*SCHEDULE\s+B(?!\s*[\-–—]\s*\d)(?!\s*[\-–—]\s*[IV])(?:\b|$)",
        re.IGNORECASE | re.MULTILINE,
    )),
    ("schedule_a", re.compile(r"^\s*SCHEDULE\s+A\b", re.IGNORECASE | re.MULTILINE)),
    ("schedule_c", re.compile(r"^\s*SCHEDULE\s+C\b", re.IGNORECASE | re.MULTILINE)),
    ("schedule_d", re.compile(r"^\s*SCHEDULE\s+D\b", re.IGNORECASE | re.MULTILINE)),
    ("endorsements", re.compile(r"^\s*ENDORSEMENT", re.IGNORECASE | re.MULTILINE)),
    ("legal_description", re.compile(
        r"^\s*(?:LEGAL\s+DESCRIPTION|EXHIBIT\s+A\b)",
        re.IGNORECASE | re.MULTILINE,
    )),
]


def _detect_section_type_from_text(text: str) -> str | None:
    """Detect section type from the first ~500 chars of a page's text.

    Looks for standard title commitment section headings at the start of a
    line. Returns the section_type string if found, None otherwise.
    """
    # Only scan the top of the page where headings appear
    header = text[:500]
    for section_type, pattern in _SECTION_HEADING_PATTERNS:
        if pattern.search(header):
            return section_type
    return None


def _rebuild_sections_from_page_text(
    pages: list[Any],
    ai_sections: list[Any],
) -> list[Any]:
    """Rebuild section list using deterministic heading detection from page text.

    Scans each page's OCR text for section headings (Schedule A, B-1, etc.)
    and builds sections from those boundaries. Falls back to AI-detected
    sections if no headings are found.

    Args:
        pages: Page model instances with page_number and ocr_text
        ai_sections: Sections from the AI (ExaminerSection instances)

    Returns:
        List of ExaminerSection instances with corrected section_type values
    """
    from app.micro_apps.title_intelligence.schemas.examiner import ExaminerSection

    if not pages:
        return list(ai_sections)

    # Sort pages by page_number
    sorted_pages = sorted(pages, key=lambda p: p.page_number)

    # Detect section boundaries from page headings
    boundaries: list[tuple[int, str]] = []  # (page_number, section_type)
    for page in sorted_pages:
        text = getattr(page, "ocr_text", None) or ""
        if not text:
            continue
        detected = _detect_section_type_from_text(text)
        if detected:
            boundaries.append((page.page_number, detected))

    if not boundaries:
        # No headings detected — return AI sections as-is
        return list(ai_sections)

    # Build sections from boundaries
    max_page = max(p.page_number for p in sorted_pages)
    rebuilt: list[ExaminerSection] = []
    for i, (start_page, section_type) in enumerate(boundaries):
        # End page is one before the next section starts, or max_page
        if i + 1 < len(boundaries):
            end_page = boundaries[i + 1][0] - 1
        else:
            end_page = max_page
        rebuilt.append(ExaminerSection(
            section_type=section_type,
            start_page=start_page,
            end_page=end_page,
            confidence=1.0,
        ))

    return rebuilt


def _sanitize_extracted_text(raw: str) -> str:
    """Remove null bytes and non-UTF-8 sequences from PyMuPDF extracted text.

    Some PDFs (scanned, encrypted, or with binary font encodings) produce raw
    byte garbage from ``fitz.Page.get_text()``.  PostgreSQL rejects ``\\x00``
    in text columns, so we strip those and any remaining non-decodable bytes.
    """
    # Fast path – most pages are clean
    if "\x00" not in raw:
        return raw
    return raw.replace("\x00", "")

# Parallel page rendering concurrency (CPU-bound work offloaded to threads)
RENDER_CONCURRENCY = 8

# In-memory page image cache: render stage populates, examine stage consumes.
# Keyed by pack_id → {page_number → jpeg_bytes}. Cleared after examine completes.
_page_image_cache: dict[uuid.UUID, dict[int, bytes]] = {}


async def stage_ingest(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """Validate files exist and mark pack as processing."""
    result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    files = list(result.scalars().all())
    if not files:
        raise ValueError("No files uploaded to this pack")

    for f in files:
        if not await storage.exists(f.storage_path):
            raise FileNotFoundError(f"File not found: {f.storage_path}")

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="ingest")
    log.info(f"Validated {len(files)} files")


async def _find_donor_pack(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, input_file_hash: str
) -> uuid.UUID | None:
    """Find a completed pack in the same org with identical file content.

    Returns the donor pack_id if found, None otherwise.
    """
    # Find most recent completed PipelineRun with same input_file_hash, same org, different pack
    result = await db.execute(
        select(PipelineRun.pack_id)
        .where(
            PipelineRun.org_id == org_id,
            PipelineRun.input_file_hash == input_file_hash,
            PipelineRun.pack_id != pack_id,
            PipelineRun.status == "completed",
        )
        .order_by(PipelineRun.completed_at.desc())
        .limit(1)
    )
    donor_pack_id = result.scalar_one_or_none()
    if donor_pack_id is None:
        return None

    # Verify donor pack still exists and is completed
    donor_pack = (await db.execute(
        select(Pack).where(Pack.id == donor_pack_id, Pack.org_id == org_id, Pack.status == "completed")
    )).scalar_one_or_none()
    if donor_pack is None:
        return None

    # Verify donor pack has pages (guard against cleaned/deleted data)
    page_count = (await db.execute(
        select(Page.id).where(Page.pack_id == donor_pack_id, Page.org_id == org_id).limit(1)
    )).scalar_one_or_none()
    if page_count is None:
        return None

    return donor_pack_id


async def _clone_pages_from_donor(
    donor_pack_id: uuid.UUID,
    target_pack_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
    storage: StorageProvider,
) -> int:
    """Clone page records and storage files from a donor pack.

    Copies image + thumbnail files to the target pack's storage namespace
    and creates new Page records with the target's pack_id and mapped file_ids.

    Returns the number of pages cloned.
    """
    # Get donor pages
    result = await db.execute(
        select(Page).where(Page.pack_id == donor_pack_id, Page.org_id == org_id)
        .order_by(Page.page_number)
    )
    donor_pages = list(result.scalars().all())
    if not donor_pages:
        return 0

    # Build file_id mapping: donor file_id → target file_id (matched by filename)
    donor_files_result = await db.execute(
        select(PackFile).where(PackFile.pack_id == donor_pack_id, PackFile.org_id == org_id)
    )
    donor_files = {f.id: f for f in donor_files_result.scalars().all()}

    target_files_result = await db.execute(
        select(PackFile).where(PackFile.pack_id == target_pack_id, PackFile.org_id == org_id)
    )
    target_files = {f.filename: f for f in target_files_result.scalars().all()}

    # Map donor file_id → target file_id by filename
    file_id_map: dict[uuid.UUID, uuid.UUID] = {}
    for donor_file_id, donor_file in donor_files.items():
        target_file = target_files.get(donor_file.filename)
        if target_file:
            file_id_map[donor_file_id] = target_file.id
            # Copy page_count from donor
            if donor_file.page_count is not None:
                target_file.page_count = donor_file.page_count

    # Clone pages in batches
    async def clone_one_page(donor_page: Page) -> None:
        target_file_id = file_id_map.get(donor_page.file_id)
        if target_file_id is None:
            return

        # Compute target storage paths
        image_path = storage.make_page_path(org_id, target_pack_id, donor_page.page_number)
        thumb_path = storage.make_thumb_path(org_id, target_pack_id, donor_page.page_number)

        # Copy storage files concurrently
        donor_image_data = await storage.read(donor_page.image_uri)
        donor_thumb_data = await storage.read(donor_page.thumb_uri)
        await asyncio.gather(
            storage.save(image_path, donor_image_data),
            storage.save(thumb_path, donor_thumb_data),
        )

        # Create new page record with target pack's data
        db.add(Page(
            pack_id=target_pack_id,
            file_id=target_file_id,
            org_id=org_id,
            page_number=donor_page.page_number,
            image_uri=image_path,
            thumb_uri=thumb_path,
            ocr_text=donor_page.ocr_text,
            ocr_uri=donor_page.ocr_uri,
        ))

    for i in range(0, len(donor_pages), CLONE_BATCH_SIZE):
        batch = donor_pages[i:i + CLONE_BATCH_SIZE]
        await asyncio.gather(*[clone_one_page(p) for p in batch])

    return len(donor_pages)


async def _stage_render_native_pdf(
    pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider
):
    """Lightweight render stage for native_pdf mode.

    Creates minimal Page records (page_number, file_id) with no images or OCR text.
    Page text will be populated later by the examine stage from LLM transcriptions.
    """
    import fitz

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="render")

    result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    files = list(result.scalars().all())

    # Clear existing pages for idempotent retry
    await db.execute(delete(Page).where(Page.pack_id == pack_id, Page.org_id == org_id))

    global_page_num = 0
    heuristic_blanks = 0
    for pack_file in files:
        pdf_data = await storage.read(pack_file.storage_path)
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        pack_file.page_count = len(doc)

        for page_idx in range(len(doc)):
            global_page_num += 1
            fitz_page = doc.load_page(page_idx)
            embedded_text = _sanitize_extracted_text(fitz_page.get_text("text").strip())

            # Determine page_type and ocr_text from embedded text.
            # Pages with images but no text are scanned pages — classify as
            # "content" so the LLM examiner processes them via vision.
            page_type = None
            ocr_text = None
            if len(embedded_text) >= MIN_EMBEDDED_TEXT_LEN:
                ocr_text = embedded_text
            elif len(embedded_text) < HEURISTIC_BLANK_THRESHOLD:
                has_images = len(fitz_page.get_images()) > 0
                if has_images:
                    # Scanned page — no extractable text but has image content
                    page_type = None  # treated as content by examiner
                else:
                    page_type = "blank"
                    heuristic_blanks += 1

            db.add(Page(
                pack_id=pack_id,
                file_id=pack_file.id,
                org_id=org_id,
                page_number=global_page_num,
                # Placeholder URIs — native_pdf mode doesn't render images.
                # image_uri/thumb_uri are NOT NULL in the schema; empty string signals "no image".
                image_uri="",
                thumb_uri="",
                ocr_text=ocr_text,
                page_type=page_type,
            ))

        doc.close()

    await db.commit()
    log.info(
        f"Native PDF render: created {global_page_num} page records "
        f"({heuristic_blanks} heuristic blanks)"
    )


async def stage_render(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """Convert PDF files to JPEG page images + thumbnails.

    In native_pdf mode, creates lightweight Page records (metadata only, no images).
    In legacy mode, renders PDFs to JPEG images + thumbnails and extracts embedded text.

    Fast path: if a previously completed pack in the same org has identical
    file content, clone its pages instead of re-rendering from scratch.
    """
    from app.config import get_settings as _get_settings
    settings = _get_settings()
    if settings.PIPELINE_MODE == "native_pdf":
        await _stage_render_native_pdf(pack_id, org_id, db, storage)
        return

    from app.micro_apps.title_intelligence.pipeline.version_tracker import compute_input_file_hash

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="render")

    result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    files = list(result.scalars().all())

    # Clear existing pages for idempotent retry
    await db.execute(delete(Page).where(Page.pack_id == pack_id, Page.org_id == org_id))

    # --- Duplicate file fast path ---
    # If all files have content_hash, check for a donor pack with identical content
    if files and all(f.content_hash for f in files):
        try:
            input_file_hash = await compute_input_file_hash(storage, org_id, files)
            donor_pack_id = await _find_donor_pack(db, org_id, pack_id, input_file_hash)
            if donor_pack_id:
                cloned = await _clone_pages_from_donor(donor_pack_id, pack_id, org_id, db, storage)
                if cloned > 0:
                    await db.commit()
                    log.info(
                        f"Duplicate detected — cloned {cloned} pages from donor pack {donor_pack_id}"
                    )
                    return
        except Exception as e:
            log.warning(f"Donor clone failed, falling back to normal render: {e}")
            # Re-clear pages in case partial clone occurred
            await db.execute(delete(Page).where(Page.pack_id == pack_id, Page.org_id == org_id))

    # --- Normal render path ---
    import fitz  # PyMuPDF

    global_page_num = 0
    text_pages = 0
    sem = asyncio.Semaphore(RENDER_CONCURRENCY)

    # Initialize in-memory image cache for this pack
    _page_image_cache[pack_id] = {}

    for pack_file in files:
        pdf_data = await storage.read(pack_file.storage_path)
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        pack_file.page_count = len(doc)

        # Build list of (page_idx, global_page_number) for parallel dispatch
        page_tasks: list[tuple[int, int]] = []
        for page_idx in range(len(doc)):
            global_page_num += 1
            page_tasks.append((page_idx, global_page_num))

        # Results collected from threads: (global_page_num, img_data, thumb_data, embedded_text)
        results: list[tuple[int, bytes, bytes, str]] = [None] * len(page_tasks)  # type: ignore[list-item]

        from app.config import get_settings as _get_settings
        render_dpi = _get_settings().EXAMINER_RENDER_DPI

        def _render_page(page_idx: int, doc_ref: Any) -> tuple[bytes | None, bytes | None, str]:
            """CPU-bound work: extract text + render images. Runs in a thread.

            Returns (img_data, thumb_data, embedded_text).
            img_data and thumb_data are None when the page has enough text
            to skip rendering (TEXT_SKIP_RENDER_THRESHOLD chars).
            """
            page = doc_ref.load_page(page_idx)

            # Extract embedded text
            embedded_text = _sanitize_extracted_text(page.get_text("text").strip())
            if len(embedded_text) < MIN_EMBEDDED_TEXT_LEN:
                blocks = page.get_text("dict").get("blocks", [])
                texts = []
                for block in blocks:
                    if block.get("type") == 0:
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                texts.append(span.get("text", ""))
                alt_text = _sanitize_extracted_text(" ".join(texts).strip())
                if len(alt_text) >= MIN_EMBEDDED_TEXT_LEN:
                    embedded_text = alt_text

            # Skip rendering for text-heavy pages — text goes directly to LLM
            if len(embedded_text) >= TEXT_SKIP_RENDER_THRESHOLD:
                return None, None, embedded_text

            # Render page image at configurable DPI (default 120)
            pix = page.get_pixmap(dpi=render_dpi)
            img_data = pix.tobytes("jpeg")

            # Render thumbnail at 72 DPI
            thumb_pix = page.get_pixmap(dpi=72)
            thumb_data = thumb_pix.tobytes("jpeg")

            return img_data, thumb_data, embedded_text

        async def _process_page(idx: int, page_idx: int, gpn: int) -> None:
            nonlocal text_pages
            async with sem:
                img_data, thumb_data, embedded_text = await asyncio.to_thread(
                    _render_page, page_idx, doc
                )

            has_text = len(embedded_text) >= MIN_EMBEDDED_TEXT_LEN
            if has_text:
                text_pages += 1

            # Text-heavy pages skip JPEG rendering — empty URIs signal "text-only"
            if img_data is None:
                db.add(Page(
                    pack_id=pack_id,
                    file_id=pack_file.id,
                    org_id=org_id,
                    page_number=gpn,
                    image_uri="",
                    thumb_uri="",
                    ocr_text=embedded_text,
                ))
                return

            # Store image in memory for examine stage (avoids storage round-trip)
            _page_image_cache[pack_id][gpn] = img_data

            image_path = storage.make_page_path(org_id, pack_id, gpn)
            thumb_path = storage.make_thumb_path(org_id, pack_id, gpn)
            await asyncio.gather(
                storage.save(image_path, img_data),
                storage.save(thumb_path, thumb_data),
            )

            db.add(Page(
                pack_id=pack_id,
                file_id=pack_file.id,
                org_id=org_id,
                page_number=gpn,
                image_uri=image_path,
                thumb_uri=thumb_path,
                ocr_text=embedded_text if has_text else None,
            ))

        await asyncio.gather(*[
            _process_page(i, pidx, gpn)
            for i, (pidx, gpn) in enumerate(page_tasks)
        ])

        doc.close()

    await db.commit()
    log.info(
        f"Processed {global_page_num} pages: {text_pages} text-only (skipped JPEG), "
        f"{global_page_num - text_pages} rendered as images"
    )


_SENTINEL_VALUES = frozenset({
    "not specified", "n/a", "na", "none", "unknown",
    "not available", "not provided",
})


def _is_real_address(addr: str) -> bool:
    """Return True if addr looks like a real property address (not a sentinel)."""
    return bool(addr and addr.strip() and addr.strip().lower() not in _SENTINEL_VALUES)


def _find_property_address(extractions: list[Any]) -> str:
    """Extract property address from extractions to use as pack name."""
    for ext_type in ("property_info", "property"):
        for label_pat in ("address", "property address", "full_address"):
            for ext in extractions:
                if ext.extraction_type == ext_type and label_pat in ext.label.lower():
                    val = ext.value
                    if isinstance(val, str) and _is_real_address(val):
                        return val.strip()
                    if isinstance(val, dict):
                        for key in ("value", "address", "full_address"):
                            v = val.get(key)
                            if isinstance(v, str) and _is_real_address(v):
                                return v.strip()
    return ""


def _compute_flags_hash(flags: list[Any]) -> str:
    """Compute a deterministic hash of flag ORM objects for cache keying."""
    import hashlib
    flags_dicts = [
        {
            "flag_type": f.flag_type,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "ai_explanation": f.ai_explanation,
            "evidence_refs": f.evidence_refs or [],
            "status": f.status,
        }
        for f in flags
    ]
    return hashlib.sha256(json.dumps(flags_dicts, sort_keys=True).encode("utf-8")).hexdigest()


async def _run_triage(
    pdf_bytes: bytes,
    total_pages: int,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    pages: list,
    db: AsyncSession,
) -> tuple[list[int], dict[int, str]]:
    """Run fast page triage and persist page_type on Page records.

    Heuristic-blank pages (already classified in render stage) are excluded
    from the LLM triage call to save tokens. Their classifications are
    merged with LLM results afterward.

    Returns:
        Tuple of (content_page_numbers, doc_type_hints) where
        doc_type_hints maps page_number → document_type_hint.
    """
    from app.micro_apps.title_intelligence.ai.triage_agent import TriageAgent
    from app.config import get_settings as _get_settings

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="triage")

    settings = _get_settings()
    chunk_size = getattr(settings, "TRIAGE_CHUNK_SIZE", 50)
    concurrency = getattr(settings, "TRIAGE_CONCURRENCY", 4)

    # Separate heuristic-blank pages from unclassified pages
    heuristic_blanks: set[int] = set()
    unclassified_pages: list[int] = []
    for p in pages:
        if p.page_type == "blank":
            heuristic_blanks.add(p.page_number)
        else:
            unclassified_pages.append(p.page_number)

    if heuristic_blanks:
        log.info(
            f"Heuristic pre-triage: {len(heuristic_blanks)} blank pages excluded from LLM triage"
        )

    # Build a filtered PDF containing only unclassified pages for triage
    triage_pdf = pdf_bytes
    triage_total = total_pages
    triage_page_map: dict[int, int] | None = None  # filtered_pos → original_pn

    if heuristic_blanks and len(unclassified_pages) < total_pages:
        triage_pdf = _build_content_only_pdf(pdf_bytes, unclassified_pages)
        triage_total = len(unclassified_pages)
        triage_page_map = {
            i + 1: orig_pn for i, orig_pn in enumerate(sorted(unclassified_pages))
        }

    log.info(f"Running page triage on {triage_total} pages (of {total_pages} total)")

    agent = TriageAgent(org_id)
    triage_result = await agent.classify_pages_parallel(
        triage_pdf, triage_total,
        chunk_size=chunk_size,
        concurrency=concurrency,
    )

    # Remap triage results back to original page numbers if we filtered
    if triage_page_map:
        for tp in triage_result.pages:
            original_pn = triage_page_map.get(tp.page_number, tp.page_number)
            tp.page_number = original_pn

    # Build lookup and persist page_type
    page_map = {p.page_number: p for p in pages}
    content_pages: list[int] = []
    doc_type_hints: dict[int, str] = {}

    # Apply LLM triage results
    for tp in triage_result.pages:
        page = page_map.get(tp.page_number)
        if page:
            page.page_type = tp.page_type
        doc_type_hints[tp.page_number] = getattr(tp, "document_type_hint", "generic")
        if tp.page_type == "content":
            content_pages.append(tp.page_number)

    # Heuristic blanks keep their "blank" classification, not content
    for pn in heuristic_blanks:
        doc_type_hints[pn] = "generic"

    await db.commit()

    skipped = total_pages - len(content_pages)
    log.info(
        f"Triage: {len(content_pages)} content, {skipped} non-content "
        f"({skipped / total_pages * 100:.0f}% skipped) "
        f"in {triage_result.llm_elapsed_seconds or 0:.1f}s"
    )
    return content_pages, doc_type_hints


def _build_content_only_pdf(pdf_bytes: bytes, content_pages: list[int]) -> bytes:
    """Build a new PDF containing only the specified content pages.

    Args:
        pdf_bytes: Original full PDF bytes.
        content_pages: 1-based page numbers to include.

    Returns:
        Bytes of the filtered PDF.
    """
    import fitz

    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    dst = fitz.open()

    for pn in sorted(content_pages):
        # fitz uses 0-based page indices
        dst.insert_pdf(src, from_page=pn - 1, to_page=pn - 1)

    result = dst.tobytes()
    dst.close()
    src.close()
    return result


def _extract_pdf_pages(pdf_bytes: bytes, start_page: int, end_page: int) -> bytes:
    """Extract a contiguous range of pages from a PDF.

    Args:
        pdf_bytes: Full PDF bytes.
        start_page: 1-based start page (inclusive).
        end_page: 1-based end page (inclusive).

    Returns:
        Bytes of the extracted PDF chunk.
    """
    import fitz

    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    dst = fitz.open()
    dst.insert_pdf(src, from_page=start_page - 1, to_page=end_page - 1)
    result = dst.tobytes()
    dst.close()
    src.close()
    return result


async def _clone_analysis_from_donor(
    donor_pack_id: uuid.UUID,
    target_pack_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """Clone flags, extractions, sections, and text chunks from a donor pack.

    Called when the target pack has the same file content as an already-completed
    pack in the same org. Guarantees identical analysis results without re-running
    the AI, regardless of LLM non-determinism or cache key changes.

    Returns True if cloning succeeded (donor has data), False otherwise.
    """
    log = get_logger(__name__, org_id=org_id, pack_id=target_pack_id, stage="examine")

    # Verify donor has sections (guard against empty / failed donors)
    donor_section_result = await db.execute(
        select(Section).where(Section.pack_id == donor_pack_id, Section.org_id == org_id)
    )
    donor_sections = list(donor_section_result.scalars().all())
    if not donor_sections:
        return False

    # Clear any existing analysis for target pack
    await db.execute(delete(Extraction).where(Extraction.pack_id == target_pack_id, Extraction.org_id == org_id))
    await db.execute(delete(Section).where(Section.pack_id == target_pack_id, Section.org_id == org_id))
    await db.execute(delete(Flag).where(Flag.pack_id == target_pack_id, Flag.org_id == org_id))
    await db.execute(delete(TextChunk).where(TextChunk.pack_id == target_pack_id, TextChunk.org_id == org_id))

    # Clone sections, building an ID mapping for extractions
    section_id_map: dict[uuid.UUID, uuid.UUID] = {}
    for s in donor_sections:
        new_id = uuid.uuid4()
        section_id_map[s.id] = new_id
        db.add(Section(
            id=new_id,
            pack_id=target_pack_id,
            org_id=org_id,
            section_type=s.section_type,
            start_page=s.start_page,
            end_page=s.end_page,
            confidence=s.confidence,
        ))

    # Clone extractions (map section_id via the above mapping)
    donor_extraction_result = await db.execute(
        select(Extraction).where(Extraction.pack_id == donor_pack_id, Extraction.org_id == org_id)
    )
    for e in donor_extraction_result.scalars().all():
        new_section_id = section_id_map.get(e.section_id) if e.section_id else None
        db.add(Extraction(
            pack_id=target_pack_id,
            org_id=org_id,
            extraction_type=e.extraction_type,
            label=e.label,
            value=e.value,
            evidence_refs=e.evidence_refs,
            section_id=new_section_id,
            confidence=e.confidence,
        ))

    # Clone flags — always start as "open" (don't carry over reviewer decisions)
    donor_flag_result = await db.execute(
        select(Flag).where(Flag.pack_id == donor_pack_id, Flag.org_id == org_id)
    )
    donor_flags = list(donor_flag_result.scalars().all())
    for f in donor_flags:
        db.add(Flag(
            pack_id=target_pack_id,
            org_id=org_id,
            flag_type=f.flag_type,
            severity=f.severity,
            title=f.title,
            description=f.description,
            ai_explanation=f.ai_explanation,
            evidence_refs=f.evidence_refs,
            status="open",
        ))

    # Clone text chunks
    donor_chunk_result = await db.execute(
        select(TextChunk).where(TextChunk.pack_id == donor_pack_id, TextChunk.org_id == org_id)
    )
    for c in donor_chunk_result.scalars().all():
        db.add(TextChunk(
            pack_id=target_pack_id,
            org_id=org_id,
            page_number=c.page_number,
            section_type=c.section_type,
            content=c.content,
        ))

    # Copy ocr_text to existing target pages from donor pages
    donor_page_result = await db.execute(
        select(Page).where(Page.pack_id == donor_pack_id, Page.org_id == org_id)
    )
    donor_pages_by_num = {p.page_number: p for p in donor_page_result.scalars().all()}
    target_page_result = await db.execute(
        select(Page).where(Page.pack_id == target_pack_id, Page.org_id == org_id)
    )
    for tp in target_page_result.scalars().all():
        dp = donor_pages_by_num.get(tp.page_number)
        if dp and dp.ocr_text:
            tp.ocr_text = dp.ocr_text

    await db.commit()
    log.info(
        f"Analysis cloned from donor pack {donor_pack_id} — "
        f"{len(donor_sections)} sections, {len(donor_flags)} flags"
    )
    return True


async def _stage_examine_native_pdf(
    pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider
):
    """Examine stage for native_pdf mode — sends PDF chunks directly to Gemini."""
    import math
    import fitz

    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    from app.micro_apps.title_intelligence.services.flag_rules import (
        normalize_flags,
        generate_deterministic_flags,
        merge_llm_and_deterministic_flags,
    )
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_input_file_hash,
        compute_examiner_cache_key,
    )
    from app.config import get_settings

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="examine")

    # Load pages
    result = await db.execute(
        select(Page).where(Page.pack_id == pack_id, Page.org_id == org_id).order_by(Page.page_number)
    )
    pages = list(result.scalars().all())
    if not pages:
        raise ValueError("No page records found — run stage_render first")

    # Compute input file hash for deduplication and cache key
    settings = get_settings()
    version_info = collect_version_info(settings)
    files_result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    pack_files = list(files_result.scalars().all())
    input_file_hash = await compute_input_file_hash(storage, org_id, pack_files)

    # --- DB-level deduplication: clone analysis from a completed pack with identical content ---
    # This is the primary determinism guarantee — identical files always produce identical
    # results regardless of AI non-determinism or cache key version changes.
    donor_pack_id = await _find_donor_pack(db, org_id, pack_id, input_file_hash)
    if donor_pack_id:
        cloned = await _clone_analysis_from_donor(donor_pack_id, pack_id, org_id, db)
        if cloned:
            return

    cache_key = compute_examiner_cache_key(input_file_hash, version_info)
    cache_path = storage.make_ai_cache_path(org_id, pack_id, "examiner_native", cache_key)

    # Check cache
    if await storage.exists(cache_path):
        cached_data = json.loads(await storage.read(cache_path))
        await _replay_examiner_cache(db, org_id, pack_id, cached_data, pages)
        await _create_text_chunks_from_transcriptions(
            db, org_id, pack_id, cached_data.get("page_transcriptions", [])
        )
        # Replay triage page_types from cache if present
        page_map = {p.page_number: p for p in pages}
        for pt_entry in cached_data.get("page_types", []):
            page = page_map.get(pt_entry.get("page_number"))
            if page:
                page.page_type = pt_entry.get("page_type", "content")
        await db.commit()
        log.info(
            f"Native PDF examiner cache hit — replayed "
            f"{len(cached_data.get('sections', []))} sections, "
            f"{len(cached_data.get('extractions', []))} extractions, "
            f"{len(cached_data.get('flags', []))} flags"
        )
        return

    # Cache miss — load PDF bytes and concatenate if multiple files
    pdf_data_list = []
    for pf in pack_files:
        pdf_data_list.append(await storage.read(pf.storage_path))

    if len(pdf_data_list) == 1:
        pdf_bytes = pdf_data_list[0]
    else:
        # Concatenate multiple PDFs into one
        merged = fitz.open()
        for data in pdf_data_list:
            src = fitz.open(stream=data, filetype="pdf")
            merged.insert_pdf(src)
            src.close()
        pdf_bytes = merged.tobytes()
        merged.close()

    total_pages = len(pages)

    # Create examiner agent early — used for cache pre-warming and later examination
    agent = TitleExaminerAgent(org_id)

    # --- Page triage: classify pages before deep extraction ---
    triage_enabled = getattr(settings, "TRIAGE_ENABLED", True)
    triage_skip_below = getattr(settings, "TRIAGE_SKIP_BELOW", 80)
    content_page_numbers: list[int] | None = None
    page_type_records: list[dict] = []
    doc_type_hints: dict[int, str] = {}
    early_batch_result = None  # Optimistic first batch dispatched during triage

    # Skip LLM triage for small documents — heuristic blanks from render suffice
    run_triage = triage_enabled and total_pages >= triage_skip_below

    if run_triage:
        # Update progress to show triage is running
        pack = (await db.execute(
            select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
        )).scalar_one()
        pack.examine_progress = "classifying pages..."
        await db.commit()

        batch_size = settings.NATIVE_PDF_BATCH_SIZE

        # Launch triage, cache pre-warm, and optimistic first batch concurrently
        triage_task = asyncio.create_task(_run_triage(
            pdf_bytes, total_pages, org_id, pack_id, pages, db,
        ))
        cache_task = asyncio.create_task(agent._ensure_context_cache(agent.JSON_SCHEMA))

        # Optimistic early batch: dispatch pages 1-batch_size during triage
        early_size = min(batch_size, total_pages)
        early_chunk = _extract_pdf_pages(pdf_bytes, 1, early_size)
        early_task = asyncio.create_task(
            agent.examine_pdf_batch(
                early_chunk, (1, early_size), total_pages, 0, -1
            )
        )

        content_page_numbers, doc_type_hints = await triage_task

        # Validate optimistic batch: check if all early pages are content
        try:
            early_batch_result = await early_task
            early_pages_are_content = all(
                pn in content_page_numbers for pn in range(1, early_size + 1)
            )
            if not early_pages_are_content:
                log.info("Optimistic batch discarded: triage excluded some early pages")
                early_batch_result = None
            else:
                log.info(
                    f"Optimistic batch valid: pages 1-{early_size} "
                    f"({len(early_batch_result.flags)} flags)"
                )
        except Exception as e:
            log.warning(f"Optimistic early batch failed (non-fatal): {e}")
            early_batch_result = None

        try:
            await cache_task
        except Exception as e:
            log.warning(f"Examiner cache pre-warm failed (non-fatal): {e}")

        # Re-query pages to get updated page_type values
        result = await db.execute(
            select(Page).where(Page.pack_id == pack_id, Page.org_id == org_id).order_by(Page.page_number)
        )
        pages = list(result.scalars().all())
        page_type_records = [
            {
                "page_number": p.page_number,
                "page_type": p.page_type or "content",
                "document_type_hint": doc_type_hints.get(p.page_number, "generic"),
            }
            for p in pages
        ]
    else:
        # No triage — use heuristic blanks from render, all non-blank pages are content
        heuristic_blanks = {p.page_number for p in pages if p.page_type == "blank"}
        content_page_numbers = [
            p.page_number for p in pages if p.page_number not in heuristic_blanks
        ]
        for p in pages:
            if p.page_type != "blank":
                p.page_type = "content"
        await db.commit()

        # Still pre-warm the examiner cache (standalone, not concurrent with triage)
        cache_task = asyncio.create_task(agent._ensure_context_cache(agent.JSON_SCHEMA))
        try:
            await cache_task
        except Exception as e:
            log.warning(f"Examiner cache pre-warm failed (non-fatal): {e}")

    # Build content-only PDF if triage filtered pages
    examine_pdf = pdf_bytes
    examine_total = total_pages
    # Mapping from position in content-only PDF to original page number
    content_page_map: dict[int, int] | None = None

    if len(content_page_numbers) < total_pages:
        examine_pdf = _build_content_only_pdf(pdf_bytes, content_page_numbers)
        examine_total = len(content_page_numbers)
        # Map: 1-based position in filtered PDF → original page number
        content_page_map = {
            i + 1: orig_pn for i, orig_pn in enumerate(sorted(content_page_numbers))
        }
        log.info(
            f"Triage filtered: {examine_total}/{total_pages} pages sent to examiner"
        )

    batch_size = settings.NATIVE_PDF_BATCH_SIZE
    concurrency = settings.NATIVE_PDF_CONCURRENCY

    # --- Document grouping: align chunks with logical document boundaries ---
    grouping_enabled = getattr(settings, "GROUPING_ENABLED", True)
    examiner_page_ranges: list[tuple[int, int]] | None = None
    examiner_doc_types: list[str] | None = None

    if grouping_enabled and run_triage and page_type_records:
        from app.micro_apps.title_intelligence.services.document_grouper import (
            group_pages,
            groups_to_page_ranges,
            groups_to_doc_types,
            remap_groups_to_filtered_pdf,
        )

        grouping_result = group_pages(page_type_records, max_chunk_size=batch_size)

        if grouping_result.groups:
            active_groups = grouping_result.groups

            # Adaptive chunk sizing: re-split groups based on page text complexity
            adaptive_enabled = getattr(settings, "ADAPTIVE_CHUNK_SIZING", True)
            if adaptive_enabled:
                from app.micro_apps.title_intelligence.services.document_grouper import (
                    regroup_with_adaptive_sizes,
                )
                page_texts = {p.page_number: (p.ocr_text or "") for p in pages}
                active_groups = regroup_with_adaptive_sizes(
                    active_groups, page_texts, base_size=batch_size,
                )

            if content_page_map:
                # Remap group page numbers to content-only PDF positions
                # content_page_map is {filtered_pos → orig_pn}, we need the inverse
                inverse_map = {orig: filt for filt, orig in content_page_map.items()}
                remapped_groups = remap_groups_to_filtered_pdf(
                    active_groups, inverse_map
                )
                examiner_page_ranges = groups_to_page_ranges(remapped_groups)
                examiner_doc_types = groups_to_doc_types(remapped_groups)
            else:
                examiner_page_ranges = groups_to_page_ranges(active_groups)
                examiner_doc_types = groups_to_doc_types(active_groups)

            log.info(
                f"Document grouping: {len(active_groups)} groups, "
                f"{grouping_result.total_content_pages} content pages"
            )

    total_batches = (
        len(examiner_page_ranges) if examiner_page_ranges
        else max(1, math.ceil(examine_total / batch_size))
    )

    # Clear existing data for idempotent retry
    await db.execute(delete(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    await db.execute(delete(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
    await db.execute(delete(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))
    await db.execute(delete(TextChunk).where(TextChunk.pack_id == pack_id, TextChunk.org_id == org_id))
    await db.commit()

    # Track batch progress for progressive UI updates
    batches_completed = 0
    total_flags_found = 0
    _progress_lock = asyncio.Lock()

    async def _on_batch_complete(batch_idx: int, batch_result: Any) -> None:
        nonlocal batches_completed, total_flags_found

        async with _progress_lock:
            batches_completed += 1
            batch_flags = len(batch_result.flags)
            total_flags_found += batch_flags

            # Update pack's examine_progress for SSE streaming
            try:
                pack = (await db.execute(
                    select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
                )).scalar_one()
                pack.examine_progress = f"{batches_completed}/{total_batches} batches, {total_flags_found} flags"
                await db.commit()
            except Exception as e:
                log.warning(f"Failed to update examine_progress (non-fatal): {e}")
                await db.rollback()

            log.info(
                f"PDF batch {batch_idx + 1} complete: "
                f"{len(batch_result.sections)} sections, "
                f"{len(batch_result.extractions)} extractions, "
                f"{batch_flags} flags "
                f"({batches_completed}/{total_batches} done)"
            )

    # Determine if we can reuse the optimistic early batch result
    # Only applicable when no document grouping overrides and no content filtering
    skip_early_pages = 0
    if early_batch_result and not examiner_page_ranges and not content_page_map:
        skip_early_pages = min(batch_size, examine_total)

    if skip_early_pages > 0 and skip_early_pages < examine_total:
        # Build remaining PDF (pages after the early batch)
        remaining_pdf = _extract_pdf_pages(examine_pdf, skip_early_pages + 1, examine_total)
        remaining_total = examine_total - skip_early_pages

        log.info(
            f"Reusing optimistic batch (pages 1-{skip_early_pages}), "
            f"examining remaining {remaining_total} pages"
        )

        remaining_consolidated = await agent.examine_document_native_pdf(
            pdf_bytes=remaining_pdf,
            total_pages=examine_total,  # pass full total for context
            batch_size=batch_size,
            concurrency=concurrency,
            on_batch_complete=_on_batch_complete,
            page_ranges=None,
            chunk_doc_types=None,
        )

        # Remap remaining batch page numbers (they start from 1 in the sub-PDF)
        # back to original positions
        from app.micro_apps.title_intelligence.schemas.examiner import PageTranscription
        remap_offset = skip_early_pages
        for t in remaining_consolidated.page_transcriptions:
            t.page_number += remap_offset
        for s in remaining_consolidated.sections:
            s.start_page += remap_offset
            s.end_page += remap_offset
        for e in remaining_consolidated.extractions:
            for ref in (e.evidence_refs or []):
                if "page_number" in ref:
                    ref["page_number"] += remap_offset
        for f in remaining_consolidated.flags:
            for ref in (f.evidence_refs or []):
                if "page_number" in ref:
                    ref["page_number"] += remap_offset

        # Consolidate early + remaining
        consolidated = agent.consolidate([early_batch_result, remaining_consolidated])
        consolidated.rate_limit_hits = remaining_consolidated.rate_limit_hits
        consolidated.total_retries = remaining_consolidated.total_retries
    else:
        # Standard path: examine all pages (no early batch reuse)
        consolidated = await agent.examine_document_native_pdf(
            pdf_bytes=examine_pdf,
            total_pages=examine_total,
            batch_size=batch_size,
            concurrency=concurrency,
            on_batch_complete=_on_batch_complete,
            page_ranges=examiner_page_ranges,
            chunk_doc_types=examiner_doc_types,
        )

    # Remap page numbers from content-only PDF back to original page numbers
    if content_page_map:
        consolidated = _remap_page_numbers(consolidated, content_page_map)

    # Race-condition guard: re-check the org-scoped cache before any DB writes.
    # If another pack processed the same document concurrently and already saved
    # the cache while we were running the AI call, replay their result instead of
    # ours. This guarantees both packs produce identical flag sets for identical
    # documents even when two pipelines start at the same time.
    if await storage.exists(cache_path):
        cached_data = json.loads(await storage.read(cache_path))
        await _replay_examiner_cache(db, org_id, pack_id, cached_data, pages)
        await _create_text_chunks_from_transcriptions(
            db, org_id, pack_id, cached_data.get("page_transcriptions", [])
        )
        page_map_rc = {p.page_number: p for p in pages}
        for pt_entry in cached_data.get("page_types", []):
            page = page_map_rc.get(pt_entry.get("page_number"))
            if page:
                page.page_type = pt_entry.get("page_type", "content")
        await db.commit()
        log.info(
            f"Race-condition guard: concurrent cache hit — replayed "
            f"{len(cached_data.get('sections', []))} sections, "
            f"{len(cached_data.get('extractions', []))} extractions, "
            f"{len(cached_data.get('flags', []))} flags"
        )
        return

    # Write consolidated results — same logic as legacy examine
    await db.execute(delete(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    await db.execute(delete(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
    await db.execute(delete(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))
    await db.execute(delete(TextChunk).where(TextChunk.pack_id == pack_id, TextChunk.org_id == org_id))

    # Update Page.ocr_text with transcriptions
    page_map = {p.page_number: p for p in pages}
    for t in consolidated.page_transcriptions:
        page = page_map.get(t.page_number)
        if page:
            page.ocr_text = t.text

    # Rebuild sections from page text headings (deterministic, overrides AI)
    consolidated.sections = _rebuild_sections_from_page_text(pages, consolidated.sections)

    # Insert sections
    section_map: dict[tuple[str, int], uuid.UUID] = {}
    for s in consolidated.sections:
        section_id = uuid.uuid4()
        section_map[(s.section_type, s.start_page)] = section_id
        db.add(Section(
            id=section_id,
            pack_id=pack_id,
            org_id=org_id,
            section_type=s.section_type,
            start_page=s.start_page,
            end_page=s.end_page,
            confidence=s.confidence,
        ))

    # Insert extractions
    for e in consolidated.extractions:
        section_id = _find_matching_section(e.evidence_refs, consolidated.sections, section_map)
        db.add(Extraction(
            pack_id=pack_id,
            org_id=org_id,
            extraction_type=e.extraction_type,
            label=e.label,
            value=e.value,
            evidence_refs=[ref.model_dump() if hasattr(ref, "model_dump") else ref for ref in e.evidence_refs],
            section_id=section_id,
            confidence=e.confidence,
        ))

    # Normalize LLM flags
    raw_flag_dicts = [
        {
            "flag_type": f.flag_type,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "ai_explanation": f.ai_explanation,
            "evidence_refs": [ref.model_dump() if hasattr(ref, "model_dump") else ref for ref in f.evidence_refs],
        }
        for f in consolidated.flags
    ]
    llm_normalized = normalize_flags(raw_flag_dicts)

    # Generate deterministic flags from extractions and merge with LLM flags
    extraction_dicts = [e.model_dump() for e in consolidated.extractions]
    section_dicts = [s.model_dump() for s in consolidated.sections]
    det_flags = generate_deterministic_flags(extraction_dicts, section_dicts)
    normalized = merge_llm_and_deterministic_flags(llm_normalized, det_flags)

    for f in normalized:
        db.add(Flag(
            pack_id=pack_id,
            org_id=org_id,
            flag_type=f["flag_type"],
            severity=f["severity"],
            title=f["title"],
            description=f["description"],
            ai_explanation=f["ai_explanation"],
            evidence_refs=f.get("evidence_refs", []),
            status="open",
        ))

    # Create text chunks from transcriptions
    transcription_dicts = [
        {"page_number": t.page_number, "text": t.text}
        for t in consolidated.page_transcriptions
    ]
    await _create_text_chunks_from_transcriptions(db, org_id, pack_id, transcription_dicts)

    # Clear examine_progress
    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one()
    pack.examine_progress = None

    # Save to cache (include page_types for replay)
    cache_data = {
        "page_transcriptions": transcription_dicts,
        "sections": section_dicts,
        "extractions": extraction_dicts,
        "flags": normalized,
        "page_types": page_type_records,
    }
    try:
        await storage.save(cache_path, json.dumps(cache_data, sort_keys=True).encode("utf-8"))
    except Exception as e:
        log.warning(f"Failed to write native PDF examiner cache (non-fatal): {e}")

    await db.commit()
    log.info(
        f"Native PDF examiner cache miss — saved "
        f"{len(consolidated.sections)} sections, "
        f"{len(consolidated.extractions)} extractions, "
        f"{len(normalized)} flags (from {len(raw_flag_dicts)} raw LLM, {len(det_flags)} deterministic)"
    )


def _remap_page_numbers(consolidated, content_page_map: dict[int, int]):
    """Remap page numbers in consolidated results from content-only PDF to original pages.

    The examiner sees a filtered PDF where page 1 might be original page 3.
    This function translates all page references back to original numbering.
    """
    # Remap transcriptions
    for t in consolidated.page_transcriptions:
        t.page_number = content_page_map.get(t.page_number, t.page_number)

    # Remap sections
    for s in consolidated.sections:
        s.start_page = content_page_map.get(s.start_page, s.start_page)
        s.end_page = content_page_map.get(s.end_page, s.end_page)

    # Remap evidence_refs in extractions
    for e in consolidated.extractions:
        for ref in e.evidence_refs:
            if isinstance(ref, dict) and "page_number" in ref:
                ref["page_number"] = content_page_map.get(ref["page_number"], ref["page_number"])
            elif hasattr(ref, "page_number"):
                ref.page_number = content_page_map.get(ref.page_number, ref.page_number)

    # Remap evidence_refs in flags
    for f in consolidated.flags:
        for ref in f.evidence_refs:
            if isinstance(ref, dict) and "page_number" in ref:
                ref["page_number"] = content_page_map.get(ref["page_number"], ref["page_number"])
            elif hasattr(ref, "page_number"):
                ref.page_number = content_page_map.get(ref.page_number, ref.page_number)

    return consolidated


async def stage_examine(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """AI title examination — native_pdf or legacy mode.

    In native_pdf mode, sends PDF chunks directly to Gemini (no image rendering needed).
    In legacy mode, sends page images/text to Gemini Vision.

    Caches output keyed by (file content hash + model + prompt + tool + rules version).
    """
    from app.config import get_settings as _get_settings
    settings = _get_settings()
    if settings.PIPELINE_MODE == "native_pdf":
        await _stage_examine_native_pdf(pack_id, org_id, db, storage)
        return

    from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
    from app.micro_apps.title_intelligence.services.flag_rules import (
        normalize_flags,
        generate_deterministic_flags,
        merge_llm_and_deterministic_flags,
    )
    from app.micro_apps.title_intelligence.services.chunker import chunk_text
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_input_file_hash,
        compute_examiner_cache_key,
    )
    from app.config import get_settings

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="examine")

    # Load pages
    result = await db.execute(
        select(Page).where(Page.pack_id == pack_id, Page.org_id == org_id).order_by(Page.page_number)
    )
    pages = list(result.scalars().all())
    if not pages:
        raise ValueError("No rendered pages found — run stage_render first")

    # Compute cache key
    settings = get_settings()
    version_info = collect_version_info(settings)
    files_result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    pack_files = list(files_result.scalars().all())
    input_file_hash = await compute_input_file_hash(storage, org_id, pack_files)
    cache_key = compute_examiner_cache_key(input_file_hash, version_info)
    cache_path = storage.make_ai_cache_path(org_id, pack_id, "examiner", cache_key)

    # Check cache
    if await storage.exists(cache_path):
        cached_data = json.loads(await storage.read(cache_path))
        await _replay_examiner_cache(db, org_id, pack_id, cached_data, pages)
        # Also create text chunks from cached transcriptions
        await _create_text_chunks_from_transcriptions(
            db, org_id, pack_id, cached_data.get("page_transcriptions", [])
        )
        await db.commit()
        log.info(
            f"Examiner cache hit — replayed "
            f"{len(cached_data.get('sections', []))} sections, "
            f"{len(cached_data.get('extractions', []))} extractions, "
            f"{len(cached_data.get('flags', []))} flags"
        )
        return

    # Cache miss — run examiner agent with progressive batch streaming
    agent = TitleExaminerAgent(org_id)

    # Filter out heuristic blank pages (classified during render stage)
    all_pages = pages
    content_pages = [p for p in pages if p.page_type != "blank"]
    blank_count = len(all_pages) - len(content_pages)
    if blank_count > 0:
        log.info(f"Filtered {blank_count} blank pages, examining {len(content_pages)} content pages")
        pages = content_pages

    # For large documents, run LLM triage to filter non-content pages further.
    # Triage and examiner cache pre-warming run concurrently for overlap.
    triage_enabled = getattr(settings, "TRIAGE_ENABLED", True)
    triage_skip_below = getattr(settings, "TRIAGE_SKIP_BELOW", 200)
    total_pages = len(all_pages)

    if triage_enabled and total_pages >= triage_skip_below:
        # Load PDF for triage
        pdf_data_list = []
        for pf in pack_files:
            pdf_data_list.append(await storage.read(pf.storage_path))
        if len(pdf_data_list) == 1:
            triage_pdf = pdf_data_list[0]
        else:
            import fitz
            merged = fitz.open()
            for data in pdf_data_list:
                src = fitz.open(stream=data, filetype="pdf")
                merged.insert_pdf(src)
                src.close()
            triage_pdf = merged.tobytes()
            merged.close()

        # Run triage + cache pre-warm concurrently (overlap)
        triage_task = asyncio.create_task(_run_triage(
            triage_pdf, total_pages, org_id, pack_id, all_pages, db,
        ))
        cache_task = asyncio.create_task(agent._ensure_context_cache(agent.JSON_SCHEMA))

        content_page_numbers, _doc_type_hints = await triage_task
        try:
            await cache_task
        except Exception as e:
            log.warning(f"Examiner cache pre-warm failed (non-fatal): {e}")

        # Re-filter pages based on triage results
        content_set = set(content_page_numbers)
        pages = [p for p in all_pages if p.page_number in content_set]
        triage_filtered = total_pages - len(pages)
        log.info(f"Triage filtered: examining {len(pages)}/{total_pages} pages")

    # Clear existing data for idempotent retry
    await db.execute(delete(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    await db.execute(delete(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
    await db.execute(delete(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))
    await db.execute(delete(TextChunk).where(TextChunk.pack_id == pack_id, TextChunk.org_id == org_id))
    await db.commit()

    # Track batch progress for progressive UI updates
    batches_completed = 0
    total_batches = 0  # will be set once batches are built
    total_flags_found = 0
    _progress_lock = asyncio.Lock()

    async def _on_batch_complete(batch_idx: int, batch_result: Any) -> None:
        """Callback fired as each batch completes — writes results to DB immediately."""
        nonlocal batches_completed, total_flags_found

        async with _progress_lock:
            batches_completed += 1
            batch_flags = len(batch_result.flags)
            total_flags_found += batch_flags

            # Update pack's examine_progress for SSE streaming
            try:
                pack = (await db.execute(
                    select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
                )).scalar_one()
                pack.examine_progress = f"{batches_completed}/{total_batches} batches, {total_flags_found} flags"
                await db.commit()
            except Exception as e:
                log.warning(f"Failed to update examine_progress (non-fatal): {e}")
                await db.rollback()

            log.info(
                f"Batch {batch_idx + 1} complete: "
                f"{len(batch_result.sections)} sections, "
                f"{len(batch_result.extractions)} extractions, "
                f"{batch_flags} flags "
                f"({batches_completed}/{total_batches} done)"
            )

    # Count batches for progress tracking (agent will build them during examine_document)
    text_pages_count = sum(1 for p in pages if p.ocr_text and len(p.ocr_text) >= 50)
    image_pages_count = len(pages) - text_pages_count
    batch_config = agent._get_batch_config()
    import math
    total_batches = max(1,
        (math.ceil(text_pages_count / batch_config["batch_size_text"]) if text_pages_count else 0) +
        (math.ceil(image_pages_count / batch_config["batch_size_image"]) if image_pages_count else 0)
    )

    # Pass in-memory image cache to avoid re-reading from storage
    image_cache = _page_image_cache.pop(pack_id, None)
    consolidated = await agent.examine_document(
        pages, storage, on_batch_complete=_on_batch_complete, image_cache=image_cache,
    )
    # Release memory
    image_cache = None

    # Now write the consolidated (deduplicated) results
    # Clear any interim data and write final consolidated output
    await db.execute(delete(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    await db.execute(delete(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
    await db.execute(delete(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))
    await db.execute(delete(TextChunk).where(TextChunk.pack_id == pack_id, TextChunk.org_id == org_id))

    # Update Page.ocr_text with transcriptions
    page_map = {p.page_number: p for p in pages}
    for t in consolidated.page_transcriptions:
        page = page_map.get(t.page_number)
        if page:
            page.ocr_text = t.text

    # Rebuild sections from page text headings (deterministic, overrides AI)
    consolidated.sections = _rebuild_sections_from_page_text(pages, consolidated.sections)

    # Insert sections, building section_map for FK linking
    section_map: dict[tuple[str, int], uuid.UUID] = {}
    for s in consolidated.sections:
        section_id = uuid.uuid4()
        section_map[(s.section_type, s.start_page)] = section_id
        db.add(Section(
            id=section_id,
            pack_id=pack_id,
            org_id=org_id,
            section_type=s.section_type,
            start_page=s.start_page,
            end_page=s.end_page,
            confidence=s.confidence,
        ))

    # Insert extractions, linking to sections where matching
    for e in consolidated.extractions:
        section_id = _find_matching_section(e.evidence_refs, consolidated.sections, section_map)
        db.add(Extraction(
            pack_id=pack_id,
            org_id=org_id,
            extraction_type=e.extraction_type,
            label=e.label,
            value=e.value,
            evidence_refs=[ref.model_dump() if hasattr(ref, "model_dump") else ref for ref in e.evidence_refs],
            section_id=section_id,
            confidence=e.confidence,
        ))

    # Normalize LLM flags
    raw_flag_dicts = [
        {
            "flag_type": f.flag_type,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "ai_explanation": f.ai_explanation,
            "evidence_refs": [ref.model_dump() if hasattr(ref, "model_dump") else ref for ref in f.evidence_refs],
        }
        for f in consolidated.flags
    ]
    llm_normalized = normalize_flags(raw_flag_dicts)

    # Generate deterministic flags from extractions and merge with LLM flags
    extraction_dicts = [e.model_dump() for e in consolidated.extractions]
    section_dicts = [s.model_dump() for s in consolidated.sections]
    det_flags = generate_deterministic_flags(extraction_dicts, section_dicts)
    normalized = merge_llm_and_deterministic_flags(llm_normalized, det_flags)

    for f in normalized:
        db.add(Flag(
            pack_id=pack_id,
            org_id=org_id,
            flag_type=f["flag_type"],
            severity=f["severity"],
            title=f["title"],
            description=f["description"],
            ai_explanation=f["ai_explanation"],
            evidence_refs=f.get("evidence_refs", []),
            status="open",
        ))

    # Create text chunks from transcriptions
    transcription_dicts = [
        {"page_number": t.page_number, "text": t.text}
        for t in consolidated.page_transcriptions
    ]
    await _create_text_chunks_from_transcriptions(db, org_id, pack_id, transcription_dicts)

    # Clear examine_progress now that examine is done
    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one()
    pack.examine_progress = None

    # Save to cache
    cache_data = {
        "page_transcriptions": transcription_dicts,
        "sections": section_dicts,
        "extractions": extraction_dicts,
        "flags": normalized,
    }
    try:
        await storage.save(cache_path, json.dumps(cache_data, sort_keys=True).encode("utf-8"))
    except Exception as e:
        log.warning(f"Failed to write examiner cache (non-fatal): {e}")

    await db.commit()
    log.info(
        f"Examiner cache miss — saved "
        f"{len(consolidated.sections)} sections, "
        f"{len(consolidated.extractions)} extractions, "
        f"{len(normalized)} flags (from {len(raw_flag_dicts)} raw LLM, {len(det_flags)} deterministic)"
    )


def _find_matching_section(
    evidence_refs: list,
    sections: list,
    section_map: dict[tuple[str, int], uuid.UUID],
) -> uuid.UUID | None:
    """Find the section that best matches an extraction's evidence refs."""
    if not evidence_refs or not sections:
        return None
    # Get page numbers from evidence refs
    page_numbers = set()
    for ref in evidence_refs:
        pn = ref.get("page_number") if isinstance(ref, dict) else getattr(ref, "page_number", None)
        if pn is not None:
            page_numbers.add(pn)
    if not page_numbers:
        return None
    # Find first section that contains any of these pages
    for s in sections:
        s_start = s.start_page if hasattr(s, "start_page") else s.get("start_page", 0)
        s_end = s.end_page if hasattr(s, "end_page") else s.get("end_page", 0)
        s_type = s.section_type if hasattr(s, "section_type") else s.get("section_type", "")
        if any(s_start <= pn <= s_end for pn in page_numbers):
            return section_map.get((s_type, s_start))
    return None


async def _replay_examiner_cache(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    cached_data: dict,
    pages: list,
) -> None:
    """Replay cached examiner output into the database."""
    # Clear existing data
    await db.execute(delete(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    await db.execute(delete(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
    await db.execute(delete(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))
    await db.execute(delete(TextChunk).where(TextChunk.pack_id == pack_id, TextChunk.org_id == org_id))

    # Update Page.ocr_text
    page_map = {p.page_number: p for p in pages}
    for t in cached_data.get("page_transcriptions", []):
        page = page_map.get(t["page_number"])
        if page:
            page.ocr_text = t["text"]

    # Rebuild sections from page text headings (deterministic, overrides AI cache)
    from app.micro_apps.title_intelligence.schemas.examiner import ExaminerSection as _ExSec
    ai_sections_objs = [
        _ExSec(
            section_type=s["section_type"],
            start_page=s["start_page"],
            end_page=s["end_page"],
            confidence=s.get("confidence", 0.0),
        )
        for s in cached_data.get("sections", [])
    ]
    rebuilt_sections = _rebuild_sections_from_page_text(pages, ai_sections_objs)

    # Insert sections
    section_map: dict[tuple[str, int], uuid.UUID] = {}
    for s in rebuilt_sections:
        section_id = uuid.uuid4()
        section_map[(s.section_type, s.start_page)] = section_id
        db.add(Section(
            id=section_id,
            pack_id=pack_id,
            org_id=org_id,
            section_type=s.section_type,
            start_page=s.start_page,
            end_page=s.end_page,
            confidence=s.confidence,
        ))

    # Insert extractions
    for e in cached_data.get("extractions", []):
        section_id = _find_matching_section(
            e.get("evidence_refs", []),
            rebuilt_sections,
            section_map,
        )
        db.add(Extraction(
            pack_id=pack_id,
            org_id=org_id,
            extraction_type=e["extraction_type"],
            label=e["label"],
            value=e.get("value", {}),
            evidence_refs=e.get("evidence_refs", []),
            section_id=section_id,
            confidence=e.get("confidence", 0.0),
        ))

    # Insert flags
    for f in cached_data.get("flags", []):
        db.add(Flag(
            pack_id=pack_id,
            org_id=org_id,
            flag_type=f["flag_type"],
            severity=f["severity"],
            title=f["title"],
            description=f["description"],
            ai_explanation=f["ai_explanation"],
            evidence_refs=f.get("evidence_refs", []),
            status=f.get("status", "open"),
        ))


async def _create_text_chunks_from_transcriptions(
    db: AsyncSession,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
    transcriptions: list[dict],
) -> None:
    """Create TextChunk records from page transcriptions using the hierarchical chunker.

    Collects all chunks first, then batch-inserts via db.add_all() for performance.
    """
    from app.micro_apps.title_intelligence.services.chunker import chunk_text

    all_chunks: list[TextChunk] = []
    for t in transcriptions:
        text = t.get("text", "")
        if not text:
            continue
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        for chunk_content in chunks:
            if len(chunk_content.strip()) < 10:
                continue
            all_chunks.append(TextChunk(
                pack_id=pack_id,
                org_id=org_id,
                page_number=t["page_number"],
                content=chunk_content,
            ))
    if all_chunks:
        db.add_all(all_chunks)


async def stage_complete(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """Generate executive summary and pre-cache PDF report.

    With SUMMARY_MODE=data_driven (default), generates the summary from
    structured data only — no LLM call, saving ~10-15s per run.
    With SUMMARY_MODE=llm, falls back to cached LLM-based summary.
    """
    from app.config import get_settings

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="complete")

    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one()

    # Load extractions and flags
    ext_result = await db.execute(select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    extractions = list(ext_result.scalars().all())
    flag_result = await db.execute(select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))
    flags = list(flag_result.scalars().all())

    # Update pack name to property address if extracted
    property_address = _find_property_address(extractions)
    if property_address:
        pack.name = property_address

    settings = get_settings()
    summary_mode = getattr(settings, "SUMMARY_MODE", "data_driven")

    if summary_mode == "data_driven":
        # Data-driven summary — deterministic, no LLM, ~0ms
        from app.micro_apps.title_intelligence.services.report_service import generate_data_driven_summary
        pack.readiness_summary = generate_data_driven_summary(
            pack_name=pack.name,
            extractions=extractions,
            flags=flags,
        )
        await db.commit()
        log.info(f"Data-driven summary — {len(flags)} flags")
    else:
        # LLM summary mode (fallback) — with cache
        from app.micro_apps.title_intelligence.ai.report_agent import ReportAgent
        from app.micro_apps.title_intelligence.pipeline.version_tracker import (
            collect_version_info,
            compute_ingestion_output_hash,
            compute_summary_cache_key,
        )

        version_info = collect_version_info(settings)

        sections_result = await db.execute(select(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
        sections = list(sections_result.scalars().all())

        ingestion_output_hash = compute_ingestion_output_hash(
            [{"section_type": s.section_type, "start_page": s.start_page, "end_page": s.end_page, "confidence": s.confidence} for s in sections],
            [{"extraction_type": e.extraction_type, "label": e.label, "value": e.value, "evidence_refs": e.evidence_refs or [], "confidence": e.confidence} for e in extractions],
        )
        risk_output_hash = _compute_flags_hash(flags)
        cache_key = compute_summary_cache_key(ingestion_output_hash, risk_output_hash, version_info)
        cache_path = storage.make_ai_cache_path(org_id, pack_id, "summary", cache_key)

        # Check cache
        if await storage.exists(cache_path):
            cached = json.loads(await storage.read(cache_path))
            pack.readiness_summary = cached["summary"]
            await db.commit()
            log.info("AI cache hit — summary replayed from cache")
        else:
            # Cache miss — generate summary via LLM
            agent = ReportAgent(org_id)
            summary = await agent.generate_summary(
                pack_name=pack.name,
                extractions=extractions,
                flags=flags,
            )
            pack.readiness_summary = summary.strip()

            # Save to cache
            try:
                cache_bytes = json.dumps({"summary": pack.readiness_summary}).encode("utf-8")
                await storage.save(cache_path, cache_bytes)
            except Exception as e:
                log.warning(f"Failed to write summary cache (non-fatal): {e}")

            await db.commit()
            log.info("AI cache miss — summary generated and cached")

    # Clear any stale chat history so the chat starts fresh for the newly processed document
    try:
        from app.micro_apps.title_intelligence.services.chat_service import clear_chat_history
        deleted = await clear_chat_history(db, org_id, pack_id)
        if deleted:
            log.info(f"Cleared {deleted} stale chat messages")
    except Exception:
        log.warning("Failed to clear chat history (non-fatal)", exc_info=True)

    # Pre-generate PDF report so download is instant
    try:
        from app.micro_apps.title_intelligence.services.report_service import generate_report_pdf
        log.info("Pre-generating PDF report...")
        await generate_report_pdf(db, org_id, pack_id, storage)
        log.info("PDF report pre-generated")
    except Exception:
        log.warning("Failed to pre-generate report (non-fatal)", exc_info=True)
