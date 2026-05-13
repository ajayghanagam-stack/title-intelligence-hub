"""``/loans/*`` operator-surface route tests.

Phase 6 cutover (2026-05-10): the legacy ``/packages/*`` top-level routes
(list/get/delete/process/pipeline) were unmounted and the comparison
tests deleted. The surviving sub-router endpoints under ``/packages/*``
(stacks, validation-results, pages, hard-stops/overrides, review-queue)
remain live because they're imported separately and are still hit by
their own dedicated test files.
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID

BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


@pytest.mark.asyncio
async def test_list_loans_returns_seeded_packages(
    client: AsyncClient, sample_package
):
    loan_resp = await client.get(f"{BASE}/loans", headers=HEADERS)
    assert loan_resp.status_code == 200
    body = loan_resp.json()
    assert any(p["id"] == str(TEST_PACKAGE_ID) for p in body)


@pytest.mark.asyncio
async def test_list_loans_passes_status_filter(
    client: AsyncClient, sample_package
):
    loan_resp = await client.get(
        f"{BASE}/loans?status=uploading", headers=HEADERS
    )
    assert loan_resp.status_code == 200
    assert len(loan_resp.json()) == 1


@pytest.mark.asyncio
async def test_get_loan_returns_package(
    client: AsyncClient, sample_package
):
    loan_resp = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}", headers=HEADERS
    )
    assert loan_resp.status_code == 200
    assert loan_resp.json()["id"] == str(TEST_PACKAGE_ID)


@pytest.mark.asyncio
async def test_get_loan_not_found(
    client: AsyncClient, lo_app_and_subscription
):
    fake = uuid.uuid4()
    loan_resp = await client.get(f"{BASE}/loans/{fake}", headers=HEADERS)
    assert loan_resp.status_code == 404


@pytest.mark.asyncio
async def test_loan_pipeline_returns_status(
    client: AsyncClient, sample_package
):
    loan_resp = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/pipeline", headers=HEADERS
    )
    assert loan_resp.status_code == 200


@pytest.mark.asyncio
async def test_loan_pages_returns_pages(
    client: AsyncClient, sample_package
):
    loan_resp = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/pages", headers=HEADERS
    )
    assert loan_resp.status_code == 200


@pytest.mark.asyncio
async def test_loan_documents_returns_stacks(
    client: AsyncClient, sample_package
):
    """``/loans/{id}/documents`` exposes the loan's classified stacks."""
    loan_resp = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/documents", headers=HEADERS
    )
    assert loan_resp.status_code == 200


@pytest.mark.asyncio
async def test_loan_validations_returns_results(
    client: AsyncClient, sample_package
):
    """``/loans/{id}/validations`` exposes per-stack rule evaluations."""
    loan_resp = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/validations", headers=HEADERS
    )
    assert loan_resp.status_code == 200


# ── Phase 4 Batch 4.2 — mutation alias smoke tests ────────────────────


def _make_create_body(**overrides):
    body = {
        "name": "Alias Loan",
        "borrower_name": "Alice Alias",
        "loan_reference": "LN-A001",
        "doc_types": [
            {"key": "urla_1003", "label": "1003", "required": True},
        ],
        "validation_rules": [],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_create_loan_uses_same_handler_as_create_package(
    client: AsyncClient, lo_app_and_subscription
):
    r = await client.post(
        f"{BASE}/loans", json=_make_create_body(), headers=HEADERS
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "Alias Loan"
    assert data["status"] == "uploading"
    assert data["org_id"] == str(TEST_ORG_ID)


@pytest.mark.asyncio
async def test_delete_loan_removes_package(
    client: AsyncClient, sample_package
):
    r = await client.delete(
        f"{BASE}/loans/{TEST_PACKAGE_ID}", headers=HEADERS
    )
    assert r.status_code == 204
    # Subsequent GET returns 404 from either prefix.
    r2 = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}", headers=HEADERS
    )
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_process_loan_moves_to_processing(
    client: AsyncClient, sample_package, db_session
):
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/process", headers=HEADERS
    )
    assert r.status_code == 202
    await db_session.refresh(sample_package)
    assert sample_package.status == "processing"
    assert sample_package.pipeline_stage == "ingest"


@pytest.mark.asyncio
async def test_create_loan_hard_stop_override_records_row(
    client: AsyncClient, sample_package
):
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/hard-stops/missing_doc:paystub/override",
        json={"reason": "investor_waived", "note": "Alias delegation"},
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["hard_stop_key"] == "missing_doc:paystub"
    assert body["reason"] == "investor_waived"
    assert body["decision"] == "active"


@pytest.mark.asyncio
async def test_loan_hard_stop_overrides_listing(
    client: AsyncClient, sample_package
):
    # Create one via the loans path.
    create = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/hard-stops/missing_doc:w2/override",
        json={"reason": "late_delivery"},
        headers=HEADERS,
    )
    assert create.status_code == 201

    loan_resp = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/hard-stops/overrides",
        headers=HEADERS,
    )
    assert loan_resp.status_code == 200
    assert any(o["hard_stop_key"] == "missing_doc:w2" for o in loan_resp.json())


# ── Phase 4 Batch 4.3 — classify confirm ──────────────────────────────


@pytest.mark.asyncio
async def test_confirm_classification_accept(
    client: AsyncClient, sample_package, db_session
):
    """No doc_type in body → records accept, leaves type unchanged."""
    from app.micro_apps.loan_onboarding.models.stack import LOStack

    stack = LOStack(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_index=0,
        doc_type="urla_1003",
        page_numbers=[1, 2],
        first_page=1,
        last_page=2,
        classification_confidence=0.7,
        status="needs_review",
        requires_hitl=True,
    )
    db_session.add(stack)
    await db_session.commit()

    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/documents/{stack.id}/classify",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decision"] == "accept"
    assert body["doc_type"] == "urla_1003"

    await db_session.refresh(stack)
    assert stack.status == "accepted"
    assert stack.requires_hitl is False


@pytest.mark.asyncio
async def test_confirm_classification_reclassify(
    client: AsyncClient, sample_package, db_session
):
    """Different doc_type → reclassify, doc_type swapped."""
    from app.micro_apps.loan_onboarding.models.stack import LOStack

    stack = LOStack(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_index=0,
        doc_type="urla_1003",
        page_numbers=[1, 2],
        first_page=1,
        last_page=2,
        classification_confidence=0.7,
        status="needs_review",
        requires_hitl=True,
    )
    db_session.add(stack)
    await db_session.commit()

    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/documents/{stack.id}/classify",
        json={"doc_type": "paystub", "notes": "It's actually a paystub"},
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decision"] == "reclassify"
    assert body["doc_type"] == "paystub"

    await db_session.refresh(stack)
    assert stack.doc_type == "paystub"


@pytest.mark.asyncio
async def test_confirm_classification_unknown_doc_404(
    client: AsyncClient, sample_package
):
    fake = uuid.uuid4()
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/documents/{fake}/classify",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 404


# ── Phase 4 Batch 4.4 — checklist ─────────────────────────────────────


@pytest.mark.asyncio
async def test_loan_checklist_returns_configured_doc_types(
    client: AsyncClient, sample_package, db_session
):
    """Each configured doc type appears once with received=False initially."""
    r = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/checklist", headers=HEADERS
    )
    assert r.status_code == 200, r.text
    items = r.json()
    keys = {item["doc_type"] for item in items}
    assert keys == {"urla_1003", "paystub", "w2"}

    by_key = {item["doc_type"]: item for item in items}
    assert by_key["urla_1003"]["requirement"] == "Required"
    assert by_key["w2"]["requirement"] == "Optional"
    assert all(item["received"] is False for item in items)


@pytest.mark.asyncio
async def test_loan_checklist_marks_received_when_stack_exists(
    client: AsyncClient, sample_package, db_session
):
    from app.micro_apps.loan_onboarding.models.stack import LOStack

    db_session.add(LOStack(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_index=0,
        doc_type="paystub",
        page_numbers=[1],
        first_page=1, last_page=1,
        classification_confidence=0.9,
        status="accepted",
        requires_hitl=False,
    ))
    db_session.add(LOStack(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_index=1,
        doc_type="w2",
        page_numbers=[2],
        first_page=2, last_page=2,
        classification_confidence=0.5,
        status="needs_review",
        requires_hitl=True,
    ))
    await db_session.commit()

    r = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/checklist", headers=HEADERS
    )
    assert r.status_code == 200
    by_key = {item["doc_type"]: item for item in r.json()}
    assert by_key["paystub"]["received"] is True
    assert by_key["paystub"]["needs_review"] is False
    assert by_key["w2"]["received"] is True
    assert by_key["w2"]["needs_review"] is True
    assert by_key["urla_1003"]["received"] is False


# ── Phase 4 Batch 4.5 — per-doc extractions GET + single-field PATCH ──


@pytest.mark.asyncio
async def test_get_loan_doc_extraction_merges_overrides(
    client: AsyncClient, sample_package, db_session
):
    from app.micro_apps.loan_onboarding.models.extraction import LOExtraction
    from app.micro_apps.loan_onboarding.models.stack import LOStack

    stack = LOStack(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        stack_index=0, doc_type="w2",
        page_numbers=[1], first_page=1, last_page=1,
        classification_confidence=0.9, status="accepted",
    )
    db_session.add(stack)
    await db_session.flush()

    db_session.add(LOExtraction(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        stack_id=stack.id, doc_type="w2",
        fields=[
            {"name": "Employer", "value": "Acme Inc",
             "confidence": 0.92, "status": "located",
             "location": {"page": 1, "bbox": [0.1, 0.1, 0.3, 0.15]}},
            {"name": "Wages", "value": "$72,000",
             "confidence": 0.5, "status": "low_confidence"},
        ],
        located_count=1, total_count=2,
    ))
    await db_session.commit()

    r = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/extractions/{stack.id}",
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_type"] == "w2"
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["Employer"]["grounded"] is True
    assert by_name["Wages"]["grounded"] is False
    assert all(f["edited"] is False for f in body["fields"])


@pytest.mark.asyncio
async def test_patch_loan_extraction_field_creates_override(
    client: AsyncClient, sample_package, db_session
):
    from app.micro_apps.loan_onboarding.models.extraction import LOExtraction
    from app.micro_apps.loan_onboarding.models.extraction_override import (
        LOExtractionOverride,
    )
    from app.micro_apps.loan_onboarding.models.stack import LOStack

    stack = LOStack(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        stack_index=0, doc_type="w2",
        page_numbers=[1], first_page=1, last_page=1,
        classification_confidence=0.9, status="accepted",
    )
    db_session.add(stack)
    await db_session.flush()
    db_session.add(LOExtraction(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        stack_id=stack.id, doc_type="w2",
        fields=[{"name": "Wages", "value": "$72,000",
                 "confidence": 0.5, "status": "low_confidence"}],
        located_count=0, total_count=1,
    ))
    await db_session.commit()

    r = await client.patch(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/extractions/{stack.id}/fields/Wages",
        json={"value": "$74,500"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == "$74,500"

    rows = (await db_session.execute(
        select(LOExtractionOverride).where(
            LOExtractionOverride.stack_id == str(stack.id)
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].field_name == "Wages"
    assert rows[0].value == "$74,500"

    # Re-PATCH idempotently updates rather than insert.
    r2 = await client.patch(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/extractions/{stack.id}/fields/Wages",
        json={"value": "$75,000"},
        headers=HEADERS,
    )
    assert r2.status_code == 200
    rows2 = (await db_session.execute(
        select(LOExtractionOverride).where(
            LOExtractionOverride.stack_id == str(stack.id)
        )
    )).scalars().all()
    assert len(rows2) == 1
    assert rows2[0].value == "$75,000"


@pytest.mark.asyncio
async def test_get_loan_doc_extraction_unknown_404(
    client: AsyncClient, sample_package
):
    fake = uuid.uuid4()
    r = await client.get(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/extractions/{fake}",
        headers=HEADERS,
    )
    assert r.status_code == 404


# ── Phase 4 Batch 4.6 — soft-flag acknowledge ─────────────────────────


def _make_validation_result(
    db_session, stack_id, rules
):
    from app.micro_apps.loan_onboarding.models.validation_result import (
        LOValidationResult,
    )
    vr = LOValidationResult(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        stack_id=stack_id,
        doc_type="w2",
        rules_evaluated=rules,
        confidence_breakdown={"classification": 0.9, "split_accuracy": 0.9, "validation": 0.9},
        overall_confidence=0.9,
        requires_hitl=False,
    )
    db_session.add(vr)
    return vr


async def _make_stack(db_session, doc_type="w2", requires_hitl=False, stack_index=0):
    from app.micro_apps.loan_onboarding.models.stack import LOStack
    s = LOStack(
        org_id=TEST_ORG_ID, package_id=TEST_PACKAGE_ID,
        stack_index=stack_index, doc_type=doc_type,
        page_numbers=[1], first_page=1, last_page=1,
        classification_confidence=0.9,
        status="needs_review" if requires_hitl else "accepted",
        requires_hitl=requires_hitl,
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.mark.asyncio
async def test_acknowledge_soft_flag_marks_rule_acknowledged(
    client: AsyncClient, sample_package, db_session
):
    from app.micro_apps.loan_onboarding.models.validation_result import (
        LOValidationResult,
    )

    stack = await _make_stack(db_session)
    _make_validation_result(db_session, stack.id, [
        {
            "rule_id": "min_page_count",
            "rule_source": "preset",
            "passed": False,
            "evidence": "Only 1 page",
        },
    ])
    await db_session.commit()

    check_id = f"{stack.id}__preset__min_page_count"
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/validations/{check_id}/acknowledge",
        json={"override_note": "Operator confirmed by phone"},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["acknowledged"] is True
    assert body["rule_source"] == "preset"
    assert body["rule_id"] == "min_page_count"
    assert body["override_note"] == "Operator confirmed by phone"

    vr = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.stack_id == stack.id
        )
    )).scalar_one()
    await db_session.refresh(vr)
    target = vr.rules_evaluated[0]
    assert target["acknowledged"] is True
    assert target["override_note"] == "Operator confirmed by phone"
    assert "acknowledged_at" in target


@pytest.mark.asyncio
async def test_acknowledge_passing_rule_rejected(
    client: AsyncClient, sample_package, db_session
):
    stack = await _make_stack(db_session)
    _make_validation_result(db_session, stack.id, [
        {"rule_id": "missing_signatures", "rule_source": "preset", "passed": True},
    ])
    await db_session.commit()

    check_id = f"{stack.id}__preset__missing_signatures"
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/validations/{check_id}/acknowledge",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_acknowledge_unknown_rule_404(
    client: AsyncClient, sample_package, db_session
):
    stack = await _make_stack(db_session)
    _make_validation_result(db_session, stack.id, [
        {"rule_id": "min_page_count", "rule_source": "preset", "passed": False},
    ])
    await db_session.commit()

    bogus = f"{stack.id}__preset__no_such_rule"
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/validations/{bogus}/acknowledge",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_malformed_check_id_400(
    client: AsyncClient, sample_package
):
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/validations/not-a-valid-id/acknowledge",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 400


# ── Phase 4 Batch 4.7 — advance ───────────────────────────────────────


@pytest.mark.asyncio
async def test_advance_loan_succeeds_when_clean(
    client: AsyncClient, sample_package, db_session
):
    sample_package.status = "awaiting_review"
    await db_session.commit()

    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["advanced"] is True
    assert body["from_status"] == "awaiting_review"
    assert body["to_status"] == "decision_ready"
    assert body["blocked_reason"] is None
    assert body["open_hard_stops"] == 0
    assert body["open_soft_flags"] == 0

    await db_session.refresh(sample_package)
    assert sample_package.status == "decision_ready"


@pytest.mark.asyncio
async def test_advance_blocked_when_hitl_stacks_remain(
    client: AsyncClient, sample_package, db_session
):
    sample_package.status = "awaiting_review"
    await _make_stack(db_session, requires_hitl=True)
    await db_session.commit()

    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["advanced"] is False
    assert "HITL" in body["blocked_reason"]

    await db_session.refresh(sample_package)
    assert sample_package.status == "awaiting_review"


@pytest.mark.asyncio
async def test_advance_blocked_by_unacknowledged_soft_flag(
    client: AsyncClient, sample_package, db_session
):
    sample_package.status = "awaiting_review"
    stack = await _make_stack(db_session)
    _make_validation_result(db_session, stack.id, [
        {"rule_id": "missing_signatures", "rule_source": "preset", "passed": False},
    ])
    await db_session.commit()

    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["advanced"] is False
    assert body["open_soft_flags"] == 1


@pytest.mark.asyncio
async def test_advance_unblocked_after_ack(
    client: AsyncClient, sample_package, db_session
):
    sample_package.status = "awaiting_review"
    stack = await _make_stack(db_session)
    _make_validation_result(db_session, stack.id, [
        {"rule_id": "missing_signatures", "rule_source": "preset", "passed": False},
    ])
    await db_session.commit()

    # Ack first.
    ack = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/validations/"
        f"{stack.id}__preset__missing_signatures/acknowledge",
        json={"override_note": "ok"},
        headers=HEADERS,
    )
    assert ack.status_code == 200

    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["advanced"] is True
    assert body["to_status"] == "decision_ready"


@pytest.mark.asyncio
async def test_advance_blocked_by_hard_stop_overridden_passes(
    client: AsyncClient, sample_package, db_session
):
    """Hard stop with active override should not block; without should."""
    from app.micro_apps.loan_onboarding.models.hard_stop_override import (
        LOHardStopOverride,
    )

    sample_package.status = "awaiting_review"
    stack = await _make_stack(db_session)
    _make_validation_result(db_session, stack.id, [
        {
            "rule_id": "missing_doc",
            "rule_source": "preset",
            "passed": False,
            "severity": "hard",
        },
    ])
    await db_session.commit()

    # Without override → blocked.
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    assert r.json()["open_hard_stops"] == 1
    assert r.json()["advanced"] is False

    # Add active override matching the key shape used by the route.
    override = LOHardStopOverride(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        hard_stop_key=f"preset:missing_doc:{stack.id}",
        supervisor_id=TEST_USER_ID,
        reason="investor_waived",
        decision="active",
    )
    db_session.add(override)
    await db_session.commit()

    r2 = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    body2 = r2.json()
    assert body2["open_hard_stops"] == 0
    assert body2["advanced"] is True


@pytest.mark.asyncio
async def test_advance_idempotent_when_already_decision_ready(
    client: AsyncClient, sample_package, db_session
):
    sample_package.status = "decision_ready"
    await db_session.commit()

    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body["advanced"] is False
    assert body["from_status"] == "decision_ready"
    assert body["blocked_reason"] == "already_decision_ready"


@pytest.mark.asyncio
async def test_advance_rejected_from_invalid_status(
    client: AsyncClient, sample_package, db_session
):
    """Cannot advance from `uploading` — must be awaiting_review or completed."""
    # sample_package starts as `uploading` from fixture.
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/advance", headers=HEADERS
    )
    assert r.status_code == 400


# ── Phase 4 Batch 4.9 — legacy /packages/* → /loans/* 301 redirect ────
# Phase 6 cutover: top-level /packages routes are gone, so the
# "disabled by default returns 200" test was removed. The middleware
# still 301s when the flag is enabled — covered below.


@pytest.mark.asyncio
async def test_legacy_redirect_when_flag_enabled(
    db_session, seed_data, lo_app_and_subscription, sample_package, monkeypatch
):
    """When LO_LEGACY_REDIRECT_ENABLED=True the /packages/* path returns 301."""
    from app.config import get_settings, Settings
    from app.core.auth import get_current_user, AuthenticatedUser
    from app.core.deps import (
        get_db, get_current_member, get_session_factory, require_platform_admin,
    )
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient as _AsyncClient

    from tests.conftest import (
        TEST_AUTH_USER_ID, TEST_DATABASE_URL, test_session_factory,
    )

    def _settings_with_flag():
        return Settings(
            DATABASE_URL=TEST_DATABASE_URL,
            JWT_SECRET="test-secret-key",
            CORS_ORIGINS=["http://localhost:3000"],
            STORAGE_PATH="./test_storage",
            PIPELINE_BACKEND="background_tasks",
            PIPELINE_MODE="legacy",
            TSA_RESEARCH_MODE="scraper",
            LO_LEGACY_REDIRECT_ENABLED=True,
        )

    monkeypatch.setattr(
        "app.main.get_settings", _settings_with_flag,
    )
    app = create_app(session_factory_override=test_session_factory)

    async def override_db():
        yield db_session
    async def override_current_user():
        return AuthenticatedUser(
            auth_user_id=TEST_AUTH_USER_ID,
            email="test@example.com",
            org_id=TEST_ORG_ID,
            role="owner",
        )
    async def override_current_member():
        return seed_data["user"]
    async def override_platform_admin():
        return seed_data["user"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = _settings_with_flag
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_member] = override_current_member
    app.dependency_overrides[require_platform_admin] = override_platform_admin
    app.dependency_overrides[get_session_factory] = lambda: test_session_factory

    transport = ASGITransport(app=app)
    async with _AsyncClient(transport=transport, base_url="http://test") as ac:
        # Bare collection.
        r = await ac.get(
            f"{BASE}/packages",
            headers=HEADERS,
            follow_redirects=False,
        )
        assert r.status_code == 301
        assert r.headers["location"] == f"{BASE}/loans"

        # Specific resource preserves the suffix and any querystring.
        r2 = await ac.get(
            f"{BASE}/packages/{TEST_PACKAGE_ID}/pipeline?x=1",
            headers=HEADERS,
            follow_redirects=False,
        )
        assert r2.status_code == 301
        assert r2.headers["location"] == (
            f"{BASE}/loans/{TEST_PACKAGE_ID}/pipeline?x=1"
        )


# ── Phase 4 Batch 4.8 — pipeline SSE stream ───────────────────────────


@pytest.mark.asyncio
async def test_pipeline_stream_emits_terminal_frame_and_closes(
    client: AsyncClient, sample_package, db_session
):
    """A package already at a terminal status should stream one frame and close."""
    sample_package.status = "decision_ready"
    sample_package.pipeline_stage = "review"
    sample_package.progress = {"processed": 5, "total": 5, "hitl_count": 0}
    await db_session.commit()

    async with client.stream(
        "GET",
        f"{BASE}/loans/{TEST_PACKAGE_ID}/pipeline/stream",
        headers=HEADERS,
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
            # Generator is expected to close itself on terminal status.
            if b"\n\n" in body:
                break

    text = body.decode("utf-8")
    assert text.startswith("data: ")
    payload = json.loads(text[len("data: "):].split("\n\n", 1)[0])
    assert payload["status"] == "decision_ready"
    assert payload["pipeline_stage"] == "review"
    assert payload["processed"] == 5
    assert payload["package_id"] == str(TEST_PACKAGE_ID)


@pytest.mark.asyncio
async def test_pipeline_stream_404_when_loan_missing(
    client: AsyncClient, lo_app_and_subscription
):
    fake = uuid.uuid4()
    r = await client.get(
        f"{BASE}/loans/{fake}/pipeline/stream", headers=HEADERS
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_upload_loan_files_persists_file(
    client: AsyncClient, sample_package, db_session
):
    """``POST /loans/{id}/files`` aliases ``POST /packages/{id}/files``."""
    from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
    from sqlalchemy import select

    # Minimal real PDF the file_service will accept.
    pdf_bytes = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"0000000010 00000 n\n0000000053 00000 n\n0000000099 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF\n"
    )
    files = {"files": ("alias.pdf", pdf_bytes, "application/pdf")}
    r = await client.post(
        f"{BASE}/loans/{TEST_PACKAGE_ID}/files", files=files, headers=HEADERS
    )
    assert r.status_code == 201, r.text
    saved = r.json()
    assert len(saved) == 1
    assert saved[0]["filename"] == "alias.pdf"

    # Persisted row exists tenant-scoped.
    rows = (await db_session.execute(
        select(LOPackageFile).where(LOPackageFile.package_id == TEST_PACKAGE_ID)
    )).scalars().all()
    assert any(f.filename == "alias.pdf" for f in rows)
