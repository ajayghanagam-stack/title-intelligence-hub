"""Tests for the Loan Onboarding ingest stage + orchestrator skeleton."""
import io
import uuid

import fitz
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.pipeline.stages import stage_ingest
from app.micro_apps.loan_onboarding.pipeline.orchestrator import run_pipeline
from app.services.storage import get_storage
from tests.conftest import TEST_ORG_ID, test_session_factory
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


def _make_pdf(page_texts: list[str]) -> bytes:
    """Build an in-memory PDF with one page per supplied text blob."""
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=612, height=792)
        if text:
            page.insert_text((72, 72), text)
    out = doc.tobytes()
    doc.close()
    return out


def _make_scanned_pdf(num_pages: int = 1) -> bytes:
    """Build a PDF whose pages carry an embedded image but no extractable text.

    Mirrors what a typical scanner-output PDF looks like (raster page content,
    no text layer). Uses a procedurally-generated noisy JPEG so `get_images()`
    returns a non-empty list.
    """
    # Build a small noisy raster (alternating dark/light bands) so the page is
    # not near-white even if an image-XObject check fails.
    import struct
    width, height = 64, 80
    # Minimal PPM → PyMuPDF can consume via Pixmap(stream=...)
    ppm_header = f"P6\n{width} {height}\n255\n".encode("ascii")
    body = bytearray()
    for y in range(height):
        row_val = 30 if (y // 4) % 2 == 0 else 200
        for _x in range(width):
            body.extend(struct.pack("BBB", row_val, row_val, row_val))
    pix_bytes = ppm_header + bytes(body)

    pix = fitz.Pixmap(io.BytesIO(pix_bytes))
    try:
        img_bytes = pix.tobytes("png")
    finally:
        pix = None  # noqa: F841

    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page(width=612, height=792)
        # Insert image covering the full page → simulates a scanner page
        page.insert_image(fitz.Rect(0, 0, 612, 792), stream=img_bytes)
    out = doc.tobytes()
    doc.close()
    return out


async def _upload_file(
    db: AsyncSession, storage, package_id: uuid.UUID, filename: str, pdf_bytes: bytes
) -> LOPackageFile:
    path = storage.make_pack_path(TEST_ORG_ID, package_id, filename)
    await storage.put_object(path, pdf_bytes, content_type="application/pdf")
    row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=package_id,
        filename=filename,
        storage_path=path,
        content_hash="x" * 64,
        size_bytes=len(pdf_bytes),
        page_count=0,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_ingest_splits_pdf_into_pages(
    sample_package, db_session: AsyncSession
):
    storage = get_storage()
    pdf_bytes = _make_pdf([
        "Uniform Residential Loan Application (Form 1003). Borrower: Jane Smith.",
        "",  # blank page (heuristic)
        "Pay stub — 03/15/2026. Gross: $5000.",
    ])
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "loan_bundle.pdf", pdf_bytes)

    output = await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)

    assert output["files"] == 1
    assert output["pages"] == 3
    assert output["blank_pages"] == 1
    assert output["text_pages"] == 2
    assert output["image_pages"] == 0

    rows = (await db_session.execute(
        select(LOPage).where(LOPage.package_id == TEST_PACKAGE_ID).order_by(LOPage.page_number)
    )).scalars().all()
    assert [r.page_number for r in rows] == [1, 2, 3]
    assert [r.source_page_number for r in rows] == [1, 2, 3]
    assert rows[0].text_length > 0
    assert rows[1].text_length == 0  # the blank page
    assert "Jane Smith" in (rows[0].heuristic_text or "")
    # Hybrid signal is populated for every ingested page
    assert [r.content_signal for r in rows] == ["text", "blank", "text"]


@pytest.mark.asyncio
async def test_ingest_detects_scanned_pages_as_image(
    sample_package, db_session: AsyncSession
):
    """Scanned / image-only pages (no text, raster content) are tagged 'image'."""
    storage = get_storage()
    pdf_bytes = _make_scanned_pdf(num_pages=2)
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "scanned.pdf", pdf_bytes)

    output = await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)

    # Both pages had an image inserted and no text layer → both must be
    # classified as image-bearing, NOT blank (which would route them to
    # Others-with-confidence-1.0 in classify).
    assert output["pages"] == 2
    assert output["image_pages"] == 2
    assert output["blank_pages"] == 0
    assert output["text_pages"] == 0

    rows = (await db_session.execute(
        select(LOPage).where(LOPage.package_id == TEST_PACKAGE_ID).order_by(LOPage.page_number)
    )).scalars().all()
    assert [r.content_signal for r in rows] == ["image", "image"]
    # No embedded text on scanned pages
    assert all((r.text_length or 0) == 0 for r in rows)


@pytest.mark.asyncio
async def test_ingest_signal_mix_across_pages(
    sample_package, db_session: AsyncSession
):
    """A package with text + blank + scanned pages lands three distinct signals."""
    storage = get_storage()
    # Page 1: normal text. Page 2: truly blank. Page 3: scanned (image only).
    text_pdf = _make_pdf(["URLA 1003 — Borrower: Jane Smith. Loan amount: $350000."])
    blank_pdf = _make_pdf([""])
    scanned_pdf = _make_scanned_pdf(num_pages=1)
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "a.pdf", text_pdf)
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "b.pdf", blank_pdf)
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "c.pdf", scanned_pdf)

    output = await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)

    assert output["pages"] == 3
    assert output["text_pages"] == 1
    assert output["image_pages"] == 1
    assert output["blank_pages"] == 1

    rows = (await db_session.execute(
        select(LOPage).where(LOPage.package_id == TEST_PACKAGE_ID).order_by(LOPage.page_number)
    )).scalars().all()
    assert [r.content_signal for r in rows] == ["text", "blank", "image"]


@pytest.mark.asyncio
async def test_ingest_numbers_pages_globally_across_files(
    sample_package, db_session: AsyncSession
):
    storage = get_storage()
    pdf_a = _make_pdf(["File A page 1", "File A page 2"])
    pdf_b = _make_pdf(["File B page 1", "File B page 2", "File B page 3"])
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "a.pdf", pdf_a)
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "b.pdf", pdf_b)

    output = await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)

    assert output["pages"] == 5

    rows = (await db_session.execute(
        select(LOPage).where(LOPage.package_id == TEST_PACKAGE_ID).order_by(LOPage.page_number)
    )).scalars().all()
    # Global page numbers are 1..5 regardless of source file.
    assert [r.page_number for r in rows] == [1, 2, 3, 4, 5]
    # Source numbers restart per file.
    assert [r.source_page_number for r in rows] == [1, 2, 1, 2, 3]


@pytest.mark.asyncio
async def test_ingest_is_idempotent(sample_package, db_session: AsyncSession):
    """Running ingest twice produces the same number of rows (no duplicates)."""
    storage = get_storage()
    pdf_bytes = _make_pdf(["page one", "page two"])
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "bundle.pdf", pdf_bytes)

    await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)
    await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)

    count = (await db_session.execute(
        select(LOPage).where(LOPage.package_id == TEST_PACKAGE_ID)
    )).scalars().all()
    assert len(count) == 2


@pytest.mark.asyncio
async def test_ingest_raises_without_files(sample_package, db_session: AsyncSession):
    storage = get_storage()
    with pytest.raises(ValueError, match="No files uploaded"):
        await stage_ingest(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)


@pytest.mark.asyncio
async def test_run_pipeline_end_to_end_with_mocked_ai(
    sample_package, db_session: AsyncSession, monkeypatch
):
    """Run the full 5-stage pipeline with both AI agents mocked.

    The sample package has a missing_signatures preset rule and no signature
    pages, so the validate stage flags the stack for HITL — the final
    package status should be `awaiting_review`.
    """
    from unittest.mock import AsyncMock, patch
    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
        PageClassifierAgent,
    )
    from app.micro_apps.loan_onboarding.ai import reasoning_agent as ra_mod
    from app.micro_apps.loan_onboarding.ai.reasoning_agent import (
        PackageReasoningOutput,
        StackReasoning,
    )

    storage = get_storage()
    pdf_bytes = _make_pdf(["Loan app URLA 1003 — Borrower: Jane Smith. Income: $120k."])
    await _upload_file(db_session, storage, TEST_PACKAGE_ID, "p.pdf", pdf_bytes)

    # Keep retries snappy in tests
    import app.micro_apps.loan_onboarding.pipeline.orchestrator as orch
    async def _no_sleep(_):
        return
    monkeypatch.setattr(orch.asyncio, "sleep", _no_sleep)

    async def fake_classify(**kwargs):
        return {"classifications": [
            {"page_number": 1, "predicted_doc_type": "URLA_1003",
             "confidence": 0.9, "page_role": "first_page"},
        ]}

    mock_reason = AsyncMock(return_value=PackageReasoningOutput(
        stacks=[],  # orchestrator pads missing entries to needs_review
        package_level_issues=[],
    ))

    with (
        patch.object(PageClassifierAgent, "call_json_structured", side_effect=fake_classify),
        patch.object(ra_mod.ReasoningAgent, "reason", mock_reason),
    ):
        await run_pipeline(TEST_PACKAGE_ID, TEST_ORG_ID, test_session_factory, storage)

    from app.micro_apps.loan_onboarding.models.package import LOPackage
    async with test_session_factory() as fresh:
        pkg = (await fresh.execute(
            select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
        )).scalar_one()
        # missing_signatures rule fails → validate marks stack HITL →
        # review routes the package to awaiting_review (not completed).
        assert pkg.status == "awaiting_review"
        assert pkg.pipeline_stage == "complete"
        assert pkg.pipeline_error is None
