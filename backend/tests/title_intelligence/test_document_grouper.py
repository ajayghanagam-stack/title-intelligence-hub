"""Tests for the document grouper service and pipeline integration."""

import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.services.document_grouper import (
    DocumentGroup,
    GroupingResult,
    group_pages,
    groups_to_page_ranges,
    remap_groups_to_filtered_pdf,
    BOUNDARY_TYPES,
    TRAILING_TYPES,
)
from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.schemas.examiner import (
    ExaminerConsolidatedResult,
    PageTranscription,
)
from app.micro_apps.title_intelligence.ai.triage_agent import (
    TriageResult,
    TriagePageResult,
)

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID, TEST_FILE_ID


# --- Document Grouper Unit Tests ---

class TestGroupPages:
    """Test group_pages() rules-based grouping logic."""

    def test_all_content_single_group(self):
        """All content pages form one group."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "content"},
            {"page_number": 3, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 1
        assert result.total_content_pages == 3
        assert result.groups[0].pages == [1, 2, 3]
        assert result.groups[0].start_page == 1
        assert result.groups[0].end_page == 3

    def test_blank_page_splits_groups(self):
        """Blank pages act as document boundaries."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "content"},
            {"page_number": 3, "page_type": "blank"},
            {"page_number": 4, "page_type": "content"},
            {"page_number": 5, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 2
        assert result.groups[0].pages == [1, 2]
        assert result.groups[1].pages == [4, 5]

    def test_cover_page_splits_groups(self):
        """Cover pages act as document boundaries."""
        pages = [
            {"page_number": 1, "page_type": "cover"},
            {"page_number": 2, "page_type": "content"},
            {"page_number": 3, "page_type": "content"},
            {"page_number": 4, "page_type": "cover"},
            {"page_number": 5, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 2
        assert result.groups[0].pages == [2, 3]
        assert result.groups[1].pages == [5]

    def test_transmittal_splits_groups(self):
        """Transmittal pages act as boundaries."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "transmittal"},
            {"page_number": 3, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 2
        assert result.groups[0].pages == [1]
        assert result.groups[1].pages == [3]

    def test_signature_trails_document(self):
        """Signature pages stay with preceding group (don't start new one)."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "content"},
            {"page_number": 3, "page_type": "signature"},
            {"page_number": 4, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        # Signature doesn't split — pages 1,2 are in group 0, page 4 continues in same group
        # (signature is trailing, doesn't break the group)
        assert result.total_groups == 1
        assert result.groups[0].pages == [1, 2, 4]

    def test_boilerplate_trails_document(self):
        """Boilerplate pages stay with preceding group."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "boilerplate"},
            {"page_number": 3, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 1
        assert result.groups[0].pages == [1, 3]

    def test_max_chunk_size_splits_large_groups(self):
        """Groups exceeding max_chunk_size are split."""
        pages = [{"page_number": i, "page_type": "content"} for i in range(1, 11)]
        result = group_pages(pages, max_chunk_size=3)
        assert result.total_groups == 4  # 3+3+3+1
        assert result.groups[0].pages == [1, 2, 3]
        assert result.groups[1].pages == [4, 5, 6]
        assert result.groups[2].pages == [7, 8, 9]
        assert result.groups[3].pages == [10]
        assert result.total_content_pages == 10

    def test_complex_document_layout(self):
        """Realistic title commitment layout."""
        pages = [
            {"page_number": 1, "page_type": "cover"},
            {"page_number": 2, "page_type": "transmittal"},
            {"page_number": 3, "page_type": "content"},   # Schedule A
            {"page_number": 4, "page_type": "content"},
            {"page_number": 5, "page_type": "content"},   # Schedule B-I
            {"page_number": 6, "page_type": "content"},
            {"page_number": 7, "page_type": "blank"},
            {"page_number": 8, "page_type": "content"},   # Schedule B-II
            {"page_number": 9, "page_type": "content"},
            {"page_number": 10, "page_type": "signature"},
            {"page_number": 11, "page_type": "blank"},
            {"page_number": 12, "page_type": "content"},  # Legal description
            {"page_number": 13, "page_type": "content"},
            {"page_number": 14, "page_type": "boilerplate"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 3
        # Group 0: pages 3-6 (Schedule A + B-I)
        assert result.groups[0].pages == [3, 4, 5, 6]
        # Group 1: pages 8-9 (Schedule B-II)
        assert result.groups[1].pages == [8, 9]
        # Group 2: pages 12-13 (Legal description)
        assert result.groups[2].pages == [12, 13]
        assert result.total_content_pages == 8

    def test_empty_input(self):
        result = group_pages([], max_chunk_size=25)
        assert result.total_groups == 0
        assert result.total_content_pages == 0

    def test_all_blank_pages(self):
        pages = [
            {"page_number": 1, "page_type": "blank"},
            {"page_number": 2, "page_type": "blank"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 0
        assert result.total_content_pages == 0

    def test_single_content_page(self):
        pages = [{"page_number": 1, "page_type": "content"}]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 1
        assert result.groups[0].pages == [1]

    def test_unknown_type_treated_as_content(self):
        """Unknown page types should be treated as content (conservative)."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "some_unknown_type"},
            {"page_number": 3, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 1
        assert result.groups[0].pages == [1, 2, 3]

    def test_consecutive_boundaries(self):
        """Multiple boundary pages in a row shouldn't produce empty groups."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "blank"},
            {"page_number": 3, "page_type": "blank"},
            {"page_number": 4, "page_type": "cover"},
            {"page_number": 5, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert result.total_groups == 2
        assert result.groups[0].pages == [1]
        assert result.groups[1].pages == [5]

    def test_group_ids_sequential(self):
        """Group IDs should be 0-based sequential."""
        pages = [
            {"page_number": 1, "page_type": "content"},
            {"page_number": 2, "page_type": "blank"},
            {"page_number": 3, "page_type": "content"},
            {"page_number": 4, "page_type": "blank"},
            {"page_number": 5, "page_type": "content"},
        ]
        result = group_pages(pages, max_chunk_size=25)
        assert [g.group_id for g in result.groups] == [0, 1, 2]


class TestGroupsToPageRanges:
    """Test groups_to_page_ranges conversion."""

    def test_basic_conversion(self):
        groups = [
            DocumentGroup(group_id=0, start_page=1, end_page=5, page_count=5, pages=[1, 2, 3, 4, 5]),
            DocumentGroup(group_id=1, start_page=8, end_page=10, page_count=3, pages=[8, 9, 10]),
        ]
        ranges = groups_to_page_ranges(groups)
        assert ranges == [(1, 5), (8, 10)]

    def test_empty_groups(self):
        assert groups_to_page_ranges([]) == []


class TestRemapGroupsToFilteredPdf:
    """Test remap_groups_to_filtered_pdf for content-only PDF."""

    def test_remap_simple(self):
        """Remap groups from original pages [2,4,5] → filtered positions [1,2,3]."""
        groups = [
            DocumentGroup(group_id=0, start_page=2, end_page=5, page_count=3, pages=[2, 4, 5]),
        ]
        # Original page → filtered position
        inverse_map = {2: 1, 4: 2, 5: 3}
        remapped = remap_groups_to_filtered_pdf(groups, inverse_map)

        assert len(remapped) == 1
        assert remapped[0].pages == [1, 2, 3]
        assert remapped[0].start_page == 1
        assert remapped[0].end_page == 3

    def test_remap_multiple_groups(self):
        groups = [
            DocumentGroup(group_id=0, start_page=2, end_page=3, page_count=2, pages=[2, 3]),
            DocumentGroup(group_id=1, start_page=6, end_page=7, page_count=2, pages=[6, 7]),
        ]
        # Original pages 2,3,6,7 → positions 1,2,3,4
        inverse_map = {2: 1, 3: 2, 6: 3, 7: 4}
        remapped = remap_groups_to_filtered_pdf(groups, inverse_map)

        assert len(remapped) == 2
        assert remapped[0].pages == [1, 2]
        assert remapped[1].pages == [3, 4]

    def test_remap_drops_empty_groups(self):
        """Groups with no matching filtered pages should be dropped."""
        groups = [
            DocumentGroup(group_id=0, start_page=1, end_page=1, page_count=1, pages=[1]),
        ]
        # Page 1 was filtered out (not in content-only PDF)
        inverse_map = {2: 1}
        remapped = remap_groups_to_filtered_pdf(groups, inverse_map)
        assert len(remapped) == 0


class TestBoundaryAndTrailingTypes:
    """Verify boundary/trailing type sets are correct."""

    def test_boundary_types(self):
        assert "blank" in BOUNDARY_TYPES
        assert "cover" in BOUNDARY_TYPES
        assert "transmittal" in BOUNDARY_TYPES
        assert "content" not in BOUNDARY_TYPES
        assert "signature" not in BOUNDARY_TYPES

    def test_trailing_types(self):
        assert "signature" in TRAILING_TYPES
        assert "boilerplate" in TRAILING_TYPES
        assert "content" not in TRAILING_TYPES
        assert "blank" not in TRAILING_TYPES


# --- Examiner page_ranges parameter tests ---

class TestExaminerPageRanges:
    """Test TitleExaminerAgent.examine_document_native_pdf with page_ranges."""

    @pytest.mark.asyncio
    async def test_page_ranges_override_fixed_size(self):
        """When page_ranges is provided, it should override fixed-size splitting."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
        from app.micro_apps.title_intelligence.schemas.examiner import ExaminerBatchResult
        import fitz

        # Create a 10-page test PDF
        doc = fitz.open()
        for i in range(10):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)

        # Track what page ranges are sent to examine_pdf_batch
        called_ranges = []

        async def mock_examine_pdf_batch(pdf_bytes, page_range, total_pages, batch_index, total_batches, **kwargs):
            called_ranges.append(page_range)
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        # Use document-aligned ranges instead of fixed-size
        custom_ranges = [(1, 4), (5, 7), (8, 10)]
        await agent.examine_document_native_pdf(
            pdf_bytes=pdf_bytes,
            total_pages=10,
            batch_size=25,  # This should be ignored
            concurrency=5,
            page_ranges=custom_ranges,
        )

        assert len(called_ranges) == 3
        # asyncio.as_completed returns in arbitrary order, so compare as sets
        assert set(called_ranges) == {(1, 4), (5, 7), (8, 10)}

    @pytest.mark.asyncio
    async def test_no_page_ranges_uses_fixed_size(self):
        """Without page_ranges, fixed-size splitting should be used."""
        from app.micro_apps.title_intelligence.ai.title_examiner_agent import TitleExaminerAgent
        from app.micro_apps.title_intelligence.schemas.examiner import ExaminerBatchResult
        import fitz

        doc = fitz.open()
        for i in range(10):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)
        called_ranges = []

        async def mock_examine_pdf_batch(pdf_bytes, page_range, total_pages, batch_index, total_batches, **kwargs):
            called_ranges.append(page_range)
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        await agent.examine_document_native_pdf(
            pdf_bytes=pdf_bytes,
            total_pages=10,
            batch_size=3,
            concurrency=5,
            page_ranges=None,  # Fixed-size splitting
        )

        # Should produce 4 chunks: 3+3+3+1
        assert len(called_ranges) == 4
        # asyncio.as_completed returns in arbitrary order, so compare as sets
        assert set(called_ranges) == {(1, 3), (4, 6), (7, 9), (10, 10)}


# --- Pipeline integration tests ---

MOCK_VERSION_INFO = {
    "ai_platform": "gemini",
    "ai_model": "gemini/gemini-2.5-flash",
    "ingestion_prompt_hash": "test_hash",
    "risk_prompt_hash": "test_hash",
    "extraction_tool_hash": "test_hash",
    "risk_tool_hash": "test_hash",
    "triage_prompt_hash": "triage_test_hash",
    "ocr_engine": "gemini_native_pdf",
    "chunker_version": "hierarchical_v1",
    "rules_version": "weighted_5cat_v2",
    "pipeline_backend": "background_tasks",
    "version_metadata": {
        "ai_platform": "gemini",
        "ai_model": "gemini/gemini-2.5-flash",
        "pipeline_mode": "native_pdf",
        "triage_enabled": True,
        "grouping_enabled": True,
    },
}


def _create_test_pdf(num_pages: int = 10) -> bytes:
    import fitz
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"Test page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest_asyncio.fixture
async def pack_with_10_pages(db_session: AsyncSession, seed_data):
    """Create a pack with 10 native_pdf mode page records."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Grouping Pack",
        status="processing",
        current_stage="examine",
    )
    db_session.add(pack)

    pack_file = PackFile(
        id=TEST_FILE_ID,
        pack_id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        filename="test.pdf",
        file_size=2048,
        storage_path=f"{TEST_ORG_ID}/{TEST_PACK_ID}/files/test.pdf",
        content_hash="abc123",
        page_count=10,
    )
    db_session.add(pack_file)

    for i in range(1, 11):
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


class TestGroupingInPipeline:
    """Test document grouping integration in the native PDF examine stage."""

    @pytest.mark.asyncio
    async def test_examine_with_grouping_uses_document_aligned_chunks(
        self, db_session: AsyncSession, pack_with_10_pages,
    ):
        """When grouping is enabled, examiner should receive document-aligned page ranges."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_examine_native_pdf

        pdf_bytes = _create_test_pdf(10)

        # Triage: pages 1(cover), 4(blank), 8(signature) are non-content
        mock_triage_result = TriageResult(
            pages=[
                TriagePageResult(page_number=1, page_type="cover"),
                TriagePageResult(page_number=2, page_type="content"),
                TriagePageResult(page_number=3, page_type="content"),
                TriagePageResult(page_number=4, page_type="blank"),
                TriagePageResult(page_number=5, page_type="content"),
                TriagePageResult(page_number=6, page_type="content"),
                TriagePageResult(page_number=7, page_type="content"),
                TriagePageResult(page_number=8, page_type="signature"),
                TriagePageResult(page_number=9, page_type="content"),
                TriagePageResult(page_number=10, page_type="content"),
            ],
            llm_elapsed_seconds=2.0,
        )

        mock_consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[
                PageTranscription(page_number=i, text=f"Page {i}")
                for i in range(1, 8)  # 7 content pages in filtered PDF
            ],
            sections=[],
            extractions=[],
            flags=[],
        )

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=pdf_bytes)
        mock_storage.exists = AsyncMock(return_value=False)
        mock_storage.save = AsyncMock()
        mock_storage.make_ai_cache_path = MagicMock(return_value="cache/path")

        mock_settings = MagicMock()
        mock_settings.PIPELINE_MODE = "native_pdf"
        mock_settings.NATIVE_PDF_BATCH_SIZE = 25
        mock_settings.NATIVE_PDF_CONCURRENCY = 5
        mock_settings.TRIAGE_ENABLED = True
        mock_settings.TRIAGE_SKIP_BELOW = 1  # Force triage on small test PDF
        mock_settings.TRIAGE_CHUNK_SIZE = 50
        mock_settings.TRIAGE_CONCURRENCY = 4
        mock_settings.GROUPING_ENABLED = True

        # Mock early batch result for optimistic dispatch during triage
        from app.micro_apps.title_intelligence.schemas.examiner import ExaminerBatchResult as EBR
        mock_early_batch = EBR(page_transcriptions=[], sections=[], extractions=[], flags=[])

        with patch(
            "app.config.get_settings",
            return_value=mock_settings,
        ), patch(
            "app.micro_apps.title_intelligence.ai.triage_agent.TriageAgent.classify_pages_parallel",
            new_callable=AsyncMock,
            return_value=mock_triage_result,
        ), patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent.examine_document_native_pdf",
            new_callable=AsyncMock,
            return_value=mock_consolidated,
        ) as mock_examine_call, patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent.examine_pdf_batch",
            new_callable=AsyncMock,
            return_value=mock_early_batch,
        ), patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent._ensure_context_cache",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.collect_version_info",
            return_value=MOCK_VERSION_INFO,
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_input_file_hash",
            new_callable=AsyncMock,
            return_value="test_file_hash",
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_examiner_cache_key",
            return_value="test_cache_key",
        ), patch(
            "app.micro_apps.title_intelligence.services.flag_rules.normalize_flags",
            return_value=[],
        ):
            await _stage_examine_native_pdf(
                TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage,
            )

        # Verify examiner was called with page_ranges (document-aligned)
        call_kwargs = mock_examine_call.call_args.kwargs
        page_ranges = call_kwargs.get("page_ranges")
        assert page_ranges is not None, "page_ranges should be passed to examiner"
        # Should have document-aligned groups, not fixed 25-page chunks
        assert len(page_ranges) >= 2  # At least 2 groups (split by blank page)

    @pytest.mark.asyncio
    async def test_examine_grouping_disabled_uses_fixed_chunks(
        self, db_session: AsyncSession, pack_with_10_pages,
    ):
        """When GROUPING_ENABLED=False, examiner should use fixed-size chunks."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_examine_native_pdf

        pdf_bytes = _create_test_pdf(10)

        mock_triage_result = TriageResult(
            pages=[
                TriagePageResult(page_number=i, page_type="content")
                for i in range(1, 11)
            ],
            llm_elapsed_seconds=2.0,
        )

        mock_consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[
                PageTranscription(page_number=i, text=f"Page {i}")
                for i in range(1, 11)
            ],
            sections=[],
            extractions=[],
            flags=[],
        )

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value=pdf_bytes)
        mock_storage.exists = AsyncMock(return_value=False)
        mock_storage.save = AsyncMock()
        mock_storage.make_ai_cache_path = MagicMock(return_value="cache/path")

        mock_settings = MagicMock()
        mock_settings.PIPELINE_MODE = "native_pdf"
        mock_settings.NATIVE_PDF_BATCH_SIZE = 25
        mock_settings.NATIVE_PDF_CONCURRENCY = 5
        mock_settings.TRIAGE_ENABLED = True
        mock_settings.TRIAGE_SKIP_BELOW = 80
        mock_settings.TRIAGE_CHUNK_SIZE = 50
        mock_settings.TRIAGE_CONCURRENCY = 4
        mock_settings.GROUPING_ENABLED = False

        with patch(
            "app.config.get_settings",
            return_value=mock_settings,
        ), patch(
            "app.micro_apps.title_intelligence.ai.triage_agent.TriageAgent.classify_pages_parallel",
            new_callable=AsyncMock,
            return_value=mock_triage_result,
        ), patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent.examine_document_native_pdf",
            new_callable=AsyncMock,
            return_value=mock_consolidated,
        ) as mock_examine_call, patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent._ensure_context_cache",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.collect_version_info",
            return_value=MOCK_VERSION_INFO,
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_input_file_hash",
            new_callable=AsyncMock,
            return_value="test_file_hash",
        ), patch(
            "app.micro_apps.title_intelligence.pipeline.version_tracker.compute_examiner_cache_key",
            return_value="test_cache_key",
        ), patch(
            "app.micro_apps.title_intelligence.services.flag_rules.normalize_flags",
            return_value=[],
        ):
            await _stage_examine_native_pdf(
                TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage,
            )

        # Verify examiner was called WITHOUT page_ranges (fixed-size chunking)
        call_kwargs = mock_examine_call.call_args.kwargs
        assert call_kwargs.get("page_ranges") is None


class TestVersionTrackerGrouping:
    """Test version tracker includes grouping metadata."""

    def test_version_info_includes_grouping_enabled(self):
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

        mock_settings = MagicMock()
        mock_settings.PIPELINE_MODE = "native_pdf"
        mock_settings.PIPELINE_BACKEND = "background_tasks"
        mock_settings.TRIAGE_ENABLED = True
        mock_settings.GROUPING_ENABLED = True

        info = collect_version_info(mock_settings)
        assert info["version_metadata"]["grouping_enabled"] is True

    def test_version_info_grouping_disabled(self):
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

        mock_settings = MagicMock()
        mock_settings.PIPELINE_MODE = "native_pdf"
        mock_settings.PIPELINE_BACKEND = "background_tasks"
        mock_settings.TRIAGE_ENABLED = True
        mock_settings.GROUPING_ENABLED = False

        info = collect_version_info(mock_settings)
        assert info["version_metadata"]["grouping_enabled"] is False
