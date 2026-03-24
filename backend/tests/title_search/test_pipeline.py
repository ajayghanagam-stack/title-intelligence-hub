"""Tests for TSA pipeline orchestrator."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.source_assignment import TASourceAssignment
from app.micro_apps.title_search.models.raw_document import TARawDocument
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.package import TAPackage
from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.pipeline.orchestrator import run_pipeline
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, test_session_factory
from tests.title_search.conftest import TEST_ORDER_ID


@pytest_asyncio.fixture
async def pipeline_order(db_session: AsyncSession, seed_data):
    """Create an order ready for pipeline processing."""
    # Add a county source so resolve produces digital assignments
    cs = TACountySource(
        county="Sangamon",
        state_code="IL",
        source_type="recorder",
        availability="digital",
        is_active=True,
    )
    db_session.add(cs)

    order = TAOrder(
        id=TEST_ORDER_ID,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="123 Main St, Springfield, IL",
        county="Sangamon",
        state_code="IL",
        status="processing",
        pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()
    return order


@pytest.mark.asyncio
async def test_full_pipeline(pipeline_order):
    """Run full pipeline and verify all stages produce data."""
    await run_pipeline(TEST_ORDER_ID, TEST_ORG_ID, test_session_factory)

    async with test_session_factory() as db:
        # Order should be completed or review_required
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
        )).scalar_one()
        assert order.status in ("completed", "review_required")
        assert order.pipeline_stage is None

        # Source assignments should exist
        sources = (await db.execute(
            select(TASourceAssignment).where(TASourceAssignment.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(sources) >= 1

        # Raw documents should exist
        raw_docs = (await db.execute(
            select(TARawDocument).where(TARawDocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(raw_docs) >= 1

        # Parsed documents should exist
        docs = (await db.execute(
            select(TADocument).where(TADocument.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(docs) >= 1

        # Chain links should exist
        chain = (await db.execute(
            select(TAChainLink).where(TAChainLink.order_id == TEST_ORDER_ID)
        )).scalars().all()
        assert len(chain) >= 1

        # Package should exist
        pkg = (await db.execute(
            select(TAPackage).where(TAPackage.order_id == TEST_ORDER_ID)
        )).scalar_one_or_none()
        assert pkg is not None
        assert pkg.package_number.startswith("TA-")


@pytest.mark.asyncio
async def test_pipeline_with_non_digital_source(db_session: AsyncSession, seed_data):
    """Pipeline pauses at retrieve when non-digital source exists."""
    cs = TACountySource(
        county="Rural",
        state_code="IL",
        source_type="recorder",
        availability="non_digital",
        is_active=True,
    )
    db_session.add(cs)

    order_id = uuid.uuid4()
    order = TAOrder(
        id=order_id,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="456 Rural Rd, Rural, IL",
        county="Rural",
        state_code="IL",
        status="processing",
    )
    db_session.add(order)
    await db_session.commit()

    await run_pipeline(order_id, TEST_ORG_ID, test_session_factory)

    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_id)
        )).scalar_one()
        assert order.status == "awaiting_abstractor"


@pytest.mark.asyncio
async def test_pipeline_idempotent_retry(pipeline_order):
    """Running pipeline twice should not create duplicate data."""
    await run_pipeline(TEST_ORDER_ID, TEST_ORG_ID, test_session_factory)

    async with test_session_factory() as db:
        docs_count_1 = len((await db.execute(
            select(TADocument).where(TADocument.order_id == TEST_ORDER_ID)
        )).scalars().all())

    # Run again — parse/chain stages use delete-then-insert
    # Reset order status first
    async with test_session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
        )).scalar_one()
        order.status = "processing"
        order.pipeline_stage = "parse"
        await db.commit()

    # Re-run from parse stage manually
    from app.micro_apps.title_search.pipeline.orchestrator import STAGE_HANDLERS
    async with test_session_factory() as db:
        await STAGE_HANDLERS["parse"](TEST_ORDER_ID, TEST_ORG_ID, db)
        await db.commit()

        docs_count_2 = len((await db.execute(
            select(TADocument).where(TADocument.order_id == TEST_ORDER_ID)
        )).scalars().all())

    assert docs_count_1 == docs_count_2
