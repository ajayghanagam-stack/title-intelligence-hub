"""Tests for server-side flag pagination, filtering, and sorting."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.flag import Flag
from app.micro_apps.title_intelligence.services import flag_service

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID

OTHER_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")


@pytest_asyncio.fixture
async def pack_with_many_flags(db_session: AsyncSession, sample_pack):
    """Create a pack with flags of various severities and statuses."""
    flags_data = [
        ("critical", "open", "chain_of_title_gap"),
        ("critical", "approved", "unreleased_mortgage"),
        ("high", "open", "name_discrepancy"),
        ("high", "rejected", "cross_section_mismatch"),
        ("medium", "open", "missing_endorsement"),
        ("medium", "escalated", "unresolved_lien"),
        ("low", "open", "document_defect"),
        ("low", "approved", "incomplete_document"),
    ]
    created = []
    for severity, status, flag_type in flags_data:
        flag = Flag(
            pack_id=TEST_PACK_ID,
            org_id=TEST_ORG_ID,
            flag_type=flag_type,
            severity=severity,
            title=f"Test {flag_type}",
            description=f"Description for {flag_type}",
            ai_explanation=f"Explanation for {flag_type}",
            evidence_refs=[{"page_number": 1, "text_snippet": "test"}],
            status=status,
        )
        db_session.add(flag)
        created.append(flag)
    await db_session.commit()
    return created


class TestFlagPagination:
    @pytest.mark.asyncio
    async def test_list_flags_default(self, db_session: AsyncSession, pack_with_many_flags):
        flags, counts, total = await flag_service.list_flags(db_session, TEST_ORG_ID, TEST_PACK_ID)
        assert total == 8
        assert len(flags) == 8
        assert counts["critical"] == 2
        assert counts["high"] == 2
        assert counts["medium"] == 2
        assert counts["low"] == 2

    @pytest.mark.asyncio
    async def test_severity_filter(self, db_session: AsyncSession, pack_with_many_flags):
        flags, counts, total = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, severity="critical"
        )
        assert total == 2
        assert len(flags) == 2
        assert all(f.severity == "critical" for f in flags)
        # counts remain unfiltered
        assert counts["critical"] == 2
        assert counts["high"] == 2

    @pytest.mark.asyncio
    async def test_status_filter(self, db_session: AsyncSession, pack_with_many_flags):
        flags, counts, total = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, status="open"
        )
        assert total == 4
        assert len(flags) == 4
        assert all(f.status == "open" for f in flags)
        # counts remain unfiltered
        assert sum(counts.values()) == 8

    @pytest.mark.asyncio
    async def test_combined_filters(self, db_session: AsyncSession, pack_with_many_flags):
        flags, counts, total = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, severity="high", status="open"
        )
        assert total == 1
        assert len(flags) == 1
        assert flags[0].severity == "high"
        assert flags[0].status == "open"

    @pytest.mark.asyncio
    async def test_limit_offset(self, db_session: AsyncSession, pack_with_many_flags):
        flags_p1, counts, total = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, limit=3, offset=0
        )
        assert total == 8
        assert len(flags_p1) == 3

        flags_p2, _, _ = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, limit=3, offset=3
        )
        assert len(flags_p2) == 3

        flags_p3, _, _ = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, limit=3, offset=6
        )
        assert len(flags_p3) == 2

        # No overlap between pages
        ids_p1 = {f.id for f in flags_p1}
        ids_p2 = {f.id for f in flags_p2}
        ids_p3 = {f.id for f in flags_p3}
        assert ids_p1.isdisjoint(ids_p2)
        assert ids_p2.isdisjoint(ids_p3)

    @pytest.mark.asyncio
    async def test_sort_by_severity(self, db_session: AsyncSession, pack_with_many_flags):
        flags, _, _ = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, sort_by="severity"
        )
        severities = [f.severity for f in flags]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        assert severities == sorted(severities, key=lambda s: order.get(s, 99))

    @pytest.mark.asyncio
    async def test_sort_by_flag_type(self, db_session: AsyncSession, pack_with_many_flags):
        flags, _, _ = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, sort_by="flag_type"
        )
        types = [f.flag_type for f in flags]
        assert types == sorted(types)

    @pytest.mark.asyncio
    async def test_sort_by_created_at(self, db_session: AsyncSession, pack_with_many_flags):
        flags, _, _ = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, sort_by="created_at"
        )
        dates = [f.created_at for f in flags]
        assert dates == sorted(dates, reverse=True)

    @pytest.mark.asyncio
    async def test_wrong_org_returns_empty(self, db_session: AsyncSession, pack_with_many_flags):
        flags, counts, total = await flag_service.list_flags(
            db_session, OTHER_ORG_ID, TEST_PACK_ID
        )
        assert len(flags) == 0
        assert len(counts) == 0
        assert total == 0

    @pytest.mark.asyncio
    async def test_counts_unaffected_by_filters(self, db_session: AsyncSession, pack_with_many_flags):
        """Counts should always reflect the full unfiltered severity breakdown."""
        _, counts_all, _ = await flag_service.list_flags(db_session, TEST_ORG_ID, TEST_PACK_ID)
        _, counts_filtered, _ = await flag_service.list_flags(
            db_session, TEST_ORG_ID, TEST_PACK_ID, severity="critical", status="open"
        )
        assert counts_all == counts_filtered
