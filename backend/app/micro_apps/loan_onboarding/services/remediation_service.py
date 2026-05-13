"""Per-doc remediation primitives for Variant A / Variant B workflows.

This module hosts the narrow, idempotent helpers that the
``RemediateMissingDocWorkflow`` (Variant A — missing required doc) and
``RemediateMissingPagesWorkflow`` (Variant B — missing pages, future)
call from Temporal activities.

Each helper operates on a *single* file or stack — never the whole
package — which is the contract Phase 3 introduces: remediation runs
in seconds, not minutes, because it touches only the row the operator
just uploaded.

Scope of this batch (3.2):
- ``doc_validation_recheck`` — REAL: re-evaluate preset rules on a
  single stack and replace that stack's ``LOValidationResult`` row.
- ``classify_single_doc`` — SKELETON: needs PDF reconstruction from
  storage + classifier dispatch. Lands in Batch 3.2b together with
  the operator-facing ``POST /loans/{id}/remediate-missing-doc``
  endpoint, which is the only caller that exercises the path
  end-to-end.
- ``extract_single_doc`` — SKELETON: needs the resolved
  extraction-schema + ``ExtractionAgent`` wiring. Lands in Batch 3.2b.
- ``data_validation_partial`` — SKELETON: the LO MVP doesn't have a
  cross-doc data-validation registry yet. PRD Phase 3.5 introduces
  ``data_validation`` as a *new* stage that runs after extract; this
  helper becomes real in Batch 3.2c.

Splitting orchestration (this batch) from per-doc business logic
(3.2b/c) lets us land the workflow + Temporal wiring + tests now, then
flesh out the heavy bits behind a stable activity contract.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.extraction import LOExtraction
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.services.validation_presets import (
    StackFacts,
    StackPageFacts,
    evaluate_all_presets,
)
from app.services.storage import StorageProvider

logger = logging.getLogger(__name__)


# ── Result shapes ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClassifySingleDocResult:
    """What ``classify_single_doc`` returns to the workflow."""
    file_id: uuid.UUID
    pages_classified: int
    new_stack_id: uuid.UUID | None
    status: str  # "deferred" until Batch 3.2b lands


@dataclass(frozen=True)
class DocValidationRecheckResult:
    """What ``doc_validation_recheck`` returns to the workflow."""
    stack_id: uuid.UUID
    rules_evaluated: int
    hard_stops: int  # count of failed preset evaluations on this stack


@dataclass(frozen=True)
class ExtractSingleDocResult:
    stack_id: uuid.UUID
    fields_extracted: int
    status: str  # "deferred" until Batch 3.2b lands


@dataclass(frozen=True)
class DataValidationPartialResult:
    stack_id: uuid.UUID
    rules_evaluated: int
    status: str  # "noop" until Batch 3.2c lands


# ── Activity 1: classify_single_doc (deferred to Batch 3.2b) ──────────


async def classify_single_doc(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    file_id: uuid.UUID,
    storage: StorageProvider,
) -> ClassifySingleDocResult:
    """Classify the pages of one freshly-ingested file and rebuild stacks.

    Reconstructs the file's PDF bytes from storage (preserving each
    page's ``source_page_number`` order), dispatches them through the
    ``PageClassifierAgent``, then upserts ``LOClassification`` rows for
    the file's pages **only** — rows for other files in the package are
    preserved untouched. After the upsert, every ``LOStack`` row is
    rebuilt from the merged classification view via ``build_stacks``,
    and the stack containing the new file's first page is returned as
    ``new_stack_id``.

    Idempotent: classifying the same file twice produces the same set
    of LOClassification rows (delete-then-insert by page_number) and
    the same LOStack layout (full rebuild of stacks).
    """
    # Local imports keep heavy module-load deps out of the cold path.
    from app.config import get_settings
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
        OTHERS_KEY,
        PageClassifierAgent,
    )
    from app.micro_apps.loan_onboarding.services.page_assignment import (
        load_effective_classifications,
    )
    from app.micro_apps.loan_onboarding.services.stacking import (
        ClassifiedPage,
        build_stacks,
    )

    pages = (await db.execute(
        select(LOPage)
        .where(
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
            LOPage.file_id == file_id,
        )
        .order_by(LOPage.page_number.asc())
    )).scalars().all()
    if not pages:
        raise ValueError(
            f"classify_single_doc: file {file_id} has no LOPage rows; "
            f"ingest must run before remediation"
        )

    file_row = (await db.execute(
        select(LOPackageFile).where(
            LOPackageFile.id == file_id,
            LOPackageFile.package_id == package_id,
            LOPackageFile.org_id == org_id,
        )
    )).scalar_one_or_none()
    if file_row is None:
        raise ValueError(
            f"classify_single_doc: LOPackageFile {file_id} not found in package "
            f"{package_id}"
        )

    # Resolve the per-package allowed doc-type enum (excluding the reserved
    # Others bucket — the classifier adds it automatically).
    config = (await db.execute(
        select(LODocTypeConfig).where(
            LODocTypeConfig.package_id == package_id,
            LODocTypeConfig.org_id == org_id,
        )
    )).scalar_one_or_none()
    if config is None or not config.doc_types:
        raise ValueError(
            f"classify_single_doc: package {package_id} has no doc-type "
            f"configuration"
        )
    allowed_keys = [
        d["key"] for d in config.doc_types
        if isinstance(d, dict) and d.get("key") and d.get("key") != OTHERS_KEY
    ]
    if not allowed_keys:
        raise ValueError(
            f"classify_single_doc: package {package_id} has empty doc-type config"
        )

    # Reconstruct the PDF bytes for just this file's pages, preserving
    # each LOPage's source_page_number ordering. We pull the raw source
    # PDF from storage and copy out the relevant pages — same pattern as
    # ``pipeline.stages._build_classify_chunks`` but scoped to one file.
    import fitz  # pymupdf
    source_bytes = await storage.get_object(file_row.storage_path)
    src_doc = fitz.open(stream=source_bytes, filetype="pdf")
    combined = fitz.open()
    try:
        for p in pages:
            src_idx = max(0, p.source_page_number - 1)
            combined.insert_pdf(src_doc, from_page=src_idx, to_page=src_idx)
        pdf_bytes = combined.tobytes()
    finally:
        combined.close()
        src_doc.close()

    settings = get_settings()
    agent = PageClassifierAgent(
        org_id=org_id,
        allowed_doc_types=allowed_keys,
        model_override=settings.LO_CLASSIFIER_MODEL or None,
    )
    page_numbers = [p.page_number for p in pages]
    batch = await agent.classify_pdf(pdf_bytes, page_numbers)

    # Idempotent upsert: only the file's page rows are wiped+rewritten,
    # so other files' classifications survive untouched.
    await db.execute(
        delete(LOClassification).where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
            LOClassification.page_number.in_(page_numbers),
        )
    )
    pages_by_num = {p.page_number: p for p in pages}
    for clf in batch.classifications:
        page = pages_by_num.get(clf.page_number)
        if page is None:
            # Defensive: classifier output stamped a page_number we didn't ask
            # for. classify_pdf overwrites with caller's numbering, so this is
            # near-impossible — but skip rather than crash.
            continue
        db.add(LOClassification(
            org_id=org_id,
            package_id=package_id,
            page_id=page.id,
            page_number=clf.page_number,
            predicted_doc_type=clf.predicted_doc_type,
            predicted_doc_type_alternatives=[
                a.model_dump() for a in clf.predicted_doc_type_alternatives
            ],
            confidence=clf.confidence,
            page_role=clf.page_role,
            detected_fields=[f.model_dump() for f in clf.detected_fields],
        ))
    await db.flush()

    # Rebuild every LOStack from the merged classification view. Stacks
    # are positional within the package — inserting/updating a few
    # classifications can split or merge neighbouring stacks, so a full
    # rebuild is the only safe option. Reviewer overrides are honored by
    # ``load_effective_classifications``.
    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == package_id, LOPackage.org_id == org_id
        )
    )).scalar_one_or_none()
    if pkg is None:
        raise ValueError(f"classify_single_doc: package {package_id} not found")

    effective = await load_effective_classifications(db, org_id, package_id)
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
    new_stacks: list[LOStack] = []
    for draft in drafts:
        s = LOStack(
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
        )
        db.add(s)
        new_stacks.append(s)
    await db.flush()

    # Find the stack covering the new file's first page — that's the
    # stack the workflow will recheck downstream.
    new_first = page_numbers[0]
    target_stack: LOStack | None = next(
        (s for s in new_stacks if new_first in (s.page_numbers or [])),
        None,
    )

    return ClassifySingleDocResult(
        file_id=file_id,
        pages_classified=len(batch.classifications),
        new_stack_id=target_stack.id if target_stack else None,
        status="ok",
    )


# ── Activity 2: doc_validation_recheck ────────────────────────────────


async def doc_validation_recheck(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    stack_id: uuid.UUID,
) -> DocValidationRecheckResult:
    """Re-evaluate preset rules on a single stack.

    Replaces ``LOValidationResult`` row for ``stack_id`` only. Other
    stacks' validation results are preserved — this is the whole point
    of "row-only recheck" in the spec.

    Returns the count of failed preset evaluations (= hard stops on
    this row). The workflow uses this to decide whether to advance.
    """
    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == stack_id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise ValueError(
            f"doc_validation_recheck: stack {stack_id} not found in package "
            f"{package_id}"
        )

    classifications = (await db.execute(
        select(LOClassification).where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
            LOClassification.page_number.in_(stack.page_numbers),
        )
    )).scalars().all()
    classifications_by_page = {c.page_number: c for c in classifications}

    page_facts: list[StackPageFacts] = []
    for pn in stack.page_numbers:
        clf = classifications_by_page.get(pn)
        field_names = frozenset(
            str(f.get("field_name"))
            for f in ((clf.detected_fields if clf else []) or [])
            if isinstance(f, dict) and f.get("field_name")
        )
        page_facts.append(StackPageFacts(
            page_number=pn,
            page_role=(clf.page_role if clf else "unknown"),
            detected_field_names=field_names,
        ))
    facts = StackFacts(
        stack_id=str(stack.id),
        doc_type=stack.doc_type,
        pages=tuple(page_facts),
    )

    preset_rules = (await db.execute(
        select(LOValidationRule).where(
            LOValidationRule.package_id == package_id,
            LOValidationRule.org_id == org_id,
            LOValidationRule.rule_source == "preset",
            LOValidationRule.enabled.is_(True),
        )
    )).scalars().all()
    rule_inputs = [(r.rule_id, dict(r.config or {})) for r in preset_rules]

    evaluations = evaluate_all_presets(rule_inputs, facts)

    # Idempotent: replace the stack's existing validation_result row.
    await db.execute(
        delete(LOValidationResult).where(
            LOValidationResult.stack_id == stack_id,
            LOValidationResult.org_id == org_id,
        )
    )

    hard_stop_count = 0
    rules_for_persist: list[dict] = []
    for ev in evaluations:
        if not ev.passed:
            hard_stop_count += 1
        rules_for_persist.append({
            "rule_id": ev.rule_id,
            "rule_source": "preset",
            "passed": ev.passed,
            "evidence": ev.evidence,
            "location_page": ev.location_page,
        })

    pass_rate = (
        1.0 - (hard_stop_count / len(rules_for_persist))
        if rules_for_persist else 1.0
    )
    result_row = LOValidationResult(
        org_id=org_id,
        package_id=package_id,
        stack_id=stack_id,
        doc_type=stack.doc_type,
        rules_evaluated=rules_for_persist,
        confidence_breakdown={"preset_pass_rate": pass_rate},
        overall_confidence=pass_rate,
        requires_hitl=(hard_stop_count > 0),
    )
    db.add(result_row)
    await db.flush()

    # Update the stack status — the doc_validation page reads this to
    # render the "needs_review" badge.
    stack.status = "needs_review" if hard_stop_count else "validated"
    stack.requires_hitl = hard_stop_count > 0
    await db.flush()

    return DocValidationRecheckResult(
        stack_id=stack_id,
        rules_evaluated=len(rule_inputs),
        hard_stops=hard_stop_count,
    )


# ── Activity 3: extract_single_doc (deferred to Batch 3.2b) ───────────


async def extract_single_doc(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    stack_id: uuid.UUID,
    storage: StorageProvider,
    *,
    force: bool = False,
) -> ExtractSingleDocResult:
    """Run the ``ExtractionAgent`` on a single stack and persist its row.

    Field list resolution mirrors ``stage_extract``: prefer the current
    resolved org/program schema (``effective_config().schemas_by_doc_type``)
    over the per-loan snapshot. Falling back to the snapshot covers loans
    on doc types not present in the resolved schema; preferring the
    resolver means admin schema edits made *after* the original run are
    picked up the next time an operator hits "Re-run extraction" — no
    re-upload required.

    A delete-then-insert on ``LOExtraction`` keeps re-runs idempotent.

    Skipped (with ``status="skipped"``) when:
      - ``LOPackage.extraction_enabled`` is ``False`` and ``force=False``
        (operator-initiated re-runs pass ``force=True``, which flips the
        toggle on as the operator's explicit consent)
      - the stack's ``doc_type`` is the reserved ``Others`` bucket
      - neither the resolver nor the per-loan snapshot has a field list
        for the stack's doc_type
      - the stack has no renderable pages (corrupt source PDF, etc.)
    """
    from app.config import get_settings
    from app.micro_apps.loan_onboarding.ai.extraction_agent import (
        ExtractionAgent,
        _conservative_fallback,
    )
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
    from app.micro_apps.loan_onboarding.services.config_resolver import (
        effective_config,
    )
    from app.micro_apps.loan_onboarding.services.ocr_words import (
        _render_pdf_page_to_jpeg,
        ocr_pdf_page,
    )

    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == stack_id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise ValueError(
            f"extract_single_doc: stack {stack_id} not found in package "
            f"{package_id}"
        )

    pkg = (await db.execute(
        select(LOPackage).where(
            LOPackage.id == package_id, LOPackage.org_id == org_id
        )
    )).scalar_one_or_none()
    if pkg is None:
        raise ValueError(f"extract_single_doc: package {package_id} not found")

    # Always wipe the existing row up front so toggling extraction off (or
    # narrowing the field list) leaves a clean slate.
    await db.execute(
        delete(LOExtraction).where(
            LOExtraction.stack_id == stack_id,
            LOExtraction.org_id == org_id,
        )
    )

    if stack.doc_type == OTHERS_KEY:
        return ExtractSingleDocResult(
            stack_id=stack_id,
            fields_extracted=0,
            status="skipped",
        )
    if not pkg.extraction_enabled:
        # Operator-initiated re-runs (``force=True``) flip the package
        # toggle on as their explicit consent — the operator just clicked
        # "Re-run Extraction" in the review UI, which is the same as
        # opting in. Automatic callers (pipeline remediation, temporal
        # activities) keep the original behavior: respect the toggle.
        if not force:
            return ExtractSingleDocResult(
                stack_id=stack_id,
                fields_extracted=0,
                status="skipped",
            )
        pkg.extraction_enabled = True
        await db.flush()

    # Prefer the resolver — admin schema edits made after the original
    # run land here without forcing a re-upload. Snapshot fallback covers
    # doc types not present in the resolver.
    requested: list[str] = []
    seen: set[str] = set()
    try:
        cfg = await effective_config(db, package_id)
        resolved_schema = cfg.schema(stack.doc_type)
    except Exception:  # pragma: no cover — never block re-run on resolver failure
        resolved_schema = None
    if resolved_schema is not None:
        for f in resolved_schema.fields:
            label = (f.label or f.key or "").strip()
            if label and label not in seen:
                seen.add(label)
                requested.append(label)
    if not requested:
        fields_by_doc = pkg.extraction_fields_by_doc or {}
        raw_fields = fields_by_doc.get(stack.doc_type) or []
        for label in raw_fields:
            label = str(label or "").strip()
            if label and label not in seen:
                seen.add(label)
                requested.append(label)
    if not requested:
        return ExtractSingleDocResult(
            stack_id=stack_id,
            fields_extracted=0,
            status="skipped",
        )

    # Build the per-page payload: render JPEG + load (or JIT-OCR) words.
    pages = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
            LOPage.page_number.in_(stack.page_numbers),
        )
    )).scalars().all()
    pages_by_num = {p.page_number: p for p in pages}

    file_ids = list({p.file_id for p in pages})
    files: list[LOPackageFile] = (await db.execute(
        select(LOPackageFile).where(LOPackageFile.id.in_(file_ids))
    )).scalars().all() if file_ids else []
    files_by_id = {f.id: f for f in files}

    pdf_bytes_cache: dict[uuid.UUID, bytes] = {}

    async def _get_pdf_bytes(fid: uuid.UUID) -> bytes | None:
        if fid in pdf_bytes_cache:
            return pdf_bytes_cache[fid]
        f = files_by_id.get(fid)
        if f is None or not f.storage_path:
            return None
        try:
            data = await storage.get_object(f.storage_path)
        except Exception as e:  # pragma: no cover — storage errors logged
            logger.warning("extract: could not load PDF for file %s: %s", fid, e)
            return None
        pdf_bytes_cache[fid] = data
        return data

    import asyncio as _asyncio

    stack_pages: list[dict] = []
    for local_idx, pn in enumerate(stack.page_numbers, start=1):
        pg = pages_by_num.get(pn)
        if pg is None:
            continue
        pdf_bytes = await _get_pdf_bytes(pg.file_id)
        if not pdf_bytes:
            continue

        words = pg.ocr_words
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
            else:
                words = []

        image_bytes = await _asyncio.to_thread(
            _render_pdf_page_to_jpeg, pdf_bytes, pg.source_page_number, 200,
        )
        if not image_bytes:
            continue

        stack_pages.append({
            "page_number": local_idx,
            "image_bytes": image_bytes,
            "words": words or [],
            "_global_page": pn,
        })

    settings = get_settings()
    agent = ExtractionAgent(
        org_id=org_id,
        model_override=settings.LO_VALIDATOR_MODEL or None,
    )

    if not stack_pages:
        extraction = _conservative_fallback(
            str(stack.id), stack.doc_type, requested,
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
            logger.warning(
                "extract_single_doc: ExtractionAgent failed for stack=%s: %s",
                stack_id, e,
            )
            extraction = _conservative_fallback(
                str(stack.id), stack.doc_type, requested,
            )
        else:
            # Remap evidence page (stack-local) → global page.
            local_to_global = {
                sp["page_number"]: sp["_global_page"] for sp in stack_pages
            }
            for f in extraction.fields:
                if f.location and f.location.page in local_to_global:
                    f.location.page = local_to_global[f.location.page]

    rows: list[dict] = []
    located = 0
    for f in extraction.fields:
        rows.append({
            "name": f.name,
            "value": f.value,
            "confidence": round(f.confidence, 6),
            "status": f.status,
            "location": f.location.model_dump() if f.location else None,
        })
        if f.status in ("located", "tentative", "ungrounded", "low_confidence"):
            located += 1

    db.add(LOExtraction(
        org_id=org_id,
        package_id=package_id,
        stack_id=stack_id,
        doc_type=stack.doc_type,
        fields=rows,
        located_count=located,
        total_count=len(rows),
    ))
    await db.flush()

    return ExtractSingleDocResult(
        stack_id=stack_id,
        fields_extracted=len(rows),
        status="ok",
    )


# ── Activity 4: data_validation_partial (deferred to Batch 3.2c) ──────


async def data_validation_partial(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    stack_id: uuid.UUID,
) -> DataValidationPartialResult:
    """Skeleton for per-stack cross-doc validation (Batch 3.2c).

    The MVP LO surface today only has *single-stack* preset rules
    (``validation_presets.py``) — there is no cross-doc data-validation
    rule registry yet. PRD Phase 3.5 introduces ``data_validation`` as a
    new stage that runs *after* extract; until that registry lands the
    activity is a no-op so the workflow can complete cleanly.
    """
    stack = (await db.execute(
        select(LOStack).where(
            LOStack.id == stack_id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if stack is None:
        raise ValueError(
            f"data_validation_partial: stack {stack_id} not found in "
            f"package {package_id}"
        )
    return DataValidationPartialResult(
        stack_id=stack_id,
        rules_evaluated=0,
        status="noop",
    )


# ── Ingest helper for the remediation POST endpoint ───────────────────


@dataclass(frozen=True)
class IngestSingleFileResult:
    file_id: uuid.UUID
    pages_added: int
    first_page_number: int
    last_page_number: int


# ── Variant B (3.3): missing-pages remediation result shapes ──────────


@dataclass(frozen=True)
class AppendPagesResult:
    """Output of ``append_pages`` (Variant B step 1).

    The ``snapshot`` is a JSON-serializable dict that ``classify_recheck``
    needs to roll back the append if the new pages don't actually belong
    to the target document. Cross-activity boundaries cleanly via the
    Temporal JSON converter.
    """
    file_id: uuid.UUID
    target_stack_id: uuid.UUID
    pages_added: int
    first_page_number: int
    last_page_number: int
    snapshot: dict


@dataclass(frozen=True)
class ClassifyRecheckResult:
    """Output of ``classify_recheck`` (Variant B step 2)."""
    merged_stack_id: uuid.UUID
    pages_classified: int
    status: str  # "ok" | "rolled_back"
    original_doc_type: str
    new_doc_type: str | None
    original_confidence: float
    new_confidence: float
    rollback_reason: str | None


async def ingest_single_file(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    file_id: uuid.UUID,
    storage: StorageProvider,
) -> IngestSingleFileResult:
    """Create LOPage rows for a single freshly-uploaded file.

    Unlike ``stage_ingest`` (which wipes-and-rebuilds every page in the
    package) this helper *appends* — pages get global numbers starting
    one after the package's current highest page_number. Reviewer
    overrides on existing pages survive untouched.

    Caller is expected to have created the LOPackageFile row already
    (typically via ``file_service.store_uploaded_file``).
    """
    file_row = (await db.execute(
        select(LOPackageFile).where(
            LOPackageFile.id == file_id,
            LOPackageFile.package_id == package_id,
            LOPackageFile.org_id == org_id,
        )
    )).scalar_one_or_none()
    if file_row is None:
        raise ValueError(
            f"ingest_single_file: LOPackageFile {file_id} not found in package "
            f"{package_id}"
        )

    # Reject re-ingest: the page_number range becomes ambiguous if we
    # silently re-add. Caller should delete-and-replace explicitly.
    existing = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
            LOPage.file_id == file_id,
        )
    )).scalars().first()
    if existing is not None:
        raise ValueError(
            f"ingest_single_file: file {file_id} already has LOPage rows; "
            f"refusing to double-ingest"
        )

    # Find the highest existing page_number for this package (across all
    # files) so we can append.
    from sqlalchemy import func as sa_func
    max_pn_row = (await db.execute(
        select(sa_func.max(LOPage.page_number)).where(
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
        )
    )).scalar()
    next_global = int(max_pn_row or 0) + 1

    if not await storage.exists(file_row.storage_path):
        raise FileNotFoundError(
            f"ingest_single_file: file not in storage: {file_row.storage_path}"
        )

    import fitz  # pymupdf
    content = await storage.get_object(file_row.storage_path)
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        raise ValueError(
            f"ingest_single_file: failed to open PDF '{file_row.filename}': {e}"
        ) from e

    first_pn = next_global
    last_pn = next_global - 1
    try:
        for src_idx in range(doc.page_count):
            page = doc.load_page(src_idx)
            text = page.get_text("text") or ""
            text_len = len(text.strip())
            db.add(LOPage(
                org_id=org_id,
                package_id=package_id,
                file_id=file_id,
                page_number=next_global,
                source_page_number=src_idx + 1,
                heuristic_text=text,
                text_length=text_len,
            ))
            last_pn = next_global
            next_global += 1
    finally:
        doc.close()

    await db.flush()
    return IngestSingleFileResult(
        file_id=file_id,
        pages_added=last_pn - first_pn + 1,
        first_page_number=first_pn,
        last_page_number=last_pn,
    )


# ── Variant B (3.3): missing-pages remediation primitives ─────────────
#
# Triggered by ``POST /loans/{id}/remediate-missing-pages``. Unlike
# Variant A — which creates a brand-new stack for a missing required doc
# — Variant B *extends an existing stack* with pages the operator just
# uploaded as a continuation of that document. The 5-step workflow is:
#
#   1. ``append_pages``           — deterministic page ingest + stack expand
#   2. ``classify_recheck``       — LLM rechecks the new pages; rolls back
#                                   the append if doc-type/confidence
#                                   diverges from the merged stack
#   3. ``doc_validation_recheck`` — preset rule recheck (existing helper)
#   4. ``extract_recheck``        — re-extract on the merged doc
#                                   (delete-then-insert via
#                                   ``extract_single_doc``)
#   5. ``data_validation_partial``— cross-doc rules (skeleton helper)
#
# The rollback contract on step 2 is the whole point of Variant B: a
# misclassified continuation must NOT silently mutate a previously-
# accepted stack. If rollback triggers, the new file's pages and the
# LOPackageFile row are deleted and the target stack's prior fields
# (page_numbers / last_page / classification_confidence) are restored
# atomically. Downstream steps (3/4/5) are then skipped.

# A doc-type majority change on the new pages always triggers rollback;
# the confidence-drop threshold catches the subtler "barely-fits"
# continuation that the operator probably mis-uploaded. 0.15 was chosen
# empirically (matches the LO_HITL_THRESHOLD floor's typical neighborhood).
CLASSIFY_RECHECK_CONFIDENCE_DROP = 0.15


async def append_pages(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    target_stack_id: uuid.UUID,
    file_id: uuid.UUID,
    storage: StorageProvider,
) -> AppendPagesResult:
    """Append the new file's pages to ``target_stack`` (deterministic, no LLM).

    Creates ``LOPage`` rows at the end of the package's global page
    numbering and ``LOClassification`` rows that *inherit* the target
    stack's doc_type and confidence as a placeholder. Step 2 of the
    Variant B workflow (``classify_recheck``) then verifies the
    inherited verdict actually fits — and rolls back if it doesn't.

    The target stack's ``page_numbers`` is extended in-place. Stacks are
    normally contiguous, but a Variant B merge legitimately makes the
    target stack span a non-contiguous block (the original pages plus a
    tail at the end of the package). That's fine: ``page_numbers`` is a
    JSONB list, ``first_page`` stays at the original first, and
    ``last_page`` advances to the new tail.
    """
    target = (await db.execute(
        select(LOStack).where(
            LOStack.id == target_stack_id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if target is None:
        raise ValueError(
            f"append_pages: stack {target_stack_id} not found in package "
            f"{package_id}"
        )

    # Snapshot — must be JSON-serializable so it survives the Temporal
    # activity boundary as input to ``classify_recheck``.
    snapshot = {
        "stack_id": str(target.id),
        "doc_type": target.doc_type,
        "page_numbers": list(target.page_numbers or []),
        "first_page": target.first_page,
        "last_page": target.last_page,
        "classification_confidence": float(target.classification_confidence or 0.0),
        "status": target.status,
        "requires_hitl": bool(target.requires_hitl),
    }

    # Step A — create LOPage rows for the new file (append mode).
    ingest = await ingest_single_file(
        db, org_id, package_id, file_id, storage,
    )

    # Step B — seed LOClassification rows inheriting the target's doc_type.
    new_pages = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
            LOPage.file_id == file_id,
        ).order_by(LOPage.page_number.asc())
    )).scalars().all()
    inherited_conf = float(target.classification_confidence or 0.0)
    for p in new_pages:
        db.add(LOClassification(
            org_id=org_id,
            package_id=package_id,
            page_id=p.id,
            page_number=p.page_number,
            predicted_doc_type=target.doc_type,
            predicted_doc_type_alternatives=[],
            confidence=inherited_conf,
            page_role="continuation",
            detected_fields=[],
        ))
    await db.flush()

    # Step C — extend the target stack's page_numbers + last_page.
    new_page_numbers = [p.page_number for p in new_pages]
    target.page_numbers = list(target.page_numbers or []) + new_page_numbers
    if new_page_numbers:
        target.last_page = max(target.last_page, max(new_page_numbers))
    db.add(target)
    await db.flush()

    return AppendPagesResult(
        file_id=file_id,
        target_stack_id=target.id,
        pages_added=ingest.pages_added,
        first_page_number=ingest.first_page_number,
        last_page_number=ingest.last_page_number,
        snapshot=snapshot,
    )


async def classify_recheck(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    target_stack_id: uuid.UUID,
    file_id: uuid.UUID,
    storage: StorageProvider,
    snapshot: dict,
    *,
    confidence_drop_threshold: float = CLASSIFY_RECHECK_CONFIDENCE_DROP,
) -> ClassifyRecheckResult:
    """Re-classify the appended pages and roll back if they don't fit.

    Runs the ``PageClassifierAgent`` on the new file's pages only, then
    decides:

    1. **Doc-type holds.** Majority predicted_doc_type on the new pages
       matches ``snapshot["doc_type"]`` AND the new average confidence
       is no more than ``confidence_drop_threshold`` below the
       snapshot's. → Persist real classifications, blend the merged
       stack's confidence (weighted by page count), return ``ok``.

    2. **Doc-type drifts** OR **confidence collapses.** → Roll back:
       delete the LOPackageFile (CASCADE wipes LOPage + LOClassification),
       restore the target stack's snapshot fields. Return
       ``rolled_back`` with a human-readable ``rollback_reason``.

    Idempotent: callers can re-run with the same snapshot — the rollback
    branch is a no-op if the file row is already gone, and the success
    branch overwrites the inherited classifications.
    """
    from app.config import get_settings
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
        OTHERS_KEY,
        PageClassifierAgent,
    )

    target = (await db.execute(
        select(LOStack).where(
            LOStack.id == target_stack_id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if target is None:
        raise ValueError(
            f"classify_recheck: stack {target_stack_id} not found in package "
            f"{package_id}"
        )

    new_pages = (await db.execute(
        select(LOPage).where(
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
            LOPage.file_id == file_id,
        ).order_by(LOPage.page_number.asc())
    )).scalars().all()
    if not new_pages:
        raise ValueError(
            f"classify_recheck: file {file_id} has no LOPage rows; "
            f"append_pages must run first"
        )

    file_row = (await db.execute(
        select(LOPackageFile).where(
            LOPackageFile.id == file_id,
            LOPackageFile.package_id == package_id,
            LOPackageFile.org_id == org_id,
        )
    )).scalar_one_or_none()
    if file_row is None:
        raise ValueError(
            f"classify_recheck: LOPackageFile {file_id} not found"
        )

    # Resolve the per-package allowed doc-type set so the classifier
    # operates against the same enum the original classify run did.
    config = (await db.execute(
        select(LODocTypeConfig).where(
            LODocTypeConfig.package_id == package_id,
            LODocTypeConfig.org_id == org_id,
        )
    )).scalar_one_or_none()
    if config is None or not config.doc_types:
        raise ValueError(
            f"classify_recheck: package {package_id} has no doc-type configuration"
        )
    allowed_keys = [
        d["key"] for d in config.doc_types
        if isinstance(d, dict) and d.get("key") and d.get("key") != OTHERS_KEY
    ]

    # Reconstruct the new file's PDF and dispatch the classifier.
    import fitz  # pymupdf
    source_bytes = await storage.get_object(file_row.storage_path)
    src_doc = fitz.open(stream=source_bytes, filetype="pdf")
    combined = fitz.open()
    try:
        for p in new_pages:
            src_idx = max(0, p.source_page_number - 1)
            combined.insert_pdf(src_doc, from_page=src_idx, to_page=src_idx)
        pdf_bytes = combined.tobytes()
    finally:
        combined.close()
        src_doc.close()

    settings = get_settings()
    agent = PageClassifierAgent(
        org_id=org_id,
        allowed_doc_types=allowed_keys,
        model_override=settings.LO_CLASSIFIER_MODEL or None,
    )
    page_numbers = [p.page_number for p in new_pages]
    batch = await agent.classify_pdf(pdf_bytes, page_numbers)

    if not batch.classifications:
        # The classifier returned nothing — treat as a rollback rather
        # than persist the inherited placeholders. Better to surface the
        # failure to the operator than to silently accept zero-evidence
        # appended pages.
        return await _rollback_append(
            db, org_id, package_id, target, file_row, snapshot,
            reason="classifier returned no verdicts for appended pages",
            new_avg_confidence=0.0,
            new_doc_type=None,
            pages_classified=0,
        )

    # Decide hold vs rollback BEFORE persisting any real classifications,
    # so a rolled-back run leaves the placeholders in place only briefly
    # (rollback also wipes them via FK cascade).
    by_doc_type: dict[str, list[float]] = {}
    for clf in batch.classifications:
        by_doc_type.setdefault(clf.predicted_doc_type, []).append(clf.confidence)
    majority_doc_type, majority_confidences = max(
        by_doc_type.items(), key=lambda kv: (len(kv[1]), sum(kv[1])),
    )
    new_avg_conf = (
        sum(c.confidence for c in batch.classifications)
        / len(batch.classifications)
    )

    snapshot_doc_type = str(snapshot.get("doc_type") or "")
    snapshot_conf = float(snapshot.get("classification_confidence") or 0.0)

    if majority_doc_type != snapshot_doc_type:
        return await _rollback_append(
            db, org_id, package_id, target, file_row, snapshot,
            reason=(
                f"appended pages classified as '{majority_doc_type}' "
                f"(majority); expected continuation of '{snapshot_doc_type}'"
            ),
            new_avg_confidence=new_avg_conf,
            new_doc_type=majority_doc_type,
            pages_classified=len(batch.classifications),
        )

    if snapshot_conf - new_avg_conf > confidence_drop_threshold:
        return await _rollback_append(
            db, org_id, package_id, target, file_row, snapshot,
            reason=(
                f"avg classification confidence dropped from "
                f"{snapshot_conf:.3f} to {new_avg_conf:.3f} "
                f"(> {confidence_drop_threshold:.2f})"
            ),
            new_avg_confidence=new_avg_conf,
            new_doc_type=majority_doc_type,
            pages_classified=len(batch.classifications),
        )

    # Hold path — overwrite the inherited LOClassification placeholders
    # with the real verdicts. Reuse delete-then-insert keyed by
    # page_number so the operation is idempotent across retries.
    await db.execute(
        delete(LOClassification).where(
            LOClassification.package_id == package_id,
            LOClassification.org_id == org_id,
            LOClassification.page_number.in_(page_numbers),
        )
    )
    pages_by_num = {p.page_number: p for p in new_pages}
    for clf in batch.classifications:
        page = pages_by_num.get(clf.page_number)
        if page is None:
            continue
        db.add(LOClassification(
            org_id=org_id,
            package_id=package_id,
            page_id=page.id,
            page_number=clf.page_number,
            predicted_doc_type=clf.predicted_doc_type,
            predicted_doc_type_alternatives=[
                a.model_dump() for a in clf.predicted_doc_type_alternatives
            ],
            confidence=clf.confidence,
            page_role=clf.page_role,
            detected_fields=[f.model_dump() for f in clf.detected_fields],
        ))
    await db.flush()

    # Blend the merged stack's confidence: page-count-weighted average of
    # the original stack's confidence and the new pages' average. This
    # keeps a tiny appended fragment from over-influencing a long stack.
    original_pages = list(snapshot.get("page_numbers") or [])
    n_orig = max(1, len(original_pages))
    n_new = len(batch.classifications)
    blended = (snapshot_conf * n_orig + new_avg_conf * n_new) / (n_orig + n_new)
    target.classification_confidence = round(blended, 6)
    db.add(target)
    await db.flush()

    return ClassifyRecheckResult(
        merged_stack_id=target.id,
        pages_classified=len(batch.classifications),
        status="ok",
        original_doc_type=snapshot_doc_type,
        new_doc_type=majority_doc_type,
        original_confidence=snapshot_conf,
        new_confidence=round(blended, 6),
        rollback_reason=None,
    )


async def _rollback_append(
    db: AsyncSession,
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    target: LOStack,
    file_row: LOPackageFile,
    snapshot: dict,
    *,
    reason: str,
    new_avg_confidence: float,
    new_doc_type: str | None,
    pages_classified: int,
) -> ClassifyRecheckResult:
    """Atomic rollback for a misclassified Variant B append.

    Explicitly deletes ``LOClassification`` → ``LOPage`` →
    ``LOPackageFile`` for the appended file, then restores the target
    stack's snapshotted fields. The deletes are explicit (rather than
    relying on FK CASCADE) so the rollback behaves identically under
    PostgreSQL and the SQLite test harness, which doesn't enable
    ``PRAGMA foreign_keys`` by default.

    The storage object itself is left in place — easier to inspect after
    the fact than to recover if we deleted it speculatively. The
    caller's POST endpoint can re-attempt by uploading a different PDF.
    """
    logger.info(
        "Variant B rollback: pkg=%s stack=%s file=%s reason=%s",
        package_id, target.id, file_row.id, reason,
    )

    # Find the appended pages so we can wipe their classifications + rows
    # before removing the file row.
    new_page_ids = (await db.execute(
        select(LOPage.id).where(
            LOPage.package_id == package_id,
            LOPage.org_id == org_id,
            LOPage.file_id == file_row.id,
        )
    )).scalars().all()
    if new_page_ids:
        await db.execute(
            delete(LOClassification).where(
                LOClassification.page_id.in_(list(new_page_ids)),
                LOClassification.org_id == org_id,
            )
        )
        await db.execute(
            delete(LOPage).where(
                LOPage.id.in_(list(new_page_ids)),
                LOPage.org_id == org_id,
            )
        )
    await db.execute(
        delete(LOPackageFile).where(
            LOPackageFile.id == file_row.id,
            LOPackageFile.org_id == org_id,
        )
    )

    # Restore stack snapshot. Don't rely on ``target`` being still
    # attached — it might be after the cascade — so re-fetch.
    fresh = (await db.execute(
        select(LOStack).where(
            LOStack.id == target.id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if fresh is not None:
        fresh.page_numbers = list(snapshot.get("page_numbers") or [])
        fresh.first_page = int(snapshot.get("first_page") or fresh.first_page)
        fresh.last_page = int(snapshot.get("last_page") or fresh.last_page)
        fresh.classification_confidence = float(
            snapshot.get("classification_confidence") or 0.0
        )
        fresh.status = str(snapshot.get("status") or fresh.status)
        fresh.requires_hitl = bool(snapshot.get("requires_hitl") or False)
        db.add(fresh)
    await db.flush()

    return ClassifyRecheckResult(
        merged_stack_id=target.id,
        pages_classified=pages_classified,
        status="rolled_back",
        original_doc_type=str(snapshot.get("doc_type") or ""),
        new_doc_type=new_doc_type,
        original_confidence=float(snapshot.get("classification_confidence") or 0.0),
        new_confidence=new_avg_confidence,
        rollback_reason=reason,
    )
