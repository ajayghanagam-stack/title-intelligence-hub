import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID, TEST_FLAG_ID
from app.micro_apps.title_intelligence.models.flag import Flag
from app.models.audit_event import AuditEvent


@pytest.mark.asyncio
async def test_list_flags(client: AsyncClient, sample_pack_with_data):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["flags"]) == 1
    assert data["flags"][0]["flag_type"] == "unresolved_lien"
    assert data["counts"]["high"] == 1


@pytest.mark.asyncio
async def test_get_flag_detail(client: AsyncClient, sample_pack_with_data):
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags/{TEST_FLAG_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Outstanding Deed of Trust"
    assert data["severity"] == "high"


@pytest.mark.asyncio
async def test_submit_review(client: AsyncClient, sample_pack_with_data):
    response = await client.post(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags/{TEST_FLAG_ID}/review",
        json={"decision": "approve", "reason_code": "valid_concern", "notes": "Needs clearing"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approve"

    # Verify flag status updated
    response = await client.get(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags/{TEST_FLAG_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_submit_review_creates_audit_event(client: AsyncClient, sample_pack_with_data, db_session: AsyncSession):
    """Submitting a review creates an audit event."""
    await client.post(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags/{TEST_FLAG_ID}/review",
        json={"decision": "reject", "reason_code": "not_applicable"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == TEST_ORG_ID,
            AuditEvent.action == "flag_reject",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None
    assert event.target_type == "ti_flag"
    assert event.target_id == TEST_FLAG_ID


@pytest.mark.asyncio
async def test_review_nonexistent_flag(client: AsyncClient, sample_pack):
    """Reviewing a flag that doesn't exist returns 404."""
    fake_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/flags/{fake_id}/review",
        json={"decision": "approve", "reason_code": "ok"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 404
