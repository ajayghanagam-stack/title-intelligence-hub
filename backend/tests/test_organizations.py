import pytest

from tests.conftest import TEST_ORG_ID


@pytest.mark.asyncio
async def test_create_organization(client):
    response = await client.post(
        "/api/v1/organizations",
        json={"name": "New Org", "slug": "new-org"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Org"
    assert data["slug"] == "new-org"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_organization(client):
    response = await client.get(
        f"/api/v1/organizations/{TEST_ORG_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Org"
    assert data["slug"] == "test-org"


@pytest.mark.asyncio
async def test_update_organization(client):
    response = await client.patch(
        f"/api/v1/organizations/{TEST_ORG_ID}",
        json={"name": "Updated Org"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Org"


@pytest.mark.asyncio
async def test_list_org_users(client):
    response = await client.get(
        f"/api/v1/organizations/{TEST_ORG_ID}/users",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    users = response.json()
    assert len(users) >= 1
    assert users[0]["email"] == "test@example.com"
