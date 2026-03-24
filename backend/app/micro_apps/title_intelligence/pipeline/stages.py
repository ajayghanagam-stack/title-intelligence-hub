import json
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
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.micro_apps.title_intelligence.services.readiness_service import calculate_readiness
from app.core.logging import get_logger

# Minimum chars of embedded text to consider a page "text-based" (skip Vision OCR)
MIN_EMBEDDED_TEXT_LEN = 50

# OCR concurrency
OCR_BATCH_SIZE = 10


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


async def stage_render(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """Convert PDF files to JPEG page images + thumbnails.

    Also extracts embedded text from the PDF — pages with embedded text
    skip Vision OCR entirely, which is the #1 performance optimization.
    """
    import fitz  # PyMuPDF

    result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    files = list(result.scalars().all())

    # Clear existing pages for idempotent retry
    await db.execute(delete(Page).where(Page.pack_id == pack_id, Page.org_id == org_id))

    global_page_num = 0
    text_pages = 0

    for pack_file in files:
        pdf_data = await storage.read(pack_file.storage_path)
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        pack_file.page_count = len(doc)

        for page_idx in range(len(doc)):
            global_page_num += 1
            page = doc.load_page(page_idx)

            # Extract embedded text directly from PDF (instant, no API call)
            embedded_text = page.get_text("text").strip()

            # Render page image at 150 DPI (sufficient for OCR, half the size of 300 DPI)
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("jpeg")
            image_path = storage.make_page_path(org_id, pack_id, global_page_num)

            # Render thumbnail at 72 DPI
            thumb_pix = page.get_pixmap(dpi=72)
            thumb_data = thumb_pix.tobytes("jpeg")
            thumb_path = storage.make_thumb_path(org_id, pack_id, global_page_num)

            # Save both concurrently
            await asyncio.gather(
                storage.save(image_path, img_data),
                storage.save(thumb_path, thumb_data),
            )

            # If page has embedded text, store it now — skip Vision OCR later
            has_text = len(embedded_text) >= MIN_EMBEDDED_TEXT_LEN
            if has_text:
                text_pages += 1

            db.add(Page(
                pack_id=pack_id,
                file_id=pack_file.id,
                org_id=org_id,
                page_number=global_page_num,
                image_uri=image_path,
                thumb_uri=thumb_path,
                ocr_text=embedded_text if has_text else None,
            ))

        doc.close()

    await db.commit()
    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="render")
    log.info(f"Created {global_page_num} page images. {text_pages} had embedded text (skip OCR)")


async def stage_ocr(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage):
    """OCR pages that don't have embedded text, using Tesseract.

    Pages with embedded text (from stage_render) are skipped entirely.
    Uses versioned OCR cache paths so Tesseract upgrades auto-invalidate.
    Processes in batches of OCR_BATCH_SIZE concurrently via asyncio.to_thread.
    """
    from app.micro_apps.title_intelligence.ai.ocr_agent import OCRAgent
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        _get_tesseract_version,
        hash_string,
    )
    from app.config import get_settings

    result = await db.execute(
        select(Page).where(Page.pack_id == pack_id, Page.org_id == org_id).order_by(Page.page_number)
    )
    all_pages = list(result.scalars().all())

    # Only OCR pages that don't already have text
    pages_needing_ocr = [p for p in all_pages if not p.ocr_text]
    skipped = len(all_pages) - len(pages_needing_ocr)

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="ocr")

    if not pages_needing_ocr:
        log.info(f"All {len(all_pages)} pages have embedded text, skipping Tesseract")
        return

    # Compute OCR version hash for cache path
    settings = get_settings()
    tesseract_version = _get_tesseract_version(settings.TESSERACT_PATH)
    ocr_version_hash = hash_string(tesseract_version)

    log.info(f"{skipped}/{len(all_pages)} pages have embedded text. Running Tesseract on {len(pages_needing_ocr)} pages (version: {tesseract_version})")

    agent = OCRAgent()
    failed_pages = []
    cache_hits = 0

    async def ocr_one_page(page):
        nonlocal cache_hits
        versioned_path = storage.make_ocr_path_versioned(
            org_id, pack_id, page.page_number, ocr_version_hash
        )
        try:
            # Check versioned cache first
            if await storage.exists(versioned_path):
                cached = json.loads(await storage.read(versioned_path))
                page.ocr_text = cached["text"]
                page.ocr_uri = versioned_path
                cache_hits += 1
                return

            image_data = await storage.read(page.image_uri)
            # Tesseract is synchronous — run in thread pool
            ocr_result = await asyncio.to_thread(agent.extract_text, image_data)
            page.ocr_text = ocr_result["text"]
            await storage.save(versioned_path, json.dumps(ocr_result).encode())
            page.ocr_uri = versioned_path
            log.info(f"Page {page.page_number} done ({pages_needing_ocr.index(page) + 1}/{len(pages_needing_ocr)})")
        except Exception as e:
            failed_pages.append(page.page_number)
            log.warning(f"Failed for page {page.page_number}: {e}")
            page.ocr_text = ""

    # Process in concurrent batches
    for i in range(0, len(pages_needing_ocr), OCR_BATCH_SIZE):
        batch = pages_needing_ocr[i:i + OCR_BATCH_SIZE]
        await asyncio.gather(*[ocr_one_page(p) for p in batch])

    await db.commit()

    succeeded = len(pages_needing_ocr) - len(failed_pages)
    if succeeded == 0 and len(pages_needing_ocr) > 0:
        raise RuntimeError(f"OCR failed for all {len(pages_needing_ocr)} pages")

    if cache_hits:
        log.info(f"{cache_hits} pages served from versioned cache")
    if failed_pages:
        log.warning(f"{succeeded}/{len(pages_needing_ocr)} pages succeeded. Failed: {failed_pages}")
    else:
        log.info(f"All {len(pages_needing_ocr)} Tesseract pages succeeded")


async def stage_index(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage):
    """Chunk OCR text into TextChunk records for search using hierarchical chunker."""
    from app.micro_apps.title_intelligence.services.chunker import chunk_text

    # Clear existing chunks for idempotent retry
    await db.execute(delete(TextChunk).where(TextChunk.pack_id == pack_id, TextChunk.org_id == org_id))

    result = await db.execute(
        select(Page).where(Page.pack_id == pack_id, Page.org_id == org_id).order_by(Page.page_number)
    )
    pages = list(result.scalars().all())

    chunk_count = 0
    for page in pages:
        if not page.ocr_text:
            continue
        # Hierarchical chunking: paragraph → sentence → character with overlap
        chunks = chunk_text(page.ocr_text, chunk_size=500, overlap=50)
        for chunk_content in chunks:
            if len(chunk_content.strip()) < 10:
                continue
            db.add(TextChunk(
                pack_id=pack_id,
                org_id=org_id,
                page_number=page.page_number,
                content=chunk_content,
            ))
            chunk_count += 1

    await db.commit()
    get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="index").info(f"Created {chunk_count} text chunks")


def _serialize_ingestion_output(sections: list[Any], extractions: list[Any]) -> bytes:
    """Serialize Section and Extraction ORM objects to JSON for caching."""
    sections_dicts = [
        {
            "section_type": s.section_type,
            "start_page": s.start_page,
            "end_page": s.end_page,
            "confidence": s.confidence,
        }
        for s in sections
    ]
    extractions_dicts = [
        {
            "extraction_type": e.extraction_type,
            "label": e.label,
            "value": e.value,
            "evidence_refs": e.evidence_refs or [],
            "section_type": e.section.section_type if e.section else None,
            "section_start_page": e.section.start_page if e.section else None,
            "confidence": e.confidence,
        }
        for e in extractions
    ]
    return json.dumps({"sections": sections_dicts, "extractions": extractions_dicts}, sort_keys=True).encode("utf-8")


def _serialize_ingestion_dicts(sections_dicts: list[dict], extractions_dicts: list[dict]) -> bytes:
    """Serialize already-dict sections/extractions to JSON for hashing."""
    return json.dumps({"sections": sections_dicts, "extractions": extractions_dicts}, sort_keys=True).encode("utf-8")


async def _replay_ingestion_cache(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, cached_data: dict
) -> None:
    """Insert sections and extractions from cached JSON into the database."""
    # Delete existing for idempotent replay
    await db.execute(delete(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    await db.execute(delete(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))

    # Insert sections, building a mapping for FK linking
    section_map: dict[tuple[str, int], uuid.UUID] = {}
    for s in cached_data["sections"]:
        section_id = uuid.uuid4()
        section_map[(s["section_type"], s["start_page"])] = section_id
        db.add(Section(
            id=section_id,
            pack_id=pack_id,
            org_id=org_id,
            section_type=s["section_type"],
            start_page=s["start_page"],
            end_page=s["end_page"],
            confidence=s.get("confidence", 0.0),
        ))

    # Insert extractions, linking to sections via type+page mapping
    for e in cached_data["extractions"]:
        section_id = None
        if e.get("section_type") and e.get("section_start_page") is not None:
            section_id = section_map.get((e["section_type"], e["section_start_page"]))
        db.add(Extraction(
            pack_id=pack_id,
            org_id=org_id,
            extraction_type=e["extraction_type"],
            label=e["label"],
            value=e["value"],
            evidence_refs=e.get("evidence_refs", []),
            section_id=section_id,
            confidence=e.get("confidence", 0.0),
        ))


def _serialize_risk_output(flags: list[Any]) -> bytes:
    """Serialize Flag ORM objects to JSON for caching (post-normalization)."""
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
    return json.dumps(flags_dicts, sort_keys=True).encode("utf-8")


def _compute_flags_hash(flags: list[Any]) -> str:
    """Compute a deterministic hash of flag ORM objects for cache keying."""
    import hashlib
    return hashlib.sha256(_serialize_risk_output(flags)).hexdigest()


async def _replay_risk_cache(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID, cached_flags: list[dict]
) -> None:
    """Insert flags from cached JSON into the database."""
    for f in cached_flags:
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


async def stage_ingestion_agent(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """AI-powered section detection and data extraction using tool-calling.

    Caches output keyed by (file content hash + model + prompt hash + tool schema hash).
    On cache hit, replays cached sections/extractions without calling the LLM.
    """
    from app.micro_apps.title_intelligence.ai.ingestion_agent import IngestionAgent
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_input_file_hash,
        compute_ingestion_cache_key,
    )
    from app.config import get_settings

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="ingestion_agent")

    # Get page text for prefetched mode decision
    result = await db.execute(
        select(Page).where(Page.pack_id == pack_id, Page.org_id == org_id).order_by(Page.page_number)
    )
    pages = list(result.scalars().all())
    pages_text = [
        {"page_number": p.page_number, "text": p.ocr_text or ""}
        for p in pages if p.ocr_text
    ]

    # Compute cache key
    settings = get_settings()
    version_info = collect_version_info(settings)
    files_result = await db.execute(
        select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
    )
    pack_files = list(files_result.scalars().all())
    input_file_hash = await compute_input_file_hash(storage, org_id, pack_files)
    cache_key = compute_ingestion_cache_key(input_file_hash, version_info)
    cache_path = storage.make_ai_cache_path(org_id, pack_id, "ingestion", cache_key)

    # Check cache
    if await storage.exists(cache_path):
        cached_data = json.loads(await storage.read(cache_path))
        await _replay_ingestion_cache(db, org_id, pack_id, cached_data)
        await db.commit()
        s_count = len(cached_data.get("sections", []))
        e_count = len(cached_data.get("extractions", []))
        log.info(f"AI cache hit — replayed {s_count} sections, {e_count} extractions")
        return

    # Cache miss — run AI agent
    agent = IngestionAgent(org_id)
    await agent.analyze_with_tools(db, pack_id, storage, pages_text=pages_text)
    await db.flush()

    # Query results and save to cache
    sec_result = await db.execute(
        select(Section).where(Section.pack_id == pack_id, Section.org_id == org_id)
    )
    sections = list(sec_result.scalars().all())
    ext_result = await db.execute(
        select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
    )
    extractions = list(ext_result.scalars().all())

    cache_bytes = _serialize_ingestion_output(sections, extractions)
    try:
        await storage.save(cache_path, cache_bytes)
    except Exception as e:
        log.warning(f"Failed to write ingestion cache (non-fatal): {e}")

    await db.commit()
    log.info(f"AI cache miss — saved {len(sections)} sections, {len(extractions)} extractions to cache")


async def stage_risk_agent(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """AI-powered risk analysis using tool-calling, with deterministic post-processing.

    Caches normalized output keyed by (ingestion output hash + model + prompt hash + tool hash + rules version).
    On cache hit, replays cached flags without calling the LLM or re-running normalization.
    """
    from app.micro_apps.title_intelligence.ai.risk_agent import RiskAgent
    from app.micro_apps.title_intelligence.services.flag_rules import normalize_flags
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_ingestion_output_hash,
        compute_risk_cache_key,
    )
    from app.config import get_settings

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="risk_agent")

    # Clear for idempotent retry
    await db.execute(delete(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))

    # Compute cache key from ingestion output
    settings = get_settings()
    version_info = collect_version_info(settings)

    sec_result = await db.execute(
        select(Section).where(Section.pack_id == pack_id, Section.org_id == org_id)
    )
    sections = list(sec_result.scalars().all())
    ext_result = await db.execute(
        select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id)
    )
    extractions = list(ext_result.scalars().all())

    sections_dicts = [
        {"section_type": s.section_type, "start_page": s.start_page, "end_page": s.end_page, "confidence": s.confidence}
        for s in sections
    ]
    extractions_dicts = [
        {
            "extraction_type": e.extraction_type, "label": e.label, "value": e.value,
            "evidence_refs": e.evidence_refs or [], "confidence": e.confidence,
        }
        for e in extractions
    ]
    ingestion_output_hash = compute_ingestion_output_hash(sections_dicts, extractions_dicts)
    cache_key = compute_risk_cache_key(ingestion_output_hash, version_info)
    cache_path = storage.make_ai_cache_path(org_id, pack_id, "risk", cache_key)

    # Check cache
    if await storage.exists(cache_path):
        cached_flags = json.loads(await storage.read(cache_path))
        await _replay_risk_cache(db, org_id, pack_id, cached_flags)
        await db.commit()
        log.info(f"AI cache hit — replayed {len(cached_flags)} flags (post-normalization)")
        return

    # Cache miss — run AI agent
    agent = RiskAgent(org_id)
    await agent.analyze_with_tools(db, pack_id, storage)
    await db.flush()

    # --- Deterministic rule engine post-processing ---
    result = await db.execute(
        select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)
    )
    raw_flags = list(result.scalars().all())

    # Convert ORM objects to dicts for normalization
    raw_dicts = [
        {
            "id": f.id,
            "flag_type": f.flag_type,
            "severity": f.severity,
            "title": f.title,
            "description": f.description,
            "ai_explanation": f.ai_explanation,
            "evidence_refs": f.evidence_refs or [],
        }
        for f in raw_flags
    ]

    normalized = normalize_flags(raw_dicts)
    normalized_ids = {f["id"] for f in normalized if "id" in f}

    # Delete flags that were dropped by normalization
    for f in raw_flags:
        if f.id not in normalized_ids:
            await db.delete(f)

    # Update severities that changed
    normalized_by_id = {f["id"]: f for f in normalized if "id" in f}
    for f in raw_flags:
        if f.id in normalized_by_id:
            new_sev = normalized_by_id[f.id]["severity"]
            if f.severity != new_sev:
                f.severity = new_sev

    await db.flush()

    # Query final normalized flags and save to cache
    final_result = await db.execute(
        select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id)
    )
    final_flags = list(final_result.scalars().all())
    cache_bytes = _serialize_risk_output(final_flags)
    try:
        await storage.save(cache_path, cache_bytes)
    except Exception as e:
        log.warning(f"Failed to write risk cache (non-fatal): {e}")

    await db.commit()
    log.info(f"AI cache miss — {len(raw_flags)} raw flags → {len(final_flags)} after rules, saved to cache")


async def stage_complete(pack_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession, storage: StorageProvider):
    """Calculate readiness score and generate summary.

    Caches the AI-generated summary keyed by (extractions + flags + readiness score + model).
    On cache hit, skips the LLM call entirely.
    """
    from app.micro_apps.title_intelligence.ai.report_agent import ReportAgent
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_ingestion_output_hash,
        compute_summary_cache_key,
    )
    from app.config import get_settings

    log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage="complete")

    # Readiness score is deterministic (pure rules) — always recompute
    readiness = await calculate_readiness(db, org_id, pack_id)

    pack = (await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )).scalar_one()

    pack.readiness_score = readiness.score

    # Load extractions and flags for cache key + potential LLM call
    ext_result = await db.execute(select(Extraction).where(Extraction.pack_id == pack_id, Extraction.org_id == org_id))
    extractions = list(ext_result.scalars().all())
    flag_result = await db.execute(select(Flag).where(Flag.pack_id == pack_id, Flag.org_id == org_id))
    flags = list(flag_result.scalars().all())

    # Compute cache key from ingestion output + flags + readiness score + model
    settings = get_settings()
    version_info = collect_version_info(settings)

    sections_result = await db.execute(select(Section).where(Section.pack_id == pack_id, Section.org_id == org_id))
    sections = list(sections_result.scalars().all())

    ingestion_output_hash = compute_ingestion_output_hash(
        [{"section_type": s.section_type, "start_page": s.start_page, "end_page": s.end_page, "confidence": s.confidence} for s in sections],
        [{"extraction_type": e.extraction_type, "label": e.label, "value": e.value, "evidence_refs": e.evidence_refs or [], "confidence": e.confidence} for e in extractions],
    )
    risk_output_hash = _compute_flags_hash(flags)
    cache_key = compute_summary_cache_key(ingestion_output_hash, risk_output_hash, readiness.score, version_info)
    cache_path = storage.make_ai_cache_path(org_id, pack_id, "summary", cache_key)

    # Check cache
    if await storage.exists(cache_path):
        cached = json.loads(await storage.read(cache_path))
        pack.readiness_summary = cached["summary"]
        await db.commit()
        log.info(f"AI cache hit — readiness score: {readiness.score}, summary replayed from cache")
        return

    # Cache miss — generate summary via LLM
    agent = ReportAgent(org_id)
    summary = await agent.generate_summary(
        pack_name=pack.name,
        extractions=extractions,
        flags=flags,
        readiness_score=readiness.score,
    )
    pack.readiness_summary = summary.strip()

    # Save to cache
    try:
        cache_bytes = json.dumps({"summary": pack.readiness_summary}).encode("utf-8")
        await storage.save(cache_path, cache_bytes)
    except Exception as e:
        log.warning(f"Failed to write summary cache (non-fatal): {e}")

    await db.commit()
    log.info(f"AI cache miss — readiness score: {readiness.score}, summary generated and cached")

    # Pre-generate all export reports so downloads are instant
    try:
        from app.micro_apps.title_intelligence.services.report_service import pregenerate_reports
        log.info("Pre-generating export reports...")
        await pregenerate_reports(db, org_id, pack_id, storage)
        log.info("Export reports pre-generated")
    except Exception:
        log.warning("Failed to pre-generate reports (non-fatal)", exc_info=True)
