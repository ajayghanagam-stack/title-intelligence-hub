"""Tests for TSA order CRUD endpoints."""
import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.title_search.conftest import TEST_ORDER_ID


@pytest.mark.asyncio
async def test_create_order(client: AsyncClient, ts_app_and_subscription):
    response = await client.post(
        "/api/v1/apps/title-search/orders",
        json={
            "property_address": "456 Oak Ave, Chicago, IL 60601",
            "county": "Cook",
            "state_code": "IL",
        },
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["property_address"] == "456 Oak Ave, Chicago, IL 60601"
    assert data["county"] == "Cook"
    assert data["state_code"] == "IL"
    assert data["status"] == "pending"
    assert data["search_scope"] == "full"
    assert data["search_years"] == 60


@pytest.mark.asyncio
async def test_create_order_invalid_state(client: AsyncClient, ts_app_and_subscription):
    response = await client.post(
        "/api/v1/apps/title-search/orders",
        json={
            "property_address": "123 Main St",
            "county": "Test",
            "state_code": "XX",
        },
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_with_options(client: AsyncClient, ts_app_and_subscription):
    response = await client.post(
        "/api/v1/apps/title-search/orders",
        json={
            "property_address": "789 Elm St, Springfield, IL",
            "county": "Sangamon",
            "state_code": "IL",
            "parcel_number": "12-34-567-890",
            "search_scope": "current_owner",
            "search_years": 30,
        },
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["parcel_number"] == "12-34-567-890"
    assert data["search_scope"] == "current_owner"
    assert data["search_years"] == 30


@pytest.mark.asyncio
async def test_list_orders(client: AsyncClient, sample_order):
    response = await client.get(
        "/api/v1/apps/title-search/orders",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["property_address"] == "123 Main St, Springfield, IL 62701"


@pytest.mark.asyncio
async def test_list_orders_with_status_filter(client: AsyncClient, sample_order):
    response = await client.get(
        "/api/v1/apps/title-search/orders?status=pending",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1

    # Filter for non-existent status
    response = await client.get(
        "/api/v1/apps/title-search/orders?status=completed",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0


@pytest.mark.asyncio
async def test_get_order(client: AsyncClient, sample_order):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(TEST_ORDER_ID)
    assert data["county"] == "Sangamon"


@pytest.mark.asyncio
async def test_get_order_not_found(client: AsyncClient, ts_app_and_subscription):
    fake_id = uuid.uuid4()
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{fake_id}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_pending_order(client: AsyncClient, sample_order):
    response = await client.delete(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 204

    # Verify it's gone
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_non_pending_order_succeeds(client: AsyncClient, db_session, sample_order):
    """Orders can be deleted regardless of status."""
    from app.micro_apps.title_search.models.order import TAOrder
    from sqlalchemy import select

    result = await db_session.execute(
        select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
    )
    order = result.scalar_one()
    order.status = "processing"
    await db_session.commit()

    response = await client.delete(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_trigger_process(client: AsyncClient, sample_order):
    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/process",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["order_id"] == str(TEST_ORDER_ID)


@pytest.mark.asyncio
async def test_trigger_process_already_processing(client: AsyncClient, db_session, sample_order):
    from app.micro_apps.title_search.models.order import TAOrder
    from sqlalchemy import select

    result = await db_session.execute(
        select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
    )
    order = result.scalar_one()
    order.status = "processing"
    await db_session.commit()

    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/process",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_get_pipeline_status(client: AsyncClient, sample_order):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/pipeline",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == str(TEST_ORDER_ID)
    assert data["status"] == "pending"
    assert len(data["stages"]) == 6
    assert all(s["status"] == "pending" for s in data["stages"])
