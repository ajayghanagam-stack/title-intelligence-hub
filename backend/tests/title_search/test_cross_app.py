"""Tests for cross-app integration between TI and TSA."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.models.extraction import Extraction
from app.micro_apps.title_intelligence.models.flag import Flag as TIFlag
from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_intelligence.services.readiness_service import calculate_readiness
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

TEST_PACK_ID = uuid.UUID("00000000-0000-0000-0000-000000010000")
TEST_ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000100000")


@pytest_asyncio.fixture
async def ti_pack_with_linked_order(db_session: AsyncSession, seed_data):
    """Create a TI pack and a TSA order linked to it."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Title Pack",
        status="completed",
    )
    db_session.add(pack)
    await db_session.flush()

    order = TAOrder(
        id=TEST_ORDER_ID,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="123 Main St",
        county="Cook",
        state_code="IL",
        status="completed",
        linked_pack_id=TEST_PACK_ID,
    )
    db_session.add(order)

    # Add a TSA flag
    ta_flag = TAFlag(
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        flag_type="unreleased_mortgage",
        severity="high",
        title="Unreleased Mortgage",
        description="Test flag from title search",
        status="open",
    )
    db_session.add(ta_flag)

    await db_session.commit()
    return pack, order


@pytest.mark.asyncio
async def test_readiness_includes_title_search_category(
    db_session: AsyncSession, ti_pack_with_linked_order
):
    """TI readiness should include a title_search category when linked order has flags."""
    result = await calculate_readiness(db_session, TEST_ORG_ID, TEST_PACK_ID)

    # Find the title_search category
    ts_categories = [c for c in result.categories if c.category == "title_search"]
    assert len(ts_categories) == 1
    ts_cat = ts_categories[0]
    assert ts_cat.total >= 1
    assert ts_cat.satisfied < ts_cat.total  # Open flag = not all satisfied


@pytest.mark.asyncio
async def test_readiness_without_linked_order(db_session: AsyncSession, seed_data):
    """TI readiness should NOT include title_search category when no linked orders."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Unlinked Pack",
        status="completed",
    )
    db_session.add(pack)
    await db_session.commit()

    result = await calculate_readiness(db_session, TEST_ORG_ID, TEST_PACK_ID)

    ts_categories = [c for c in result.categories if c.category == "title_search"]
    assert len(ts_categories) == 0


@pytest.mark.asyncio
async def test_linked_pack_id_validation(client, ts_app_and_subscription, db_session):
    """Creating an order with invalid linked_pack_id should fail."""
    fake_pack_id = uuid.uuid4()
    response = await client.post(
        "/api/v1/apps/title-search/orders",
        json={
            "property_address": "123 Main St",
            "county": "Cook",
            "state_code": "IL",
            "linked_pack_id": str(fake_pack_id),
        },
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_linked_pack_id_valid(client, ts_app_and_subscription, db_session):
    """Creating an order with valid linked_pack_id should succeed."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Test Pack",
        status="completed",
    )
    db_session.add(pack)
    await db_session.commit()

    response = await client.post(
        "/api/v1/apps/title-search/orders",
        json={
            "property_address": "123 Main St",
            "county": "Cook",
            "state_code": "IL",
            "linked_pack_id": str(TEST_PACK_ID),
        },
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 201
    assert response.json()["linked_pack_id"] == str(TEST_PACK_ID)
