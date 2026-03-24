import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent
from tests.conftest import TEST_ORG_ID
from tests.title_intelligence.conftest import TEST_PACK_ID


# Minimal valid PDF (just the header + minimal structure)
VALID_PDF = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\nxref\n0 3\ntrailer<</Size 3/Root 1 0 R>>\nstartxref\n0\n%%EOF"

INVALID_FILE = b"This is not a PDF file at all."


@pytest.mark.asyncio
async def test_upload_valid_pdf(client: AsyncClient, sample_pack):
    """Upload a valid PDF to a pack."""
    # Change pack status to "uploading" so it accepts files
    response = await client.post(
        "/api/v1/apps/title-intelligence/packs",
        json={"name": "Upload Test Pack"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 201
    pack_id = response.json()["id"]

    response = await client.post(
        f"/api/v1/apps/title-intelligence/packs/{pack_id}/files",
        files={"files": ("test.pdf", io.BytesIO(VALID_PDF), "application/pdf")},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["files"]) == 1
    assert data["files"][0]["filename"] == "test.pdf"


@pytest.mark.asyncio
async def test_upload_invalid_extension(client: AsyncClient):
    """Reject non-PDF file extension."""
    response = await client.post(
        "/api/v1/apps/title-intelligence/packs",
        json={"name": "Extension Test"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    pack_id = response.json()["id"]

    response = await client.post(
        f"/api/v1/apps/title-intelligence/packs/{pack_id}/files",
        files={"files": ("test.txt", io.BytesIO(INVALID_FILE), "text/plain")},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 400
    assert "Only PDF files" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_invalid_magic_bytes(client: AsyncClient):
    """Reject file with .pdf extension but invalid content."""
    response = await client.post(
        "/api/v1/apps/title-intelligence/packs",
        json={"name": "Magic Bytes Test"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    pack_id = response.json()["id"]

    response = await client.post(
        f"/api/v1/apps/title-intelligence/packs/{pack_id}/files",
        files={"files": ("fake.pdf", io.BytesIO(INVALID_FILE), "application/pdf")},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 400
    assert "not a valid PDF" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_to_nonexistent_pack(client: AsyncClient):
    """Upload to a pack that doesn't exist."""
    fake_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/apps/title-intelligence/packs/{fake_id}/files",
        files={"files": ("test.pdf", io.BytesIO(VALID_PDF), "application/pdf")},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_process_already_processing(client: AsyncClient, sample_pack, db_session):
    """Cannot start processing on a pack that's already processing."""
    from app.micro_apps.title_intelligence.models.pack import Pack
    from sqlalchemy import select

    # Set pack to processing status
    result = await db_session.execute(select(Pack).where(Pack.id == TEST_PACK_ID))
    pack = result.scalar_one()
    pack.status = "processing"
    await db_session.commit()

    response = await client.post(
        f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/process",
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    assert response.status_code == 409
    assert "already being processed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_creates_audit_event(client: AsyncClient, db_session: AsyncSession):
    """Uploading files creates a files_uploaded audit event."""
    response = await client.post(
        "/api/v1/apps/title-intelligence/packs",
        json={"name": "Audit Upload Test"},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )
    pack_id = response.json()["id"]

    await client.post(
        f"/api/v1/apps/title-intelligence/packs/{pack_id}/files",
        files={"files": ("audit.pdf", io.BytesIO(VALID_PDF), "application/pdf")},
        headers={"X-Org-Id": str(TEST_ORG_ID)},
    )

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == TEST_ORG_ID,
            AuditEvent.action == "files_uploaded",
            AuditEvent.target_id == uuid.UUID(pack_id),
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None
    assert event.target_type == "ti_pack"
    assert event.metadata_["file_count"] == 1
    assert "audit.pdf" in event.metadata_["filenames"]


@pytest.mark.asyncio
async def test_process_creates_audit_event(client: AsyncClient, sample_pack, db_session: AsyncSession):
    """Triggering pipeline processing creates a pipeline_started audit event."""
    from unittest.mock import AsyncMock, patch
    from app.micro_apps.title_intelligence.models.pack import Pack

    # Set pack to uploadable state
    result = await db_session.execute(select(Pack).where(Pack.id == TEST_PACK_ID))
    pack = result.scalar_one()
    pack.status = "uploading"
    await db_session.commit()

    with patch(
        "app.micro_apps.title_intelligence.routes.packs.trigger_pipeline",
        new_callable=AsyncMock,
    ):
        response = await client.post(
            f"/api/v1/apps/title-intelligence/packs/{TEST_PACK_ID}/process",
            headers={"X-Org-Id": str(TEST_ORG_ID)},
        )
    assert response.status_code == 202

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == TEST_ORG_ID,
            AuditEvent.action == "pipeline_started",
            AuditEvent.target_id == TEST_PACK_ID,
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None
    assert event.target_type == "ti_pack"
