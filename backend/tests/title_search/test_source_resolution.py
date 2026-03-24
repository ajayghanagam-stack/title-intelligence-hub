"""Tests for source resolution and source assignment endpoints."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.services.source_service import resolve_sources
from tests.conftest import TEST_ORG_ID
from tests.title_search.conftest import TEST_ORDER_ID, TEST_COUNTY_SOURCE_ID


@pytest.mark.asyncio
async def test_resolve_sources_with_matching_county(
    db_session: AsyncSession, sample_order
):
    """When county sources exist, create matching assignments."""
    cs = TACountySource(
        id=TEST_COUNTY_SOURCE_ID,
        county="Sangamon",
        state_code="IL",
        source_type="recorder",
        availability="digital",
        is_active=True,
    )
    db_session.add(cs)
    await db_session.commit()

    assignments = await resolve_sources(
        db_session, TEST_ORG_ID, TEST_ORDER_ID, "Sangamon", "IL"
    )
    assert len(assignments) == 1
    assert assignments[0].source_type == "recorder"
    assert assignments[0].availability == "digital"
    assert assignments[0].portal_config_id == TEST_COUNTY_SOURCE_ID


@pytest.mark.asyncio
async def test_resolve_sources_no_matching_county(
    db_session: AsyncSession, sample_order
):
    """When no county sources exist, create a default digital mock assignment."""
    assignments = await resolve_sources(
        db_session, TEST_ORG_ID, TEST_ORDER_ID, "Sangamon", "IL"
    )
    assert len(assignments) == 1
    assert assignments[0].availability == "digital"
    assert assignments[0].portal_config_id is None


@pytest.mark.asyncio
async def test_list_source_assignments_endpoint(
    client: AsyncClient, db_session: AsyncSession, sample_order
):
    """Test the GET /orders/{orderId}/sources endpoint."""
    cs = TACountySource(
        county="Sangamon",
        state_code="IL",
        source_type="recorder",
        availability="digital",
        is_active=True,
    )
    db_session.add(cs)
    await db_session.commit()

    await resolve_sources(
        db_session, TEST_ORG_ID, TEST_ORDER_ID, "Sangamon", "IL"
    )

    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/sources",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["source_type"] == "recorder"
