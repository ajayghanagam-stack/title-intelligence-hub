"""Tests for Loan Onboarding package CRUD + upload + process endpoints."""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID

BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


def _make_create_body(**overrides):
    body = {
        "name": "Test Loan Package",
        "borrower_name": "John Doe",
        "loan_reference": "LN-9001",
        "hitl_threshold": 0.8,
        "doc_types": [
            {"key": "URLA_1003", "label": "1003", "required": True},
            {"key": "PAYSTUB", "label": "Pay Stub", "required": True},
        ],
        "validation_rules": [
            {
                "rule_source": "preset",
                "rule_id": "missing_signatures",
                "config": {},
                "enabled": True,
            },
            {
                "rule_source": "custom",
                "rule_id": "income-consistency",
                "description": "Borrower income on 1003 should match paystub YTD within 10%",
                "config": {},
                "enabled": True,
            },
        ],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_app_root_advertises_ready(client: AsyncClient, lo_app_and_subscription):
    r = await client.get(f"{BASE}/", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {"app": "Loan Onboarding", "status": "ready"}


@pytest.mark.asyncio
async def test_create_package(client: AsyncClient, lo_app_and_subscription, db_session: AsyncSession):
    r = await client.post(f"{BASE}/packages", json=_make_create_body(), headers=HEADERS)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "Test Loan Package"
    assert data["borrower_name"] == "John Doe"
    assert data["hitl_threshold"] == 0.8
    assert data["status"] == "uploading"
    assert data["org_id"] == str(TEST_ORG_ID)

    # Rules were persisted
    rules = (await db_session.execute(select(LOValidationRule))).scalars().all()
    assert len(rules) == 2
    assert {r.rule_id for r in rules} == {"missing_signatures", "income-consistency"}


@pytest.mark.asyncio
async def test_create_package_rejects_empty_doc_types(client: AsyncClient, lo_app_and_subscription):
    body = _make_create_body(doc_types=[])
    r = await client.post(f"{BASE}/packages", json=body, headers=HEADERS)
    # Pydantic min_length=1 → 422
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_package_rejects_duplicate_doc_type_keys(
    client: AsyncClient, lo_app_and_subscription
):
    body = _make_create_body(doc_types=[
        {"key": "URLA_1003", "label": "1003", "required": True},
        {"key": "URLA_1003", "label": "Duplicate", "required": False},
    ])
    r = await client.post(f"{BASE}/packages", json=body, headers=HEADERS)
    assert r.status_code == 400
    assert "Duplicate" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_package_rejects_reserved_others_key(
    client: AsyncClient, lo_app_and_subscription
):
    body = _make_create_body(doc_types=[
        {"key": "others", "label": "Others", "required": False},
    ])
    r = await client.post(f"{BASE}/packages", json=body, headers=HEADERS)
    assert r.status_code == 400
    assert "Others" in r.json()["detail"]


@pytest.mark.asyncio
async def test_list_packages(client: AsyncClient, sample_package):
    r = await client.get(f"{BASE}/packages", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert any(p["id"] == str(TEST_PACKAGE_ID) for p in data)


@pytest.mark.asyncio
async def test_list_packages_filters_by_status(client: AsyncClient, sample_package):
    r = await client.get(f"{BASE}/packages?status=uploading", headers=HEADERS)
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.get(f"{BASE}/packages?status=completed", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_package(client: AsyncClient, sample_package):
    r = await client.get(f"{BASE}/packages/{TEST_PACKAGE_ID}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["id"] == str(TEST_PACKAGE_ID)


@pytest.mark.asyncio
async def test_get_package_not_found(client: AsyncClient, lo_app_and_subscription):
    fake = uuid.uuid4()
    r = await client.get(f"{BASE}/packages/{fake}", headers=HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_package(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    r = await client.delete(f"{BASE}/packages/{TEST_PACKAGE_ID}", headers=HEADERS)
    assert r.status_code == 204

    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one_or_none()
    assert pkg is None
    # Note: ON DELETE CASCADE is enforced by PostgreSQL in production; SQLite in
    # tests does not enforce FK cascade by default. See migration for cascade setup.


@pytest.mark.asyncio
async def test_process_package_moves_to_processing(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    r = await client.post(f"{BASE}/packages/{TEST_PACKAGE_ID}/process", headers=HEADERS)
    assert r.status_code == 202

    await db_session.refresh(sample_package)
    assert sample_package.status == "processing"
    assert sample_package.pipeline_stage == "ingest"


@pytest.mark.asyncio
async def test_process_package_rejects_already_processing(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    sample_package.status = "processing"
    await db_session.commit()
    r = await client.post(f"{BASE}/packages/{TEST_PACKAGE_ID}/process", headers=HEADERS)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pipeline_status_endpoint(client: AsyncClient, sample_package):
    r = await client.get(f"{BASE}/packages/{TEST_PACKAGE_ID}/pipeline", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["package_id"] == str(TEST_PACKAGE_ID)
    assert data["status"] == "uploading"


@pytest.mark.asyncio
async def test_upload_file(
    client: AsyncClient, sample_package, db_session: AsyncSession, tmp_path
):
    # Minimal valid-ish PDF header — pymupdf will handle (page_count may be 0)
    pdf_bytes = b"%PDF-1.4\n%%EOF\n"
    files = {"files": ("loan.pdf", pdf_bytes, "application/pdf")}
    r = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/files", files=files, headers=HEADERS
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert len(data) == 1
    assert data[0]["filename"] == "loan.pdf"
    assert data[0]["size_bytes"] == len(pdf_bytes)

    rows = (await db_session.execute(
        select(LOPackageFile).where(LOPackageFile.package_id == TEST_PACKAGE_ID)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].content_hash is not None


@pytest.mark.asyncio
async def test_upload_rejects_non_pdf(client: AsyncClient, sample_package):
    files = {"files": ("loan.txt", b"not a pdf", "text/plain")}
    r = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/files", files=files, headers=HEADERS
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(client: AsyncClient, sample_package):
    files = {"files": ("empty.pdf", b"", "application/pdf")}
    r = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/files", files=files, headers=HEADERS
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_tenant_isolation(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    """A package owned by org A must not be readable by org B."""
    other_org_id = uuid.UUID("00000000-0000-0000-0000-00000000dead")
    r = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}",
        headers={"X-Org-Id": str(other_org_id)},
    )
    # Org B has no subscription → middleware blocks with 403
    assert r.status_code == 403
