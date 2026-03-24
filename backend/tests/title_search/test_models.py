"""Tests for TSA model creation and app registration."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models import (
    TAOrder, TASourceAssignment, TARawDocument, TADocument,
    TAChainLink, TAFlag, TAReview, TAPackage, TACountySource,
)
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.title_search.conftest import (
    TEST_ORDER_ID, TEST_SOURCE_ASSIGNMENT_ID, TEST_RAW_DOC_ID,
    TEST_DOCUMENT_ID, TEST_CHAIN_LINK_ID, TEST_FLAG_ID, TEST_COUNTY_SOURCE_ID,
)


@pytest.mark.asyncio
async def test_order_creation(db_session: AsyncSession, seed_data):
    """Test TAOrder model instantiation and persistence."""
    order = TAOrder(
        id=TEST_ORDER_ID,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="123 Main St",
        county="Cook",
        state_code="IL",
    )
    db_session.add(order)
    await db_session.commit()

    result = await db_session.execute(
        select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
    )
    fetched = result.scalar_one()
    assert fetched.property_address == "123 Main St"
    assert fetched.county == "Cook"
    assert fetched.state_code == "IL"
    assert fetched.status == "pending"
    assert fetched.search_scope == "full"
    assert fetched.search_years == 60


@pytest.mark.asyncio
async def test_county_source_creation(db_session: AsyncSession):
    """Test TACountySource (non-tenant-scoped) model."""
    source = TACountySource(
        id=TEST_COUNTY_SOURCE_ID,
        county="Cook",
        state_code="IL",
        source_type="recorder",
        availability="digital",
        portal_url="https://recorder.cookcounty.gov",
        portal_type="api",
        search_config={"api_key": "test", "base_url": "https://api.example.com"},
        is_active=True,
    )
    db_session.add(source)
    await db_session.commit()

    result = await db_session.execute(
        select(TACountySource).where(TACountySource.id == TEST_COUNTY_SOURCE_ID)
    )
    fetched = result.scalar_one()
    assert fetched.county == "Cook"
    assert fetched.source_type == "recorder"
    assert fetched.search_config["api_key"] == "test"


@pytest.mark.asyncio
async def test_source_assignment_creation(db_session: AsyncSession, sample_order):
    """Test TASourceAssignment linked to order."""
    source = TASourceAssignment(
        id=TEST_SOURCE_ASSIGNMENT_ID,
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        source_type="recorder",
        availability="digital",
    )
    db_session.add(source)
    await db_session.commit()

    result = await db_session.execute(
        select(TASourceAssignment).where(TASourceAssignment.id == TEST_SOURCE_ASSIGNMENT_ID)
    )
    fetched = result.scalar_one()
    assert fetched.source_type == "recorder"
    assert fetched.status == "pending"


@pytest.mark.asyncio
async def test_document_chain(db_session: AsyncSession, sample_order_with_data):
    """Test full data chain: order → raw_doc → document → chain_link → flag."""
    # Verify document
    result = await db_session.execute(
        select(TADocument).where(TADocument.id == TEST_DOCUMENT_ID)
    )
    doc = result.scalar_one()
    assert doc.doc_type == "deed"
    assert doc.grantor["names"] == ["John Smith"]
    assert doc.confidence == 0.95

    # Verify chain link
    result = await db_session.execute(
        select(TAChainLink).where(TAChainLink.id == TEST_CHAIN_LINK_ID)
    )
    link = result.scalar_one()
    assert link.position == 1
    assert link.link_type == "conveyance"
    assert not link.is_gap

    # Verify flag
    result = await db_session.execute(
        select(TAFlag).where(TAFlag.id == TEST_FLAG_ID)
    )
    flag = result.scalar_one()
    assert flag.flag_type == "unreleased_mortgage"
    assert flag.severity == "high"


@pytest.mark.asyncio
async def test_package_creation(db_session: AsyncSession, sample_order):
    """Test TAPackage creation."""
    pkg = TAPackage(
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        package_number="TA-20260323-0001",
        status="draft",
        search_scope="full",
        years_covered=60,
        total_documents=5,
        chain_complete=True,
        open_flags_count=0,
    )
    db_session.add(pkg)
    await db_session.commit()

    result = await db_session.execute(
        select(TAPackage).where(TAPackage.order_id == TEST_ORDER_ID)
    )
    fetched = result.scalar_one()
    assert fetched.package_number == "TA-20260323-0001"
    assert fetched.chain_complete is True


@pytest.mark.asyncio
async def test_review_creation(db_session: AsyncSession, sample_order_with_data):
    """Test TAReview creation."""
    review = TAReview(
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        flag_id=TEST_FLAG_ID,
        reviewer_id=TEST_USER_ID,
        decision="approve",
        notes="Verified mortgage was satisfied",
    )
    db_session.add(review)
    await db_session.commit()

    result = await db_session.execute(
        select(TAReview).where(TAReview.order_id == TEST_ORDER_ID)
    )
    fetched = result.scalar_one()
    assert fetched.decision == "approve"


@pytest.mark.asyncio
async def test_app_discovery():
    """Test that the TSA micro app is discovered by the registry."""
    from app.micro_apps.registry import discover_micro_apps

    # Clear registry cache for fresh discovery
    from app.micro_apps import registry
    registry._registry.clear()

    apps = discover_micro_apps()
    assert "title-search" in apps
    app = apps["title-search"]
    assert app.slug == "title-search"
    assert app.name == "Title Search & Abstracting"
    assert len(app.get_models()) == 10
