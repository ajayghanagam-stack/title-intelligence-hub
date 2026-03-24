"""Tests for package endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.package import TAPackage
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.title_search.conftest import TEST_ORDER_ID


@pytest_asyncio.fixture
async def sample_package(db_session: AsyncSession, sample_order_with_data):
    """Create a sample draft package."""
    pkg = TAPackage(
        org_id=TEST_ORG_ID,
        order_id=TEST_ORDER_ID,
        package_number="TA-20260323-0001",
        status="draft",
        search_scope="full",
        years_covered=60,
        total_documents=1,
        chain_complete=True,
        open_flags_count=1,
        property_summary={
            "address": "123 Main St, Springfield, IL 62701",
            "county": "Sangamon",
            "state": "IL",
        },
    )
    db_session.add(pkg)
    await db_session.commit()
    return pkg


@pytest.mark.asyncio
async def test_get_package(client: AsyncClient, sample_package):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["package_number"] == "TA-20260323-0001"
    assert data["status"] == "draft"
    assert data["chain_complete"] is True


@pytest.mark.asyncio
async def test_get_package_not_found(client: AsyncClient, sample_order):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_issue_package(client: AsyncClient, sample_package):
    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package/issue",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "issued"
    assert data["issued_by"] == "manual"
    assert data["issued_at"] is not None


@pytest.mark.asyncio
async def test_issue_already_issued(client: AsyncClient, db_session, sample_package):
    sample_package.status = "issued"
    await db_session.commit()

    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package/issue",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_download_package_pdf(client: AsyncClient, sample_package):
    response = await client.get(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package/pdf",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    # PDF should start with %PDF
    assert response.content[:5] == b"%PDF-"
