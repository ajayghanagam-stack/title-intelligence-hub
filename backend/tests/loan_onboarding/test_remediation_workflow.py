"""Tests for the Phase 3.2 Variant A remediation primitives.

Covers the 4 service-layer helpers (one real, three skeletons) and the
Temporal activities that wrap them. The workflow itself is exercised
by chaining the activity calls — running it under
``WorkflowEnvironment`` would slow the suite down for what is
essentially a sequencing test, and the ProcessLoanWorkflow tests
already cover the Temporal harness end-to-end.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from app.micro_apps.loan_onboarding.services import remediation_service
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


# ── Fixtures: build a stack with classifications + preset rule ────────


async def _seed_stack_with_signature_page(
    db: AsyncSession, stack_doc_type: str = "paystub",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a 2-page stack where page 2 is the signature page.

    Returns (file_id, stack_id).
    """
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        filename="paystub.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/paystub.pdf",
        content_hash="x" * 64,
        size_bytes=200,
        page_count=2,
    )
    db.add(file_row)
    await db.flush()

    pages = []
    for pn, role in [(1, "first_page"), (2, "signature_page")]:
        page = LOPage(
            id=uuid.uuid4(),
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            file_id=file_row.id,
            page_number=pn,
            source_page_number=pn,
            heuristic_text=f"text for page {pn}",
            text_length=20,
        )
        db.add(page)
        await db.flush()
        pages.append(page)
        db.add(LOClassification(
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            page_id=page.id,
            page_number=pn,
            predicted_doc_type=stack_doc_type,
            predicted_doc_type_alternatives=[],
            confidence=0.95,
            page_role=role,
            detected_fields=[],
        ))

    stack = LOStack(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_index=0,
        doc_type=stack_doc_type,
        page_numbers=[1, 2],
        first_page=1,
        last_page=2,
        classification_confidence=0.95,
        status="classified",
    )
    db.add(stack)
    await db.commit()
    return file_row.id, stack.id


# ── doc_validation_recheck — REAL implementation tests ────────────────


@pytest.mark.asyncio
async def test_doc_validation_recheck_passes_when_signature_present(
    db_session: AsyncSession, sample_package,
):
    _, stack_id = await _seed_stack_with_signature_page(db_session)

    result = await remediation_service.doc_validation_recheck(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack_id,
    )
    await db_session.commit()

    # sample_package fixture installs a `missing_signatures` preset rule.
    assert result.rules_evaluated == 1
    assert result.hard_stops == 0

    # Persisted row exists and reflects the pass.
    row = (await db_session.execute(
        select(LOValidationResult).where(LOValidationResult.stack_id == stack_id)
    )).scalar_one()
    assert row.requires_hitl is False
    assert row.overall_confidence == 1.0
    assert row.rules_evaluated[0]["rule_id"] == "missing_signatures"
    assert row.rules_evaluated[0]["passed"] is True


@pytest.mark.asyncio
async def test_doc_validation_recheck_fails_when_signature_missing(
    db_session: AsyncSession, sample_package,
):
    # Build a 1-page stack with no signature_page role.
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        filename="x.pdf", storage_path="p", content_hash="x" * 64,
        size_bytes=10, page_count=1,
    )
    db_session.add(file_row)
    await db_session.flush()
    page = LOPage(
        id=uuid.uuid4(), org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        file_id=file_row.id, page_number=1, source_page_number=1,
        heuristic_text="t", text_length=10,
    )
    db_session.add(page)
    await db_session.flush()
    db_session.add(LOClassification(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        page_id=page.id, page_number=1,
        predicted_doc_type="w2",
        predicted_doc_type_alternatives=[], confidence=0.9,
        page_role="first_page", detected_fields=[],
    ))
    stack = LOStack(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        stack_index=0, doc_type="w2",
        page_numbers=[1], first_page=1, last_page=1,
        classification_confidence=0.9, status="classified",
    )
    db_session.add(stack)
    await db_session.commit()

    result = await remediation_service.doc_validation_recheck(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack.id,
    )
    await db_session.commit()
    assert result.hard_stops == 1

    row = (await db_session.execute(
        select(LOValidationResult).where(LOValidationResult.stack_id == stack.id)
    )).scalar_one()
    assert row.requires_hitl is True


@pytest.mark.asyncio
async def test_doc_validation_recheck_replaces_prior_row(
    db_session: AsyncSession, sample_package,
):
    """Running recheck twice replaces the prior result — idempotent."""
    _, stack_id = await _seed_stack_with_signature_page(db_session)

    await remediation_service.doc_validation_recheck(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack_id,
    )
    await db_session.commit()
    await remediation_service.doc_validation_recheck(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack_id,
    )
    await db_session.commit()

    rows = (await db_session.execute(
        select(LOValidationResult).where(LOValidationResult.stack_id == stack_id)
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_doc_validation_recheck_unknown_stack_raises(
    db_session: AsyncSession, sample_package,
):
    with pytest.raises(ValueError, match="not found"):
        await remediation_service.doc_validation_recheck(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID, uuid.uuid4(),
        )


# ── classify_single_doc — REAL impl tests (mocked agent + storage) ────


def _build_blank_pdf_bytes(num_pages: int) -> bytes:
    """Tiny in-memory PDF with ``num_pages`` blank pages — enough for the
    PyMuPDF reconstruction in classify_single_doc to round-trip."""
    import fitz
    doc = fitz.open()
    try:
        for _ in range(num_pages):
            doc.new_page(width=612, height=792)
        return doc.tobytes()
    finally:
        doc.close()


class _FakeStorage:
    """Minimal StorageProvider stand-in that serves a fixed PDF for
    every key. Used by remediation_service tests so we don't have to
    write real bytes to ./test_storage/."""
    def __init__(self, pdf_bytes: bytes):
        self._pdf = pdf_bytes

    async def get_object(self, key: str) -> bytes:
        return self._pdf

    async def exists(self, key: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_classify_single_doc_runs_real_classifier_and_rebuilds_stacks(
    db_session: AsyncSession, sample_package, monkeypatch,
):
    """Happy path: classifier returns updated labels, classifications are
    upserted for the file's pages, stacks are rebuilt, and the returned
    ``new_stack_id`` points at the stack covering the file's first page."""
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
        PageClassifierAgent,
    )
    from app.micro_apps.loan_onboarding.schemas.classification import (
        Classification,
        ClassificationBatchResult,
    )

    file_id, _ = await _seed_stack_with_signature_page(db_session)

    async def _fake_classify_pdf(self, pdf_bytes, page_numbers, timeout=None):
        return ClassificationBatchResult(classifications=[
            Classification(
                page_number=pn,
                predicted_doc_type="w2",
                predicted_doc_type_alternatives=[],
                confidence=0.92,
                page_role=("first_page" if i == 0 else "signature_page"),
                detected_fields=[],
            )
            for i, pn in enumerate(page_numbers)
        ])

    monkeypatch.setattr(
        PageClassifierAgent, "classify_pdf", _fake_classify_pdf,
    )

    storage = _FakeStorage(_build_blank_pdf_bytes(2))
    result = await remediation_service.classify_single_doc(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, file_id, storage,  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert result.status == "ok"
    assert result.pages_classified == 2
    assert result.new_stack_id is not None

    # Classifications now reflect the mocked verdict.
    rows = (await db_session.execute(
        select(LOClassification).where(
            LOClassification.package_id == TEST_PACKAGE_ID,
        ).order_by(LOClassification.page_number.asc())
    )).scalars().all()
    assert len(rows) == 2
    assert all(r.predicted_doc_type == "w2" for r in rows)

    # Stacks rebuilt from the new classifications.
    stacks = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalars().all()
    assert len(stacks) >= 1
    target = next(s for s in stacks if s.id == result.new_stack_id)
    assert target.doc_type == "w2"
    assert 1 in target.page_numbers


@pytest.mark.asyncio
async def test_classify_single_doc_unknown_file_raises(
    db_session: AsyncSession, sample_package,
):
    with pytest.raises(ValueError, match="no LOPage rows"):
        await remediation_service.classify_single_doc(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID, uuid.uuid4(), object(),  # type: ignore[arg-type]
        )


# ── extract_single_doc — REAL impl tests (skip-path coverage) ─────────


@pytest.mark.asyncio
async def test_extract_single_doc_skipped_when_extraction_disabled(
    db_session: AsyncSession, sample_package,
):
    """``extraction_enabled=False`` short-circuits before any AI call."""
    _, stack_id = await _seed_stack_with_signature_page(db_session)

    sample_package.extraction_enabled = False
    db_session.add(sample_package)
    await db_session.commit()

    result = await remediation_service.extract_single_doc(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack_id, object(),  # type: ignore[arg-type]
    )
    await db_session.commit()
    assert result.status == "skipped"
    assert result.fields_extracted == 0


@pytest.mark.asyncio
async def test_extract_single_doc_skipped_for_others_bucket(
    db_session: AsyncSession, sample_package,
):
    """Stacks in the reserved Others bucket never go to extraction."""
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY

    _, stack_id = await _seed_stack_with_signature_page(
        db_session, stack_doc_type=OTHERS_KEY,
    )
    # Configure fields anyway; OTHERS short-circuits regardless.
    sample_package.extraction_enabled = True
    sample_package.extraction_fields_by_doc = {OTHERS_KEY: ["irrelevant"]}
    db_session.add(sample_package)
    await db_session.commit()

    result = await remediation_service.extract_single_doc(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack_id, object(),  # type: ignore[arg-type]
    )
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_extract_single_doc_skipped_when_no_fields_configured(
    db_session: AsyncSession, sample_package,
):
    """No requested-field list → no extraction call, status="skipped"."""
    _, stack_id = await _seed_stack_with_signature_page(db_session)

    sample_package.extraction_enabled = True
    sample_package.extraction_fields_by_doc = {}  # nothing for any doc_type
    db_session.add(sample_package)
    await db_session.commit()

    result = await remediation_service.extract_single_doc(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack_id, object(),  # type: ignore[arg-type]
    )
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_data_validation_partial_skeleton_returns_noop(
    db_session: AsyncSession, sample_package,
):
    _, stack_id = await _seed_stack_with_signature_page(db_session)
    result = await remediation_service.data_validation_partial(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, stack_id,
    )
    assert result.status == "noop"
    assert result.rules_evaluated == 0


# ── ingest_single_file — append-mode page ingest ──────────────────────


async def _seed_package_file(
    db: AsyncSession, *, filename: str, storage_path: str,
) -> uuid.UUID:
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        filename=filename,
        storage_path=storage_path,
        content_hash="x" * 64,
        size_bytes=200,
        page_count=2,
    )
    db.add(file_row)
    await db.commit()
    return file_row.id


@pytest.mark.asyncio
async def test_ingest_single_file_appends_after_existing_pages(
    db_session: AsyncSession, sample_package,
):
    """First file already has pages 1-2; new file's pages should land at
    3-4 (append, not overwrite)."""
    # Pretend an earlier file took pages 1-2.
    await _seed_stack_with_signature_page(db_session)

    # Now upload a fresh file.
    new_file_id = await _seed_package_file(
        db_session,
        filename="paystub_remediation.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/paystub_remediation.pdf",
    )
    storage = _FakeStorage(_build_blank_pdf_bytes(2))

    result = await remediation_service.ingest_single_file(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, new_file_id, storage,  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert result.pages_added == 2
    assert result.first_page_number == 3
    assert result.last_page_number == 4

    rows = (await db_session.execute(
        select(LOPage).where(
            LOPage.package_id == TEST_PACKAGE_ID,
            LOPage.file_id == new_file_id,
        ).order_by(LOPage.page_number.asc())
    )).scalars().all()
    assert [r.page_number for r in rows] == [3, 4]
    assert [r.source_page_number for r in rows] == [1, 2]


@pytest.mark.asyncio
async def test_ingest_single_file_rejects_double_ingest(
    db_session: AsyncSession, sample_package,
):
    file_id, _ = await _seed_stack_with_signature_page(db_session)
    storage = _FakeStorage(_build_blank_pdf_bytes(2))

    with pytest.raises(ValueError, match="already has LOPage rows"):
        await remediation_service.ingest_single_file(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID, file_id, storage,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_ingest_single_file_unknown_file_raises(
    db_session: AsyncSession, sample_package,
):
    storage = _FakeStorage(_build_blank_pdf_bytes(1))
    with pytest.raises(ValueError, match="LOPackageFile .* not found"):
        await remediation_service.ingest_single_file(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID, uuid.uuid4(), storage,  # type: ignore[arg-type]
        )


# ── Workflow wiring (import + activity registration sanity) ───────────


def test_workflow_and_activities_importable():
    """Workflow + activities are wired into the unified worker.

    Catches the common breakage where someone adds a new activity but
    forgets to register it in unified_worker — the worker would start
    but Temporal would reject any workflow trying to call it.
    """
    from app.micro_apps.loan_onboarding.pipeline.temporal_workflows import (
        RemediateMissingDocWorkflow,
        RemediateMissingPagesWorkflow,
    )
    from app.pipeline.unified_worker import LO_ACTIVITIES

    activity_names = {act.__name__ for act in LO_ACTIVITIES}
    # Variant A
    assert "lo_activity_classify_single_doc" in activity_names
    assert "lo_activity_doc_validation_recheck" in activity_names
    assert "lo_activity_extract_single_doc" in activity_names
    assert "lo_activity_data_validation_partial" in activity_names
    # Variant B
    assert "lo_activity_append_pages" in activity_names
    assert "lo_activity_classify_recheck" in activity_names
    assert RemediateMissingDocWorkflow is not None
    assert RemediateMissingPagesWorkflow is not None


# ── Variant B (3.3): append_pages + classify_recheck tests ────────────


@pytest.mark.asyncio
async def test_append_pages_extends_target_stack(
    db_session: AsyncSession, sample_package,
):
    """append_pages adds new LOPage rows, inherits the target's doc_type
    on placeholder classifications, and grows the stack's page list."""
    _, target_stack_id = await _seed_stack_with_signature_page(
        db_session, stack_doc_type="paystub",
    )
    new_file_id = await _seed_package_file(
        db_session,
        filename="paystub_pages.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/paystub_pages.pdf",
    )
    storage = _FakeStorage(_build_blank_pdf_bytes(2))

    result = await remediation_service.append_pages(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        target_stack_id, new_file_id, storage,  # type: ignore[arg-type]
    )
    await db_session.commit()

    # Pages exist with global numbers 3-4 (target had 1-2).
    assert result.pages_added == 2
    assert result.first_page_number == 3
    assert result.last_page_number == 4
    assert result.snapshot["doc_type"] == "paystub"
    assert result.snapshot["page_numbers"] == [1, 2]

    # Stack now spans 1-4 (non-contiguous tracking is fine).
    target = (await db_session.execute(
        select(LOStack).where(LOStack.id == target_stack_id)
    )).scalar_one()
    assert target.page_numbers == [1, 2, 3, 4]
    assert target.last_page == 4

    # Inherited classifications on the new pages reflect the target.
    new_clfs = (await db_session.execute(
        select(LOClassification).where(
            LOClassification.package_id == TEST_PACKAGE_ID,
            LOClassification.page_number.in_([3, 4]),
        ).order_by(LOClassification.page_number.asc())
    )).scalars().all()
    assert [c.predicted_doc_type for c in new_clfs] == ["paystub", "paystub"]
    assert all(c.page_role == "continuation" for c in new_clfs)


@pytest.mark.asyncio
async def test_append_pages_unknown_stack_raises(
    db_session: AsyncSession, sample_package,
):
    new_file_id = await _seed_package_file(
        db_session,
        filename="x.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/x.pdf",
    )
    storage = _FakeStorage(_build_blank_pdf_bytes(1))
    with pytest.raises(ValueError, match="not found"):
        await remediation_service.append_pages(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
            uuid.uuid4(), new_file_id, storage,  # type: ignore[arg-type]
        )


def _patch_classifier(monkeypatch, *, doc_type: str, confidence: float):
    """Helper: replace PageClassifierAgent.classify_pdf with a stub
    returning ``(doc_type, confidence)`` for every requested page."""
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
        PageClassifierAgent,
    )
    from app.micro_apps.loan_onboarding.schemas.classification import (
        Classification,
        ClassificationBatchResult,
    )

    async def _fake(self, pdf_bytes, page_numbers, timeout=None):
        return ClassificationBatchResult(classifications=[
            Classification(
                page_number=pn,
                predicted_doc_type=doc_type,
                predicted_doc_type_alternatives=[],
                confidence=confidence,
                page_role="continuation",
                detected_fields=[],
            )
            for pn in page_numbers
        ])
    monkeypatch.setattr(PageClassifierAgent, "classify_pdf", _fake)


@pytest.mark.asyncio
async def test_classify_recheck_holds_when_doc_type_matches(
    db_session: AsyncSession, sample_package, monkeypatch,
):
    """Recheck verdict matches the target — classifications are persisted,
    confidence blends, no rollback."""
    _, target_stack_id = await _seed_stack_with_signature_page(
        db_session, stack_doc_type="paystub",
    )
    new_file_id = await _seed_package_file(
        db_session,
        filename="paystub_pages.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/paystub_pages.pdf",
    )
    storage = _FakeStorage(_build_blank_pdf_bytes(2))

    append = await remediation_service.append_pages(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        target_stack_id, new_file_id, storage,  # type: ignore[arg-type]
    )
    await db_session.commit()

    _patch_classifier(monkeypatch, doc_type="paystub", confidence=0.93)

    result = await remediation_service.classify_recheck(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        target_stack_id, new_file_id, storage, append.snapshot,  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert result.status == "ok"
    assert result.merged_stack_id == target_stack_id
    assert result.new_doc_type == "paystub"
    assert result.rollback_reason is None

    # Stack still spans 1-4.
    target = (await db_session.execute(
        select(LOStack).where(LOStack.id == target_stack_id)
    )).scalar_one()
    assert target.page_numbers == [1, 2, 3, 4]
    # File row survived (no rollback).
    assert (await db_session.execute(
        select(LOPackageFile).where(LOPackageFile.id == new_file_id)
    )).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_classify_recheck_rolls_back_on_doc_type_drift(
    db_session: AsyncSession, sample_package, monkeypatch,
):
    """Recheck classifies new pages as a different doc_type — rollback
    deletes the file (CASCADE) and restores the target stack."""
    _, target_stack_id = await _seed_stack_with_signature_page(
        db_session, stack_doc_type="paystub",
    )
    new_file_id = await _seed_package_file(
        db_session,
        filename="bad_pages.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/bad_pages.pdf",
    )
    storage = _FakeStorage(_build_blank_pdf_bytes(2))

    append = await remediation_service.append_pages(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        target_stack_id, new_file_id, storage,  # type: ignore[arg-type]
    )
    await db_session.commit()

    # Operator uploaded what turned out to be a W-2, not paystub continuation.
    _patch_classifier(monkeypatch, doc_type="w2", confidence=0.91)

    result = await remediation_service.classify_recheck(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        target_stack_id, new_file_id, storage, append.snapshot,  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert result.status == "rolled_back"
    assert "w2" in (result.rollback_reason or "")

    # File row is gone.
    assert (await db_session.execute(
        select(LOPackageFile).where(LOPackageFile.id == new_file_id)
    )).scalar_one_or_none() is None
    # CASCADE wiped the new pages too.
    assert (await db_session.execute(
        select(LOPage).where(LOPage.file_id == new_file_id)
    )).scalars().first() is None

    # Target stack restored to its pre-append state.
    target = (await db_session.execute(
        select(LOStack).where(LOStack.id == target_stack_id)
    )).scalar_one()
    assert target.page_numbers == [1, 2]
    assert target.last_page == 2


@pytest.mark.asyncio
async def test_classify_recheck_rolls_back_on_confidence_collapse(
    db_session: AsyncSession, sample_package, monkeypatch,
):
    """Doc-type matches but confidence dives — still a rollback."""
    _, target_stack_id = await _seed_stack_with_signature_page(
        db_session, stack_doc_type="paystub",
    )
    # Bump the seeded stack's stored confidence so the drop trigger fires
    # cleanly. The seed fixture sets it at 0.95.
    new_file_id = await _seed_package_file(
        db_session,
        filename="blurry_pages.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/blurry_pages.pdf",
    )
    storage = _FakeStorage(_build_blank_pdf_bytes(2))

    append = await remediation_service.append_pages(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        target_stack_id, new_file_id, storage,  # type: ignore[arg-type]
    )
    await db_session.commit()

    # Same doc_type but confidence drops far below the 0.95 baseline
    # (drop = 0.95 - 0.40 = 0.55 > 0.15 threshold).
    _patch_classifier(monkeypatch, doc_type="paystub", confidence=0.40)

    result = await remediation_service.classify_recheck(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        target_stack_id, new_file_id, storage, append.snapshot,  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert result.status == "rolled_back"
    assert "confidence" in (result.rollback_reason or "")

    # File row is gone.
    assert (await db_session.execute(
        select(LOPackageFile).where(LOPackageFile.id == new_file_id)
    )).scalar_one_or_none() is None
    # Stack restored.
    target = (await db_session.execute(
        select(LOStack).where(LOStack.id == target_stack_id)
    )).scalar_one()
    assert target.page_numbers == [1, 2]


@pytest.mark.asyncio
async def test_classify_recheck_unknown_file_raises(
    db_session: AsyncSession, sample_package,
):
    _, target_stack_id = await _seed_stack_with_signature_page(db_session)
    storage = _FakeStorage(_build_blank_pdf_bytes(1))
    with pytest.raises(ValueError, match="no LOPage rows"):
        await remediation_service.classify_recheck(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
            target_stack_id, uuid.uuid4(), storage, {"doc_type": "paystub"},  # type: ignore[arg-type]
        )
