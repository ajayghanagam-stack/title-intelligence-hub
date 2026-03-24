import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


@pytest.mark.asyncio
async def test_readiness_score(client: AsyncClient, sample_pack_with_data):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/readiness",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert 0 <= data["score"] <= 100
    assert "status" in data
    assert data["status"] in ("ready", "at_risk", "not_ready")
    assert "categories" in data
    assert len(data["categories"]) == 5  # requirements, endorsements, liens, exceptions, consistency
    assert "checklist" in data
    assert "estimated_days" in data
    assert isinstance(data["estimated_days"], int)

    # Verify category structure
    for cat in data["categories"]:
        assert "category" in cat
        assert "weight" in cat
        assert "score" in cat
        assert "satisfied" in cat
        assert "total" in cat
        assert "details" in cat


@pytest.mark.asyncio
async def test_readiness_empty_pack(client: AsyncClient, sample_pack):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/readiness",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "categories" in data
    assert "checklist" in data
    assert "estimated_days" in data
    assert data["estimated_days"] == 0  # No open flags


@pytest.mark.asyncio
async def test_readiness_with_resolved_flags(client: AsyncClient, sample_pack_with_data, db_session):
    """Readiness improves when flags are resolved."""
    from app.micro_apps.title_intelligence.models.flag import Flag
    from sqlalchemy import select

    # Resolve the flag
    result = await db_session.execute(
        select(Flag).where(Flag.pack_id == TEST_PACK_ID)
    )
    flag = result.scalar_one()
    flag.status = "approved"
    await db_session.commit()

    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/readiness",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["estimated_days"] == 0  # No more open flags
