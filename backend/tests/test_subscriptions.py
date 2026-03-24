import uuid

import pytest

from tests.conftest import TEST_ORG_ID, TEST_APP_ID


@pytest.mark.asyncio
async def test_list_subscriptions(client):
    response = await client.get(
        "/api/v1/subscriptions",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    # seed_data creates a TI subscription
    assert len(data) >= 1
    assert data[0]["app_id"] == str(TEST_APP_ID)


@pytest.mark.asyncio
async def test_disable_and_enable_subscription(client):
    # Get existing subscription
    list_resp = await client.get(
        "/api/v1/subscriptions",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    sub_id = list_resp.json()[0]["id"]

    # Disable
    disable_resp = await client.patch(
        f"/api/v1/subscriptions/{sub_id}/disable",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["status"] == "disabled"

    # Enable
    enable_resp = await client.patch(
        f"/api/v1/subscriptions/{sub_id}/enable",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert enable_resp.status_code == 200
    assert enable_resp.json()["status"] == "active"
