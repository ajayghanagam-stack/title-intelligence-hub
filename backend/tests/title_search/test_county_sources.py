"""Tests for county source admin CRUD endpoints."""
import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID


@pytest.mark.asyncio
async def test_create_county_source(client: AsyncClient, ts_app_and_subscription):
    response = await client.post(
        "/api/v1/apps/title-search/admin/county-sources",
        json={
            "county": "Cook",
            "state_code": "IL",
            "source_type": "recorder",
            "availability": "digital",
            "portal_url": "https://recorder.cookcounty.gov",
            "portal_type": "api",
            "search_config": {"api_key": "secret123", "base_url": "https://api.example.com"},
        },
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["county"] == "Cook"
    assert data["state_code"] == "IL"
    assert data["source_type"] == "recorder"
    # Credentials should be masked
    assert data["search_config"]["api_key"] == "***MASKED***"
    assert data["search_config"]["base_url"] == "https://api.example.com"


@pytest.mark.asyncio
async def test_create_duplicate_county_source(client: AsyncClient, ts_app_and_subscription):
    payload = {
        "county": "DuPage",
        "state_code": "IL",
        "source_type": "recorder",
    }
    response = await client.post(
        "/api/v1/apps/title-search/admin/county-sources",
        json=payload,
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 201

    response = await client.post(
        "/api/v1/apps/title-search/admin/county-sources",
        json=payload,
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_county_sources(client: AsyncClient, ts_app_and_subscription):
    # Create two sources
    for source_type in ["recorder", "clerk"]:
        await client.post(
            "/api/v1/apps/title-search/admin/county-sources",
            json={
                "county": "Cook",
                "state_code": "IL",
                "source_type": source_type,
            },
            headers={"X-Org-Id": str(TEST_ORG_ID)},
        )

    response = await client.get(
        "/api/v1/apps/title-search/admin/county-sources",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_list_county_sources_with_filter(client: AsyncClient, ts_app_and_subscription):
    await client.post(
        "/api/v1/apps/title-search/admin/county-sources",
        json={"county": "Cook", "state_code": "IL", "source_type": "recorder"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    await client.post(
        "/api/v1/apps/title-search/admin/county-sources",
        json={"county": "Harris", "state_code": "TX", "source_type": "recorder"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )

    response = await client.get(
        "/api/v1/apps/title-search/admin/county-sources?state_code=IL",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert all(s["state_code"] == "IL" for s in data)


@pytest.mark.asyncio
async def test_update_county_source(client: AsyncClient, ts_app_and_subscription):
    create_resp = await client.post(
        "/api/v1/apps/title-search/admin/county-sources",
        json={"county": "Lake", "state_code": "IL", "source_type": "recorder"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    source_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/v1/apps/title-search/admin/county-sources/{source_id}",
        json={"availability": "partial", "is_active": False},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["availability"] == "partial"
    assert data["is_active"] is False
