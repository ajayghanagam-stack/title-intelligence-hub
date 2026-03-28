import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


@pytest.mark.asyncio
async def test_pipeline_status(client: AsyncClient, sample_pack):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/pipeline",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pack_id"] == str(TEST_PACK_ID)
    assert "stages" in data
    assert len(data["stages"]) == 4


@pytest.mark.asyncio
async def test_extractions_empty(client: AsyncClient, sample_pack):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/extractions",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_extractions_with_data(client: AsyncClient, sample_pack_with_data):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/extractions",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["extraction_type"] == "party"
    assert data[0]["label"] == "Buyer"


@pytest.mark.asyncio
async def test_search(client: AsyncClient, sample_pack_with_data):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/search?q=sample",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "sample"
    assert len(data["results"]) >= 1
