"""Tests for reviewer-authored extracted-field overrides.

The dashboard's per-field "Save" button persists a single value via
PUT /packages/{pid}/extractions/overrides; downloads merge these on top
of the AI-emitted extractions. Covers:

- Service: insert vs update on the composite key, opaque stack_id, delete
  rowcount, idempotent no-op delete.
- Routes: GET / PUT / DELETE happy path + tenant isolation via the
  micro-app subscription gate.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.extraction_override import (
    LOExtractionOverride,
)
from app.micro_apps.loan_onboarding.services import extraction_override_service
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


# ── Service-level ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_inserts_new_row(sample_package, db_session: AsyncSession):
    row = await extraction_override_service.upsert_override(
        db_session,
        TEST_ORG_ID,
        TEST_PACKAGE_ID,
        doc_type="URLA_1003",
        field_name="borrower_name",
        stack_id=str(uuid.uuid4()),
        value="Jane A. Smith",
        edited_by_id=TEST_USER_ID,
    )
    await db_session.commit()
    assert row.value == "Jane A. Smith"
    assert row.edited_by == TEST_USER_ID
    assert row.edited_at is not None


@pytest.mark.asyncio
async def test_upsert_updates_existing_row_in_place(
    sample_package, db_session: AsyncSession
):
    """Re-saves replace value+edited_at on the same row, not insert a new one."""
    stack_id = str(uuid.uuid4())
    first = await extraction_override_service.upsert_override(
        db_session,
        TEST_ORG_ID,
        TEST_PACKAGE_ID,
        doc_type="URLA_1003",
        field_name="loan_amount",
        stack_id=stack_id,
        value="350000",
        edited_by_id=TEST_USER_ID,
    )
    await db_session.commit()
    first_id = first.id

    second = await extraction_override_service.upsert_override(
        db_session,
        TEST_ORG_ID,
        TEST_PACKAGE_ID,
        doc_type="URLA_1003",
        field_name="loan_amount",
        stack_id=stack_id,
        value="375000",
        edited_by_id=TEST_USER_ID,
    )
    await db_session.commit()

    assert second.id == first_id
    assert second.value == "375000"

    # Verify no second row was inserted
    rows = (await db_session.execute(
        select(LOExtractionOverride).where(
            LOExtractionOverride.package_id == TEST_PACKAGE_ID
        )
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_upsert_accepts_placeholder_stack_id(
    sample_package, db_session: AsyncSession
):
    """`stack_id` is opaque — placeholder strings for unmatched rows must work."""
    row = await extraction_override_service.upsert_override(
        db_session,
        TEST_ORG_ID,
        TEST_PACKAGE_ID,
        doc_type="W2",
        field_name="employer_name",
        stack_id="placeholder-W2",
        value="Acme Corp",
        edited_by_id=TEST_USER_ID,
    )
    await db_session.commit()
    assert row.stack_id == "placeholder-W2"


@pytest.mark.asyncio
async def test_list_returns_saved_overrides(
    sample_package, db_session: AsyncSession
):
    sid = str(uuid.uuid4())
    await extraction_override_service.upsert_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        doc_type="URLA_1003", field_name="borrower_name", stack_id=sid,
        value="Jane Smith", edited_by_id=TEST_USER_ID,
    )
    await extraction_override_service.upsert_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        doc_type="W2", field_name="wages", stack_id="placeholder-W2",
        value="85000", edited_by_id=TEST_USER_ID,
    )
    await db_session.commit()

    rows = await extraction_override_service.list_overrides(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID
    )
    assert len(rows) == 2
    # Sorted by (doc_type, field_name, stack_id)
    assert rows[0].doc_type == "URLA_1003"
    assert rows[1].doc_type == "W2"


@pytest.mark.asyncio
async def test_delete_removes_row(sample_package, db_session: AsyncSession):
    sid = str(uuid.uuid4())
    await extraction_override_service.upsert_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        doc_type="URLA_1003", field_name="borrower_name", stack_id=sid,
        value="Jane", edited_by_id=TEST_USER_ID,
    )
    await db_session.commit()

    removed = await extraction_override_service.delete_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        doc_type="URLA_1003", field_name="borrower_name", stack_id=sid,
    )
    await db_session.commit()
    assert removed is True

    rows = await extraction_override_service.list_overrides(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID
    )
    assert rows == []


@pytest.mark.asyncio
async def test_delete_noop_returns_false(
    sample_package, db_session: AsyncSession
):
    """The Reset button calls delete unconditionally — no-op must succeed."""
    removed = await extraction_override_service.delete_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        doc_type="URLA_1003", field_name="borrower_name",
        stack_id="never-existed",
    )
    await db_session.commit()
    assert removed is False


# ── HTTP route coverage ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_route_creates_override(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    sid = str(uuid.uuid4())
    resp = await client.put(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS,
        json={
            "doc_type": "URLA_1003",
            "field_name": "borrower_name",
            "stack_id": sid,
            "value": "Jane Smith",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["doc_type"] == "URLA_1003"
    assert body["field_name"] == "borrower_name"
    assert body["stack_id"] == sid
    assert body["value"] == "Jane Smith"
    assert body["edited_by"] == str(TEST_USER_ID)


@pytest.mark.asyncio
async def test_put_route_updates_existing_override(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    sid = str(uuid.uuid4())
    payload = {
        "doc_type": "URLA_1003",
        "field_name": "loan_amount",
        "stack_id": sid,
        "value": "350000",
    }
    first = await client.put(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS, json=payload,
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    payload["value"] = "375000"
    second = await client.put(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS, json=payload,
    )
    assert second.status_code == 200
    assert second.json()["id"] == first_id
    assert second.json()["value"] == "375000"


@pytest.mark.asyncio
async def test_get_route_lists_overrides(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    sid = str(uuid.uuid4())
    await client.put(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS,
        json={
            "doc_type": "URLA_1003", "field_name": "borrower_name",
            "stack_id": sid, "value": "Jane",
        },
    )
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["value"] == "Jane"


@pytest.mark.asyncio
async def test_delete_route_removes_override(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    sid = str(uuid.uuid4())
    await client.put(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS,
        json={
            "doc_type": "URLA_1003", "field_name": "borrower_name",
            "stack_id": sid, "value": "Jane",
        },
    )
    resp = await client.request(
        "DELETE",
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS,
        json={
            "doc_type": "URLA_1003", "field_name": "borrower_name",
            "stack_id": sid,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"removed": True}

    # And it's gone from the list
    listing = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS,
    )
    assert listing.json() == []


@pytest.mark.asyncio
async def test_delete_route_idempotent_no_op(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    """The Reset button fires unconditionally — DELETE without an existing
    override returns 200 with `removed: false`, not 404."""
    resp = await client.request(
        "DELETE",
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers=HEADERS,
        json={
            "doc_type": "URLA_1003", "field_name": "borrower_name",
            "stack_id": "never-existed",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"removed": False}


@pytest.mark.asyncio
async def test_overrides_route_tenant_isolated(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    """Org B has no subscription to loan-onboarding → middleware 403s."""
    other_org_id = uuid.UUID("00000000-0000-0000-0000-00000000dead")
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/extractions/overrides",
        headers={"X-Org-Id": str(other_org_id)},
    )
    assert resp.status_code == 403
