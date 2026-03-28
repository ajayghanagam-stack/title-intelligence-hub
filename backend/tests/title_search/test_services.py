"""Isolated service-layer unit tests for error paths."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ConflictError
from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.package import TAPackage
from app.micro_apps.title_search.services import (
    order_service,
    document_service,
    flag_service,
    package_service,
    source_service,
)

from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.title_search.conftest import (
    TEST_ORDER_ID,
    TEST_FLAG_ID,
    TEST_DOCUMENT_ID,
)

WRONG_ORG = uuid.UUID("00000000-0000-0000-0000-ffffffffffff")
WRONG_ID = uuid.UUID("00000000-0000-0000-0000-eeeeeeeeeeee")


# ── order_service error paths ──


@pytest.mark.asyncio
async def test_get_order_or_raise_not_found(db_session: AsyncSession, seed_data):
    """get_order_or_raise raises NotFoundError for missing order."""
    with pytest.raises(NotFoundError):
        await order_service.get_order_or_raise(db_session, TEST_ORG_ID, WRONG_ID)


@pytest.mark.asyncio
async def test_get_order_wrong_org(db_session: AsyncSession, sample_order):
    """get_order_or_raise raises NotFoundError when org_id doesn't match."""
    with pytest.raises(NotFoundError):
        await order_service.get_order_or_raise(db_session, WRONG_ORG, TEST_ORDER_ID)


@pytest.mark.asyncio
async def test_delete_order_any_status(db_session: AsyncSession, sample_order):
    """delete_order_or_raise works for any status."""
    sample_order.status = "processing"
    await db_session.commit()
    await order_service.delete_order_or_raise(db_session, TEST_ORG_ID, TEST_ORDER_ID)
    order = await order_service.get_order(db_session, TEST_ORG_ID, TEST_ORDER_ID)
    assert order is None


@pytest.mark.asyncio
async def test_require_order_already_processing(db_session: AsyncSession, sample_order):
    """require_order_for_processing raises ConflictError if already processing."""
    sample_order.status = "processing"
    await db_session.commit()
    with pytest.raises(ConflictError, match="already being processed"):
        await order_service.require_order_for_processing(db_session, TEST_ORG_ID, TEST_ORDER_ID)


@pytest.mark.asyncio
async def test_require_order_completed_status(db_session: AsyncSession, sample_order):
    """require_order_for_processing raises ConflictError for completed orders."""
    sample_order.status = "completed"
    await db_session.commit()
    with pytest.raises(ConflictError, match="cannot be processed"):
        await order_service.require_order_for_processing(db_session, TEST_ORG_ID, TEST_ORDER_ID)


# ── document_service error paths ──


@pytest.mark.asyncio
async def test_get_document_not_found(db_session: AsyncSession, sample_order):
    """get_document_or_raise raises NotFoundError for missing document."""
    with pytest.raises(NotFoundError):
        await document_service.get_document_or_raise(
            db_session, TEST_ORG_ID, TEST_ORDER_ID, WRONG_ID
        )


@pytest.mark.asyncio
async def test_get_document_wrong_org(db_session: AsyncSession, sample_order_with_data):
    """get_document_or_raise raises NotFoundError when org doesn't match."""
    with pytest.raises(NotFoundError):
        await document_service.get_document_or_raise(
            db_session, WRONG_ORG, TEST_ORDER_ID, TEST_DOCUMENT_ID
        )


# ── flag_service error paths ──


@pytest.mark.asyncio
async def test_get_flag_not_found(db_session: AsyncSession, sample_order):
    """get_flag_or_raise raises NotFoundError for missing flag."""
    with pytest.raises(NotFoundError):
        await flag_service.get_flag_or_raise(
            db_session, TEST_ORG_ID, TEST_ORDER_ID, WRONG_ID
        )


@pytest.mark.asyncio
async def test_get_flag_wrong_org(db_session: AsyncSession, sample_order_with_data):
    """get_flag_or_raise raises NotFoundError when org doesn't match."""
    with pytest.raises(NotFoundError):
        await flag_service.get_flag_or_raise(
            db_session, WRONG_ORG, TEST_ORDER_ID, TEST_FLAG_ID
        )


# ── package_service error paths ──


@pytest.mark.asyncio
async def test_get_package_not_found(db_session: AsyncSession, sample_order):
    """get_package_or_raise raises NotFoundError when no package exists."""
    with pytest.raises(NotFoundError):
        await package_service.get_package_or_raise(
            db_session, TEST_ORG_ID, TEST_ORDER_ID
        )


@pytest.mark.asyncio
async def test_issue_package_already_issued(db_session: AsyncSession, sample_order):
    """issue_package raises ConflictError if package already issued."""
    pkg = TAPackage(
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        package_number="TA-20260323-001",
        status="issued",
    )
    db_session.add(pkg)
    await db_session.commit()
    with pytest.raises(ConflictError, match="already issued"):
        await package_service.issue_package(
            db_session, TEST_ORG_ID, TEST_ORDER_ID, TEST_USER_ID
        )


@pytest.mark.asyncio
async def test_issue_package_blocked_by_critical_flags(db_session: AsyncSession, sample_order):
    """issue_package raises ConflictError when unresolved critical flags exist."""
    pkg = TAPackage(
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        package_number="TA-20260323-002",
        status="draft",
    )
    flag = TAFlag(
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        flag_type="chain_gap",
        severity="critical",
        title="Critical Gap",
        description="Chain gap found",
        status="open",
    )
    db_session.add(pkg)
    db_session.add(flag)
    await db_session.commit()
    with pytest.raises(ConflictError, match="unresolved critical"):
        await package_service.issue_package(
            db_session, TEST_ORG_ID, TEST_ORDER_ID, TEST_USER_ID
        )


# ── source_service error paths ──


@pytest.mark.asyncio
async def test_get_source_assignment_not_found(db_session: AsyncSession, sample_order):
    """get_source_assignment_or_raise raises NotFoundError for missing source."""
    with pytest.raises(NotFoundError):
        await source_service.get_source_assignment_or_raise(
            db_session, TEST_ORG_ID, TEST_ORDER_ID, WRONG_ID
        )


@pytest.mark.asyncio
async def test_get_source_assignment_wrong_org(
    db_session: AsyncSession, sample_order_with_data
):
    """get_source_assignment_or_raise raises NotFoundError when org doesn't match."""
    from tests.title_search.conftest import TEST_SOURCE_ASSIGNMENT_ID
    with pytest.raises(NotFoundError):
        await source_service.get_source_assignment_or_raise(
            db_session, WRONG_ORG, TEST_ORDER_ID, TEST_SOURCE_ASSIGNMENT_ID
        )
