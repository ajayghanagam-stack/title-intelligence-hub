"""Tests for Phase 7 routes — documents, validation, rules, review."""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.hitl_review import LOHITLReview
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID

BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


async def _seed_stack(
    db: AsyncSession,
    stack_index: int = 0,
    doc_type: str = "URLA_1003",
    page_numbers: list[int] = None,
    requires_hitl: bool = True,
    overall_confidence: float = 0.6,
) -> LOStack:
    page_numbers = page_numbers or [1, 2]
    # Need a file/pages to make the FKs happy
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        filename=f"s{stack_index}.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/s{stack_index}.pdf",
        content_hash="x" * 64,
        size_bytes=100,
        page_count=len(page_numbers),
    )
    db.add(file_row)
    await db.flush()
    for pn in page_numbers:
        page = LOPage(
            id=uuid.uuid4(),
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            file_id=file_row.id,
            page_number=pn,
            source_page_number=pn,
            heuristic_text="x" * 100,
            text_length=100,
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
            confidence=0.9,
            page_role="first_page" if pn == page_numbers[0] else "continuation",
            detected_fields=[],
        ))
    stack = LOStack(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_index=stack_index,
        doc_type=doc_type,
        page_numbers=page_numbers,
        first_page=page_numbers[0],
        last_page=page_numbers[-1],
        classification_confidence=0.9,
        overall_confidence=overall_confidence,
        status="needs_review" if requires_hitl else "accepted",
        requires_hitl=requires_hitl,
    )
    db.add(stack)
    await db.flush()
    return stack


@pytest.mark.asyncio
async def test_list_pages_route(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    await _seed_stack(db_session, page_numbers=[1, 2])
    await db_session.commit()
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/pages", headers=HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert [p["page_number"] for p in data] == [1, 2]


@pytest.mark.asyncio
async def test_list_stacks_route_joins_classifications(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    await _seed_stack(db_session)
    await db_session.commit()
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/stacks", headers=HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    s = data[0]
    assert s["doc_type"] == "URLA_1003"
    assert s["page_count"] == 2
    assert len(s["pages"]) == 2
    assert s["pages"][0]["predicted_doc_type"] == "URLA_1003"
    # page_id needed by the "Move to…" override flow on the Documents tab
    assert s["pages"][0]["page_id"] is not None


@pytest.mark.asyncio
async def test_list_rules_route(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    # sample_package seeds a single preset rule
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/rules", headers=HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rule_source"] == "preset"
    assert data[0]["rule_id"] == "missing_signatures"


@pytest.mark.asyncio
async def test_preset_catalog_route(
    client: AsyncClient, lo_app_and_subscription
):
    resp = await client.get(f"{BASE}/rules/presets", headers=HEADERS)
    assert resp.status_code == 200
    catalog = resp.json()
    rule_ids = {r["rule_id"] for r in catalog}
    assert {"missing_signatures", "missing_pages", "missing_fields"} <= rule_ids


@pytest.mark.asyncio
async def test_list_validation_results_route(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    stack = await _seed_stack(db_session)
    db_session.add(LOValidationResult(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_id=stack.id,
        doc_type="URLA_1003",
        rules_evaluated=[{
            "rule_id": "missing_signatures",
            "rule_source": "preset",
            "passed": False,
            "evidence": "No signature_page found",
            "location": None,
        }],
        confidence_breakdown={
            "classification": 0.9, "split_accuracy": 0.95, "validation": 0.0,
        },
        overall_confidence=0.6,
        requires_hitl=True,
    ))
    await db_session.commit()

    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/validation-results", headers=HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["requires_hitl"] is True
    assert len(data[0]["rules_evaluated"]) == 1


@pytest.mark.asyncio
async def test_review_queue_lists_hitl_stacks(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    stack = await _seed_stack(db_session, requires_hitl=True)
    db_session.add(LOValidationResult(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_id=stack.id,
        doc_type="URLA_1003",
        rules_evaluated=[
            {"rule_id": "missing_signatures", "rule_source": "preset", "passed": False, "evidence": "No signature_page"},
            {"rule_id": "missing_pages", "rule_source": "preset", "passed": True, "evidence": "OK"},
        ],
        confidence_breakdown={"classification": 0.9, "split_accuracy": 0.9, "validation": 0.5},
        overall_confidence=0.7,
        requires_hitl=True,
    ))
    # Also seed a stack that does NOT require HITL — it must be excluded from the queue
    await _seed_stack(db_session, stack_index=1, page_numbers=[3, 4], requires_hitl=False, overall_confidence=0.95)
    await db_session.commit()

    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/review-queue", headers=HEADERS
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1  # only the HITL-flagged stack
    assert items[0]["stack_id"] == str(stack.id)
    assert items[0]["rules_failed"] == 1
    assert items[0]["rules_total"] == 2


@pytest.mark.asyncio
async def test_accept_decision_marks_stack_accepted_and_completes_package(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    stack = await _seed_stack(db_session, requires_hitl=True)
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    pkg.status = "awaiting_review"
    await db_session.commit()

    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/stacks/{stack.id}/review",
        headers=HEADERS,
        json={"decision": "accept", "notes": "Looks good"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["decision"] == "accept"

    # Verify persistence
    fresh_stack = (await db_session.execute(
        select(LOStack).where(LOStack.id == stack.id)
    )).scalar_one()
    assert fresh_stack.status == "accepted"
    assert fresh_stack.requires_hitl is False

    fresh_pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    # No more HITL stacks → package auto-transitions to completed
    assert fresh_pkg.status == "completed"


@pytest.mark.asyncio
async def test_reject_decision_keeps_stack_open_and_package_awaiting(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    stack = await _seed_stack(db_session, requires_hitl=True)
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    pkg.status = "awaiting_review"
    await db_session.commit()

    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/stacks/{stack.id}/review",
        headers=HEADERS,
        json={"decision": "reject", "notes": "Wrong doc type"},
    )
    assert resp.status_code == 201

    fresh_stack = (await db_session.execute(
        select(LOStack).where(LOStack.id == stack.id)
    )).scalar_one()
    assert fresh_stack.status == "rejected"
    assert fresh_stack.requires_hitl is True  # stays in queue

    fresh_pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert fresh_pkg.status == "awaiting_review"


@pytest.mark.asyncio
async def test_reclassify_updates_doc_type(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    stack = await _seed_stack(db_session, requires_hitl=True, doc_type="URLA_1003")
    await db_session.commit()

    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/stacks/{stack.id}/review",
        headers=HEADERS,
        json={"decision": "reclassify", "corrected_doc_type": "PAYSTUB"},
    )
    assert resp.status_code == 201

    fresh_stack = (await db_session.execute(
        select(LOStack).where(LOStack.id == stack.id)
    )).scalar_one()
    assert fresh_stack.doc_type == "PAYSTUB"
    assert fresh_stack.status == "accepted"


@pytest.mark.asyncio
async def test_reclassify_requires_corrected_doc_type(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    stack = await _seed_stack(db_session, requires_hitl=True)
    await db_session.commit()

    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/stacks/{stack.id}/review",
        headers=HEADERS,
        json={"decision": "reclassify"},
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_list_reviews_for_stack(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    stack = await _seed_stack(db_session, requires_hitl=True)
    await db_session.commit()

    # Submit two decisions (history tracking)
    for decision in ("reject", "accept"):
        await client.post(
            f"{BASE}/packages/{TEST_PACKAGE_ID}/stacks/{stack.id}/review",
            headers=HEADERS,
            json={"decision": decision, "notes": f"Decision: {decision}"},
        )

    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/stacks/{stack.id}/reviews",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    reviews = resp.json()
    assert len(reviews) == 2
    # Newest first
    assert reviews[0]["decision"] == "accept"
    assert reviews[1]["decision"] == "reject"
