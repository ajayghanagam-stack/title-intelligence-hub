"""Pipeline stages for Loan Onboarding.

Each stage is a pure async function that operates against a single DB session
and the configured storage provider. Stages are idempotent (delete-then-insert
for derived rows) so retries and replays produce identical output.

The 5 stages: ingest → classify → stack → validate → review.

Only `stage_ingest` is fully implemented in Phase 4. The AI stages (classify,
validate, review) and the deterministic stack stage are wired up in later
phases — they currently raise `NotImplementedError` so the orchestrator will
clearly fail a pipeline run if called before those phases land.
"""
import json
import uuid

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.extraction import LOExtraction
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.services.stacking import (
    ClassifiedPage,
    build_stacks,
)
from app.micro_apps.loan_onboarding.services.page_assignment import (
    EffectiveClassification,
    load_effective_classifications,
)
from app.micro_apps.loan_onboarding.services.validation_presets import (
    StackFacts,
    StackPageFacts,
    evaluate_all_presets,
)
from app.micro_apps.loan_onboarding.services.confidence_scorer import (
    ConfidenceInputs,
    blend_confidence,
    split_accuracy_from_roles,
    validation_score_from_rules,
)
from app.services.storage import StorageProvider


def _lo_cache_path(org_id: str, package_id: str, stage: str, cache_key: str) -> str:
    """LO AI cache path — package-scoped (not org-scoped).

    Why this isn't `storage.make_ai_cache_path()`: the shared helper writes
    under `{org_id}/ai_cache/...` so that re-uploads of identical content
    across packages hit the cache. TI/TSA rely on that. LO deliberately
    doesn't, because when an operator deletes a loan file they expect the
    re-uploaded copy to run through the pipeline fresh — not snap back to
    cached results in milliseconds. Anchoring the cache under
    `{org_id}/{package_id}/ai_cache/` means `delete_dir({org_id}/{package_id})`
    in `package_service.delete_package` wipes it for free.
    """
    return f"{org_id}/{package_id}/ai_cache/{stage}/v_{cache_key[:12]}.json"


# Heuristic blank-page threshold — matches the TI pipeline value
HEURISTIC_BLANK_THRESHOLD = 20

# Phase 2 hallucination guardrail: scanned/image-only pages with effectively
# no embedded text (PyMuPDF text_length < HEURISTIC_BLANK_THRESHOLD) have
# historically produced confident-but-wrong classifications (e.g. labeling a
# VA Certificate of Eligibility page as "voe" at 0.99 because the model
# matched on visual layout alone). We clamp the LLM's confidence on these
# pages to a hard ceiling so the page's stack lands below the default HITL
# threshold (0.75) and an operator confirms the call.
HALLUCINATION_CONFIDENCE_CEILING = 0.30

# Per-classify-chunk page count — split large packages for parallelism.
# Kept conservative (20) because image-heavy scanned pages can blow Gemini's
# output token budget at higher counts. On failure, the classifier agent
# split-retries down to single pages, so this is just the happy-path size.
CLASSIFY_CHUNK_SIZE = 20

# Hybrid ingest: when a page has no embedded text, render a tiny pixmap and
# treat the page as image-bearing if the fraction of non-white pixels exceeds
# this threshold. Catches rasterized-into-PDF scans that do not register as
# image XObjects. Kept intentionally low so single-line faxes still qualify.
IMAGE_PIXMAP_DPI = 36
IMAGE_NONWHITE_FRACTION = 0.02  # 2% of pixels not near-white → page has ink


def _detect_content_signal(page, text_len: int) -> str:
    """Classify a PyMuPDF page as 'text' | 'image' | 'blank'.

    Cheap-first detection:
    1. If embedded text ≥ threshold → "text" (fast path, no rendering).
    2. Else, if the page has any image XObjects → "image".
    3. Else, render a tiny pixmap and call it "image" if more than
       IMAGE_NONWHITE_FRACTION of the pixels are not near-white.
    4. Otherwise "blank".

    Step 3 catches scans stored as raw page streams rather than image
    XObjects — otherwise a common scanner output would be misclassified as
    blank and auto-routed to Others.
    """
    if text_len >= HEURISTIC_BLANK_THRESHOLD:
        return "text"

    try:
        if page.get_images(full=True):
            return "image"
    except Exception:
        # get_images can fail on malformed PDFs; fall through to pixmap check
        pass

    # Tiny pixmap — very cheap at dpi=36 (roughly 300×400 px for US Letter).
    try:
        pix = page.get_pixmap(dpi=IMAGE_PIXMAP_DPI, alpha=False)
    except Exception:
        return "blank"

    try:
        samples = pix.samples  # bytes; 3 bytes per pixel (RGB)
        total_pixels = pix.width * pix.height
        if total_pixels <= 0:
            return "blank"

        # Count pixels meaningfully darker than white. We use a cheap heuristic:
        # any R/G/B channel below 240 (roughly 94%) counts as "ink".
        # Iterating bytes in Python is fast enough at DPI 36 (~120k pixels).
        ink = 0
        # Step by 3 to walk RGB triples
        for i in range(0, len(samples), 3):
            if samples[i] < 240 or samples[i + 1] < 240 or samples[i + 2] < 240:
                ink += 1
        if ink / total_pixels >= IMAGE_NONWHITE_FRACTION:
            return "image"
    finally:
        # Pixmap holds C-level buffers; release explicitly
        pix = None  # noqa: F841

    return "blank"


async def stage_ingest(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
) -> dict:
    """Split every uploaded PDF into LOPage rows with heuristic text extraction.

    This stage is deterministic and does no LLM calls. For each file in the
    package, we open the PDF via PyMuPDF (fitz), extract embedded text
    per-page, and create an LOPage row. Page numbering is global across the
    whole package (1-indexed) so later stages can reason about continuity
    without joining through files.

    Connection lifecycle: this stage takes `session_factory` (not a live
    session) and deliberately uses *two* short-lived sessions sandwiching the
    long-running storage I/O + PyMuPDF parsing — never holds a DB transaction
    open across an `await storage.get_object(...)` call. Holding a transaction
    open across async I/O previously exhausted the connection pool on stage
    when S3 fetches were slow (5 sessions stuck `idle in transaction` for
    16+ minutes → `QueuePool limit reached` on every other request).

    Idempotent: any existing LOPage rows for this package are deleted first.
    """
    log = get_logger(__name__, org_id=org_id, pack_id=package_id, stage="ingest")

    # Phase 1: short-lived read session — snapshot file metadata into plain
    # values, then close. After this `async with` exits, the connection is
    # released back to the pool.
    async with session_factory() as db:
        file_rows = (await db.execute(
            select(LOPackageFile)
            .where(LOPackageFile.package_id == package_id, LOPackageFile.org_id == org_id)
            .order_by(LOPackageFile.created_at.asc(), LOPackageFile.filename.asc())
        )).scalars().all()
        if not file_rows:
            raise ValueError("No files uploaded to this package")
        file_specs = [
            {"id": f.id, "storage_path": f.storage_path, "filename": f.filename}
            for f in file_rows
        ]

    # Phase 2: no DB session held. Verify storage existence, fetch bytes, and
    # parse with PyMuPDF in memory. Pages are accumulated as plain dicts and
    # bulk-inserted in Phase 3 below.
    for f in file_specs:
        if not await storage.exists(f["storage_path"]):
            raise FileNotFoundError(f"File not found in storage: {f['storage_path']}")

    import fitz  # pymupdf — imported here so test envs without fitz can still import the module

    page_rows: list[dict] = []
    global_page_num = 0
    total_text_chars = 0
    text_count = 0
    image_count = 0
    blank_count = 0

    for f in file_specs:
        content = await storage.get_object(f["storage_path"])
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            raise ValueError(f"Failed to open PDF '{f['filename']}': {e}") from e

        try:
            for source_idx in range(doc.page_count):
                global_page_num += 1
                page = doc.load_page(source_idx)
                text = page.get_text("text") or ""
                text_len = len(text.strip())
                total_text_chars += text_len

                signal = _detect_content_signal(page, text_len)
                if signal == "text":
                    text_count += 1
                elif signal == "image":
                    image_count += 1
                else:
                    blank_count += 1

                page_rows.append({
                    "org_id": org_id,
                    "package_id": package_id,
                    "file_id": f["id"],
                    "page_number": global_page_num,
                    "source_page_number": source_idx + 1,
                    "heuristic_text": text,
                    "text_length": text_len,
                    "content_signal": signal,
                })
        finally:
            doc.close()

    # Phase 3: short-lived write session — wipe any previous ingest output and
    # bulk-insert the new pages in one transaction.
    async with session_factory() as db:
        await db.execute(
            delete(LOPage).where(
                LOPage.package_id == package_id, LOPage.org_id == org_id
            )
        )
        for row in page_rows:
            db.add(LOPage(**row))
        await db.commit()

    log.info(
        f"Ingested {global_page_num} pages from {len(file_specs)} file(s); "
        f"{text_count} text, {image_count} image-bearing, {blank_count} blank"
    )
    return {
        "files": len(file_specs),
        "pages": global_page_num,
        "text_pages": text_count,
        "image_pages": image_count,
        "blank_pages": blank_count,
        "total_text_chars": total_text_chars,
    }


async def stage_classify(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
    storage: StorageProvider,
) -> dict:
    """Classify every page into a doc_type via Gemini (Vertex AI when configured).

    Reads LOPages produced by stage_ingest, loads the package doc-type config,
    dispatches the PDF to the classifier (chunked + parallelized for large
    packages), and writes LOClassification rows.

    Uses the hybrid-ingest `content_signal` to decide which pages the LLM sees:
    - "text":  embedded-text pages → sent to Gemini as part of a PDF chunk
    - "image": image-only / scanned pages → also sent to Gemini (vision pass)
    - "blank": no text AND no meaningful image content → deterministically
               assigned predicted_doc_type="Others" with confidence 1.0

    Rows ingested before `content_signal` existed fall back to the legacy
    text-length heuristic (`text_length < HEURISTIC_BLANK_THRESHOLD` → blank).

    Idempotent: any existing LOClassification rows for this package are
    deleted first.
    """
    from app.config import get_settings
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
        OTHERS_KEY,
        PageClassifierAgent,
    )
    from app.micro_apps.loan_onboarding.services.config_resolver import (
        effective_config,
    )

    log = get_logger(__name__, org_id=org_id, pack_id=package_id, stage="classify")

    # Phase 2: resolved org/profile/loan config. ``allowed_doc_type_keys()``
    # is preferred over the per-loan ``LODocTypeConfig`` for shaping the
    # classifier's enum; ``cfg.config_hash`` is folded into the classify
    # cache key so an org-level catalog edit busts dependent slots.
    cfg = await effective_config(db, package_id)

    pages = (await db.execute(
        select(LOPage)
        .where(LOPage.package_id == package_id, LOPage.org_id == org_id)
        .order_by(LOPage.page_number.asc())
    )).scalars().all()
    if not pages:
        raise ValueError("No pages to classify — run ingest first")

    # Prefer resolver-supplied allowed keys (drives auto-classify gating
    # via ``ResolvedDocType.auto_classify_enabled``). Fall back to the
    # per-loan LODocTypeConfig for loans not yet on the catalog model.
    allowed_keys = list(cfg.allowed_doc_type_keys())
    if not allowed_keys:
        config = (await db.execute(
            select(LODocTypeConfig).where(
                LODocTypeConfig.package_id == package_id,
                LODocTypeConfig.org_id == org_id,
            )
        )).scalar_one_or_none()
        if config is None or not config.doc_types:
            raise ValueError("Package has no doc-type configuration — cannot classify")
        allowed_keys = [
            d["key"] for d in config.doc_types
            if isinstance(d, dict) and d.get("key")
        ]
    if not allowed_keys:
        raise ValueError("doc-type config is empty")

    # Hybrid dispatch: text + image pages go to the LLM; only truly-blank
    # pages short-circuit to Others. Rows without content_signal (ingested
    # before that column existed) fall back to the legacy text-length rule.
    def _effective_signal(p: LOPage) -> str:
        if p.content_signal:
            return p.content_signal
        return "text" if (p.text_length or 0) >= HEURISTIC_BLANK_THRESHOLD else "blank"

    content_pages: list[LOPage] = []
    blank_pages: list[LOPage] = []
    image_page_count = 0
    for p in pages:
        sig = _effective_signal(p)
        if sig == "blank":
            blank_pages.append(p)
        else:
            content_pages.append(p)
            if sig == "image":
                image_page_count += 1

    # Idempotent wipe
    await db.execute(
        delete(LOClassification).where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
        )
    )

    # Blank pages → deterministic Others classifications with confidence 1.0
    # (we are certain these are non-content; downstream stack/validate treat
    # them as non-meaningful).
    for p in blank_pages:
        db.add(LOClassification(
            org_id=org_id,
            package_id=package_id,
            page_id=p.id,
            page_number=p.page_number,
            predicted_doc_type=OTHERS_KEY,
            predicted_doc_type_alternatives=[],
            confidence=1.0,
            page_role="unknown",
            detected_fields=[],
        ))

    if content_pages:
        settings = get_settings()
        agent = PageClassifierAgent(
            org_id=org_id,
            allowed_doc_types=allowed_keys,
            model_override=settings.LO_CLASSIFIER_MODEL or None,
        )

        # Deterministic re-run contract: hash the package content + model +
        # prompt + schema + allowed_doc_types and replay from cache if
        # present. Keeps classify output byte-stable across re-runs even
        # though Gemini at temp=0 is only *practically* stable.
        from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
            collect_version_info,
            compute_classify_cache_key,
            compute_package_content_hash,
        )

        version_info = collect_version_info(settings)
        files = (await db.execute(
            select(LOPackageFile).where(
                LOPackageFile.package_id == package_id,
                LOPackageFile.org_id == org_id,
            )
        )).scalars().all()
        content_hash = await compute_package_content_hash(storage, files)
        cache_key = compute_classify_cache_key(
            content_hash,
            allowed_keys,
            version_info,
            effective_config_hash=cfg.config_hash,
        )
        cache_path = _lo_cache_path(org_id, package_id, "lo_classify", cache_key)

        cached_classifications: list | None = None
        if await storage.exists(cache_path):
            try:
                raw_json = await storage.get_object(cache_path)
                cached_classifications = json.loads(raw_json)["classifications"]
                log.info(
                    f"classify cache HIT ({cache_key[:12]}…): replaying "
                    f"{len(cached_classifications)} cached classifications"
                )
            except Exception as e:
                log.warning(f"classify cache read failed ({cache_key[:12]}…): {e}; falling through to LLM")
                cached_classifications = None

        if cached_classifications is None:
            # Build chunked PDFs keyed by global page number
            chunks = await _build_classify_chunks(db, storage, org_id, content_pages)

            result = await agent.classify_pdf_chunked(
                pdf_bytes_per_chunk=chunks,
                concurrency=4,
            )
            # Persist a canonical serialization for future replays. Keys
            # are sorted for byte-stable storage.
            serialized = {
                "classifications": [
                    {
                        "page_number": c.page_number,
                        "predicted_doc_type": c.predicted_doc_type,
                        "predicted_doc_type_alternatives": [
                            a.model_dump() for a in c.predicted_doc_type_alternatives
                        ],
                        "confidence": c.confidence,
                        "page_role": c.page_role,
                        "detected_fields": [f.model_dump() for f in c.detected_fields],
                    }
                    for c in result.classifications
                ],
            }
            try:
                await storage.put_object(
                    cache_path,
                    json.dumps(serialized, sort_keys=True).encode("utf-8"),
                    content_type="application/json",
                )
                log.info(f"classify cache MISS ({cache_key[:12]}…): stored {len(result.classifications)} classifications")
            except Exception as e:
                log.warning(f"classify cache write failed ({cache_key[:12]}…): {e}")
            classifications_iter = [
                {
                    "page_number": c.page_number,
                    "predicted_doc_type": c.predicted_doc_type,
                    "predicted_doc_type_alternatives": [
                        a.model_dump() for a in c.predicted_doc_type_alternatives
                    ],
                    "confidence": c.confidence,
                    "page_role": c.page_role,
                    "detected_fields": [f.model_dump() for f in c.detected_fields],
                }
                for c in result.classifications
            ]
        else:
            classifications_iter = cached_classifications

        # Map page_number → LOPage for FK lookup
        pages_by_num = {p.page_number: p for p in content_pages}
        guard_clamped = 0
        for clf in classifications_iter:
            page_num = clf["page_number"]
            page = pages_by_num.get(page_num)
            if page is None:
                log.warning(f"Classifier returned unknown page_number={page_num}, skipping")
                continue

            confidence = clf["confidence"]
            # Phase 2 hallucination guardrail. A scanned/image-only page with
            # effectively no embedded text has no textual signal — the model
            # is guessing from visual layout alone, which produces the worst
            # known failure mode (high-confidence wrong label, e.g. VA COE →
            # "voe" at 0.99). Clamp the confidence so the stack drops below
            # the HITL threshold and an operator confirms. Real Others/blank
            # pages were already short-circuited above.
            is_image_only = (page.content_signal == "image")
            is_text_empty = (page.text_length or 0) < HEURISTIC_BLANK_THRESHOLD
            if is_image_only and is_text_empty and confidence > HALLUCINATION_CONFIDENCE_CEILING:
                guard_clamped += 1
                log.info(
                    f"hallucination guard: page {page_num} "
                    f"({clf['predicted_doc_type']} @ {confidence:.2f}) "
                    f"clamped to {HALLUCINATION_CONFIDENCE_CEILING} "
                    f"(content_signal=image, text_length={page.text_length or 0})"
                )
                confidence = HALLUCINATION_CONFIDENCE_CEILING

            db.add(LOClassification(
                org_id=org_id,
                package_id=package_id,
                page_id=page.id,
                page_number=page_num,
                predicted_doc_type=clf["predicted_doc_type"],
                predicted_doc_type_alternatives=clf.get("predicted_doc_type_alternatives") or [],
                confidence=confidence,
                page_role=clf["page_role"],
                detected_fields=clf.get("detected_fields") or [],
            ))
        if guard_clamped:
            log.info(
                f"hallucination guard fired on {guard_clamped}/"
                f"{len(classifications_iter)} pages"
            )

    await db.flush()
    log.info(
        f"Classified {len(content_pages)} content pages "
        f"({image_page_count} image-bearing), "
        f"{len(blank_pages)} blank pages auto-assigned Others"
    )
    return {
        "pages": len(pages),
        "content_pages": len(content_pages),
        "image_pages": image_page_count,
        "blank_pages": len(blank_pages),
    }


async def _build_classify_chunks(
    db: AsyncSession,
    storage: StorageProvider,
    org_id: uuid.UUID,
    content_pages: list[LOPage],
) -> list[tuple[bytes, list[int]]]:
    """Return a list of (pdf_bytes, global_page_numbers) chunks.

    Pages from different source files are never mixed within a chunk — we
    build the PDF by copying pages from the original PDFs in order, preserving
    the package-level global numbering.
    """
    if not content_pages:
        return []

    import fitz  # pymupdf

    # Group content pages by file_id so we can open each source PDF once.
    file_ids = list({p.file_id for p in content_pages})
    files = (await db.execute(
        select(LOPackageFile).where(LOPackageFile.id.in_(file_ids))
    )).scalars().all()
    files_by_id = {f.id: f for f in files}

    chunks: list[tuple[bytes, list[int]]] = []

    for i in range(0, len(content_pages), CLASSIFY_CHUNK_SIZE):
        batch = content_pages[i:i + CLASSIFY_CHUNK_SIZE]
        # Build a combined PDF from the source files, preserving page order
        combined = fitz.open()
        try:
            # Group contiguous pages from the same file for efficient insert_pdf copies
            current_file_id: uuid.UUID | None = None
            current_source_doc = None
            for p in batch:
                file_row = files_by_id.get(p.file_id)
                if file_row is None:
                    continue
                if p.file_id != current_file_id:
                    # Close previous, open new source
                    if current_source_doc is not None:
                        current_source_doc.close()
                    content = await storage.get_object(file_row.storage_path)
                    current_source_doc = fitz.open(stream=content, filetype="pdf")
                    current_file_id = p.file_id

                # source_page_number is 1-indexed; insert_pdf uses 0-indexed ranges
                src_idx = p.source_page_number - 1
                combined.insert_pdf(current_source_doc, from_page=src_idx, to_page=src_idx)

            if current_source_doc is not None:
                current_source_doc.close()

            pdf_bytes = combined.tobytes()
        finally:
            combined.close()

        global_nums = [p.page_number for p in batch]
        chunks.append((pdf_bytes, global_nums))

    return chunks


async def stage_stack(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
    storage: StorageProvider,
) -> dict:
    """Group contiguous pages of the same doc_type into LOStack rows.

    Deterministic — no LLM calls. Reads LOClassification rows, groups by the
    rules in `services.stacking.build_stacks`, and writes LOStack rows.

    Idempotent: any existing LOStack rows for this package are deleted first.
    """
    log = get_logger(__name__, org_id=org_id, pack_id=package_id, stage="stack")

    # Load the package to pick up its hitl_threshold override
    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == package_id, LOPackage.org_id == org_id
        )
    )).scalar_one_or_none()
    if pkg is None:
        raise ValueError(f"Package {package_id} not found")

    # Merged view: ML classifications + reviewer overrides (if any). When no
    # overrides exist this is equivalent to reading LOClassification directly.
    effective = await load_effective_classifications(db, org_id, package_id)
    if not effective:
        raise ValueError("No classifications to stack — run classify first")

    # Idempotent wipe
    await db.execute(
        delete(LOStack).where(
            LOStack.package_id == package_id, LOStack.org_id == org_id
        )
    )

    drafts = build_stacks(
        [
            ClassifiedPage(
                page_number=e.page_number,
                predicted_doc_type=e.doc_type,
                confidence=e.confidence,
                page_role=e.page_role,
            )
            for e in effective
        ],
        hitl_threshold=pkg.hitl_threshold,
    )

    for draft in drafts:
        db.add(LOStack(
            org_id=org_id,
            package_id=package_id,
            stack_index=draft.stack_index,
            doc_type=draft.doc_type,
            page_numbers=draft.page_numbers,
            first_page=draft.first_page,
            last_page=draft.last_page,
            classification_confidence=draft.classification_confidence,
            status=draft.status,
            requires_hitl=draft.requires_hitl,
        ))

    await db.flush()
    hitl_count = sum(1 for d in drafts if d.requires_hitl)
    log.info(
        f"Built {len(drafts)} stacks from {len(effective)} pages; "
        f"{hitl_count} flagged for HITL"
    )
    return {
        "pages": len(effective),
        "stacks": len(drafts),
        "hitl_stacks": hitl_count,
    }


async def stage_validate(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
    storage: StorageProvider,
) -> dict:
    """Run preset + Claude Sonnet validation over every stack.

    Per stack we:
    1. Evaluate every enabled preset rule deterministically
    2. Evaluate every enabled custom (NL) rule via StackValidatorAgent
    3. Compute ConfidenceBreakdown and overall_confidence
    4. Write an LOValidationResult row and update LOStack.overall_confidence /
       requires_hitl

    Idempotent: existing LOValidationResult rows are deleted first.
    """
    import asyncio as _asyncio
    from app.config import get_settings
    from app.micro_apps.loan_onboarding.ai.stack_validator_agent import (
        StackValidatorAgent,
    )
    from app.micro_apps.loan_onboarding.services.config_resolver import (
        effective_config,
    )

    log = get_logger(__name__, org_id=org_id, pack_id=package_id, stage="validate")

    # Phase 2: ``cfg.config_hash`` is folded into every per-rule cache key
    # so an org-level rule edit (or profile threshold tighten) busts
    # dependent validate slots. The rule list itself still comes from
    # ``LOValidationRule`` rows for now — the resolver-driven rule wiring
    # ships in a later batch.
    cfg = await effective_config(db, package_id)

    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == package_id, LOPackage.org_id == org_id
        )
    )).scalar_one_or_none()
    if pkg is None:
        raise ValueError(f"Package {package_id} not found")

    stacks = (await db.execute(
        select(LOStack)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()
    if not stacks:
        raise ValueError("No stacks to validate — run stack first")

    rules = (await db.execute(
        select(LOValidationRule)
        .where(
            LOValidationRule.package_id == package_id,
            LOValidationRule.org_id == org_id,
            LOValidationRule.enabled == True,  # noqa: E712
        )
        # Stable sort: preset evals are deterministic but their OUTPUT order
        # flows directly into the `rules_evaluated` JSONB. Without an explicit
        # ORDER BY, Postgres natural row order can vary across runs, causing
        # the persisted JSONB array to drift even when every LLM call is
        # cache-hit. Sort by rule_id for byte-stable rule order across runs.
        .order_by(LOValidationRule.rule_source.asc(), LOValidationRule.rule_id.asc())
    )).scalars().all()

    preset_rules = [
        (r.rule_id, r.config or {}) for r in rules if r.rule_source == "preset"
    ]
    custom_rules = [
        (r.rule_id, r.description or "") for r in rules if r.rule_source == "custom"
    ]

    # Classifications + pages for building StackFacts and NL-rule snippets.
    # Raw LOClassification rows supply `detected_fields` (never overridden).
    # The effective map supplies `page_role` so reviewer overrides of role
    # flow into preset-rule evaluation (split_accuracy_from_roles).
    classifications = (await db.execute(
        select(LOClassification)
        .where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
        )
    )).scalars().all()
    classifications_by_page = {c.page_number: c for c in classifications}
    effective = await load_effective_classifications(db, org_id, package_id)
    effective_by_page = {e.page_number: e for e in effective}

    pages = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id, LOPage.org_id == org_id
        )
    )).scalars().all()
    pages_by_num = {p.page_number: p for p in pages}

    # Idempotent wipe
    await db.execute(
        delete(LOValidationResult).where(
            LOValidationResult.package_id == package_id,
            LOValidationResult.org_id == org_id,
        )
    )

    # Build per-stack StackFacts once
    stack_facts_by_id: dict = {}
    for s in stacks:
        page_facts = []
        for pn in s.page_numbers:
            clf = classifications_by_page.get(pn)
            eff = effective_by_page.get(pn)
            field_names = frozenset(
                str(f.get("field_name"))
                for f in ((clf.detected_fields if clf else []) or [])
                if isinstance(f, dict) and f.get("field_name")
            )
            page_facts.append(StackPageFacts(
                page_number=pn,
                page_role=(eff.page_role if eff else (clf.page_role if clf else "unknown")),
                detected_field_names=field_names,
            ))
        stack_facts_by_id[s.id] = StackFacts(
            stack_id=str(s.id),
            doc_type=s.doc_type,
            pages=tuple(page_facts),
        )

    # Dispatch NL rules in parallel (if any)
    nl_evaluations_by_stack: dict = {s.id: [] for s in stacks}
    if custom_rules:
        from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
            collect_version_info,
            compute_stack_content_hash,
            compute_validate_rule_cache_key,
        )
        from app.micro_apps.loan_onboarding.schemas.validation import (
            RuleEvaluation,
            RuleLocation,
        )

        settings = get_settings()
        version_info = collect_version_info(settings)
        agent = StackValidatorAgent(
            org_id=org_id,
            model_override=settings.LO_VALIDATOR_MODEL or None,
        )
        sem = _asyncio.Semaphore(4)

        def _build_snippets(stack) -> list[dict]:
            snippets = []
            for pn in stack.page_numbers:
                pg = pages_by_num.get(pn)
                clf = classifications_by_page.get(pn)
                snippets.append({
                    "page_number": pn,
                    "text": (pg.heuristic_text or "")[:3000] if pg else "",
                    "detected_fields": (clf.detected_fields if clf else []) or [],
                })
            return snippets

        def _serialize_eval(ev: RuleEvaluation) -> dict:
            return {
                "rule_id": ev.rule_id,
                "rule_source": ev.rule_source,
                "passed": ev.passed,
                "evidence": ev.evidence,
                "location": ev.location.model_dump() if ev.location else None,
            }

        def _deserialize_eval(d: dict) -> RuleEvaluation:
            loc = d.get("location")
            location = None
            if isinstance(loc, dict):
                bbox = loc.get("bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    location = RuleLocation(
                        page=int(loc.get("page", 1)),
                        bbox=[float(x) for x in bbox],
                    )
            return RuleEvaluation(
                rule_id=str(d["rule_id"]),
                rule_source=d.get("rule_source", "custom"),
                passed=bool(d.get("passed", False)),
                evidence=str(d.get("evidence") or ""),
                location=location,
            )

        async def _run_custom(stack, rule_id: str, rule_text: str):
            async with sem:
                snippets = _build_snippets(stack)
                # Per-rule, per-stack content-hash cache. Keyed by stack
                # semantic content + rule text + model/prompt/schema so
                # unchanged rules get a cache hit on re-run.
                stack_hash = compute_stack_content_hash(stack.doc_type, snippets)
                cache_key = compute_validate_rule_cache_key(
                    stack_hash,
                    rule_id,
                    rule_text,
                    version_info,
                    effective_config_hash=cfg.config_hash,
                )
                cache_path = _lo_cache_path(
                    org_id, package_id, "lo_validate_rule", cache_key
                )

                if await storage.exists(cache_path):
                    try:
                        raw_json = await storage.get_object(cache_path)
                        ev = _deserialize_eval(json.loads(raw_json))
                        log.info(
                            f"validate cache HIT stack={stack.stack_index} "
                            f"rule={rule_id} ({cache_key[:12]}…)"
                        )
                        return stack.id, ev
                    except Exception as e:
                        log.warning(
                            f"validate cache read failed ({cache_key[:12]}…): {e}; "
                            f"falling through to LLM"
                        )

                ev = await agent.validate_rule(
                    stack_id=str(stack.id),
                    doc_type=stack.doc_type,
                    page_snippets=snippets,
                    rule_id=rule_id,
                    rule_text=rule_text,
                )
                try:
                    await storage.put_object(
                        cache_path,
                        json.dumps(_serialize_eval(ev), sort_keys=True).encode("utf-8"),
                        content_type="application/json",
                    )
                except Exception as e:
                    log.warning(f"validate cache write failed ({cache_key[:12]}…): {e}")
                return stack.id, ev

        tasks = [
            _run_custom(s, rid, rtext)
            for s in stacks
            for rid, rtext in custom_rules
        ]
        # Use as_completed for responsive dispatch, but sort per-stack by
        # rule_id afterwards so the rules_evaluated list is byte-stable
        # regardless of which rule finished first.
        for coro in _asyncio.as_completed(tasks):
            stack_id, evaluation = await coro
            nl_evaluations_by_stack[stack_id].append(evaluation)
        for sid in nl_evaluations_by_stack:
            nl_evaluations_by_stack[sid].sort(key=lambda ev: ev.rule_id)

    # Build LOValidationResult rows
    for s in stacks:
        facts = stack_facts_by_id[s.id]
        preset_evals = evaluate_all_presets(preset_rules, facts)

        rules_evaluated_rows = []
        passed_count = 0
        total_count = 0

        for ev in preset_evals:
            total_count += 1
            if ev.passed:
                passed_count += 1
            rules_evaluated_rows.append({
                "rule_id": ev.rule_id,
                "rule_source": "preset",
                "passed": ev.passed,
                "evidence": ev.evidence,
                "location": (
                    {"page": ev.location_page, "bbox": [0.0, 0.0, 0.0, 0.0]}
                    if ev.location_page is not None
                    else None
                ),
            })

        for nl_ev in nl_evaluations_by_stack.get(s.id, []):
            total_count += 1
            if nl_ev.passed:
                passed_count += 1
            rules_evaluated_rows.append({
                "rule_id": nl_ev.rule_id,
                "rule_source": "custom",
                "passed": nl_ev.passed,
                "evidence": nl_ev.evidence,
                "location": (
                    nl_ev.location.model_dump() if nl_ev.location else None
                ),
            })

        split_score = split_accuracy_from_roles(facts)
        validation_score = validation_score_from_rules(passed_count, total_count)
        overall = blend_confidence(ConfidenceInputs(
            classification=s.classification_confidence,
            split_accuracy=split_score,
            validation=validation_score,
        ))

        needs_hitl = (
            overall < pkg.hitl_threshold
            or passed_count < total_count
            or s.requires_hitl  # preserve Others → HITL from stack stage
        )

        db.add(LOValidationResult(
            org_id=org_id,
            package_id=package_id,
            stack_id=s.id,
            doc_type=s.doc_type,
            rules_evaluated=rules_evaluated_rows,
            confidence_breakdown={
                "classification": round(s.classification_confidence, 6),
                "split_accuracy": round(split_score, 6),
                "validation": round(validation_score, 6),
            },
            overall_confidence=round(overall, 6),
            requires_hitl=needs_hitl,
        ))

        # Update the stack with the post-validate rollup
        s.overall_confidence = round(overall, 6)
        s.requires_hitl = needs_hitl
        s.status = "validated"

    await db.flush()
    hitl_count = sum(
        1 for s in stacks if s.requires_hitl
    )
    log.info(
        f"Validated {len(stacks)} stack(s); {hitl_count} requires HITL. "
        f"Rules: {len(preset_rules)} preset, {len(custom_rules)} custom"
    )
    return {
        "stacks": len(stacks),
        "hitl_stacks": hitl_count,
        "preset_rules": len(preset_rules),
        "custom_rules": len(custom_rules),
    }


async def stage_extract(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
    storage: StorageProvider,
) -> dict:
    """Pull structured fields from each stack via Claude.

    Reads `LOPackage.extraction_enabled` + `extraction_fields_by_doc` to
    decide which doc types are in scope and which field labels to request
    per stack. Skips:
      - the whole stage when `extraction_enabled=False`
      - stacks whose `doc_type` has no configured field list
      - the "Others" bucket (the prototype never extracts from it)

    Idempotent: existing LOExtraction rows are deleted before insert.
    Cached per (stack content + requested fields + model/prompt/schema).
    """
    import asyncio as _asyncio
    from app.config import get_settings
    from app.micro_apps.loan_onboarding.ai.extraction_agent import (
        ExtractionAgent,
        _conservative_fallback,
    )
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
    from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
        collect_version_info,
        compute_extract_cache_key,
        compute_stack_content_hash,
    )
    from app.micro_apps.loan_onboarding.schemas.extraction import (
        ExtractedField,
        FieldLocation,
        StackExtraction,
    )
    from app.micro_apps.loan_onboarding.services.config_resolver import (
        effective_config,
    )
    from app.micro_apps.loan_onboarding.services.ocr_words import (
        ocr_pdf_page,
    )

    log = get_logger(__name__, org_id=org_id, pack_id=package_id, stage="extract")

    # Phase 2: resolve org/profile/loan config once. ``cfg.config_hash`` is
    # folded into every extract cache key so any change to a higher layer
    # (org schema edit, profile threshold tighten, etc.) busts dependent
    # cache slots. ``cfg.schema(doc_type)`` is the preferred source for
    # the per-doc-type field list — falls back to the per-loan
    # ``extraction_fields_by_doc`` for loans without resolved schemas yet.
    cfg = await effective_config(db, package_id)

    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == package_id, LOPackage.org_id == org_id
        )
    )).scalar_one_or_none()
    if pkg is None:
        raise ValueError(f"Package {package_id} not found")

    # Always wipe existing rows up front so toggling off still leaves a
    # clean slate — re-running with extraction_enabled=False yields zero
    # rows, not stale data from a prior run.
    await db.execute(
        delete(LOExtraction).where(
            LOExtraction.package_id == package_id,
            LOExtraction.org_id == org_id,
        )
    )

    if not pkg.extraction_enabled:
        log.info("Extraction disabled for package; skipping stage")
        return {"stacks_extracted": 0, "fields_total": 0, "located_total": 0, "skipped": True}

    # Resolved org/profile schemas take precedence per doc type. For doc
    # types absent from ``cfg.schemas_by_doc_type`` (loans not yet migrated
    # to the catalog model), fall back to the per-loan
    # ``extraction_fields_by_doc`` JSON. Field order is preserved — the
    # extractor emits records in request order and the cache key folds in
    # the ordered tuple.
    cleaned_by_doc: dict[str, list[str]] = {}
    for resolved in cfg.schemas_by_doc_type:
        labels: list[str] = []
        seen: set[str] = set()
        for f in resolved.fields:
            label = (f.label or f.key or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
        if labels:
            cleaned_by_doc[resolved.doc_type_key] = labels

    fields_by_doc: dict[str, list[str]] = pkg.extraction_fields_by_doc or {}
    for k, v in fields_by_doc.items():
        if k in cleaned_by_doc or not isinstance(v, list):
            continue
        seen = set()
        cleaned: list[str] = []
        for label in v:
            label = str(label or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            cleaned.append(label)
        if cleaned:
            cleaned_by_doc[k] = cleaned

    if not cleaned_by_doc:
        log.info("No extraction fields configured; skipping stage")
        return {"stacks_extracted": 0, "fields_total": 0, "located_total": 0, "skipped": True}

    stacks = (await db.execute(
        select(LOStack)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()
    if not stacks:
        log.info("No stacks to extract; skipping stage")
        return {"stacks_extracted": 0, "fields_total": 0, "located_total": 0, "skipped": True}

    # Stacks we'll actually run the agent on.
    targets = [
        s for s in stacks
        if s.doc_type != OTHERS_KEY and s.doc_type in cleaned_by_doc
    ]
    if not targets:
        log.info("No stacks match the extraction config; skipping stage")
        return {"stacks_extracted": 0, "fields_total": 0, "located_total": 0, "skipped": True}

    # Page snippets — same shape the validator uses.
    classifications = (await db.execute(
        select(LOClassification)
        .where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
        )
    )).scalars().all()
    classifications_by_page = {c.page_number: c for c in classifications}
    pages = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id, LOPage.org_id == org_id
        )
    )).scalars().all()
    pages_by_num = {p.page_number: p for p in pages}

    # Group pages by source file for batched PDF reads (avoid re-fetching
    # the same PDF from storage once per page).
    file_ids = list({p.file_id for p in pages})
    files_by_id: dict[uuid.UUID, LOPackageFile] = {}
    if file_ids:
        rows = (await db.execute(
            select(LOPackageFile).where(LOPackageFile.id.in_(file_ids))
        )).scalars().all()
        files_by_id = {f.id: f for f in rows}
    pdf_bytes_cache: dict[uuid.UUID, bytes] = {}

    async def _get_pdf_bytes(file_id: uuid.UUID) -> bytes | None:
        if file_id in pdf_bytes_cache:
            return pdf_bytes_cache[file_id]
        f = files_by_id.get(file_id)
        if f is None or not f.storage_path:
            return None
        try:
            data = await storage.get_object(f.storage_path)
        except Exception as e:
            log.warning("Could not load PDF for file %s: %s", file_id, e)
            return None
        pdf_bytes_cache[file_id] = data
        return data

    def _build_snippets(stack: LOStack) -> list[dict]:
        """Cache-key inputs only — same shape used by ``compute_stack_content_hash``.

        The agent itself no longer consumes snippets (text + detected_fields);
        Phase 1 feeds it ``pages: [{page_number, image_bytes, words}]``. We
        keep snippets purely so the cache key continues to flip when the
        page text changes — bumping ``GROUNDING_CONTRACT_VERSION`` already
        invalidated every pre-v2 cache slot.
        """
        snippets: list[dict] = []
        for pn in stack.page_numbers:
            pg = pages_by_num.get(pn)
            clf = classifications_by_page.get(pn)
            snippets.append({
                "page_number": pn,
                "text": (pg.heuristic_text or "")[:3000] if pg else "",
                "detected_fields": (clf.detected_fields if clf else []) or [],
            })
        return snippets

    async def _build_pages(stack: LOStack) -> list[dict]:
        """Render image + load ocr_words for each page in the stack.

        Output shape: ``[{page_number, image_bytes, words}, ...]`` keyed by
        the *stack-local* page number (1-indexed within the stack's
        ``page_numbers``) so the model's evidence cite is interpretable
        without leaking package-global numbering.

        OCR fallback: if ``LOPage.ocr_words`` is null (legacy row) we
        invoke ``ocr_pdf_page`` JIT and persist the result so the next
        run is a cache hit. If rendering fails the page is silently
        dropped — the validator will mark every field that cited it as
        ``ungrounded``.
        """
        out: list[dict] = []
        for local_idx, pn in enumerate(stack.page_numbers, start=1):
            pg = pages_by_num.get(pn)
            if pg is None:
                continue
            pdf_bytes = await _get_pdf_bytes(pg.file_id)
            if not pdf_bytes:
                continue

            words = pg.ocr_words
            engine = pg.ocr_engine
            if not words:
                jit_words, jit_engine = await ocr_pdf_page(
                    pdf_bytes,
                    pg.source_page_number,
                    org_id=org_id,
                    allow_fallback=True,
                )
                if jit_words:
                    pg.ocr_words = jit_words
                    pg.ocr_engine = jit_engine or "tesseract"
                    db.add(pg)
                    words = jit_words
                    engine = jit_engine
                else:
                    words = []

            # Render the JPEG once for the model.
            from app.micro_apps.loan_onboarding.services.ocr_words import (
                _render_pdf_page_to_jpeg,
            )
            image_bytes = await _asyncio.to_thread(
                _render_pdf_page_to_jpeg,
                pdf_bytes, pg.source_page_number, 200,
            )
            if not image_bytes:
                continue

            out.append({
                "page_number": local_idx,
                "image_bytes": image_bytes,
                "words": words or [],
                "_global_page": pn,
                "_engine": engine,
            })
        return out

    settings = get_settings()
    version_info = collect_version_info(settings)
    agent = ExtractionAgent(
        org_id=org_id,
        model_override=settings.LO_VALIDATOR_MODEL or None,
    )
    sem = _asyncio.Semaphore(4)

    def _serialize(extraction: StackExtraction) -> dict:
        return {
            "stack_id": extraction.stack_id,
            "doc_type": extraction.doc_type,
            "fields": [
                {
                    "name": f.name,
                    "value": f.value,
                    "confidence": f.confidence,
                    "status": f.status,
                    "location": f.location.model_dump() if f.location else None,
                }
                for f in extraction.fields
            ],
        }

    def _deserialize(raw: dict, stack_id: str, doc_type: str) -> StackExtraction:
        out: list[ExtractedField] = []
        for f in raw.get("fields") or []:
            if not isinstance(f, dict):
                continue
            loc_raw = f.get("location")
            location: FieldLocation | None = None
            if isinstance(loc_raw, dict):
                bbox = loc_raw.get("bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    try:
                        evidence = loc_raw.get("evidence_token_indices")
                        if isinstance(evidence, list):
                            evidence = [int(i) for i in evidence]
                        else:
                            evidence = None
                        ocr_count = loc_raw.get("ocr_word_count")
                        ocr_count = int(ocr_count) if isinstance(ocr_count, (int, float)) else None
                        location = FieldLocation(
                            page=int(loc_raw.get("page", 1)),
                            bbox=[float(x) for x in bbox],
                            evidence_token_indices=evidence,
                            ocr_word_count=ocr_count,
                        )
                    except (TypeError, ValueError):
                        location = None
            out.append(ExtractedField(
                name=str(f.get("name", "")),
                value=str(f.get("value") or ""),
                confidence=float(f.get("confidence", 0.0) or 0.0),
                status=f.get("status") or "missing",
                location=location,
            ))
        return StackExtraction(stack_id=stack_id, doc_type=doc_type, fields=out)

    async def _run_one(stack: LOStack):
        async with sem:
            requested = cleaned_by_doc[stack.doc_type]
            snippets = _build_snippets(stack)
            stack_hash = compute_stack_content_hash(stack.doc_type, snippets)
            cache_key = compute_extract_cache_key(
                stack_hash,
                requested,
                version_info,
                effective_config_hash=cfg.config_hash,
            )
            cache_path = _lo_cache_path(
                org_id, package_id, "lo_extract", cache_key
            )

            extraction: StackExtraction | None = None
            if await storage.exists(cache_path):
                try:
                    raw_json = await storage.get_object(cache_path)
                    extraction = _deserialize(
                        json.loads(raw_json), str(stack.id), stack.doc_type
                    )
                    log.info(
                        f"extract cache HIT stack={stack.stack_index} "
                        f"({cache_key[:12]}…)"
                    )
                except Exception as e:
                    log.warning(
                        f"extract cache read failed ({cache_key[:12]}…): {e}; "
                        f"falling through to LLM"
                    )

            if extraction is None:
                stack_pages = await _build_pages(stack)
                if not stack_pages:
                    log.warning(
                        "stack=%s had no renderable pages; emitting all-missing",
                        stack.stack_index,
                    )
                    extraction = _conservative_fallback(
                        str(stack.id), stack.doc_type, requested
                    )
                else:
                    try:
                        extraction = await agent.extract_fields(
                            stack_id=str(stack.id),
                            doc_type=stack.doc_type,
                            pages=stack_pages,
                            requested_fields=requested,
                        )
                    except Exception as e:
                        log.warning(
                            f"ExtractionAgent failed for stack={stack.stack_index}: {e}"
                        )
                        extraction = _conservative_fallback(
                            str(stack.id), stack.doc_type, requested
                        )
                    else:
                        # Remap evidence page (stack-local) → global page
                        # so persisted bboxes are addressable from the
                        # workbench without context.
                        local_to_global = {
                            sp["page_number"]: sp["_global_page"] for sp in stack_pages
                        }
                        for f in extraction.fields:
                            if f.location and f.location.page in local_to_global:
                                f.location.page = local_to_global[f.location.page]
                        try:
                            await storage.put_object(
                                cache_path,
                                json.dumps(_serialize(extraction), sort_keys=True).encode("utf-8"),
                                content_type="application/json",
                            )
                        except Exception as e:
                            log.warning(
                                f"extract cache write failed ({cache_key[:12]}…): {e}"
                            )
            return stack, extraction

    results = await _asyncio.gather(*[_run_one(s) for s in targets])

    fields_total = 0
    located_total = 0
    for stack, extraction in results:
        rows = []
        located = 0
        for f in extraction.fields:
            rows.append({
                "name": f.name,
                "value": f.value,
                "confidence": round(f.confidence, 6),
                "status": f.status,
                "location": f.location.model_dump() if f.location else None,
            })
            # Count any field with a value as "found" for the dashboard
            # tally. After Phase 1: "located" (high-confidence + grounded
            # bbox), "tentative" (mid-confidence + grounded bbox), and
            # "ungrounded" (value extracted but evidence cite failed) all
            # surface a value to the operator. Only "missing" is hidden.
            # ``low_confidence`` is the deprecated alias for tentative kept
            # for one release of cache back-compat.
            if f.status in ("located", "tentative", "ungrounded", "low_confidence"):
                located += 1
        fields_total += len(rows)
        located_total += located
        db.add(LOExtraction(
            org_id=org_id,
            package_id=package_id,
            stack_id=stack.id,
            doc_type=stack.doc_type,
            fields=rows,
            located_count=located,
            total_count=len(rows),
        ))

    await db.flush()
    log.info(
        f"Extracted from {len(targets)} stack(s): "
        f"{located_total}/{fields_total} fields located"
    )
    return {
        "stacks_extracted": len(targets),
        "fields_total": fields_total,
        "located_total": located_total,
        "skipped": False,
    }


async def stage_review(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
    storage: StorageProvider,
) -> dict:
    """Claude Opus cross-doc reasoning + HITL routing.

    Reads every validated stack and runs the ReasoningAgent. Updates each
    stack's `status` to `accepted`, `needs_review`, or `rejected` based on
    the agent's recommendation plus the package-level HITL floor.

    Also updates the package status to `awaiting_review` if any stack
    requires HITL, otherwise `completed`.
    """
    from app.config import get_settings
    from app.micro_apps.loan_onboarding.ai.reasoning_agent import ReasoningAgent
    from app.micro_apps.loan_onboarding.services.config_resolver import (
        effective_config,
    )

    log = get_logger(__name__, org_id=org_id, pack_id=package_id, stage="review")

    # Phase 2: resolved config feeds two places — ``required_doc_types``
    # for the package summary, and ``effective_config_hash`` into the
    # reason cache key.
    cfg = await effective_config(db, package_id)

    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == package_id, LOPackage.org_id == org_id
        )
    )).scalar_one_or_none()
    if pkg is None:
        raise ValueError(f"Package {package_id} not found")

    stacks = (await db.execute(
        select(LOStack)
        .where(LOStack.package_id == package_id, LOStack.org_id == org_id)
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()
    if not stacks:
        raise ValueError("No stacks to review — run validate first")

    # Required doc types: prefer the resolved tuple. For loans not on the
    # catalog model yet, fall back to per-loan LODocTypeConfig.
    resolved_required = [d.key for d in cfg.required_doc_types()]
    if resolved_required:
        required_doc_types = resolved_required
    else:
        config = (await db.execute(
            select(LODocTypeConfig).where(
                LODocTypeConfig.package_id == package_id,
                LODocTypeConfig.org_id == org_id,
            )
        )).scalar_one_or_none()
        required_doc_types = []
        if config and config.doc_types:
            # Defensive lowercase: legacy rows may carry UPPER_SNAKE keys.
            # The ReasoningAgent compares these against stack doc_types
            # (always lowercase) so an unnormalized key produces phantom
            # "missing required document" findings.
            required_doc_types = [
                d["key"].strip().lower()
                for d in config.doc_types
                if isinstance(d, dict)
                and isinstance(d.get("key"), str)
                and d.get("required")
            ]

    # Build a lean package summary for the reasoning agent
    validation_rows = (await db.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == package_id,
            LOValidationResult.org_id == org_id,
        )
    )).scalars().all()
    val_by_stack = {v.stack_id: v for v in validation_rows}

    # Build package summary with STABLE stack keys (stack_index) instead of
    # UUIDs. LOStack rows are wiped-and-rebuilt every run so their UUIDs
    # churn; stack_index is derived from page_numbers and is deterministic.
    # The reasoning cache key depends on this hash, so stable keys = stable
    # cache hits on re-run.
    def _stable_key(s) -> str:
        return f"s{s.stack_index}"

    stacks_by_stable_key = {_stable_key(s): s for s in stacks}

    summary_stacks = []
    for s in stacks:
        val = val_by_stack.get(s.id)
        rules_total = len(val.rules_evaluated) if val else 0
        rules_passed = sum(
            1 for r in (val.rules_evaluated if val else [])
            if isinstance(r, dict) and r.get("passed")
        )
        summary_stacks.append({
            "stack_id": _stable_key(s),
            "doc_type": s.doc_type,
            "first_page": s.first_page,
            "last_page": s.last_page,
            "overall_confidence": s.overall_confidence or s.classification_confidence,
            "rules_passed": rules_passed,
            "rules_total": rules_total,
        })

    package_summary = {
        "hitl_threshold": pkg.hitl_threshold,
        "required_doc_types": sorted(required_doc_types),
        "stacks": summary_stacks,
    }

    settings = get_settings()
    agent = ReasoningAgent(
        org_id=org_id,
        model_override=settings.LO_REASONER_MODEL or None,
    )

    # Reasoning output cache — identical package_summary + model + prompt
    # + schema + rules_version → cache hit → byte-stable decisions.
    from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
        collect_version_info,
        compute_package_summary_hash,
        compute_reason_cache_key,
    )
    from app.micro_apps.loan_onboarding.ai.reasoning_agent import (
        PackageLevelIssue,
        PackageReasoningOutput,
        StackReasoning,
    )

    version_info = collect_version_info(settings)
    summary_hash = compute_package_summary_hash(package_summary)
    reason_cache_key = compute_reason_cache_key(
        summary_hash,
        version_info,
        effective_config_hash=cfg.config_hash,
    )
    reason_cache_path = _lo_cache_path(
        org_id, package_id, "lo_reason", reason_cache_key
    )

    output: PackageReasoningOutput | None = None
    if await storage.exists(reason_cache_path):
        try:
            raw_json = await storage.get_object(reason_cache_path)
            cached = json.loads(raw_json)
            output = PackageReasoningOutput(
                stacks=[StackReasoning(**e) for e in cached.get("stacks", [])],
                package_level_issues=[
                    PackageLevelIssue(**e) for e in cached.get("package_level_issues", [])
                ],
            )
            log.info(f"reason cache HIT ({reason_cache_key[:12]}…): replaying {len(output.stacks)} decisions")
        except Exception as e:
            log.warning(f"reason cache read failed ({reason_cache_key[:12]}…): {e}; falling through to LLM")
            output = None

    if output is None:
        output = await agent.reason(package_summary)
        try:
            serialized = {
                "stacks": [s.model_dump() for s in output.stacks],
                "package_level_issues": [p.model_dump() for p in output.package_level_issues],
            }
            await storage.put_object(
                reason_cache_path,
                json.dumps(serialized, sort_keys=True).encode("utf-8"),
                content_type="application/json",
            )
            log.info(f"reason cache MISS ({reason_cache_key[:12]}…): stored {len(output.stacks)} decisions")
        except Exception as e:
            log.warning(f"reason cache write failed ({reason_cache_key[:12]}…): {e}")

    # decisions_by_stack is keyed by the stable key we sent to the agent.
    # Downstream code iterates the real LOStack rows and looks up decisions
    # via the same stable key.
    decisions_by_stable_key = {d.stack_id: d for d in output.stacks}
    decisions_by_stack = {
        s.id: decisions_by_stable_key.get(_stable_key(s))
        for s in stacks
    }

    # Apply decisions. A stack marked requires_hitl from earlier stages always
    # lands in needs_review (human must confirm) — we never auto-accept it.
    hitl_count = 0
    for s in stacks:
        decision = decisions_by_stack.get(s.id)
        if decision is None:
            s.status = "needs_review"
            s.requires_hitl = True
            hitl_count += 1
            continue

        if s.requires_hitl and decision.decision == "accept":
            # HITL floor wins: can't auto-accept a low-confidence or Others stack
            s.status = "needs_review"
            hitl_count += 1
        elif decision.decision == "accept":
            s.status = "accepted"
            s.requires_hitl = False
        elif decision.decision == "reject":
            s.status = "rejected"
            s.requires_hitl = True
            hitl_count += 1
        else:  # needs_review
            s.status = "needs_review"
            s.requires_hitl = True
            hitl_count += 1

    # Persist package-level issues into progress metadata for the frontend.
    # Map stable stack keys back to real UUIDs here — the frontend deep-links
    # to stack rows by UUID, not by stack_index.
    progress = dict(pkg.progress or {})
    progress["package_level_issues"] = [
        issue.model_dump() for issue in output.package_level_issues
    ]
    progress["reasoning_decisions"] = [
        {
            "stack_id": str(stacks_by_stable_key[d.stack_id].id)
                        if d.stack_id in stacks_by_stable_key else d.stack_id,
            "decision": d.decision,
            "reasoning": d.reasoning,
        }
        for d in output.stacks
    ]
    progress["hitl_count"] = hitl_count
    pkg.progress = progress

    # Package status: awaiting_review if any stack needs HITL, else completed.
    pkg.status = "awaiting_review" if hitl_count > 0 else "completed"

    await db.flush()
    log.info(
        f"Reviewed {len(stacks)} stack(s); {hitl_count} need HITL. "
        f"Package status → {pkg.status}"
    )
    return {
        "stacks": len(stacks),
        "hitl_stacks": hitl_count,
        "package_level_issues": len(output.package_level_issues),
    }
