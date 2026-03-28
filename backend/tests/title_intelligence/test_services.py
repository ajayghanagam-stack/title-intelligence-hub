"""Direct service-layer tests for pack_service, flag_service, page_service, pipeline_service.

These test the raising variants and business logic without going through HTTP,
ensuring the service layer works correctly as an independent unit.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ConflictError, ValidationError, ForbiddenError
from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.page import Page
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.services import pack_service, flag_service
from app.micro_apps.title_intelligence.services import page_service, pipeline_service
from app.micro_apps.title_intelligence.services.readiness_service import (
    FLAG_CATEGORY_MAP,
    FLAG_TYPE_RESOLUTION_DAYS,
    _estimate_days,
)

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID, TEST_FILE_ID, TEST_FLAG_ID

OTHER_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
MISSING_ID = uuid.UUID("00000000-0000-0000-0000-ffffffffffff")


# ---------------------------------------------------------------------------
# pack_service
# ---------------------------------------------------------------------------

class TestPackService:
    @pytest.mark.asyncio
    async def test_create_and_get_pack(self, db_session: AsyncSession, seed_data):
        pack = await pack_service.create_pack(db_session, TEST_ORG_ID, "My Pack")
        assert pack.name == "My Pack"
        assert pack.status == "uploading"
        assert pack.org_id == TEST_ORG_ID

        fetched = await pack_service.get_pack(db_session, TEST_ORG_ID, pack.id)
        assert fetched is not None
        assert fetched.id == pack.id

    @pytest.mark.asyncio
    async def test_get_pack_or_raise_not_found(self, db_session: AsyncSession, seed_data):
        with pytest.raises(NotFoundError):
            await pack_service.get_pack_or_raise(db_session, TEST_ORG_ID, MISSING_ID)

    @pytest.mark.asyncio
    async def test_get_pack_wrong_org_returns_none(self, db_session: AsyncSession, sample_pack):
        result = await pack_service.get_pack(db_session, OTHER_ORG_ID, TEST_PACK_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_packs_respects_org(self, db_session: AsyncSession, sample_pack):
        packs = await pack_service.list_packs(db_session, TEST_ORG_ID)
        assert len(packs) == 1
        assert packs[0].id == TEST_PACK_ID

        other_packs = await pack_service.list_packs(db_session, OTHER_ORG_ID)
        assert len(other_packs) == 0

    @pytest.mark.asyncio
    async def test_require_pack_for_processing_already_processing(self, db_session: AsyncSession, seed_data):
        pack = await pack_service.create_pack(db_session, TEST_ORG_ID, "Processing Pack")
        pack.status = "processing"
        await db_session.commit()

        with pytest.raises(ConflictError, match="already being processed"):
            await pack_service.require_pack_for_processing(db_session, TEST_ORG_ID, pack.id)

    @pytest.mark.asyncio
    async def test_require_pack_for_processing_not_found(self, db_session: AsyncSession, seed_data):
        with pytest.raises(NotFoundError):
            await pack_service.require_pack_for_processing(db_session, TEST_ORG_ID, MISSING_ID)

    @pytest.mark.asyncio
    async def test_add_file_and_get_files(self, db_session: AsyncSession, sample_pack):
        pf = await pack_service.add_file(
            db_session, TEST_ORG_ID, TEST_PACK_ID, "doc.pdf", "path/doc.pdf", 1024,
        )
        assert pf.filename == "doc.pdf"
        assert pf.org_id == TEST_ORG_ID

        files = await pack_service.get_pack_files(db_session, TEST_ORG_ID, TEST_PACK_ID)
        assert len(files) == 1

        # Wrong org returns empty
        files_other = await pack_service.get_pack_files(db_session, OTHER_ORG_ID, TEST_PACK_ID)
        assert len(files_other) == 0

    @pytest.mark.asyncio
    async def test_get_file_download_data_or_raise_not_found(self, db_session: AsyncSession, sample_pack):
        from unittest.mock import AsyncMock
        storage = AsyncMock()
        with pytest.raises(NotFoundError):
            await pack_service.get_file_download_data_or_raise(
                db_session, TEST_ORG_ID, TEST_PACK_ID, MISSING_ID, storage,
            )

    def test_validate_pdf_upload_valid(self):
        pack_service.validate_pdf_upload("doc.pdf", b"%PDF-1.0 content", 1024 * 1024)

    def test_validate_pdf_upload_bad_extension(self):
        with pytest.raises(ValidationError, match="Only PDF files"):
            pack_service.validate_pdf_upload("doc.txt", b"%PDF-1.0 content", 1024 * 1024)

    def test_validate_pdf_upload_no_filename(self):
        with pytest.raises(ValidationError, match="Only PDF files"):
            pack_service.validate_pdf_upload(None, b"%PDF-1.0 content", 1024 * 1024)

    def test_validate_pdf_upload_too_large(self):
        with pytest.raises(ValidationError, match="File too large"):
            pack_service.validate_pdf_upload("doc.pdf", b"%PDF-1.0 content", 5)

    def test_validate_pdf_upload_bad_magic_bytes(self):
        with pytest.raises(ValidationError, match="not a valid PDF"):
            pack_service.validate_pdf_upload("doc.pdf", b"not a pdf", 1024 * 1024)


# ---------------------------------------------------------------------------
# report_service
# ---------------------------------------------------------------------------

class TestReportService:
    @pytest.mark.asyncio
    async def test_get_report_by_uri_or_raise_wrong_prefix(self):
        from unittest.mock import AsyncMock
        from app.micro_apps.title_intelligence.services.report_service import get_report_by_uri_or_raise
        storage = AsyncMock()
        with pytest.raises(ForbiddenError, match="does not belong"):
            await get_report_by_uri_or_raise(
                TEST_ORG_ID, TEST_PACK_ID, "other-org/other-pack/reports/report.pdf", storage,
            )

    @pytest.mark.asyncio
    async def test_get_report_by_uri_or_raise_not_found(self):
        from unittest.mock import AsyncMock
        from app.micro_apps.title_intelligence.services.report_service import get_report_by_uri_or_raise
        storage = AsyncMock()
        storage.read.side_effect = FileNotFoundError("not found")
        uri = f"{TEST_ORG_ID}/{TEST_PACK_ID}/reports/missing.pdf"
        with pytest.raises(NotFoundError):
            await get_report_by_uri_or_raise(TEST_ORG_ID, TEST_PACK_ID, uri, storage)

    @pytest.mark.asyncio
    async def test_get_report_by_uri_or_raise_success(self):
        from unittest.mock import AsyncMock
        from app.micro_apps.title_intelligence.services.report_service import get_report_by_uri_or_raise
        storage = AsyncMock()
        storage.read.return_value = b"PDF content"
        uri = f"{TEST_ORG_ID}/{TEST_PACK_ID}/reports/report.pdf"
        data = await get_report_by_uri_or_raise(TEST_ORG_ID, TEST_PACK_ID, uri, storage)
        assert data == b"PDF content"


# ---------------------------------------------------------------------------
# flag_service
# ---------------------------------------------------------------------------

class TestFlagService:
    @pytest.mark.asyncio
    async def test_list_flags_with_severity_counts(self, db_session: AsyncSession, sample_pack_with_data):
        flags, counts, total = await flag_service.list_flags(db_session, TEST_ORG_ID, TEST_PACK_ID)
        assert len(flags) == 1
        assert counts["high"] == 1
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_flags_wrong_org_empty(self, db_session: AsyncSession, sample_pack_with_data):
        flags, counts, total = await flag_service.list_flags(db_session, OTHER_ORG_ID, TEST_PACK_ID)
        assert len(flags) == 0
        assert len(counts) == 0
        assert total == 0

    @pytest.mark.asyncio
    async def test_get_flag_for_pack_or_raise_success(self, db_session: AsyncSession, sample_pack_with_data):
        flag = await flag_service.get_flag_for_pack_or_raise(
            db_session, TEST_ORG_ID, TEST_PACK_ID, TEST_FLAG_ID,
        )
        assert flag.id == TEST_FLAG_ID
        assert flag.severity == "high"

    @pytest.mark.asyncio
    async def test_get_flag_for_pack_or_raise_wrong_pack(self, db_session: AsyncSession, sample_pack_with_data):
        other_pack_id = uuid.uuid4()
        with pytest.raises(NotFoundError):
            await flag_service.get_flag_for_pack_or_raise(
                db_session, TEST_ORG_ID, other_pack_id, TEST_FLAG_ID,
            )

    @pytest.mark.asyncio
    async def test_get_flag_for_pack_or_raise_wrong_org(self, db_session: AsyncSession, sample_pack_with_data):
        with pytest.raises(NotFoundError):
            await flag_service.get_flag_for_pack_or_raise(
                db_session, OTHER_ORG_ID, TEST_PACK_ID, TEST_FLAG_ID,
            )

    @pytest.mark.asyncio
    async def test_get_flag_for_pack_or_raise_missing_flag(self, db_session: AsyncSession, sample_pack_with_data):
        with pytest.raises(NotFoundError):
            await flag_service.get_flag_for_pack_or_raise(
                db_session, TEST_ORG_ID, TEST_PACK_ID, MISSING_ID,
            )

    @pytest.mark.asyncio
    async def test_create_review_updates_flag_status(self, db_session: AsyncSession, sample_pack_with_data):
        from tests.conftest import TEST_USER_ID
        review = await flag_service.create_review(
            db_session, TEST_ORG_ID, TEST_FLAG_ID, TEST_USER_ID, "approve",
        )
        assert review.decision == "approve"

        flag = await flag_service.get_flag(db_session, TEST_ORG_ID, TEST_FLAG_ID)
        assert flag.status == "approved"

    @pytest.mark.asyncio
    async def test_get_extraction_context(self, db_session: AsyncSession, sample_pack_with_data):
        ctx = await flag_service.get_extraction_context(db_session, TEST_ORG_ID, TEST_PACK_ID)
        assert len(ctx) == 1
        assert ctx[0]["extraction_type"] == "party"
        assert ctx[0]["label"] == "Buyer"

    @pytest.mark.asyncio
    async def test_get_extraction_context_wrong_org_empty(self, db_session: AsyncSession, sample_pack_with_data):
        ctx = await flag_service.get_extraction_context(db_session, OTHER_ORG_ID, TEST_PACK_ID)
        assert len(ctx) == 0


# ---------------------------------------------------------------------------
# page_service
# ---------------------------------------------------------------------------

class TestPageService:
    @pytest_asyncio.fixture
    async def sample_page(self, db_session: AsyncSession, sample_pack):
        page = Page(
            pack_id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            file_id=TEST_FILE_ID,
            page_number=1,
            image_uri="pages/page_0001.jpg",
            thumb_uri="thumbs/page_0001.jpg",
            ocr_text="Sample OCR text",
        )
        db_session.add(page)
        await db_session.commit()
        return page

    @pytest.mark.asyncio
    async def test_list_pages(self, db_session: AsyncSession, sample_page):
        pages = await page_service.list_pages(db_session, TEST_ORG_ID, TEST_PACK_ID)
        assert len(pages) == 1
        assert pages[0].page_number == 1

    @pytest.mark.asyncio
    async def test_list_pages_wrong_org_empty(self, db_session: AsyncSession, sample_page):
        pages = await page_service.list_pages(db_session, OTHER_ORG_ID, TEST_PACK_ID)
        assert len(pages) == 0

    @pytest.mark.asyncio
    async def test_get_page_image_data_or_raise_not_found(self, db_session: AsyncSession, sample_pack):
        from unittest.mock import AsyncMock
        storage = AsyncMock()
        with pytest.raises(NotFoundError):
            await page_service.get_page_image_data_or_raise(
                db_session, TEST_ORG_ID, TEST_PACK_ID, 999, storage,
            )

    @pytest.mark.asyncio
    async def test_get_page_thumb_data_or_raise_not_found(self, db_session: AsyncSession, sample_pack):
        from unittest.mock import AsyncMock
        storage = AsyncMock()
        with pytest.raises(NotFoundError):
            await page_service.get_page_thumb_data_or_raise(
                db_session, TEST_ORG_ID, TEST_PACK_ID, 999, storage,
            )


# ---------------------------------------------------------------------------
# pipeline_service
# ---------------------------------------------------------------------------

class TestPipelineService:
    @pytest.mark.asyncio
    async def test_get_pipeline_status_completed(self, db_session: AsyncSession, sample_pack):
        result = await pipeline_service.get_pipeline_status(db_session, TEST_ORG_ID, TEST_PACK_ID)
        assert result is not None
        assert result.status == "completed"
        assert all(s.status == "completed" for s in result.stages)

    @pytest.mark.asyncio
    async def test_get_pipeline_status_processing(self, db_session: AsyncSession, seed_data):
        pack = Pack(org_id=TEST_ORG_ID, name="Processing", status="processing", current_stage="render")
        db_session.add(pack)
        await db_session.commit()

        result = await pipeline_service.get_pipeline_status(db_session, TEST_ORG_ID, pack.id)
        assert result.status == "processing"
        assert result.current_stage == "render"

        stage_statuses = {s.stage: s.status for s in result.stages}
        assert stage_statuses["ingest"] == "completed"
        assert stage_statuses["render"] == "running"

    @pytest.mark.asyncio
    async def test_get_pipeline_status_or_raise_not_found(self, db_session: AsyncSession, seed_data):
        with pytest.raises(NotFoundError):
            await pipeline_service.get_pipeline_status_or_raise(db_session, TEST_ORG_ID, MISSING_ID)

    @pytest.mark.asyncio
    async def test_get_pipeline_status_wrong_org(self, db_session: AsyncSession, sample_pack):
        result = await pipeline_service.get_pipeline_status(db_session, OTHER_ORG_ID, TEST_PACK_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pipeline_status_failed(self, db_session: AsyncSession, seed_data):
        pack = Pack(
            org_id=TEST_ORG_ID, name="Failed", status="failed",
            current_stage="render", error_message="Render crashed",
        )
        db_session.add(pack)
        await db_session.commit()

        result = await pipeline_service.get_pipeline_status(db_session, TEST_ORG_ID, pack.id)
        assert result.status == "failed"
        assert result.error_message == "Render crashed"

        stage_statuses = {s.stage: s.status for s in result.stages}
        assert stage_statuses["ingest"] == "completed"
        assert stage_statuses["render"] == "failed"


# ---------------------------------------------------------------------------
# readiness_service — _estimate_days and FLAG_CATEGORY_MAP
# ---------------------------------------------------------------------------

class _MockFlag:
    """Lightweight mock for flag objects used in _estimate_days tests."""
    def __init__(self, flag_type: str, severity: str = "high"):
        self.flag_type = flag_type
        self.severity = severity


class TestReadinessService:
    def test_estimate_days_trust_issue(self):
        """trust_issue should resolve in 10 days (max base)."""
        flags = [_MockFlag("trust_issue", "high")]
        assert _estimate_days(flags) == 10

    def test_estimate_days_estate_issue(self):
        """estate_issue should resolve in 10 days."""
        flags = [_MockFlag("estate_issue", "high")]
        assert _estimate_days(flags) == 10

    def test_estimate_days_tax_issue(self):
        """tax_issue should resolve in 7 days."""
        flags = [_MockFlag("tax_issue", "medium")]
        assert _estimate_days(flags) == 7

    def test_estimate_days_concurrent_takes_max(self):
        """Multiple flag types → max base_days (concurrent resolution)."""
        flags = [
            _MockFlag("name_discrepancy", "medium"),     # 2 days
            _MockFlag("trust_issue", "high"),             # 10 days
            _MockFlag("missing_endorsement", "medium"),   # 2 days
        ]
        assert _estimate_days(flags) == 10

    def test_estimate_days_with_critical(self):
        """Critical flags add 2 days escalation buffer each."""
        flags = [
            _MockFlag("trust_issue", "critical"),   # 10 base + 2 escalation
        ]
        assert _estimate_days(flags) == 12

    def test_estimate_days_multiple_critical(self):
        """Multiple critical flags each add 2 days buffer."""
        flags = [
            _MockFlag("trust_issue", "critical"),        # 10 base
            _MockFlag("unreleased_mortgage", "critical"), # 5 base
        ]
        # max(10, 5) = 10 base + 2 * 2 = 4 escalation = 14
        assert _estimate_days(flags) == 14

    def test_estimate_days_empty(self):
        """No flags → 0 days."""
        assert _estimate_days([]) == 0

    def test_estimate_days_unknown_type_defaults_to_2(self):
        """Unknown flag types default to 2 days base."""
        flags = [_MockFlag("unknown_type", "medium")]
        assert _estimate_days(flags) == 2

    def test_flag_category_map_new_types(self):
        """All 17 flag types are mapped to categories."""
        from app.micro_apps.title_intelligence.services.flag_rules import VALID_FLAG_TYPES
        for ft in VALID_FLAG_TYPES:
            assert ft in FLAG_CATEGORY_MAP, f"Flag type '{ft}' missing from FLAG_CATEGORY_MAP"

    def test_flag_category_map_mineral_rights(self):
        """mineral_rights maps to exceptions category."""
        assert FLAG_CATEGORY_MAP["mineral_rights"] == "exceptions"

    def test_flag_category_map_trust_issue(self):
        """trust_issue maps to requirements category."""
        assert FLAG_CATEGORY_MAP["trust_issue"] == "requirements"

    def test_flag_type_resolution_days_coverage(self):
        """All VALID_FLAG_TYPES have resolution day estimates."""
        from app.micro_apps.title_intelligence.services.flag_rules import VALID_FLAG_TYPES
        for ft in VALID_FLAG_TYPES:
            assert ft in FLAG_TYPE_RESOLUTION_DAYS, f"Flag type '{ft}' missing from FLAG_TYPE_RESOLUTION_DAYS"
