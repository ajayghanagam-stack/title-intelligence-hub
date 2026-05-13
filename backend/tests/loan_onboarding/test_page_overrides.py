"""Tests for reviewer-authored page overrides + re-stack/re-validate.

Covers:
- Service: validate target type, reject no-ops, first-override preserves
  previous_doc_type, upsert on second override, removal.
- Rebuild: effective classifications flow into stacking so overridden pages
  regroup under the new doc_type.
- Route: POST/DELETE/GET behave end-to-end + rebuild summary shape.
- Determinism: same override set → same override_set_hash.
- Pipeline-run stamp: rebuild records the hash in version_metadata.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.page_override import LOPageOverride
from app.micro_apps.loan_onboarding.models.pipeline_run import LOPipelineRun
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.services import page_override_service
from app.micro_apps.loan_onboarding.services.page_assignment import (
    load_effective_classifications,
    override_set_hash,
)
from app.services.storage import get_storage
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


async def _seed_pages_and_classifications(
    db: AsyncSession,
    rows: list[tuple[int, str, float, str]],
) -> list[uuid.UUID]:
    """Seed LOPageFile + LOPage + LOClassification. Returns page_ids in input order."""
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
            heuristic_text=f"Page {pn} text for {doc_type}",
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
async def test_apply_override_rejects_unknown_doc_type(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    with pytest.raises(Exception):
        await page_override_service.apply_override(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
            assigned_doc_type="NOT_A_REAL_TYPE",
            page_role_override=None,
            reviewer_id=TEST_USER_ID,
            note=None,
        )


@pytest.mark.asyncio
async def test_apply_override_allows_others_bucket(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    override = await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
        assigned_doc_type=OTHERS_KEY,
        page_role_override=None,
        reviewer_id=TEST_USER_ID,
        note="not a real doc",
    )
    assert override.assigned_doc_type == OTHERS_KEY
    assert override.previous_doc_type == "urla_1003"


@pytest.mark.asyncio
async def test_apply_override_rejects_noop(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    # Target matches ML prediction with no role change → no-op
    with pytest.raises(Exception):
        await page_override_service.apply_override(
            db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
            assigned_doc_type="urla_1003",
            page_role_override=None,
            reviewer_id=TEST_USER_ID,
            note=None,
        )


@pytest.mark.asyncio
async def test_apply_override_upserts_preserving_previous_doc_type(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    # First override: 1003 → PAYSTUB
    first = await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
        assigned_doc_type="paystub",
        page_role_override="first_page",
        reviewer_id=TEST_USER_ID,
        note="thought it was a paystub",
    )
    assert first.previous_doc_type == "urla_1003"
    assert first.assigned_doc_type == "paystub"

    # Second override of same page: PAYSTUB → W2. `previous_doc_type` stays
    # at the ML's original prediction (1003), NOT the intermediate PAYSTUB —
    # this is what the audit trail needs.
    second = await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
        assigned_doc_type="w2",
        page_role_override=None,
        reviewer_id=TEST_USER_ID,
        note="actually a W2",
    )
    assert second.id == first.id  # same row, upserted
    assert second.previous_doc_type == "urla_1003"
    assert second.assigned_doc_type == "w2"
    assert second.page_role_override is None


@pytest.mark.asyncio
async def test_remove_override_returns_to_ml_classification(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session, [(1, "urla_1003", 0.9, "first_page")]
    )
    await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
        assigned_doc_type="paystub",
        page_role_override=None,
        reviewer_id=TEST_USER_ID,
        note=None,
    )
    await db_session.commit()

    removed = await page_override_service.remove_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0]
    )
    await db_session.commit()
    assert removed is True

    # Effective view should now match the ML classification again
    effective = await load_effective_classifications(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID
    )
    assert len(effective) == 1
    assert effective[0].doc_type == "urla_1003"
    assert effective[0].is_overridden is False


# ── Rebuild: stacks + validation reflect overrides ────────────────────────


@pytest.mark.asyncio
async def test_rebuild_regroups_stacks_after_override(
    sample_package, db_session: AsyncSession
):
    """Moving page 3 from URLA_1003 → PAYSTUB must split the stack."""
    page_ids = await _seed_pages_and_classifications(
        db_session,
        [
            (1, "urla_1003", 0.95, "first_page"),
            (2, "urla_1003", 0.95, "continuation"),
            (3, "urla_1003", 0.95, "last_page"),
            (4, "paystub", 0.95, "first_page"),
        ],
    )
    storage = get_storage()

    # Before: single 1003 stack(1-3) + paystub stack(4)
    from app.micro_apps.loan_onboarding.pipeline.stages import stage_stack
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()
    before = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()
    assert [(s.doc_type, s.first_page, s.last_page) for s in before] == [
        ("urla_1003", 1, 3), ("paystub", 4, 4),
    ]

    # Move page 3 → PAYSTUB and rebuild
    await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[2],
        assigned_doc_type="paystub",
        page_role_override="first_page",
        reviewer_id=TEST_USER_ID,
        note=None,
    )
    summary = await page_override_service.rebuild_stacks_and_validation(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, storage
    )
    await db_session.commit()

    # After: 1003 stack(1-2), PAYSTUB stack(3), PAYSTUB stack(4)
    # (pages 3 and 4 are separate stacks because page 3 is `first_page` role)
    after = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
        .order_by(LOStack.stack_index.asc())
    )).scalars().all()
    doc_types = [(s.doc_type, s.first_page, s.last_page) for s in after]
    assert ("urla_1003", 1, 2) in doc_types
    assert summary["pages"] == 4


# ── Determinism of override_set_hash ──────────────────────────────────────


@pytest.mark.asyncio
async def test_override_set_hash_is_stable(
    sample_package, db_session: AsyncSession
):
    """Same override set → same hash, regardless of insertion order."""
    page_ids = await _seed_pages_and_classifications(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "last_page"),
        ],
    )
    await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
        assigned_doc_type="paystub",
        page_role_override=None,
        reviewer_id=TEST_USER_ID,
        note=None,
    )
    await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[1],
        assigned_doc_type="w2",
        page_role_override=None,
        reviewer_id=TEST_USER_ID,
        note=None,
    )
    await db_session.commit()
    rows = (await db_session.execute(
        select(LOPageOverride).where(LOPageOverride.package_id == TEST_PACKAGE_ID)
    )).scalars().all()

    h1 = override_set_hash(rows)
    h2 = override_set_hash(list(reversed(rows)))
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_rebuild_records_override_set_hash_in_pipeline_run(
    sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "last_page"),
        ],
    )
    # Pre-seed a pipeline run so the rebuild has something to stamp
    run = LOPipelineRun(
        package_id=TEST_PACKAGE_ID,
        org_id=TEST_ORG_ID,
        ai_platform="vertex",
        classifier_model="gemini-2.5-flash",
        validator_model="claude-sonnet-4-6",
        reasoner_model="claude-opus-4-6",
        classify_prompt_hash="a" * 64,
        validate_prompt_hash="b" * 64,
        reason_prompt_hash="c" * 64,
        classify_schema_hash="d" * 64,
        validate_schema_hash="e" * 64,
        rules_version="lo_validation_rules_v1",
        pipeline_backend="background_tasks",
        status="completed",
        version_metadata={"seed": True},
    )
    db_session.add(run)
    await db_session.commit()

    await page_override_service.apply_override(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, page_ids[0],
        assigned_doc_type="paystub",
        page_role_override=None,
        reviewer_id=TEST_USER_ID,
        note=None,
    )
    storage = get_storage()
    await page_override_service.rebuild_stacks_and_validation(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID, storage
    )
    await db_session.commit()

    await db_session.refresh(run)
    assert run.version_metadata is not None
    assert "override_set_hash" in run.version_metadata
    assert run.version_metadata["override_count"] == 1
    # Seed field preserved
    assert run.version_metadata.get("seed") is True


# ── HTTP route coverage ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_override_route_applies_and_returns_rebuild_summary(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "last_page"),
        ],
    )
    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_ids[0]}/override",
        headers=HEADERS,
        json={"assigned_doc_type": "paystub", "note": "moved"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["override"]["assigned_doc_type"] == "paystub"
    assert body["override"]["previous_doc_type"] == "urla_1003"
    assert body["rebuild"]["pages"] == 2
    assert body["rebuild"]["stacks"] >= 1


@pytest.mark.asyncio
async def test_override_route_delete_returns_null_override(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "last_page"),
        ],
    )
    # Create an override first
    await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_ids[0]}/override",
        headers=HEADERS,
        json={"assigned_doc_type": "paystub"},
    )
    resp = await client.delete(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_ids[0]}/override",
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["override"] is None
    assert body["rebuild"]["pages"] == 2


@pytest.mark.asyncio
async def test_list_overrides_route(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    page_ids = await _seed_pages_and_classifications(
        db_session,
        [
            (1, "urla_1003", 0.9, "first_page"),
            (2, "urla_1003", 0.9, "last_page"),
        ],
    )
    await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages/{page_ids[0]}/override",
        headers=HEADERS,
        json={"assigned_doc_type": "paystub"},
    )
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/overrides", headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["assigned_doc_type"] == "paystub"
