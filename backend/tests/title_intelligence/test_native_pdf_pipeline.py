"""Tests for native PDF pipeline mode.

Tests PDF splitting, native_pdf render/examine stages, cache isolation,
timing instrumentation, and return_usage in base_service.
"""

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
from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
from app.micro_apps.title_intelligence.schemas.examiner import (
    ExaminerBatchResult,
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
    "ocr_engine": "gemini_native_pdf",
    "chunker_version": "hierarchical_v1",
    "rules_version": "weighted_5cat_v2",
    "pipeline_backend": "background_tasks",
    "version_metadata": {
        "ai_platform": "gemini",
        "ai_model": "gemini/gemini-2.5-flash",
        "pipeline_mode": "native_pdf",
    },
}


def _create_test_pdf(num_pages: int = 3) -> bytes:
    """Create a minimal test PDF with the given number of pages using PyMuPDF."""
    import fitz

    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"Test page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class TestPdfSplitting:
    """Test PDF splitting via PyMuPDF."""

    def test_split_pdf_into_chunks(self):
        import fitz

        pdf_bytes = _create_test_pdf(10)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        assert len(doc) == 10

        # Split into chunks of 3
        chunks = []
        for start in range(0, len(doc), 3):
            end = min(start + 3, len(doc))
            chunk_doc = fitz.open()
            chunk_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
            chunks.append((chunk_doc.tobytes(), end - start))
            chunk_doc.close()

        doc.close()

        # Should have 4 chunks: 3+3+3+1
        assert len(chunks) == 4
        assert chunks[0][1] == 3
        assert chunks[1][1] == 3
        assert chunks[2][1] == 3
        assert chunks[3][1] == 1

        # Verify each chunk is a valid PDF with correct page count
        for chunk_bytes, expected_pages in chunks:
            chunk_doc = fitz.open(stream=chunk_bytes, filetype="pdf")
            assert len(chunk_doc) == expected_pages
            chunk_doc.close()

    def test_single_page_pdf_no_split(self):
        import fitz

        pdf_bytes = _create_test_pdf(1)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        assert len(doc) == 1
        doc.close()

    def test_concatenate_pdfs(self):
        import fitz

        pdf1 = _create_test_pdf(3)
        pdf2 = _create_test_pdf(2)

        merged = fitz.open()
        for data in [pdf1, pdf2]:
            src = fitz.open(stream=data, filetype="pdf")
            merged.insert_pdf(src)
            src.close()

        assert len(merged) == 5
        merged_bytes = merged.tobytes()
        merged.close()

        # Verify merged PDF is valid
        verify = fitz.open(stream=merged_bytes, filetype="pdf")
        assert len(verify) == 5
        verify.close()


@pytest_asyncio.fixture
async def pack_with_native_pages(db_session: AsyncSession, seed_data):
    """Create a pack with native_pdf mode page records (no images)."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Native PDF Pack",
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
        page_count=3,
    )
    db_session.add(pack_file)

    # Create 3 page records with no images (native_pdf mode)
    for i in range(1, 4):
        db_session.add(Page(
            pack_id=TEST_PACK_ID,
            file_id=TEST_FILE_ID,
            org_id=TEST_ORG_ID,
            page_number=i,
            image_uri="",
            thumb_uri="",
            ocr_text=None,
        ))

    await db_session.commit()
    return pack


class TestNativePdfRenderStage:
    """Test _stage_render_native_pdf creates Page records without images."""

    @pytest.mark.asyncio
    async def test_render_creates_page_records(self, db_session: AsyncSession, seed_data):
        """Native PDF render should create page records with empty image URIs."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_render_native_pdf

        # Create pack and file
        pack = Pack(
            id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            name="Test Pack",
            status="processing",
        )
        db_session.add(pack)

        pack_file = PackFile(
            id=TEST_FILE_ID,
            pack_id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            filename="test.pdf",
            file_size=1024,
            storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        )
        db_session.add(pack_file)
        await db_session.commit()

        pdf_bytes = _create_test_pdf(5)
        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=pdf_bytes)

        await _stage_render_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)

        pages = (await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )).scalars().all()

        assert len(pages) == 5
        for i, page in enumerate(pages, 1):
            assert page.page_number == i
            assert page.image_uri == ""
            assert page.thumb_uri == ""
            assert page.ocr_text is None

        # Verify page_count was set on PackFile
        pf = (await db_session.execute(
            select(PackFile).where(PackFile.id == TEST_FILE_ID)
        )).scalar_one()
        assert pf.page_count == 5

    @pytest.mark.asyncio
    async def test_render_idempotent(self, db_session: AsyncSession, seed_data):
        """Running native_pdf render twice should produce the same result."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_render_native_pdf

        pack = Pack(
            id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            name="Test Pack",
            status="processing",
        )
        db_session.add(pack)

        pack_file = PackFile(
            id=TEST_FILE_ID,
            pack_id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            filename="test.pdf",
            file_size=1024,
            storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        )
        db_session.add(pack_file)
        await db_session.commit()

        pdf_bytes = _create_test_pdf(3)
        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=pdf_bytes)

        await _stage_render_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
        await _stage_render_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)

        pages = (await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID)
        )).scalars().all()
        assert len(pages) == 3


class TestNativePdfExamineStage:
    """Test _stage_examine_native_pdf with mocked Gemini calls."""

    @pytest.mark.asyncio
    async def test_examine_creates_records(
        self, db_session: AsyncSession, pack_with_native_pages
    ):
        """Native PDF examine should create sections, extractions, flags, text chunks."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_examine_native_pdf

        mock_consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[
                PageTranscription(page_number=1, text="COMMITMENT FOR TITLE INSURANCE"),
                PageTranscription(page_number=2, text="Schedule A\nEffective Date: 2024-01-15"),
                PageTranscription(page_number=3, text="Schedule B-I\n1. Pay off mortgage"),
            ],
            sections=[
                ExaminerSection(section_type="schedule_a", start_page=2, end_page=2, confidence=0.95),
            ],
            extractions=[
                ExaminerExtraction(
                    extraction_type="policy_info",
                    label="Effective Date",
                    value={"date": "2024-01-15"},
                    evidence_refs=[{"page_number": 2, "text_snippet": "Effective Date: 2024-01-15"}],
                    confidence=0.9,
                ),
            ],
            flags=[
                ExaminerFlag(
                    flag_type="unresolved_lien",
                    severity="high",
                    title="Outstanding Mortgage",
                    description="Existing mortgage requires payoff",
                    ai_explanation="Schedule B-I requires mortgage payoff.",
                    evidence_refs=[{"page_number": 3, "text_snippet": "Pay off mortgage"}],
                ),
            ],
        )

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=_create_test_pdf(3))
        mock_storage.exists = AsyncMock(return_value=False)
        mock_storage.save = AsyncMock()
        mock_storage.make_ai_cache_path = MagicMock(return_value="cache/examiner_native/test")

        mock_agent_instance = MagicMock()
        mock_agent_instance.examine_document_native_pdf = AsyncMock(return_value=mock_consolidated)
        mock_agent_instance._ensure_context_cache = AsyncMock(return_value=None)
        mock_agent_instance.JSON_SCHEMA = {}

        patches = [
            patch(
                "app.config.get_settings",
                return_value=MagicMock(
                    PIPELINE_MODE="native_pdf",
                    NATIVE_PDF_BATCH_SIZE=20,
                    NATIVE_PDF_CONCURRENCY=12,
                    TRIAGE_ENABLED=False,
                    TRIAGE_SKIP_BELOW=80,
                    GROUPING_ENABLED=True,
                ),
            ),
            patch(
                "app.micro_apps.title_intelligence.pipeline.version_tracker.collect_version_info",
                return_value=MOCK_VERSION_INFO,
            ),
            patch(
                "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_examiner_cache_key",
                return_value="test_native_cache_key",
            ),
            patch(
                "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent",
                return_value=mock_agent_instance,
            ),
        ]

        for p in patches:
            p.start()
        try:
            await _stage_examine_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
        finally:
            for p in patches:
                p.stop()

        # Verify agent was called with correct args
        mock_agent_instance.examine_document_native_pdf.assert_called_once()
        call_kwargs = mock_agent_instance.examine_document_native_pdf.call_args.kwargs
        assert call_kwargs["batch_size"] == 20
        assert call_kwargs["concurrency"] == 12
        assert call_kwargs["on_batch_complete"] is not None

        # Check pages got OCR text from transcriptions
        pages = (await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )).scalars().all()
        assert "COMMITMENT" in pages[0].ocr_text
        assert "Schedule A" in pages[1].ocr_text

        # Check sections
        sections = (await db_session.execute(
            select(Section).where(Section.pack_id == TEST_PACK_ID)
        )).scalars().all()
        assert len(sections) == 1
        assert sections[0].section_type == "schedule_a"

        # Check extractions
        extractions = (await db_session.execute(
            select(Extraction).where(Extraction.pack_id == TEST_PACK_ID)
        )).scalars().all()
        assert len(extractions) == 1

        # Check flags
        flags = (await db_session.execute(
            select(Flag).where(Flag.pack_id == TEST_PACK_ID)
        )).scalars().all()
        assert len(flags) == 1
        assert flags[0].flag_type == "unresolved_lien"

        # Check text chunks
        chunks = (await db_session.execute(
            select(TextChunk).where(TextChunk.pack_id == TEST_PACK_ID)
        )).scalars().all()
        assert len(chunks) > 0

        # Check cache was saved with examiner_native prefix
        mock_storage.make_ai_cache_path.assert_called_with(
            TEST_ORG_ID, TEST_PACK_ID, "examiner_native", "test_native_cache_key"
        )

    @pytest.mark.asyncio
    async def test_examine_cache_hit(
        self, db_session: AsyncSession, pack_with_native_pages
    ):
        """On cache hit, native PDF examine should replay without calling the agent."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_examine_native_pdf

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
                    "label": "Buyer",
                    "value": {"name": "John Doe"},
                    "evidence_refs": [{"page_number": 1, "text_snippet": "Buyer: John Doe"}],
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

        mock_storage = AsyncMock()
        mock_storage.exists = AsyncMock(return_value=True)
        mock_storage.read = AsyncMock(return_value=json.dumps(cached_data).encode())
        mock_storage.make_ai_cache_path = MagicMock(return_value="cache/examiner_native/test")

        patches = [
            patch(
                "app.config.get_settings",
                return_value=MagicMock(
                    PIPELINE_MODE="native_pdf",
                    NATIVE_PDF_BATCH_SIZE=20,
                    NATIVE_PDF_CONCURRENCY=12,
                    TRIAGE_ENABLED=False,
                    TRIAGE_SKIP_BELOW=80,
                ),
            ),
            patch(
                "app.micro_apps.title_intelligence.pipeline.version_tracker.collect_version_info",
                return_value=MOCK_VERSION_INFO,
            ),
            patch(
                "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_examiner_cache_key",
                return_value="test_native_cache_key",
            ),
        ]

        for p in patches:
            p.start()
        try:
            await _stage_examine_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
        finally:
            for p in patches:
                p.stop()

        sections = (await db_session.execute(
            select(Section).where(Section.pack_id == TEST_PACK_ID)
        )).scalars().all()
        assert len(sections) == 1

        pages = (await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )).scalars().all()
        assert pages[0].ocr_text == "Cached text page 1"


class TestCacheKeyIsolation:
    """Test that native_pdf and legacy modes use different cache paths."""

    def test_native_pdf_uses_examiner_native_prefix(self):
        """Native PDF mode should use 'examiner_native' as the cache stage prefix."""
        # The isolation is via the stage parameter in make_ai_cache_path
        # Native uses "examiner_native", legacy uses "examiner"
        from app.services.storage import LocalStorage

        storage = LocalStorage("/tmp/test_storage")
        native_path = storage.make_ai_cache_path(
            TEST_ORG_ID, TEST_PACK_ID, "examiner_native", "abc123"
        )
        legacy_path = storage.make_ai_cache_path(
            TEST_ORG_ID, TEST_PACK_ID, "examiner", "abc123"
        )
        assert native_path != legacy_path
        assert "examiner_native" in native_path
        assert "examiner_native" not in legacy_path


class TestExaminerBatchResultTiming:
    """Test that ExaminerBatchResult timing fields work."""

    def test_timing_fields_default_none(self):
        result = ExaminerBatchResult()
        assert result.llm_elapsed_seconds is None
        assert result.input_tokens is None
        assert result.output_tokens is None

    def test_timing_fields_set(self):
        result = ExaminerBatchResult(
            llm_elapsed_seconds=12.5,
            input_tokens=1500,
            output_tokens=3000,
        )
        assert result.llm_elapsed_seconds == 12.5
        assert result.input_tokens == 1500
        assert result.output_tokens == 3000


class TestVersionTrackerNativePdf:
    """Test version tracker reflects pipeline mode."""

    def test_native_pdf_mode_ocr_engine(self):
        from app.config import Settings
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

        settings = Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            PIPELINE_BACKEND="background_tasks",
            PIPELINE_MODE="native_pdf",
            DEBUG=True,
        )
        info = collect_version_info(settings)
        assert info["ocr_engine"] == "gemini_native_pdf"
        assert info["version_metadata"]["pipeline_mode"] == "native_pdf"

    def test_legacy_mode_ocr_engine(self):
        from app.config import Settings
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

        settings = Settings(
            DATABASE_URL="sqlite+aiosqlite:///./test.db",
            JWT_SECRET="test-secret",
            PIPELINE_BACKEND="background_tasks",
            PIPELINE_MODE="legacy",
            DEBUG=True,
        )
        info = collect_version_info(settings)
        assert info["ocr_engine"] == "gemini_vision"
        assert info["version_metadata"]["pipeline_mode"] == "legacy"


class TestModeDispatch:
    """Test that stage_render and stage_examine dispatch to the correct mode."""

    @pytest.mark.asyncio
    async def test_stage_render_dispatches_to_native_pdf(self, db_session: AsyncSession, seed_data):
        """When PIPELINE_MODE=native_pdf, stage_render should call _stage_render_native_pdf."""
        from app.micro_apps.title_intelligence.pipeline.stages import stage_render

        with patch(
            "app.micro_apps.title_intelligence.pipeline.stages._stage_render_native_pdf",
            new_callable=AsyncMock,
        ) as mock_native:
            with patch(
                "app.config.get_settings",
                return_value=MagicMock(PIPELINE_MODE="native_pdf"),
            ):
                await stage_render(TEST_PACK_ID, TEST_ORG_ID, db_session, AsyncMock())
                mock_native.assert_called_once()

    @pytest.mark.asyncio
    async def test_stage_examine_dispatches_to_native_pdf(self, db_session: AsyncSession, seed_data):
        """When PIPELINE_MODE=native_pdf, stage_examine should call _stage_examine_native_pdf."""
        from app.micro_apps.title_intelligence.pipeline.stages import stage_examine

        with patch(
            "app.micro_apps.title_intelligence.pipeline.stages._stage_examine_native_pdf",
            new_callable=AsyncMock,
        ) as mock_native:
            with patch(
                "app.config.get_settings",
                return_value=MagicMock(PIPELINE_MODE="native_pdf"),
            ):
                await stage_examine(TEST_PACK_ID, TEST_ORG_ID, db_session, AsyncMock())
                mock_native.assert_called_once()


class TestPdfBatchExamination:
    """Test TitleExaminerAgent PDF batch methods."""

    @pytest.fixture
    def agent(self):
        with patch("app.ai.base_service._ensure_configured"):
            return __import__(
                "app.micro_apps.title_intelligence.ai.title_examiner_agent",
                fromlist=["TitleExaminerAgent"],
            ).TitleExaminerAgent(uuid.UUID("00000000-0000-0000-0000-000000000010"))

    @pytest.mark.asyncio
    async def test_examine_pdf_batch_builds_pdf_content(self, agent):
        """examine_pdf_batch should include a PDF content block."""
        pdf_bytes = _create_test_pdf(3)

        mock_settings = MagicMock(
            EXAMINER_MAX_OUTPUT_TOKENS=65536,
            EXAMINER_CALL_TIMEOUT=300,
        )

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=mock_settings):
            with patch.object(agent, "_ensure_context_cache", new_callable=AsyncMock, return_value=None):
                with patch.object(agent, "call_json_structured", new_callable=AsyncMock) as mock_call:
                    mock_call.return_value = (
                        {
                            "page_transcriptions": [{"page_number": 1, "text": "Test"}],
                            "sections": [],
                            "extractions": [],
                            "flags": [],
                        },
                        {"input_tokens": 100, "output_tokens": 50},
                    )

                    result = await agent.examine_pdf_batch(
                        pdf_bytes=pdf_bytes,
                        page_range=(1, 3),
                        total_pages=3,
                        batch_index=0,
                        total_batches=1,
                    )

                    # Verify the LLM was called with PDF content
                    call_args = mock_call.call_args
                    messages = call_args.kwargs.get("messages")
                    content = messages[0]["content"]

                    pdf_blocks = [b for b in content if b.get("type") == "pdf"]
                    assert len(pdf_blocks) == 1
                    assert pdf_blocks[0]["pdf"]["data"] == pdf_bytes

                    # Verify return_usage was requested
                    assert call_args.kwargs.get("return_usage") is True

                    # Verify timing was recorded
                    assert result.llm_elapsed_seconds is not None
                    assert result.llm_elapsed_seconds >= 0
                    assert result.input_tokens == 100
                    assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_examine_document_native_pdf(self, agent):
        """examine_document_native_pdf should split PDF and consolidate results."""
        pdf_bytes = _create_test_pdf(5)

        mock_result = ExaminerBatchResult(
            page_transcriptions=[PageTranscription(page_number=1, text="Test page")],
            sections=[],
            extractions=[],
            flags=[],
            llm_elapsed_seconds=1.5,
        )

        callback = AsyncMock()

        mock_settings = MagicMock(
            NATIVE_PDF_STAGGER_MS=0,
            SPECIALIZED_EXTRACTION_ENABLED=False,
        )

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings", return_value=mock_settings):
            with patch.object(
                agent,
                "_call_pdf_with_rate_limit_retry",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_retry:
                result = await agent.examine_document_native_pdf(
                    pdf_bytes=pdf_bytes,
                    total_pages=5,
                    batch_size=3,
                    concurrency=2,
                    on_batch_complete=callback,
                )

                # 5 pages / 3 per batch = 2 batches
                assert mock_retry.call_count == 2
                assert isinstance(result, ExaminerConsolidatedResult)

                # Callback should have been called for each batch
                assert callback.call_count == 2
