"""Tests for billing / usage report endpoints."""

import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_search.models.order import TAOrder
from app.models.micro_app import MicroApp
from app.models.subscription import Subscription

from tests.conftest import (
    TEST_ORG_ID,
    TEST_USER_ID,
    TEST_APP_ID,
    TEST_AUTH_USER_ID,
    test_session_factory,
    get_test_settings,
)

TEST_TS_APP_ID = uuid.UUID("00000000-0000-0000-0000-000000002000")


@pytest_asyncio.fixture
async def billing_data(db_session: AsyncSession, seed_data):
    """Seed TI packs and TSA orders with varying statuses and dates."""
    # Create TSA micro app + subscription
    ts_app = MicroApp(
        id=TEST_TS_APP_ID,
        name="Title Search & Abstracting",
        slug="title-search",
        description="Automated county record searches",
        icon="search",
    )
    db_session.add(ts_app)
    sub = Subscription(
        org_id=TEST_ORG_ID,
        app_id=TEST_TS_APP_ID,
        status="active",
        purchased_at=datetime.now(timezone.utc),
        enabled_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)

    now = datetime.now(timezone.utc)

    pack_ids: list[uuid.UUID] = []
    # TI packs: 2 completed, 1 processing (all in current month)
    for i, status in enumerate(["completed", "completed", "processing"]):
        pack_id = uuid.uuid4()
        pack = Pack(
            id=pack_id,
            org_id=TEST_ORG_ID,
            name=f"Pack {i+1}",
            status=status,
            created_at=now - timedelta(days=i),
        )
        db_session.add(pack)
        pack_ids.append(pack_id)

    # Add PackFile records so filename details are populated
    for i, pack_id in enumerate(pack_ids):
        pf = PackFile(
            id=uuid.uuid4(),
            pack_id=pack_id,
            org_id=TEST_ORG_ID,
            filename=f"commitment_{i+1}.pdf",
            storage_path=f"{TEST_ORG_ID}/{pack_id}/files/commitment_{i+1}.pdf",
            file_size=1024 * (i + 1),
        )
        db_session.add(pf)

    # TI pack outside date range (90 days ago)
    old_pack = Pack(
        id=uuid.uuid4(),
        org_id=TEST_ORG_ID,
        name="Old Pack",
        status="completed",
        created_at=now - timedelta(days=90),
    )
    db_session.add(old_pack)

    # TSA orders: 1 completed, 1 pending (in current month)
    for i, status in enumerate(["completed", "pending"]):
        order = TAOrder(
            id=uuid.uuid4(),
            org_id=TEST_ORG_ID,
            created_by=TEST_USER_ID,
            property_address=f"123 Test St #{i+1}",
            status=status,
            created_at=now - timedelta(days=i),
        )
        db_session.add(order)

    await db_session.commit()
    return {"now": now}


@pytest.mark.asyncio
async def test_get_billing_unauthorized(db_session: AsyncSession, seed_data):
    """Non-admin users get 403 on billing endpoints."""
    from app.config import get_settings
    from app.core.auth import get_current_user
    from app.core.deps import get_db, require_platform_admin
    from app.main import create_app
    from fastapi import HTTPException

    app = create_app(session_factory_override=test_session_factory)

    async def override_db():
        yield db_session

    def override_settings():
        return get_test_settings()

    async def deny_platform_admin():
        raise HTTPException(status_code=403, detail="Not a platform admin")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[require_platform_admin] = deny_platform_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/admin/billing/{TEST_ORG_ID}")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_billing_default_dates(client, billing_data):
    """GET /admin/billing/{org_id} returns usage with default date range."""
    resp = await client.get(f"/api/v1/admin/billing/{TEST_ORG_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["org_id"] == str(TEST_ORG_ID)
    assert data["org_name"] == "Test Org"
    assert "start_date" in data
    assert "end_date" in data
    assert len(data["apps"]) >= 1


@pytest.mark.asyncio
async def test_get_billing_custom_dates(client, billing_data):
    """GET /admin/billing/{org_id} with explicit start/end dates."""
    now = billing_data["now"]
    start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    resp = await client.get(
        f"/api/v1/admin/billing/{TEST_ORG_ID}?start_date={start}&end_date={end}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["start_date"] == start
    assert data["end_date"] == end


@pytest.mark.asyncio
async def test_get_billing_nonexistent_org(client, billing_data):
    """GET /admin/billing/{org_id} returns 404 for unknown org."""
    fake_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/admin/billing/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_billing_pdf(client, billing_data):
    """GET /admin/billing/{org_id}/pdf returns a PDF."""
    resp = await client.get(f"/api/v1/admin/billing/{TEST_ORG_ID}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    # PDF starts with %PDF
    assert resp.content[:5] == b"%PDF-"


@pytest.mark.asyncio
async def test_billing_counts_completed_only(client, billing_data):
    """Completed count only includes status='completed' items."""
    now = billing_data["now"]
    start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    resp = await client.get(
        f"/api/v1/admin/billing/{TEST_ORG_ID}?start_date={start}&end_date={end}"
    )
    assert resp.status_code == 200
    data = resp.json()

    ti_app = next((a for a in data["apps"] if a["app_slug"] == "title-intelligence"), None)
    assert ti_app is not None
    assert ti_app["completed_count"] == 2  # 2 completed packs in range
    assert ti_app["total_count"] == 3  # 3 total packs in range (2 completed + 1 processing)

    tsa_app = next((a for a in data["apps"] if a["app_slug"] == "title-search"), None)
    assert tsa_app is not None
    assert tsa_app["completed_count"] == 1  # 1 completed order
    assert tsa_app["total_count"] == 2  # 2 total orders


@pytest.mark.asyncio
async def test_billing_includes_item_details(client, billing_data):
    """Usage response includes per-item details: TI filenames and TSA order names."""
    now = billing_data["now"]
    start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    resp = await client.get(
        f"/api/v1/admin/billing/{TEST_ORG_ID}?start_date={start}&end_date={end}"
    )
    assert resp.status_code == 200
    data = resp.json()

    # TI items should only include completed packs with filenames
    ti_app = next((a for a in data["apps"] if a["app_slug"] == "title-intelligence"), None)
    assert ti_app is not None
    assert len(ti_app["items"]) == 2  # only 2 completed packs (processing excluded)
    for item in ti_app["items"]:
        assert "name" in item
        assert item["status"] == "completed"
        assert "created_at" in item
        assert "filenames" in item
    # Each completed pack has one file
    filenames_flat = [fn for item in ti_app["items"] for fn in (item["filenames"] or [])]
    assert len(filenames_flat) == 2
    assert any("commitment_" in fn for fn in filenames_flat)

    # TSA items should only include completed orders
    tsa_app = next((a for a in data["apps"] if a["app_slug"] == "title-search"), None)
    assert tsa_app is not None
    assert len(tsa_app["items"]) == 1  # only 1 completed order (pending excluded)
    assert tsa_app["items"][0]["status"] == "completed"
    assert "123 Test St" in tsa_app["items"][0]["name"]


@pytest.mark.asyncio
async def test_billing_respects_date_range(client, billing_data):
    """Items outside the date range are excluded from counts."""
    now = billing_data["now"]
    # Use a narrow range that only includes items from the last 2 days
    start = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    resp = await client.get(
        f"/api/v1/admin/billing/{TEST_ORG_ID}?start_date={start}&end_date={end}"
    )
    assert resp.status_code == 200
    data = resp.json()

    ti_app = next((a for a in data["apps"] if a["app_slug"] == "title-intelligence"), None)
    assert ti_app is not None
    # The old pack (90 days ago) should be excluded
    assert ti_app["total_count"] <= 3
    # Completed count should be <= total
    assert ti_app["completed_count"] <= ti_app["total_count"]
