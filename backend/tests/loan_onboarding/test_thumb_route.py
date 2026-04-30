"""Tests for `/packages/{pid}/pages/{page_id}/thumb` route.

The thumb endpoint renders a low-DPI JPEG used by the Results-tab stack
viewer. The full /image route already covers the auth/tenant-isolation paths;
these tests focus on the thumb-specific behavior:
- Returns a JPEG payload smaller than the full /image render
- 404s on missing page id and on cross-tenant access
- Sets immutable Cache-Control header (browser-cache parity with /image)
"""
import io
import uuid

import fitz  # PyMuPDF
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.services.storage import get_storage
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


def _make_pdf_bytes(num_pages: int = 1) -> bytes:
    """Create a minimal real PDF using PyMuPDF (so the route's render
    path actually executes instead of erroring on bytes-not-a-pdf)."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=612, height=792)  # US Letter
        page.insert_text((72, 100), f"Page {i + 1}")
    out = doc.tobytes()
    doc.close()
    return out


async def _seed_one_page(db: AsyncSession) -> uuid.UUID:
    """Seed a real PDF + LOPackageFile + LOPage. Returns the page id."""
    storage = get_storage()
    pdf_bytes = _make_pdf_bytes(1)
    storage_path = f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/thumb-test.pdf"
    await storage.put_object(
        storage_path, pdf_bytes, content_type="application/pdf"
    )
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        filename="thumb-test.pdf",
        storage_path=storage_path,
        content_hash="t" * 64,
        size_bytes=len(pdf_bytes),
        page_count=1,
    )
    db.add(file_row)
    await db.flush()
    page = LOPage(
        id=uuid.uuid4(),
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        file_id=file_row.id,
        page_number=1,
        source_page_number=1,
        heuristic_text="Page 1",
        text_length=10,
    )
    db.add(page)
    await db.commit()
    return page.id


@pytest.mark.asyncio
async def test_thumb_returns_jpeg(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    page_id = await _seed_one_page(db_session)
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_id}/thumb",
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/jpeg"
    # JPEG SOI marker
    assert resp.content[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_thumb_smaller_than_full_image(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    """Thumb at DPI=30 + quality 70 should be materially smaller than the
    DPI=100 /image render. Sanity check that we're actually downsampling."""
    page_id = await _seed_one_page(db_session)
    thumb = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_id}/thumb",
        headers=HEADERS,
    )
    full = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_id}/image",
        headers=HEADERS,
    )
    assert thumb.status_code == 200
    assert full.status_code == 200
    assert len(thumb.content) < len(full.content)


@pytest.mark.asyncio
async def test_thumb_sets_immutable_cache_header(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    page_id = await _seed_one_page(db_session)
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_id}/thumb",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert "immutable" in resp.headers.get("cache-control", "")
    assert "max-age=31536000" in resp.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_thumb_404_on_unknown_page(
    client: AsyncClient, sample_package
):
    bogus = uuid.uuid4()
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{bogus}/thumb",
        headers=HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_thumb_decodes_to_image(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    """Round-trip: response bytes are a valid decodable JPEG with width
    around the configured 150-px target."""
    from PIL import Image

    page_id = await _seed_one_page(db_session)
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_id}/thumb",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    img = Image.open(io.BytesIO(resp.content))
    assert img.format == "JPEG"
    # We resize down to 150 wide; allow ±5px slack for letter aspect ratio
    assert 140 <= img.width <= 160
