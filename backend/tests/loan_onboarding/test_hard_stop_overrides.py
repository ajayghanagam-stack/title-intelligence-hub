"""Routes tests for the Phase 3.4 supervisor hard-stop override surface."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.hard_stop_override import LOHardStopOverride
from app.models.audit_event import AuditEvent
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID

BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


@pytest.mark.asyncio
async def test_create_override_records_row_and_audit(
    client: AsyncClient, sample_package, db_session: AsyncSession,
):
    r = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/hard-stops/missing_doc:paystub/override",
        json={"reason": "investor_waived", "note": "Borrower exempt per FHA waiver"},
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["hard_stop_key"] == "missing_doc:paystub"
    assert body["reason"] == "investor_waived"
    assert body["decision"] == "active"
    assert body["supervisor_id"] == str(TEST_USER_ID)

    # The persisted row matches.
    row = (await db_session.execute(
        select(LOHardStopOverride).where(LOHardStopOverride.id == uuid.UUID(body["id"]))
    )).scalar_one()
    assert row.note == "Borrower exempt per FHA waiver"
    assert row.org_id == TEST_ORG_ID

    # And an audit event was emitted.
    audit = (await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.action == "lo.hard_stop.override_recorded",
            AuditEvent.target_id == TEST_PACKAGE_ID,
        )
    )).scalar_one()
    assert audit.actor_id == TEST_USER_ID
    assert audit.metadata_["hard_stop_key"] == "missing_doc:paystub"
    assert audit.metadata_["reason"] == "investor_waived"


@pytest.mark.asyncio
async def test_create_override_unknown_package_404(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.post(
        f"{BASE}/packages/{uuid.uuid4()}/hard-stops/missing_doc:w2/override",
        json={"reason": "other"},
        headers=HEADERS,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_override_rejects_duplicate_active(
    client: AsyncClient, sample_package,
):
    payload = {"reason": "late_delivery", "note": "Doc arrived after lock"}
    r1 = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/hard-stops/missing_pages:stack:1/override",
        json=payload, headers=HEADERS,
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/hard-stops/missing_pages:stack:1/override",
        json=payload, headers=HEADERS,
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_create_override_rejects_invalid_reason(
    client: AsyncClient, sample_package,
):
    r = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/hard-stops/missing_doc:paystub/override",
        json={"reason": "made_up_reason"},
        headers=HEADERS,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_overrides_only_returns_active(
    client: AsyncClient, sample_package, db_session: AsyncSession,
):
    # Two active overrides + one reversed row that must be filtered out.
    db_session.add_all([
        LOHardStopOverride(
            org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
            hard_stop_key="missing_doc:paystub", supervisor_id=TEST_USER_ID,
            reason="business_exception", decision="active",
        ),
        LOHardStopOverride(
            org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
            hard_stop_key="missing_pages:stack:2", supervisor_id=TEST_USER_ID,
            reason="late_delivery", decision="active",
        ),
        LOHardStopOverride(
            org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
            hard_stop_key="missing_doc:w2", supervisor_id=TEST_USER_ID,
            reason="other", decision="reversed",
        ),
    ])
    await db_session.commit()

    r = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/hard-stops/overrides",
        headers=HEADERS,
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    keys = {row["hard_stop_key"] for row in rows}
    assert keys == {"missing_doc:paystub", "missing_pages:stack:2"}


@pytest.mark.asyncio
async def test_list_overrides_unknown_package_404(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.get(
        f"{BASE}/packages/{uuid.uuid4()}/hard-stops/overrides",
        headers=HEADERS,
    )
    assert r.status_code == 404
