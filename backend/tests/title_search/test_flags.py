"""Tests for flag and review endpoints."""
import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_search.conftest import TEST_ORDER_ID, TEST_FLAG_ID


@pytest.mark.asyncio
async def test_list_flags(client: AsyncClient, sample_order_with_data):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/flags",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["flags"]) >= 1
    assert "high" in data["counts"]
    # Flags should be sorted by severity
    assert data["flags"][0]["severity"] == "high"


@pytest.mark.asyncio
async def test_submit_review_approve(client: AsyncClient, sample_order_with_data):
    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/flags/{TEST_FLAG_ID}/review",
        json={"decision": "approve", "notes": "Verified mortgage satisfaction exists"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approve"
    assert data["flag_id"] == str(TEST_FLAG_ID)

    # Flag should now be resolved
    flags_resp = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/flags",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    flags = flags_resp.json()["flags"]
    resolved = [f for f in flags if f["id"] == str(TEST_FLAG_ID)]
    assert resolved[0]["status"] == "resolved"


@pytest.mark.asyncio
async def test_submit_review_reject(client: AsyncClient, sample_order_with_data):
    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/flags/{TEST_FLAG_ID}/review",
        json={"decision": "reject", "notes": "False positive"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "reject"


@pytest.mark.asyncio
async def test_submit_review_invalid_decision(client: AsyncClient, sample_order_with_data):
    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/flags/{TEST_FLAG_ID}/review",
        json={"decision": "invalid"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 422
