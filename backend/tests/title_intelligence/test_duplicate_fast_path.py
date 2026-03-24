"""Tests for the duplicate file fast path in stage_render.

When a user uploads the same PDF into a new pack, the pipeline should detect
the duplicate via input_file_hash, clone pages from the donor pack, and skip
PDF rendering + OCR entirely.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
from app.micro_apps.title_intelligence.pipeline.stages import (
    _find_donor_pack,
    _clone_pages_from_donor,
    stage_render,
)
from tests.conftest import TEST_ORG_ID

DONOR_PACK_ID = uuid.UUID("00000000-0000-0000-0000-000000100000")
TARGET_PACK_ID = uuid.UUID("00000000-0000-0000-0000-000000200000")
DONOR_FILE_ID = uuid.UUID("00000000-0000-0000-0000-000000100001")
TARGET_FILE_ID = uuid.UUID("00000000-0000-0000-0000-000000200001")
OTHER_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000999999")
INPUT_FILE_HASH = "a" * 64


@pytest_asyncio.fixture
async def donor_pack(db_session: AsyncSession, seed_data):
    """Create a completed donor pack with pages."""
    pack = Pack(
        id=DONOR_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Donor Pack",
        status="completed",
    )
    db_session.add(pack)

    pack_file = PackFile(
        id=DONOR_FILE_ID,
        pack_id=DONOR_PACK_ID,
        org_id=TEST_ORG_ID,
        filename="test.pdf",
        storage_path=f"{TEST_ORG_ID}/{DONOR_PACK_ID}/files/test.pdf",
        file_size=1024,
        content_hash="abc123" + "0" * 58,
        page_count=2,
    )
    db_session.add(pack_file)

    # Add pipeline run
    run = PipelineRun(
        org_id=TEST_ORG_ID,
        pack_id=DONOR_PACK_ID,
        input_file_hash=INPUT_FILE_HASH,
        status="completed",
        completed_at=datetime.now(timezone.utc),
        ai_platform="anthropic",
        ai_model="claude-haiku-4-5-20251001",
        ingestion_prompt_hash="h" * 64,
        risk_prompt_hash="h" * 64,
        extraction_tool_hash="h" * 64,
        risk_tool_hash="h" * 64,
        ocr_engine="tesseract 5.3.0",
        chunker_version="hierarchical_v1",
        rules_version="weighted_5cat_v2",
        pipeline_backend="background_tasks",
    )
    db_session.add(run)

    # Add pages with OCR text
    for i in range(1, 3):
        page = Page(
            pack_id=DONOR_PACK_ID,
            file_id=DONOR_FILE_ID,
            org_id=TEST_ORG_ID,
            page_number=i,
            image_uri=f"{TEST_ORG_ID}/{DONOR_PACK_ID}/pages/page_{i:04d}.jpg",
            thumb_uri=f"{TEST_ORG_ID}/{DONOR_PACK_ID}/thumbs/page_{i:04d}.jpg",
            ocr_text=f"Page {i} text content from the title commitment document.",
        )
        db_session.add(page)

    await db_session.commit()
    return pack


@pytest_asyncio.fixture
async def target_pack(db_session: AsyncSession, seed_data):
    """Create a target pack (no pages yet)."""
    pack = Pack(
        id=TARGET_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Target Pack",
        status="processing",
    )
    db_session.add(pack)

    pack_file = PackFile(
        id=TARGET_FILE_ID,
        pack_id=TARGET_PACK_ID,
        org_id=TEST_ORG_ID,
        filename="test.pdf",
        storage_path=f"{TEST_ORG_ID}/{TARGET_PACK_ID}/files/test.pdf",
        file_size=1024,
        content_hash="abc123" + "0" * 58,
        page_count=None,
    )
    db_session.add(pack_file)
    await db_session.commit()
    return pack


# --- _find_donor_pack tests ---


@pytest.mark.asyncio
async def test_find_donor_pack_returns_completed_pack(db_session, donor_pack, target_pack):
    """Happy path: finds a completed donor pack with matching input_file_hash."""
    result = await _find_donor_pack(db_session, TEST_ORG_ID, TARGET_PACK_ID, INPUT_FILE_HASH)
    assert result == DONOR_PACK_ID


@pytest.mark.asyncio
async def test_find_donor_pack_skips_different_org(db_session, donor_pack, target_pack):
    """Tenant isolation: donor from a different org is not returned."""
    result = await _find_donor_pack(db_session, OTHER_ORG_ID, TARGET_PACK_ID, INPUT_FILE_HASH)
    assert result is None


@pytest.mark.asyncio
async def test_find_donor_pack_skips_failed_pack(db_session, seed_data, target_pack):
    """Only completed packs qualify as donors."""
    # Create a failed pack with matching hash
    failed_pack_id = uuid.uuid4()
    pack = Pack(id=failed_pack_id, org_id=TEST_ORG_ID, name="Failed", status="failed")
    db_session.add(pack)
    run = PipelineRun(
        org_id=TEST_ORG_ID,
        pack_id=failed_pack_id,
        input_file_hash=INPUT_FILE_HASH,
        status="failed",
        ai_platform="anthropic",
        ai_model="claude-haiku-4-5-20251001",
        ingestion_prompt_hash="h" * 64,
        risk_prompt_hash="h" * 64,
        extraction_tool_hash="h" * 64,
        risk_tool_hash="h" * 64,
        ocr_engine="tesseract 5.3.0",
        chunker_version="hierarchical_v1",
        rules_version="weighted_5cat_v2",
        pipeline_backend="background_tasks",
    )
    db_session.add(run)
    await db_session.commit()

    result = await _find_donor_pack(db_session, TEST_ORG_ID, TARGET_PACK_ID, INPUT_FILE_HASH)
    assert result is None


@pytest.mark.asyncio
async def test_find_donor_pack_skips_pack_without_pages(db_session, seed_data, target_pack):
    """Donor pack exists and is completed but has no pages (data deleted)."""
    empty_pack_id = uuid.uuid4()
    pack = Pack(id=empty_pack_id, org_id=TEST_ORG_ID, name="Empty", status="completed")
    db_session.add(pack)
    run = PipelineRun(
        org_id=TEST_ORG_ID,
        pack_id=empty_pack_id,
        input_file_hash=INPUT_FILE_HASH,
        status="completed",
        completed_at=datetime.now(timezone.utc),
        ai_platform="anthropic",
        ai_model="claude-haiku-4-5-20251001",
        ingestion_prompt_hash="h" * 64,
        risk_prompt_hash="h" * 64,
        extraction_tool_hash="h" * 64,
        risk_tool_hash="h" * 64,
        ocr_engine="tesseract 5.3.0",
        chunker_version="hierarchical_v1",
        rules_version="weighted_5cat_v2",
        pipeline_backend="background_tasks",
    )
    db_session.add(run)
    await db_session.commit()

    result = await _find_donor_pack(db_session, TEST_ORG_ID, TARGET_PACK_ID, INPUT_FILE_HASH)
    assert result is None


@pytest.mark.asyncio
async def test_find_donor_pack_skips_self(db_session, donor_pack):
    """Current pack is excluded even if it has a completed pipeline run."""
    result = await _find_donor_pack(db_session, TEST_ORG_ID, DONOR_PACK_ID, INPUT_FILE_HASH)
    assert result is None


# --- _clone_pages_from_donor tests ---


@pytest.mark.asyncio
async def test_clone_pages_copies_ocr_text(db_session, donor_pack, target_pack):
    """Key optimization: cloned pages preserve ocr_text so OCR stage is skipped."""
    storage = AsyncMock()
    storage.read = AsyncMock(return_value=b"fake-image-data")
    storage.save = AsyncMock(return_value="saved")
    storage.make_page_path = lambda org, pack, num: f"{org}/{pack}/pages/page_{num:04d}.jpg"
    storage.make_thumb_path = lambda org, pack, num: f"{org}/{pack}/thumbs/page_{num:04d}.jpg"

    cloned = await _clone_pages_from_donor(DONOR_PACK_ID, TARGET_PACK_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    assert cloned == 2

    result = await db_session.execute(
        select(Page).where(Page.pack_id == TARGET_PACK_ID, Page.org_id == TEST_ORG_ID)
        .order_by(Page.page_number)
    )
    target_pages = list(result.scalars().all())

    assert len(target_pages) == 2
    assert target_pages[0].ocr_text == "Page 1 text content from the title commitment document."
    assert target_pages[1].ocr_text == "Page 2 text content from the title commitment document."


@pytest.mark.asyncio
async def test_clone_pages_creates_independent_storage_paths(db_session, donor_pack, target_pack):
    """Cloned pages use target pack's storage namespace, not donor's."""
    storage = AsyncMock()
    storage.read = AsyncMock(return_value=b"fake-image-data")
    storage.save = AsyncMock(return_value="saved")
    storage.make_page_path = lambda org, pack, num: f"{org}/{pack}/pages/page_{num:04d}.jpg"
    storage.make_thumb_path = lambda org, pack, num: f"{org}/{pack}/thumbs/page_{num:04d}.jpg"

    await _clone_pages_from_donor(DONOR_PACK_ID, TARGET_PACK_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    result = await db_session.execute(
        select(Page).where(Page.pack_id == TARGET_PACK_ID, Page.org_id == TEST_ORG_ID)
        .order_by(Page.page_number)
    )
    target_pages = list(result.scalars().all())

    for page in target_pages:
        assert str(TARGET_PACK_ID) in page.image_uri
        assert str(TARGET_PACK_ID) in page.thumb_uri
        assert str(DONOR_PACK_ID) not in page.image_uri
        assert str(DONOR_PACK_ID) not in page.thumb_uri


# --- stage_render integration tests ---


@pytest.mark.asyncio
async def test_stage_render_uses_fast_path(db_session, donor_pack, target_pack):
    """Integration: stage_render clones from donor instead of rendering PDFs."""
    storage = AsyncMock()
    storage.read = AsyncMock(return_value=b"fake-image-data")
    storage.save = AsyncMock(return_value="saved")
    storage.exists = AsyncMock(return_value=True)
    storage.make_page_path = lambda org, pack, num: f"{org}/{pack}/pages/page_{num:04d}.jpg"
    storage.make_thumb_path = lambda org, pack, num: f"{org}/{pack}/thumbs/page_{num:04d}.jpg"

    with patch(
        "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_input_file_hash",
        new_callable=AsyncMock,
        return_value=INPUT_FILE_HASH,
    ):
        await stage_render(TARGET_PACK_ID, TEST_ORG_ID, db_session, storage)

    # Verify pages were created from donor
    result = await db_session.execute(
        select(Page).where(Page.pack_id == TARGET_PACK_ID, Page.org_id == TEST_ORG_ID)
    )
    pages = list(result.scalars().all())
    assert len(pages) == 2
    # All pages should have ocr_text (cloned from donor)
    assert all(p.ocr_text for p in pages)


@pytest.mark.asyncio
async def test_stage_render_falls_back_on_clone_failure(db_session, donor_pack, target_pack):
    """Graceful degradation: if clone fails, fall through to normal PDF render."""
    import logging

    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.make_page_path = lambda org, pack, num: f"{org}/{pack}/pages/page_{num:04d}.jpg"
    storage.make_thumb_path = lambda org, pack, num: f"{org}/{pack}/thumbs/page_{num:04d}.jpg"

    # storage.read fails for donor pages (clone) but returns minimal bytes
    # for the actual PDF (normal render). The fitz open will fail on invalid
    # PDF data, proving the fallback path executed.
    target_file_path = f"{TEST_ORG_ID}/{TARGET_PACK_ID}/files/test.pdf"

    async def read_side_effect(path):
        if path == target_file_path:
            return b"not-a-real-pdf"  # fitz will fail to parse this
        raise IOError("Storage unavailable")

    storage.read = AsyncMock(side_effect=read_side_effect)

    with patch(
        "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_input_file_hash",
        new_callable=AsyncMock,
        return_value=INPUT_FILE_HASH,
    ):
        # Clone fails → falls back to normal render → fitz fails on bad PDF
        with pytest.raises(Exception) as exc_info:
            await stage_render(TARGET_PACK_ID, TEST_ORG_ID, db_session, storage)

        # The error should be from fitz (bad PDF), NOT the clone IOError
        assert "Storage unavailable" not in str(exc_info.value)
