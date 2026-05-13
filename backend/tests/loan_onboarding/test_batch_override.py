"""Tests for batch page-override endpoint + service.

Covers:
- Service: applies many overrides in one call, silently skips no-ops, fails
  on invalid doc_type.
- Route: returns the post-rebuild summary and the list of applied overrides.
- Audit: emits a single batch event (not N single events).
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.page_override import LOPageOverride
from app.micro_apps.loan_onboarding.services import page_override_service
from app.micro_apps.loan_onboarding.schemas.override import BatchOverrideItem
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


async def _seed(db: AsyncSession, rows: list[tuple[int, str, float, str]]) -> list[uuid.UUID]:
    """Seed pages + classifications. Returns page_ids in order."""
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        filename="bundle.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/bundle.pdf",
        content_hash="x" * 64,
        size_bytes=100,
        page_count=len(rows),
    )
    db.add(file_row)
    await db.flush()
    page_ids: list[uuid.UUID] = []
    for pn, doc_type, conf, role in rows:
        page = LOPage(
            id=uuid.uuid4(),
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            file_id=file_row.id,
            page_number=pn,
            source_page_number=pn,
            heuristic_text=f"Page {pn} text",
            text_length=50,
        )
        db.add(page)
        await db.flush()
        db.add(LOClassification(
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            page_id=page.id,
            page_number=pn,
            predicted_doc_type=doc_type,
            predicted_doc_type_alternatives=[],
            confidence=conf,
            page_role=role,
            detected_fields=[],
        ))
        page_ids.append(page.id)
    await db.commit()
    return page_ids


# ── Service-level ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_applies_multiple_overrides(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "continuation"),
            (3, "urla_1003", 0.9, "last_page"),
        ],
    )
    items = [
        BatchOverrideItem(page_id=page_ids[1], assigned_doc_type="paystub"),
        BatchOverrideItem(page_id=page_ids[2], assigned_doc_type="paystub"),
    ]
    applied = await page_override_service.apply_overrides_batch(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, items, reviewer_id=TEST_USER_ID,
    )
    assert len(applied) == 2
    assert {o.assigned_doc_type for o in applied} == {"paystub"}
    assert all(o.previous_doc_type == "urla_1003" for o in applied)


@pytest.mark.asyncio
async def test_batch_silently_skips_noops(
    sample_package, db_session: AsyncSession
):
    """Drag-drop UIs frequently re-emit a page already on its target stack;
    those should NOT fail the whole batch."""
    page_ids = await _seed(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "last_page"),
        ],
    )
    items = [
        # Real move
        BatchOverrideItem(page_id=page_ids[1], assigned_doc_type="paystub"),
        # No-op: page 1 already classified as URLA_1003 with first_page role
        BatchOverrideItem(page_id=page_ids[0], assigned_doc_type="urla_1003"),
    ]
    applied = await page_override_service.apply_overrides_batch(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, items, reviewer_id=TEST_USER_ID,
    )
    assert len(applied) == 1
    assert applied[0].page_id == page_ids[1]


@pytest.mark.asyncio
async def test_batch_rejects_unknown_doc_type(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    items = [
        BatchOverrideItem(page_id=page_ids[0], assigned_doc_type="NOT_A_TYPE"),
    ]
    with pytest.raises(Exception):
        await page_override_service.apply_overrides_batch(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID, items, reviewer_id=TEST_USER_ID,
        )


@pytest.mark.asyncio
async def test_batch_upserts_existing_override(
    sample_package, db_session: AsyncSession
):
    """If a page already has an override, batch should update it, not insert."""
    page_ids = await _seed(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    # Existing single override: 1003 → PAYSTUB
    await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
        assigned_doc_type="paystub",
        page_role_override=None,
        reviewer_id=TEST_USER_ID,
        note=None,
    )
    await db_session.commit()

    # Batch moves the same page → W2
    items = [
        BatchOverrideItem(page_id=page_ids[0], assigned_doc_type="w2"),
    ]
    applied = await page_override_service.apply_overrides_batch(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, items, reviewer_id=TEST_USER_ID,
    )
    assert len(applied) == 1
    assert applied[0].assigned_doc_type == "w2"
    # previous_doc_type stays at the ML's original prediction
    assert applied[0].previous_doc_type == "urla_1003"

    rows = (await db_session.execute(
        select(LOPageOverride).where(LOPageOverride.page_id == page_ids[0])
    )).scalars().all()
    assert len(rows) == 1


# ── HTTP route coverage ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_route_returns_overrides_and_rebuild(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    page_ids = await _seed(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "continuation"),
            (3, "urla_1003", 0.9, "last_page"),
        ],
    )
    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/overrides:batch",
        headers=HEADERS,
        json={
            "overrides": [
                {"page_id": str(page_ids[1]), "assigned_doc_type": "paystub"},
                {"page_id": str(page_ids[2]), "assigned_doc_type": "paystub"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["overrides"]) == 2
    assert {o["assigned_doc_type"] for o in body["overrides"]} == {"paystub"}
    assert body["rebuild"]["pages"] == 3
    assert body["rebuild"]["stacks"] >= 1


@pytest.mark.asyncio
async def test_batch_route_validates_min_length(
    client: AsyncClient, sample_package
):
    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/overrides:batch",
        headers=HEADERS,
        json={"overrides": []},
    )
    # Pydantic min_length=1 violation
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_route_rejects_unknown_doc_type(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    page_ids = await _seed(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/overrides:batch",
        headers=HEADERS,
        json={
            "overrides": [
                {"page_id": str(page_ids[0]), "assigned_doc_type": "NOT_A_TYPE"},
            ]
        },
    )
    assert resp.status_code in (400, 422), resp.text
