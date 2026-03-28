"""Tests for the page triage agent and pipeline integration."""

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
    VALID_PAGE_TYPES,
    TRIAGE_SYSTEM_PROMPT,
    TRIAGE_JSON_SCHEMA,
)
from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.section import Section
from app.micro_apps.title_intelligence.models.text_chunk import TextChunk
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

TEST_ORG = TEST_ORG_ID


# --- TriageAgent unit tests ---

class TestTriageAgentParsing:
    """Test TriageAgent._parse_result with various LLM outputs."""

    def _make_agent(self):
        return TriageAgent(TEST_ORG)

    def test_parse_all_content(self):
        agent = self._make_agent()
        raw = {
            "pages": [
                {"page_number": 1, "page_type": "content"},
                {"page_number": 2, "page_type": "content"},
                {"page_number": 3, "page_type": "content"},
            ]
        }
        result = agent._parse_result(raw, total_pages=3, elapsed=1.0, usage={})
        assert len(result.pages) == 3
        assert all(p.page_type == "content" for p in result.pages)

    def test_parse_mixed_types(self):
        agent = self._make_agent()
        raw = {
            "pages": [
                {"page_number": 1, "page_type": "cover"},
                {"page_number": 2, "page_type": "content"},
                {"page_number": 3, "page_type": "blank"},
                {"page_number": 4, "page_type": "content"},
                {"page_number": 5, "page_type": "signature"},
            ]
        }
        result = agent._parse_result(raw, total_pages=5, elapsed=2.0, usage={})
        assert len(result.pages) == 5
        assert result.pages[0].page_type == "cover"
        assert result.pages[1].page_type == "content"
        assert result.pages[2].page_type == "blank"
        assert result.pages[3].page_type == "content"
        assert result.pages[4].page_type == "signature"

    def test_parse_missing_pages_default_to_content(self):
        """Pages not returned by LLM should default to content (conservative)."""
        agent = self._make_agent()
        raw = {
            "pages": [
                {"page_number": 1, "page_type": "blank"},
                # Pages 2 and 3 missing from LLM output
            ]
        }
        result = agent._parse_result(raw, total_pages=3, elapsed=1.0, usage={})
        assert len(result.pages) == 3
        assert result.pages[0].page_type == "blank"
        assert result.pages[1].page_type == "content"  # defaulted
        assert result.pages[2].page_type == "content"  # defaulted

    def test_parse_invalid_page_type_defaults_to_content(self):
        """Unknown page types should default to content."""
        agent = self._make_agent()
        raw = {
            "pages": [
                {"page_number": 1, "page_type": "unknown_type"},
                {"page_number": 2, "page_type": "garbage"},
            ]
        }
        result = agent._parse_result(raw, total_pages=2, elapsed=1.0, usage={})
        assert result.pages[0].page_type == "content"
        assert result.pages[1].page_type == "content"

    def test_parse_empty_response(self):
        """Empty LLM response should classify all pages as content."""
        agent = self._make_agent()
        raw = {"pages": []}
        result = agent._parse_result(raw, total_pages=5, elapsed=1.0, usage={})
        assert len(result.pages) == 5
        assert all(p.page_type == "content" for p in result.pages)

    def test_parse_records_usage(self):
        agent = self._make_agent()
        raw = {"pages": [{"page_number": 1, "page_type": "content"}]}
        usage = {"input_tokens": 500, "output_tokens": 100}
        result = agent._parse_result(raw, total_pages=1, elapsed=3.5, usage=usage)
        assert result.llm_elapsed_seconds == 3.5
        assert result.input_tokens == 500
        assert result.output_tokens == 100


class TestTriageAgentClassify:
    """Test TriageAgent.classify_pages with mocked LLM."""

    @pytest.mark.asyncio
    async def test_classify_pages_cached(self):
        agent = TriageAgent(TEST_ORG)
        mock_result = {
            "pages": [
                {"page_number": 1, "page_type": "cover"},
                {"page_number": 2, "page_type": "content"},
                {"page_number": 3, "page_type": "blank"},
            ]
        }
        agent._ensure_context_cache = AsyncMock(return_value="test_cache")
        agent.call_json_structured_cached = AsyncMock(
            return_value=(mock_result, {"input_tokens": 300, "output_tokens": 50})
        )

        result = await agent.classify_pages(b"fake_pdf", total_pages=3)

        assert len(result.pages) == 3
        assert result.pages[0].page_type == "cover"
        assert result.pages[1].page_type == "content"
        assert result.pages[2].page_type == "blank"

    @pytest.mark.asyncio
    async def test_classify_pages_fallback_uncached(self):
        agent = TriageAgent(TEST_ORG)
        mock_result = {
            "pages": [
                {"page_number": 1, "page_type": "content"},
                {"page_number": 2, "page_type": "content"},
            ]
        }
        agent._ensure_context_cache = AsyncMock(return_value=None)
        agent.call_json_structured = AsyncMock(
            return_value=(mock_result, {"input_tokens": 400, "output_tokens": 30})
        )

        result = await agent.classify_pages(b"fake_pdf", total_pages=2)

        assert len(result.pages) == 2
        agent.call_json_structured.assert_called_once()


class TestValidPageTypes:
    """Verify page type constants."""

    def test_valid_page_types_set(self):
        assert "content" in VALID_PAGE_TYPES
        assert "blank" in VALID_PAGE_TYPES
        assert "cover" in VALID_PAGE_TYPES
        assert "signature" in VALID_PAGE_TYPES
        assert "transmittal" in VALID_PAGE_TYPES
        assert "boilerplate" in VALID_PAGE_TYPES
        assert len(VALID_PAGE_TYPES) == 6

    def test_triage_schema_matches_valid_types(self):
        schema_enum = TRIAGE_JSON_SCHEMA["properties"]["pages"]["items"]["properties"]["page_type"]["enum"]
        assert set(schema_enum) == VALID_PAGE_TYPES


# --- Page number remapping tests ---

class TestPageNumberRemapping:
    """Test _remap_page_numbers for content-only PDF → original pages."""

    def test_remap_transcriptions(self):
        from app.micro_apps.title_intelligence.pipeline.stages import _remap_page_numbers

        consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[
                PageTranscription(page_number=1, text="Page 3 content"),
                PageTranscription(page_number=2, text="Page 5 content"),
            ],
            sections=[],
            extractions=[],
            flags=[],
        )
        # Content pages 3, 5 → positions 1, 2 in filtered PDF
        content_map = {1: 3, 2: 5}
        result = _remap_page_numbers(consolidated, content_map)

        assert result.page_transcriptions[0].page_number == 3
        assert result.page_transcriptions[1].page_number == 5

    def test_remap_sections(self):
        from app.micro_apps.title_intelligence.pipeline.stages import _remap_page_numbers

        consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[],
            sections=[
                ExaminerSection(section_type="schedule_a", start_page=1, end_page=2, confidence=0.9),
            ],
            extractions=[],
            flags=[],
        )
        content_map = {1: 3, 2: 5}
        result = _remap_page_numbers(consolidated, content_map)

        assert result.sections[0].start_page == 3
        assert result.sections[0].end_page == 5

    def test_remap_extraction_evidence_refs(self):
        from app.micro_apps.title_intelligence.pipeline.stages import _remap_page_numbers

        consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[],
            sections=[],
            extractions=[
                ExaminerExtraction(
                    extraction_type="party",
                    label="Buyer",
                    value={"name": "John"},
                    evidence_refs=[{"page_number": 1, "text_snippet": "test"}],
                    confidence=0.9,
                ),
            ],
            flags=[],
        )
        content_map = {1: 4}
        result = _remap_page_numbers(consolidated, content_map)

        assert result.extractions[0].evidence_refs[0]["page_number"] == 4

    def test_remap_flag_evidence_refs(self):
        from app.micro_apps.title_intelligence.pipeline.stages import _remap_page_numbers

        consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[],
            sections=[],
            extractions=[],
            flags=[
                ExaminerFlag(
                    flag_type="unresolved_lien",
                    severity="high",
                    title="Test Flag",
                    description="Test",
                    ai_explanation="Test",
                    evidence_refs=[{"page_number": 2, "text_snippet": "test"}],
                ),
            ],
        )
        content_map = {1: 3, 2: 7}
        result = _remap_page_numbers(consolidated, content_map)

        assert result.flags[0].evidence_refs[0]["page_number"] == 7


# --- Content-only PDF builder tests ---

class TestBuildContentOnlyPdf:
    """Test _build_content_only_pdf creates filtered PDF."""

    def test_build_content_only_pdf(self):
        import fitz
        from app.micro_apps.title_intelligence.pipeline.stages import _build_content_only_pdf

        # Create a 5-page test PDF
        doc = fitz.open()
        for i in range(5):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        # Keep only pages 2, 4, 5
        result = _build_content_only_pdf(pdf_bytes, [2, 4, 5])

        filtered = fitz.open(stream=result, filetype="pdf")
        assert len(filtered) == 3
        filtered.close()

    def test_build_content_only_pdf_all_pages(self):
        import fitz
        from app.micro_apps.title_intelligence.pipeline.stages import _build_content_only_pdf

        doc = fitz.open()
        for i in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        result = _build_content_only_pdf(pdf_bytes, [1, 2, 3])

        filtered = fitz.open(stream=result, filetype="pdf")
        assert len(filtered) == 3
        filtered.close()

    def test_build_content_only_pdf_single_page(self):
        import fitz
        from app.micro_apps.title_intelligence.pipeline.stages import _build_content_only_pdf

        doc = fitz.open()
        for i in range(5):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        result = _build_content_only_pdf(pdf_bytes, [3])

        filtered = fitz.open(stream=result, filetype="pdf")
        assert len(filtered) == 1
        filtered.close()


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
    },
}


def _create_test_pdf(num_pages: int = 5) -> bytes:
    import fitz
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"Test page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest_asyncio.fixture
async def pack_with_native_pages(db_session: AsyncSession, seed_data):
    """Create a pack with 5 native_pdf mode page records."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Triage Pack",
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
        page_count=5,
    )
    db_session.add(pack_file)

    for i in range(1, 6):
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


class TestTriageInPipeline:
    """Test triage integration within the native PDF examine stage."""

    @pytest.mark.asyncio
    async def test_run_triage_persists_page_types(
        self, db_session: AsyncSession, pack_with_native_pages,
    ):
        """_run_triage should persist page_type on Page records."""
        from app.micro_apps.title_intelligence.pipeline.stages import _run_triage

        pages_result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        pages = list(pages_result.scalars().all())

        mock_triage_result = TriageResult(
            pages=[
                TriagePageResult(page_number=1, page_type="cover"),
                TriagePageResult(page_number=2, page_type="content"),
                TriagePageResult(page_number=3, page_type="blank"),
                TriagePageResult(page_number=4, page_type="content"),
                TriagePageResult(page_number=5, page_type="signature"),
            ],
            llm_elapsed_seconds=2.0,
        )

        with patch(
            "app.micro_apps.title_intelligence.ai.triage_agent.TriageAgent.classify_pages",
            new_callable=AsyncMock,
            return_value=mock_triage_result,
        ):
            content_pages, doc_type_hints = await _run_triage(
                b"fake_pdf", 5, TEST_ORG_ID, TEST_PACK_ID, pages, db_session,
            )

        assert content_pages == [2, 4]
        assert isinstance(doc_type_hints, dict)

        # Verify page_type persisted
        result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        updated_pages = list(result.scalars().all())
        assert updated_pages[0].page_type == "cover"
        assert updated_pages[1].page_type == "content"
        assert updated_pages[2].page_type == "blank"
        assert updated_pages[3].page_type == "content"
        assert updated_pages[4].page_type == "signature"

    @pytest.mark.asyncio
    async def test_examine_with_triage_filters_pages(
        self, db_session: AsyncSession, pack_with_native_pages,
    ):
        """Full examine stage with triage should only send content pages to examiner."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_examine_native_pdf

        pdf_bytes = _create_test_pdf(5)

        # Mock triage to mark pages 1 (cover) and 3 (blank) as non-content
        mock_triage_result = TriageResult(
            pages=[
                TriagePageResult(page_number=1, page_type="cover"),
                TriagePageResult(page_number=2, page_type="content"),
                TriagePageResult(page_number=3, page_type="blank"),
                TriagePageResult(page_number=4, page_type="content"),
                TriagePageResult(page_number=5, page_type="content"),
            ],
            llm_elapsed_seconds=2.0,
        )

        # Mock examiner to return results with remapped page numbers
        mock_consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[
                PageTranscription(page_number=1, text="Schedule A content"),
                PageTranscription(page_number=2, text="Schedule B content"),
                PageTranscription(page_number=3, text="Legal description"),
            ],
            sections=[
                ExaminerSection(section_type="schedule_a", start_page=1, end_page=1, confidence=0.9),
            ],
            extractions=[
                ExaminerExtraction(
                    extraction_type="party",
                    label="Buyer",
                    value={"name": "John Doe"},
                    evidence_refs=[{"page_number": 1, "text_snippet": "John Doe"}],
                    confidence=0.9,
                ),
            ],
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
        mock_early_batch = ExaminerBatchResult(
            page_transcriptions=[],
            sections=[],
            extractions=[],
            flags=[],
        )

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
        ), patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent._ensure_context_cache",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await _stage_examine_native_pdf(
                TEST_PACK_ID, TEST_ORG_ID, db_session, mock_storage,
            )

        # Verify examiner was called with filtered PDF (3 content pages, not 5)
        call_args = mock_examine_call.call_args
        assert call_args.kwargs["total_pages"] == 3  # Only content pages

        # Verify page_types were persisted
        result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        pages = list(result.scalars().all())
        assert pages[0].page_type == "cover"
        assert pages[1].page_type == "content"
        assert pages[2].page_type == "blank"

        # Verify transcriptions were remapped to original page numbers
        # Content pages [2,4,5] → positions [1,2,3] in filtered PDF
        # So page_number 1 in examiner output → page 2 in original
        content_pages = [p for p in pages if p.page_type == "content"]
        assert content_pages[0].page_number == 2
        # Page 2 (first content page) should have transcription text
        assert content_pages[0].ocr_text == "Schedule A content"

    @pytest.mark.asyncio
    async def test_examine_triage_disabled(
        self, db_session: AsyncSession, pack_with_native_pages,
    ):
        """When TRIAGE_ENABLED=False, all pages should be sent to examiner."""
        from app.micro_apps.title_intelligence.pipeline.stages import _stage_examine_native_pdf

        pdf_bytes = _create_test_pdf(5)

        mock_consolidated = ExaminerConsolidatedResult(
            page_transcriptions=[
                PageTranscription(page_number=i, text=f"Page {i}")
                for i in range(1, 6)
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
        mock_settings.TRIAGE_ENABLED = False
        mock_settings.TRIAGE_SKIP_BELOW = 80

        with patch(
            "app.config.get_settings",
            return_value=mock_settings,
        ), patch(
            "app.micro_apps.title_intelligence.ai.title_examiner_agent.TitleExaminerAgent.examine_document_native_pdf",
            new_callable=AsyncMock,
            return_value=mock_consolidated,
        ) as mock_examine_call, patch(
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

        # Examiner should receive all 5 pages (no triage filtering)
        call_args = mock_examine_call.call_args
        assert call_args.kwargs["total_pages"] == 5

        # All pages should be marked as "content"
        result = await db_session.execute(
            select(Page).where(Page.pack_id == TEST_PACK_ID).order_by(Page.page_number)
        )
        pages = list(result.scalars().all())
        assert all(p.page_type == "content" for p in pages)


class TestVersionTrackerTriage:
    """Test version tracker includes triage prompt hash."""

    def test_version_info_includes_triage_hash(self):
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

        mock_settings = MagicMock()
        mock_settings.PIPELINE_MODE = "native_pdf"
        mock_settings.PIPELINE_BACKEND = "background_tasks"
        mock_settings.TRIAGE_ENABLED = True

        info = collect_version_info(mock_settings)
        assert "triage_prompt_hash" in info
        assert info["triage_prompt_hash"] != ""
        assert info["version_metadata"]["triage_enabled"] is True

    def test_version_info_no_triage_hash_when_disabled(self):
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

        mock_settings = MagicMock()
        mock_settings.PIPELINE_MODE = "native_pdf"
        mock_settings.PIPELINE_BACKEND = "background_tasks"
        mock_settings.TRIAGE_ENABLED = False

        info = collect_version_info(mock_settings)
        assert info["triage_prompt_hash"] == ""

    def test_version_info_no_triage_hash_in_legacy_mode(self):
        from app.micro_apps.title_intelligence.pipeline.version_tracker import collect_version_info

        mock_settings = MagicMock()
        mock_settings.PIPELINE_MODE = "legacy"
        mock_settings.PIPELINE_BACKEND = "background_tasks"
        mock_settings.TRIAGE_ENABLED = True

        info = collect_version_info(mock_settings)
        assert info["triage_prompt_hash"] == ""

    def test_cache_key_changes_with_triage(self):
        from app.micro_apps.title_intelligence.pipeline.version_tracker import (
            compute_examiner_cache_key,
        )

        base_info = {
            "ai_model": "test",
            "ingestion_prompt_hash": "h1",
            "extraction_tool_hash": "h2",
            "rules_version": "v1",
            "triage_prompt_hash": "",
        }
        key_no_triage = compute_examiner_cache_key("file_hash", base_info)

        triage_info = {**base_info, "triage_prompt_hash": "triage_hash_v1"}
        key_with_triage = compute_examiner_cache_key("file_hash", triage_info)

        assert key_no_triage != key_with_triage
