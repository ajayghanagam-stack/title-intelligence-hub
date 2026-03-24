"""Tests for ground abstractor upload endpoint."""
import io
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from tests.conftest import TEST_ORG_ID
from tests.title_search.conftest import TEST_ORDER_ID, TEST_SOURCE_ASSIGNMENT_ID


@pytest.mark.asyncio
async def test_upload_pdf(client: AsyncClient, sample_order_with_data):
    """Test uploading a PDF to a source assignment."""
    pdf_content = b"%PDF-1.4 test content"

    with patch("app.micro_apps.title_search.routes.sources.get_storage") as mock_get:
        mock_storage = AsyncMock()
        mock_get.return_value = mock_storage

        response = await client.post(
            f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/sources/{TEST_SOURCE_ASSIGNMENT_ID}/upload",
            files={"file": ("test_deed.pdf", io.BytesIO(pdf_content), "application/pdf")},
            headers={"X-Org-Id": str(TEST_ORG_ID)},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["content_format"] == "pdf"
    assert data["order_id"] == str(TEST_ORDER_ID)


@pytest.mark.asyncio
async def test_upload_image(client: AsyncClient, sample_order_with_data):
    """Test uploading an image file."""
    image_content = b"\x89PNG\r\n\x1a\n test image"

    with patch("app.micro_apps.title_search.routes.sources.get_storage") as mock_get:
        mock_storage = AsyncMock()
        mock_get.return_value = mock_storage

        response = await client.post(
            f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/sources/{TEST_SOURCE_ASSIGNMENT_ID}/upload",
            files={"file": ("scan.png", io.BytesIO(image_content), "image/png")},
            headers={"X-Org-Id": str(TEST_ORG_ID)},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["content_format"] == "image"


@pytest.mark.asyncio
async def test_upload_invalid_extension(client: AsyncClient, sample_order_with_data):
    """Test rejecting invalid file type."""
    response = await client.post(
        f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/sources/{TEST_SOURCE_ASSIGNMENT_ID}/upload",
        files={"file": ("test.exe", io.BytesIO(b"malware"), "application/octet-stream")},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_spoofed_pdf_extension(client: AsyncClient, sample_order_with_data):
    """Test rejecting a file with .pdf extension but non-PDF content (magic byte check)."""
    fake_pdf = b"This is not a real PDF file"

    with patch("app.micro_apps.title_search.routes.sources.get_storage") as mock_get:
        mock_storage = AsyncMock()
        mock_get.return_value = mock_storage

        response = await client.post(
            f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/sources/{TEST_SOURCE_ASSIGNMENT_ID}/upload",
            files={"file": ("spoofed.pdf", io.BytesIO(fake_pdf), "application/pdf")},
            headers={"X-Org-Id": str(TEST_ORG_ID)},
        )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_spoofed_png_extension(client: AsyncClient, sample_order_with_data):
    """Test rejecting a file with .png extension but non-PNG content."""
    fake_png = b"not a real png image content"

    with patch("app.micro_apps.title_search.routes.sources.get_storage") as mock_get:
        mock_storage = AsyncMock()
        mock_get.return_value = mock_storage

        response = await client.post(
            f"/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/sources/{TEST_SOURCE_ASSIGNMENT_ID}/upload",
            files={"file": ("spoofed.png", io.BytesIO(fake_png), "image/png")},
            headers={"X-Org-Id": str(TEST_ORG_ID)},
        )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]
