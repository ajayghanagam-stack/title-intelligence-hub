"""Integration tests for stage_examine pipeline stage."""

import json
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.section import Section
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.text_chunk import TextChunk
from app.micro_apps.title_intelligence.schemas.examiner import (
    ExaminerConsolidatedResult,
    ExaminerExtraction,
    ExaminerFlag,
    ExaminerSection,
    PageTranscription,
)

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID, TEST_FILE_ID

MOCK_VERSION_INFO = {
    "ai_platform": "gemini",
    "ai_model": "gemini/gemini-2.5-flash",
    "ingestion_prompt_hash": "test_hash",
    "risk_prompt_hash": "test_hash",
    "extraction_tool_hash": "test_hash",
    "risk_tool_hash": "test_hash",
    "ocr_engine": "gemini_vision",
    "chunker_version": "hierarchical_v1",
    "rules_version": "weighted_5cat_v2",
    "pipeline_backend": "background_tasks",
    "version_metadata": {"ai_platform": "gemini", "ai_model": "gemini/gemini-2.5-flash", "pipeline_mode": "examiner"},
}


@pytest_asyncio.fixture
async def pack_with_pages(db_session: AsyncSession, seed_data):
    """Create a pack with rendered pages (simulating post-stage_render)."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Examiner Pack",
        status="processing",
        current_stage="examine",
    )
    db_session.add(pack)

    pack_file = PackFile(
        id=TEST_FILE_ID,
        pack_id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        filename="test.pdf",
        file_size=1024,
        storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        content_hash="abc123",
    )
    db_session.add(pack_file)

    # Create 3 rendered pages — 2 with embedded text, 1 scanned (no text)
    embedded_texts = {
        1: "COMMITMENT FOR TITLE INSURANCE — This is the cover page with enough embedded text to qualify as a text page for hybrid processing.",
        2: "Schedule A — Effective Date: January 15, 2024. Buyer: John Doe. This page has sufficient embedded text for the hybrid optimization.",
    }
    for i in range(1, 4):
        db_session.add(Page(
            pack_id=TEST_PACK_ID,
            file_id=TEST_FILE_ID,
            org_id=TEST_ORG_ID,
            page_number=i,
            image_uri=f"{TEST_ORG_ID}/{TEST_PACK_ID}/pages/page_{i:04d}.jpg",
            thumb_uri=f"{TEST_ORG_ID}/{TEST_PACK_ID}/thumbs/page_{i:04d}.jpg",
            ocr_text=embedded_texts.get(i),
        ))

    await db_session.commit()
    return pack


def _make_mock_consolidated():
    """Create a mock ExaminerConsolidatedResult."""
    return ExaminerConsolidatedResult(
        page_transcriptions=[
            PageTranscription(page_number=1, text="COMMITMENT FOR TITLE INSURANCE\nIssued by First American"),
            PageTranscription(page_number=2, text="Schedule A\nEffective Date: January 15, 2024\nBuyer: John Doe"),
            PageTranscription(page_number=3, text="Schedule B-I\n1. Pay off existing mortgage"),
        ],
        sections=[
            ExaminerSection(section_type="schedule_a", start_page=2, end_page=2, confidence=0.95),
            ExaminerSection(section_type="schedule_b1", start_page=3, end_page=3, confidence=0.9),
        ],
        extractions=[
            ExaminerExtraction(
                extraction_type="policy_info",
                label="Effective Date",
                value={"date": "2024-01-15"},
                evidence_refs=[{"page_number": 2, "text_snippet": "Effective Date: January 15, 2024"}],
                confidence=0.9,
            ),
            ExaminerExtraction(
                extraction_type="party",
                label="Buyer",
                value={"name": "John Doe", "role": "buyer"},
                evidence_refs=[{"page_number": 2, "text_snippet": "Buyer: John Doe"}],
                confidence=0.85,
            ),
        ],
        flags=[
            ExaminerFlag(
                flag_type="unresolved_lien",
                severity="high",
                title="Outstanding Mortgage",
                description="Existing mortgage requires payoff",
                ai_explanation="Schedule B-I requires mortgage payoff, indicating an unresolved lien.",
                evidence_refs=[{"page_number": 3, "text_snippet": "Pay off existing mortgage"}],
            ),
        ],
    )


def _make_mock_storage():
    """Create a mock storage that returns fake image bytes."""
    storage = AsyncMock()
    storage.read = AsyncMock(return_value=b"fake-image-bytes")
    storage.exists = AsyncMock(return_value=False)
    storage.save = AsyncMock()
    storage.make_ai_cache_path = MagicMock(return_value="cache/examiner/test")
    return storage


def _make_mock_agent(mock_consolidated):
    """Create a mock TitleExaminerAgent with proper batch config."""
    mock_agent = MagicMock()
    mock_agent.examine_document = AsyncMock(return_value=mock_consolidated)
    mock_agent._get_batch_config = MagicMock(return_value={
        "batch_size_image": 8,
        "batch_size_text": 25,
        "concurrency": 8,
        "stagger_ms": 100,
        "rpm": 50,
    })
    mock_agent._ensure_context_cache = AsyncMock(return_value=None)
    mock_agent.JSON_SCHEMA = {}
    return mock_agent


def _stage_examine_patches():
    """Return a stack of patches needed for stage_examine tests."""
    return [
        patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.collect_version_info",
            return_value=MOCK_VERSION_INFO,
        ),
        patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_examiner_cache_key",
            return_value="test_cache_key",
        ),
    ]


@pytest.mark.asyncio
async def test_stage_examine_creates_records(db_session: AsyncSession, pack_with_pages):
    """stage_examine should create sections, extractions, flags, text chunks, and update pages."""
    from app.micro_apps.title_intelligence.pipeline.stages import stage_examine

    mock_storage = _make_mock_storage()
    mock_consolidated = _make_mock_consolidated()

    mock_agent_instance = _make_mock_agent(mock_consolidated)

    patches = _stage_examine_patches() + [
        patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent",
            return_value=mock_agent_instance,
        ),
    ]

    for p in patches:
        p.start()
    try:
        await stage_examine(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
    finally:
        for p in patches:
            p.stop()

    # Verify on_batch_complete callback was passed
    examine_call = mock_agent_instance.examine_document.call_args
    assert examine_call.kwargs.get("on_batch_complete") is not None or len(examine_call.args) >= 3

    # Check pages got OCR text
    pages = (await db_session.execute(
        select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
    )).scalars().all()
    assert pages[0].ocr_text is not None
    assert "COMMITMENT" in pages[0].ocr_text
    assert "Schedule A" in pages[1].ocr_text

    # Check sections
    sections = (await db_session.execute(
        select(Section).where(Section.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(sections) == 2
    section_types = {s.section_type for s in sections}
    assert "schedule_a" in section_types
    assert "schedule_b1" in section_types

    # Check extractions
    extractions = (await db_session.execute(
        select(Extraction).where(Extraction.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(extractions) == 2
    ext_types = {e.extraction_type for e in extractions}
    assert "policy_info" in ext_types
    assert "party" in ext_types

    # Check flags (after normalization)
    flags = (await db_session.execute(
        select(Flag).where(Flag.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(flags) == 1
    assert flags[0].flag_type == "unresolved_lien"
    assert flags[0].severity == "high"

    # Check text chunks were created
    chunks = (await db_session.execute(
        select(TextChunk).where(TextChunk.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_stage_examine_cache_hit(db_session: AsyncSession, pack_with_pages):
    """On cache hit, stage_examine should replay without calling the agent."""
    from app.micro_apps.title_intelligence.pipeline.stages import stage_examine

    cached_data = {
        "page_transcriptions": [
            {"page_number": 1, "text": "Cached text page 1"},
            {"page_number": 2, "text": "Cached text page 2"},
            {"page_number": 3, "text": "Cached text page 3"},
        ],
        "sections": [
            {"section_type": "schedule_a", "start_page": 1, "end_page": 2, "confidence": 0.9},
        ],
        "extractions": [
            {
                "extraction_type": "party",
                "label": "Seller",
                "value": {"name": "Jane Smith"},
                "evidence_refs": [{"page_number": 1, "text_snippet": "Seller: Jane Smith"}],
                "confidence": 0.88,
            },
        ],
        "flags": [
            {
                "flag_type": "missing_endorsement",
                "severity": "medium",
                "title": "Missing EPA Endorsement",
                "description": "EPA endorsement not found",
                "ai_explanation": "No EPA endorsement listed.",
                "evidence_refs": [{"page_number": 2, "text_snippet": "Endorsements: none"}],
                "status": "open",
            },
        ],
    }

    mock_storage = _make_mock_storage()
    mock_storage.exists = AsyncMock(return_value=True)
    mock_storage.read = AsyncMock(return_value=json.dumps(cached_data).encode())

    patches = _stage_examine_patches()
    for p in patches:
        p.start()
    try:
        await stage_examine(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
    finally:
        for p in patches:
            p.stop()

    # Should have replayed from cache
    sections = (await db_session.execute(
        select(Section).where(Section.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(sections) == 1
    assert sections[0].section_type == "schedule_a"

    extractions = (await db_session.execute(
        select(Extraction).where(Extraction.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(extractions) == 1

    flags = (await db_session.execute(
        select(Flag).where(Flag.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(flags) == 1
    assert flags[0].flag_type == "missing_endorsement"

    # Pages should have cached text
    pages = (await db_session.execute(
        select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
    )).scalars().all()
    assert pages[0].ocr_text == "Cached text page 1"


@pytest.mark.asyncio
async def test_stage_examine_idempotent(db_session: AsyncSession, pack_with_pages):
    """Running stage_examine twice should produce the same result (delete-then-insert)."""
    from app.micro_apps.title_intelligence.pipeline.stages import stage_examine

    mock_storage = _make_mock_storage()
    mock_consolidated = _make_mock_consolidated()

    mock_agent_instance = _make_mock_agent(mock_consolidated)

    patches = _stage_examine_patches() + [
        patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent",
            return_value=mock_agent_instance,
        ),
    ]

    for p in patches:
        p.start()
    try:
        # Run twice
        await stage_examine(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
        await stage_examine(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
    finally:
        for p in patches:
            p.stop()

    # Should have exactly the same number of records as one run
    sections = (await db_session.execute(
        select(Section).where(Section.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(sections) == 2

    extractions = (await db_session.execute(
        select(Extraction).where(Extraction.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(extractions) == 2

    flags = (await db_session.execute(
        select(Flag).where(Flag.pack_id == TEST_PACK_ID)
    )).scalars().all()
    assert len(flags) == 1


@pytest.mark.asyncio
async def test_stage_examine_normalizes_flags(db_session: AsyncSession, pack_with_pages):
    """Flags should be normalized (invalid types dropped, severity clamped)."""
    from app.micro_apps.title_intelligence.pipeline.stages import stage_examine

    mock_consolidated = ExaminerConsolidatedResult(
        page_transcriptions=[
            PageTranscription(page_number=1, text="Test text"),
        ],
        sections=[],
        extractions=[],
        flags=[
            # Valid flag
            ExaminerFlag(
                flag_type="unresolved_lien",
                severity="low",  # should be clamped to "high" by floor rule
                title="Low Severity Lien",
                description="This lien has low severity",
                ai_explanation="Test",
                evidence_refs=[{"page_number": 1, "text_snippet": "test"}],
            ),
            # Invalid flag type -- should be dropped
            ExaminerFlag(
                flag_type="invalid_type",
                severity="high",
                title="Invalid Flag",
                description="This should be dropped",
                ai_explanation="Test",
                evidence_refs=[{"page_number": 1, "text_snippet": "test"}],
            ),
        ],
    )

    mock_storage = _make_mock_storage()

    mock_agent_instance = _make_mock_agent(mock_consolidated)

    patches = _stage_examine_patches() + [
        patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent",
            return_value=mock_agent_instance,
        ),
    ]

    for p in patches:
        p.start()
    try:
        await stage_examine(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
    finally:
        for p in patches:
            p.stop()

    flags = (await db_session.execute(
        select(Flag).where(Flag.pack_id == TEST_PACK_ID)
    )).scalars().all()

    # Only the valid flag should remain, with severity clamped to "high"
    assert len(flags) == 1
    assert flags[0].flag_type == "unresolved_lien"
    assert flags[0].severity == "high"  # floor rule: unresolved_lien >= high


@pytest.mark.asyncio
async def test_stage_examine_clears_progress(db_session: AsyncSession, pack_with_pages):
    """After examine completes, examine_progress should be cleared."""
    from app.micro_apps.title_intelligence.pipeline.stages import stage_examine

    mock_storage = _make_mock_storage()
    mock_consolidated = _make_mock_consolidated()

    mock_agent_instance = _make_mock_agent(mock_consolidated)

    patches = _stage_examine_patches() + [
        patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent",
            return_value=mock_agent_instance,
        ),
    ]

    for p in patches:
        p.start()
    try:
        await stage_examine(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
    finally:
        for p in patches:
            p.stop()

    # examine_progress should be None after completion
    pack = (await db_session.execute(
        select(Pack).where(Pack.id == TEST_PACK_ID)
    )).scalar_one()
    assert pack.examine_progress is None
