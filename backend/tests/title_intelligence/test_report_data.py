"""Tests for GET /report-data endpoint."""

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


@pytest.mark.asyncio
async def test_report_data_returns_expected_keys(client: AsyncClient, sample_pack_with_data):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/report-data",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()

    expected_keys = {
        "subtitle", "property_address", "commitment_number", "faf_file_number",
        "effective_date", "issued_date", "flags_by_severity", "total_open",
        "risk_assessment", "standard_exceptions", "specific_exceptions",
        "requirements", "warnings", "checklist_items",
    }
    assert expected_keys.issubset(data.keys())
    assert isinstance(data["standard_exceptions"], list)
    assert isinstance(data["specific_exceptions"], list)
    assert isinstance(data["requirements"], list)
    assert isinstance(data["warnings"], list)
    assert isinstance(data["checklist_items"], list)
    assert isinstance(data["flags_by_severity"], dict)
    assert data["total_open"] >= 0


@pytest.mark.asyncio
async def test_report_data_empty_pack(client: AsyncClient, sample_pack):
    """Report data for a pack with no extractions/flags still returns valid structure."""
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/report-data",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_open"] == 0
    assert data["standard_exceptions"] == []
    assert data["specific_exceptions"] == []
    assert data["requirements"] == []
    assert data["checklist_items"] == []


@pytest.mark.asyncio
async def test_report_data_reflects_flag_review(client: AsyncClient, sample_pack_with_data):
    """After reviewing a flag, report-data should reflect the change."""
    from tests.title_intelligence.conftest import TEST_FLAG_ID

    # Get initial report data
    resp1 = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/report-data",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    data1 = resp1.json()
    initial_open = data1["total_open"]
    assert initial_open >= 1

    # Review the flag (approve it)
    await client.post(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags/{TEST_FLAG_ID}/review",
        json={"decision": "approve", "reason_code": "acceptable_risk", "notes": "OK"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )

    # Report data should now show fewer open flags
    resp2 = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/report-data",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    data2 = resp2.json()
    assert data2["total_open"] < initial_open
