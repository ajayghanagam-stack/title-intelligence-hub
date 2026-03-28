"""Test new order form fields: borrower_name, city, zip_code, order_reference, effective_date."""
import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.schemas.order import OrderCreate, OrderResponse
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.title_search.conftest import ts_app_and_subscription  # noqa: F401


ORDER_PAYLOAD = {
    "property_address": "870 Friendship Cir",
    "city": "Jacksonville",
    "zip_code": "32210",
    "county": "Hendry",
    "state_code": "FL",
    "borrower_name": "Derrick R. Pitts",
    "parcel_number": "012875-1145",
    "search_scope": "current_owner",
    "search_years": 60,
    "order_reference": "Test",
    "effective_date": "2026-03-28",
}


def test_schema_accepts_new_fields():
    """OrderCreate schema validates all new fields."""
    data = OrderCreate(**{**ORDER_PAYLOAD, "effective_date": date(2026, 3, 28)})
    assert data.city == "Jacksonville"
    assert data.zip_code == "32210"
    assert data.borrower_name == "Derrick R. Pitts"
    assert data.order_reference == "Test"
    assert data.effective_date == date(2026, 3, 28)


def test_schema_new_fields_optional():
    """New fields default to None when not provided."""
    data = OrderCreate(
        property_address="123 Main St",
        county="Test",
        state_code="FL",
    )
    assert data.city is None
    assert data.zip_code is None
    assert data.borrower_name is None
    assert data.order_reference is None
    assert data.effective_date is None


@pytest.mark.asyncio
async def test_order_model_persists_new_fields(db_session: AsyncSession, seed_data):
    """New fields are persisted to and read from the database."""
    order = TAOrder(
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="870 Friendship Cir",
        city="Jacksonville",
        zip_code="32210",
        county="Hendry",
        state_code="FL",
        borrower_name="Derrick R. Pitts",
        parcel_number="012875-1145",
        search_scope="current_owner",
        search_years=60,
        order_reference="Test",
        effective_date=date(2026, 3, 28),
        status="pending",
    )
    db_session.add(order)
    await db_session.commit()

    row = (await db_session.execute(
        select(TAOrder).where(TAOrder.id == order.id)
    )).scalar_one()

    assert row.city == "Jacksonville"
    assert row.zip_code == "32210"
    assert row.borrower_name == "Derrick R. Pitts"
    assert row.order_reference == "Test"
    assert str(row.effective_date) == "2026-03-28"


@pytest.mark.asyncio
async def test_order_response_includes_new_fields(db_session: AsyncSession, seed_data):
    """OrderResponse serializes new fields correctly."""
    order = TAOrder(
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="870 Friendship Cir",
        city="Jacksonville",
        zip_code="32210",
        county="Hendry",
        state_code="FL",
        borrower_name="Derrick R. Pitts",
        order_reference="Loan-12345",
        effective_date=date(2026, 3, 28),
        status="pending",
    )
    db_session.add(order)
    await db_session.commit()

    resp = OrderResponse.model_validate(order)
    assert resp.city == "Jacksonville"
    assert resp.zip_code == "32210"
    assert resp.borrower_name == "Derrick R. Pitts"
    assert resp.order_reference == "Loan-12345"
    assert resp.effective_date == date(2026, 3, 28)


ORG_HEADER = {"X-Org-Id": str(TEST_ORG_ID)}


@pytest.mark.asyncio
async def test_create_order_endpoint(client: AsyncClient, ts_app_and_subscription):
    """POST /orders accepts and returns all new fields."""
    resp = await client.post(
        "/api/v1/apps/title-search/orders",
        json=ORDER_PAYLOAD,
        headers=ORG_HEADER,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["borrower_name"] == "Derrick R. Pitts"
    assert data["city"] == "Jacksonville"
    assert data["zip_code"] == "32210"
    assert data["order_reference"] == "Test"
    assert data["effective_date"] == "2026-03-28"
    assert data["search_scope"] == "current_owner"


@pytest.mark.asyncio
async def test_get_order_returns_new_fields(client: AsyncClient, ts_app_and_subscription):
    """GET /orders/{id} returns all new fields."""
    create_resp = await client.post(
        "/api/v1/apps/title-search/orders",
        json=ORDER_PAYLOAD,
        headers=ORG_HEADER,
    )
    assert create_resp.status_code == 201
    order_id = create_resp.json()["id"]

    get_resp = await client.get(
        f"/api/v1/apps/title-search/orders/{order_id}",
        headers=ORG_HEADER,
    )
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["borrower_name"] == "Derrick R. Pitts"
    assert data["city"] == "Jacksonville"
    assert data["zip_code"] == "32210"
    assert data["order_reference"] == "Test"
    assert data["effective_date"] == "2026-03-28"


@pytest.mark.asyncio
async def test_list_orders_includes_borrower(client: AsyncClient, ts_app_and_subscription):
    """GET /orders list includes borrower_name."""
    await client.post(
        "/api/v1/apps/title-search/orders",
        json=ORDER_PAYLOAD,
        headers=ORG_HEADER,
    )
    resp = await client.get(
        "/api/v1/apps/title-search/orders",
        headers=ORG_HEADER,
    )
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) >= 1
    assert orders[0]["borrower_name"] == "Derrick R. Pitts"
