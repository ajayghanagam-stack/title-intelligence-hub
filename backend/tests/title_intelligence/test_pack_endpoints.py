import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


@pytest.mark.asyncio
async def test_create_pack(client: AsyncClient):
    response = await client.post(
        "/api/v1/apps/title-intelligence/packs",
        json={"name": "My Test Pack"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Test Pack"
    assert data["status"] == "uploading"
    assert data["org_id"] == str(TEST_ORG_ID)


@pytest.mark.asyncio
async def test_list_packs(client: AsyncClient, sample_pack):
    response = await client.get(
        "/api/v1/apps/title-intelligence/packs",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Test Title Pack"


@pytest.mark.asyncio
async def test_get_pack(client: AsyncClient, sample_pack):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(TEST_PACK_ID)
    assert data["name"] == "Test Title Pack"


@pytest.mark.asyncio
async def test_get_pack_not_found(client: AsyncClient):
    fake_id = uuid.uuid4()
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{fake_id}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_pack(client: AsyncClient, sample_pack):
    response = await client.delete(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 204

    # Verify it's gone
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 404
