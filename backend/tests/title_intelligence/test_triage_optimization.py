"""Tests for Phase 11: Triage parallelism & examine stage latency optimization."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.ai.triage_agent import (
    TriageAgent,
    TriageResult,
    TriagePageResult,
)
from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.pipeline.stages import (
    HEURISTIC_BLANK_THRESHOLD,
    _build_content_only_pdf,
    _extract_pdf_pages,
)

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID, TEST_FILE_ID

TEST_ORG = TEST_ORG_ID


def _create_test_pdf(num_pages: int = 5, text_per_page: str | None = None) -> bytes:
    import fitz
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=612, height=792)
        text = text_per_page if text_per_page is not None else f"Test page {i + 1} with some content text here"
        page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _create_mixed_pdf(page_texts: list[str]) -> bytes:
    """Create a PDF where each page has specific text content."""
    import fitz
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=612, height=792)
        if text:
            page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# =============================================================================
# Heuristic pre-triage tests
# =============================================================================

class TestHeuristicPreTriage:
    """Test heuristic blank page detection in render stage."""

    @pytest.mark.asyncio
    async def test_render_native_pdf_extracts_text(
        self, db_session: AsyncSession, seed_data,
    ):
        """Verify _stage_render_native_pdf populates Page.ocr_text for text-heavy pages."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_render_native_pdf

        long_text = "This is a substantial amount of text that exceeds the minimum threshold for embedded text detection in the pipeline."
        pdf_bytes = _create_test_pdf(3, text_per_page=long_text)

        pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Test", status="processing")
        db_session.add(pack)
        pf = PackFile(
            id=TEST_FILE_ID, pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
            filename="test.pdf", file_size=len(pdf_bytes),
            storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        )
        db_session.add(pf)
        await db_session.commit()

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=pdf_bytes)

        await _stage_render_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)

        result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        pages = list(result.scalars().all())
        assert len(pages) == 3
        # All pages have substantial text → ocr_text should be populated
        for p in pages:
            assert p.ocr_text is not None
            assert len(p.ocr_text) > 50

    @pytest.mark.asyncio
    async def test_render_native_pdf_heuristic_blank(
        self, db_session: AsyncSession, seed_data,
    ):
        """Pages with <20 chars get page_type='blank'."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_render_native_pdf

        # Create a PDF with blank pages (no text inserted) and content pages
        page_texts = [
            "",  # blank
            "This is a substantial amount of text for a content page in the PDF document.",
            "",  # blank
        ]
        pdf_bytes = _create_mixed_pdf(page_texts)

        pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Test", status="processing")
        db_session.add(pack)
        pf = PackFile(
            id=TEST_FILE_ID, pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
            filename="test.pdf", file_size=len(pdf_bytes),
            storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        )
        db_session.add(pf)
        await db_session.commit()

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=pdf_bytes)

        await _stage_render_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)

        result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        pages = list(result.scalars().all())
        assert len(pages) == 3
        assert pages[0].page_type == "blank"
        assert pages[1].page_type != "blank"  # has text, not heuristic blank
        assert pages[2].page_type == "blank"

    @pytest.mark.asyncio
    async def test_triage_excludes_heuristic_blanks(
        self, db_session: AsyncSession, seed_data,
    ):
        """Heuristic blanks should not be sent to LLM triage."""
        from app.micro_apps.title_intelligence.pipeline.stages import _run_triage

        # Set up pack with pages — 2 are heuristic blank, 3 are unclassified
        pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Test", status="processing")
        db_session.add(pack)
        pf = PackFile(
            id=TEST_FILE_ID, pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
            filename="test.pdf", file_size=1024,
            storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        )
        db_session.add(pf)

        for i in range(1, 6):
            page_type = "blank" if i in (1, 3) else None
            db_session.add(Page(
                pack_id=TEST_PACK_ID, file_id=TEST_FILE_ID, org_id=TEST_ORG_ID,
                page_number=i, image_uri="", thumb_uri="",
                page_type=page_type,
            ))
        await db_session.commit()

        pages_result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        pages = list(pages_result.scalars().all())

        # Mock triage agent to return results for 3 unclassified pages
        mock_triage_result = TriageResult(
            pages=[
                TriagePageResult(page_number=1, page_type="content"),
                TriagePageResult(page_number=2, page_type="content"),
                TriagePageResult(page_number=3, page_type="boilerplate"),
            ],
            llm_elapsed_seconds=1.0,
        )

        pdf_bytes = _create_test_pdf(5)
        classify_mock = AsyncMock(return_value=mock_triage_result)

        with patch(
            "app.micro_apps.title_intelligence.ai.triage_agent.TriageAgent.classify_pages_parallel",
            classify_mock,
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.stages._build_content_only_pdf",
            return_value=b"filtered_pdf",
        ):
            content_pages, doc_type_hints = await _run_triage(
                pdf_bytes, 5, TEST_ORG_ID, TEST_PACK_ID, pages, db_session,
            )

        # classify_pages_parallel should receive 3 pages (not 5)
        call_args = classify_mock.call_args
        assert call_args[1]["chunk_size"] >= 1  # called with settings
        # Content pages should not include heuristic blanks (1, 3)
        assert 1 not in content_pages
        assert 3 not in content_pages

    @pytest.mark.asyncio
    async def test_heuristic_blank_excluded_from_content(
        self, db_session: AsyncSession, seed_data,
    ):
        """Heuristic blank pages should not appear in content_page_numbers."""
        from app.micro_apps.title_intelligence.pipeline.stages import _run_triage

        pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Test", status="processing")
        db_session.add(pack)
        pf = PackFile(
            id=TEST_FILE_ID, pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
            filename="test.pdf", file_size=1024,
            storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        )
        db_session.add(pf)

        # Pages 2, 4 are heuristic blank
        for i in range(1, 6):
            page_type = "blank" if i in (2, 4) else None
            db_session.add(Page(
                pack_id=TEST_PACK_ID, file_id=TEST_FILE_ID, org_id=TEST_ORG_ID,
                page_number=i, image_uri="", thumb_uri="",
                page_type=page_type,
            ))
        await db_session.commit()

        pages_result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        pages = list(pages_result.scalars().all())

        # All unclassified pages returned as content by triage
        mock_triage_result = TriageResult(
            pages=[
                TriagePageResult(page_number=1, page_type="content"),
                TriagePageResult(page_number=2, page_type="content"),
                TriagePageResult(page_number=3, page_type="content"),
            ],
            llm_elapsed_seconds=1.0,
        )

        pdf_bytes = _create_test_pdf(5)

        with patch(
            "app.micro_apps.title_intelligence.ai.triage_agent.TriageAgent.classify_pages_parallel",
            new_callable=AsyncMock,
            return_value=mock_triage_result,
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.stages._build_content_only_pdf",
            return_value=b"filtered_pdf",
        ):
            content_pages, doc_type_hints = await _run_triage(
                pdf_bytes, 5, TEST_ORG_ID, TEST_PACK_ID, pages, db_session,
            )

        # Blanks (2, 4) should not be in content pages
        assert 2 not in content_pages
        assert 4 not in content_pages
        # Non-blank pages (1, 3, 5) should be content
        assert 1 in content_pages
        assert 3 in content_pages
        assert 5 in content_pages


# =============================================================================
# Parallel triage tests
# =============================================================================

class TestParallelTriage:
    """Test TriageAgent.classify_pages_parallel."""

    @pytest.mark.asyncio
    async def test_parallel_small_pdf_single_call(self):
        """PDFs with <= chunk_size pages should delegate to classify_pages directly."""
        agent = TriageAgent(TEST_ORG)
        mock_result = TriageResult(
            pages=[TriagePageResult(page_number=i, page_type="content") for i in range(1, 6)],
            llm_elapsed_seconds=1.0,
        )
        agent.classify_pages = AsyncMock(return_value=mock_result)

        result = await agent.classify_pages_parallel(b"fake_pdf", total_pages=5, chunk_size=50)

        agent.classify_pages.assert_called_once_with(b"fake_pdf", 5)
        assert len(result.pages) == 5

    @pytest.mark.asyncio
    async def test_parallel_large_pdf_splits(self):
        """PDFs > chunk_size should be split into parallel calls."""
        agent = TriageAgent(TEST_ORG)

        # Create a 100-page PDF
        pdf_bytes = _create_test_pdf(100)

        # Mock classify_pages to return all content
        async def mock_classify(chunk_bytes, total_pages):
            return TriageResult(
                pages=[
                    TriagePageResult(page_number=i, page_type="content")
                    for i in range(1, total_pages + 1)
                ],
                llm_elapsed_seconds=1.0,
                input_tokens=100,
                output_tokens=50,
            )

        agent.classify_pages = AsyncMock(side_effect=mock_classify)
        agent._ensure_context_cache = AsyncMock(return_value="cache")

        result = await agent.classify_pages_parallel(
            pdf_bytes, total_pages=100, chunk_size=50, concurrency=4
        )

        # Should have been called twice (2 chunks of 50)
        assert agent.classify_pages.call_count == 2
        assert len(result.pages) == 100
        # All pages should be content
        assert all(p.page_type == "content" for p in result.pages)

    @pytest.mark.asyncio
    async def test_parallel_merge_page_remapping(self):
        """Chunk page numbers should be correctly remapped to global."""
        agent = TriageAgent(TEST_ORG)

        pdf_bytes = _create_test_pdf(6)

        call_count = 0

        async def mock_classify(chunk_bytes, total_pages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First chunk: pages 1-3
                return TriageResult(
                    pages=[
                        TriagePageResult(page_number=1, page_type="cover"),
                        TriagePageResult(page_number=2, page_type="content"),
                        TriagePageResult(page_number=3, page_type="blank"),
                    ],
                    llm_elapsed_seconds=2.0,
                    input_tokens=100,
                    output_tokens=50,
                )
            else:
                # Second chunk: pages 1-3 (chunk-local, maps to global 4-6)
                return TriageResult(
                    pages=[
                        TriagePageResult(page_number=1, page_type="content"),
                        TriagePageResult(page_number=2, page_type="signature"),
                        TriagePageResult(page_number=3, page_type="content"),
                    ],
                    llm_elapsed_seconds=1.5,
                    input_tokens=80,
                    output_tokens=40,
                )

        agent.classify_pages = AsyncMock(side_effect=mock_classify)
        agent._ensure_context_cache = AsyncMock(return_value="cache")

        result = await agent.classify_pages_parallel(
            pdf_bytes, total_pages=6, chunk_size=3, concurrency=4
        )

        assert len(result.pages) == 6
        # Verify remapping: chunk 1 pages 1-3 → global 1-3
        assert result.pages[0].page_type == "cover"     # global page 1
        assert result.pages[1].page_type == "content"    # global page 2
        assert result.pages[2].page_type == "blank"      # global page 3
        # Verify remapping: chunk 2 pages 1-3 → global 4-6
        assert result.pages[3].page_type == "content"    # global page 4
        assert result.pages[4].page_type == "signature"  # global page 5
        assert result.pages[5].page_type == "content"    # global page 6

    @pytest.mark.asyncio
    async def test_parallel_chunk_failure_defaults_content(self):
        """Failed chunk should default those pages to 'content'."""
        agent = TriageAgent(TEST_ORG)

        pdf_bytes = _create_test_pdf(6)

        call_count = 0

        async def mock_classify(chunk_bytes, total_pages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return TriageResult(
                    pages=[
                        TriagePageResult(page_number=1, page_type="cover"),
                        TriagePageResult(page_number=2, page_type="content"),
                        TriagePageResult(page_number=3, page_type="blank"),
                    ],
                    llm_elapsed_seconds=2.0,
                )
            else:
                raise RuntimeError("Simulated LLM failure")

        agent.classify_pages = AsyncMock(side_effect=mock_classify)
        agent._ensure_context_cache = AsyncMock(return_value="cache")

        result = await agent.classify_pages_parallel(
            pdf_bytes, total_pages=6, chunk_size=3, concurrency=4
        )

        assert len(result.pages) == 6
        # First chunk results preserved
        assert result.pages[0].page_type == "cover"
        assert result.pages[1].page_type == "content"
        assert result.pages[2].page_type == "blank"
        # Second chunk failed → defaults to "content"
        assert result.pages[3].page_type == "content"
        assert result.pages[4].page_type == "content"
        assert result.pages[5].page_type == "content"

    @pytest.mark.asyncio
    async def test_parallel_token_aggregation(self):
        """Tokens should be summed, elapsed should be max across chunks."""
        agent = TriageAgent(TEST_ORG)

        pdf_bytes = _create_test_pdf(6)

        call_count = 0

        async def mock_classify(chunk_bytes, total_pages):
            nonlocal call_count
            call_count += 1
            return TriageResult(
                pages=[
                    TriagePageResult(page_number=i, page_type="content")
                    for i in range(1, total_pages + 1)
                ],
                llm_elapsed_seconds=2.0 if call_count == 1 else 3.0,
                input_tokens=100 if call_count == 1 else 150,
                output_tokens=50 if call_count == 1 else 60,
            )

        agent.classify_pages = AsyncMock(side_effect=mock_classify)
        agent._ensure_context_cache = AsyncMock(return_value="cache")

        result = await agent.classify_pages_parallel(
            pdf_bytes, total_pages=6, chunk_size=3, concurrency=4
        )

        # Tokens summed
        assert result.input_tokens == 250   # 100 + 150
        assert result.output_tokens == 110  # 50 + 60
        # Elapsed = max (parallel wall time)
        assert result.llm_elapsed_seconds == 3.0


# =============================================================================
# Merge chunk results unit tests
# =============================================================================

class TestMergeChunkResults:
    """Test TriageAgent._merge_chunk_results directly."""

    def test_merge_basic(self):
        agent = TriageAgent(TEST_ORG)
        chunk_results = [
            (1, 3, TriageResult(
                pages=[
                    TriagePageResult(page_number=1, page_type="cover"),
                    TriagePageResult(page_number=2, page_type="content"),
                    TriagePageResult(page_number=3, page_type="content"),
                ],
                llm_elapsed_seconds=1.0,
                input_tokens=100,
                output_tokens=50,
            )),
            (4, 2, TriageResult(
                pages=[
                    TriagePageResult(page_number=1, page_type="content"),
                    TriagePageResult(page_number=2, page_type="blank"),
                ],
                llm_elapsed_seconds=0.8,
                input_tokens=80,
                output_tokens=30,
            )),
        ]

        result = agent._merge_chunk_results(chunk_results, total_pages=5)
        assert len(result.pages) == 5
        assert result.pages[0].page_type == "cover"   # page 1
        assert result.pages[3].page_type == "content"  # page 4
        assert result.pages[4].page_type == "blank"    # page 5
        assert result.input_tokens == 180
        assert result.output_tokens == 80
        assert result.llm_elapsed_seconds == 1.0  # max

    def test_merge_with_none_chunk(self):
        agent = TriageAgent(TEST_ORG)
        chunk_results = [
            (1, 3, TriageResult(
                pages=[
                    TriagePageResult(page_number=1, page_type="cover"),
                    TriagePageResult(page_number=2, page_type="content"),
                    TriagePageResult(page_number=3, page_type="content"),
                ],
                llm_elapsed_seconds=1.0,
            )),
            (4, 2, None),  # failed chunk
        ]

        result = agent._merge_chunk_results(chunk_results, total_pages=5)
        assert result.pages[3].page_type == "content"  # defaulted
        assert result.pages[4].page_type == "content"  # defaulted


# =============================================================================
# Cache pre-warm tests
# =============================================================================

class TestCachePreWarm:
    """Test examiner context cache pre-warming during triage."""

    @pytest.mark.asyncio
    async def test_cache_lock_prevents_double_creation(self):
        """_ensure_context_cache with lock should only create cache once."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent

        agent = TitleExaminerAgent(TEST_ORG)
        agent.create_context_cache = AsyncMock(return_value="test_cache_name")

        # Call concurrently
        results = await asyncio.gather(
            agent._ensure_context_cache(agent.JSON_SCHEMA),
            agent._ensure_context_cache(agent.JSON_SCHEMA),
            agent._ensure_context_cache(agent.JSON_SCHEMA),
        )

        # Cache should only be created once
        assert agent.create_context_cache.call_count == 1
        assert all(r == "test_cache_name" for r in results)

    @pytest.mark.asyncio
    async def test_prewarm_failure_nonfatal(self):
        """Exception in pre-warm should not crash the pipeline."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent

        agent = TitleExaminerAgent(TEST_ORG)
        agent.create_context_cache = AsyncMock(side_effect=RuntimeError("Cache creation failed"))

        # Should return None, not raise
        result = await agent._ensure_context_cache(agent.JSON_SCHEMA)
        assert result is None

    @pytest.mark.asyncio
    async def test_prewarm_idempotent_after_success(self):
        """After successful cache creation, subsequent calls return immediately."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent

        agent = TitleExaminerAgent(TEST_ORG)
        agent.create_context_cache = AsyncMock(return_value="cached_name")

        # First call creates
        r1 = await agent._ensure_context_cache(agent.JSON_SCHEMA)
        assert r1 == "cached_name"
        assert agent.create_context_cache.call_count == 1

        # Second call returns immediately without creating
        r2 = await agent._ensure_context_cache(agent.JSON_SCHEMA)
        assert r2 == "cached_name"
        assert agent.create_context_cache.call_count == 1  # still 1


# =============================================================================
# Config settings tests
# =============================================================================

class TestTriageConfig:
    """Test new triage config settings."""

    def test_default_triage_chunk_size(self):
        from app.config import Settings
        s = Settings(DEBUG=True, JWT_SECRET="test")
        assert s.TRIAGE_CHUNK_SIZE == 50

    def test_default_triage_concurrency(self):
        from app.config import Settings
        s = Settings(DEBUG=True, JWT_SECRET="test")
        assert s.TRIAGE_CONCURRENCY == 4

    def test_default_triage_skip_below(self):
        from app.config import Settings
        s = Settings(DEBUG=True, JWT_SECRET="test")
        assert s.TRIAGE_SKIP_BELOW == 80

    def test_heuristic_blank_threshold_constant(self):
        assert HEURISTIC_BLANK_THRESHOLD == 20


class TestTriageSkipForSmallDocs:
    """Test that triage is skipped for documents under TRIAGE_SKIP_BELOW pages."""

    @pytest.mark.asyncio
    async def test_small_doc_skips_triage(
        self, db_session: AsyncSession, seed_data,
    ):
        """Documents under 80 pages should skip LLM triage."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_examine_native_pdf
        from app.micro_apps.title_intelligence.schemas.examiner import (
            ExaminerConsolidatedResult,
            PageTranscription,
        )

        pdf_bytes = _create_test_pdf(10, text_per_page="Content page text for testing.")

        pack = Pack(id=TEST_PACK_ID, org_id=TEST_ORG_ID, name="Test", status="processing")
        db_session.add(pack)
        pf = PackFile(
            id=TEST_FILE_ID, pack_id=TEST_PACK_ID, org_id=TEST_ORG_ID,
            filename="test.pdf", file_size=len(pdf_bytes),
            storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        )
        db_session.add(pf)
        # Create page records
        for i in range(1, 11):
            db_session.add(Page(
                pack_id=TEST_PACK_ID, file_id=TEST_FILE_ID, org_id=TEST_ORG_ID,
                page_number=i, image_uri="", thumb_uri="",
            ))
        await db_session.commit()

        mock_consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[
                PageTranscription(page_number=i, text=f"Page {i}")
                for i in range(1, 11)
            ],
        )

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=pdf_bytes)
        mock_storage.exists = AsyncMock(return_value=False)
        mock_storage.save = AsyncMock()
        mock_storage.make_ai_cache_path = MagicMock(return_value="cache/test")

        mock_agent = MagicMock()
        mock_agent.examine_document_native_pdf = AsyncMock(return_value=mock_consolidated)
        mock_agent._ensure_context_cache = AsyncMock(return_value=None)
        mock_agent.JSON_SCHEMA = {}

        triage_mock = AsyncMock()

        patches = [
            patch("app.config.get_settings", return_value=MagicMock(
                PIPELINE_MODE="native_pdf",
                NATIVE_PDF_BATCH_SIZE=20,
                NATIVE_PDF_CONCURRENCY=12,
                TRIAGE_ENABLED=True,
                TRIAGE_SKIP_BELOW=80,
                GROUPING_ENABLED=False,
            )),
            patch(
                "app.micro_apps.title_intelligence.pipeline.version_tracker.collect_version_info",
                return_value={"ai_platform": "gemini", "ai_model": "gemini/gemini-2.5-flash",
                              "ingestion_prompt_hash": "h", "risk_prompt_hash": "h",
                              "extraction_tool_hash": "h", "risk_tool_hash": "h",
                              "ocr_engine": "gemini_native_pdf", "chunker_version": "v1",
                              "rules_version": "v2", "pipeline_backend": "bg",
                              "version_metadata": {"pipeline_mode": "native_pdf"}},
            ),
            patch(
                "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_examiner_cache_key",
                return_value="test_key",
            ),
            patch(
                "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent",
                return_value=mock_agent,
            ),
            patch(
                "app.micro_apps.title_intelligence.pipeline.stages._run_triage",
                triage_mock,
            ),
        ]

        for p in patches:
            p.start()
        try:
            await _stage_examine_native_pdf(TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage)
        finally:
            for p in patches:
                p.stop()

        # Triage should NOT have been called (10 < 80)
        triage_mock.assert_not_called()
        # Examiner should still have been called
        mock_agent.examine_document_native_pdf.assert_called_once()
