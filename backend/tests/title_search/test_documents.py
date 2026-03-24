"""Tests for document list, filter, and correction endpoints."""
import pytest
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_search.conftest import TEST_ORDER_ID, TEST_DOCUMENT_ID


@pytest.mark.asyncio
async def test_list_documents(client: AsyncClient, sample_order_with_data):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/documents",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["doc_type"] == "deed"


@pytest.mark.asyncio
async def test_list_documents_filter_by_type(client: AsyncClient, sample_order_with_data):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/documents?doc_type=deed",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert len(response.json()) >= 1

    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/documents?doc_type=mortgage",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0


@pytest.mark.asyncio
async def test_list_documents_filter_needs_review(client: AsyncClient, sample_order_with_data):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/documents?needs_review=false",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert len(response.json()) >= 1

    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/documents?needs_review=true",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0


@pytest.mark.asyncio
async def test_correct_document(client: AsyncClient, sample_order_with_data):
    response = await client.patch(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/documents/{TEST_DOCUMENT_ID}",
        json={
            "grantor": {"names": ["John A. Smith"], "entity_type": "individual"},
            "consideration": 275000.00,
        },
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["grantor"]["names"] == ["John A. Smith"]
    assert data["consideration"] == 275000.00
    assert data["needs_review"] is False
