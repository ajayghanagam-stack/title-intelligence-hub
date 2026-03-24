"""Tests for chain-of-title endpoint."""
import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_search.conftest import TEST_ORDER_ID


@pytest.mark.asyncio
async def test_get_chain(client: AsyncClient, sample_order_with_data):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/chain",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == str(TEST_ORDER_ID)
    assert len(data["chain_links"]) >= 1
    assert data["total_links"] >= 1
    # Our sample data has no gaps
    assert data["gap_count"] == 0
    assert data["chain_complete"] is True


@pytest.mark.asyncio
async def test_get_chain_empty(client: AsyncClient, sample_order):
    """Order with no chain links returns empty chain."""
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/chain",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_links"] == 0
    assert data["chain_complete"] is False
